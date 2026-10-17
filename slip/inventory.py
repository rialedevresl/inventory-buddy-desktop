"""Inventory model built from Firestorm's saved inventory cache.

Read-only. Builds the folder tree, item details, and detects "product
folders": a folder that holds one product's pieces (a hairstyle with its
mesh, tattoo layers and HUD, a furniture set with its notecard), so the app
can treat the whole folder as one unit instead of loose items.

From v0.8 a folder is moved as a whole by default. Only folders that look like
your own organizing folders (mixed creators, many products side by side) and
sorting-category folders are opened up. You can split a product folder or
mark any folder as one product yourself.
"""
from __future__ import annotations

import collections
import datetime
import gzip
import os
import re
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import llsd

NULL = "00000000-0000-0000-0000-000000000000"
PERM_TRANSFER, PERM_MODIFY, PERM_COPY = 1 << 13, 1 << 14, 1 << 15
MAGIC_ID = uuid.UUID("3c115e51-04f4-523c-9fa6-98aff1034730").bytes
CACHE_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\..+)?\.inv\.llsd\.gz$", re.I)

TYPE_LABEL = {
    "object": "Object", "clothing": "Clothing", "bodypart": "Body part", "texture": "Texture",
    "notecard": "Notecard", "landmark": "Landmark", "animatn": "Animation", "callcard": "Calling card",
    "lsltext": "Script", "material": "Material", "settings": "Settings", "gesture": "Gesture",
    "sound": "Sound", "link": "Link", "link_f": "Folder link", "snapshot": "Snapshot",
}
TYPE_PLURAL = {
    "object": "Objects", "clothing": "Clothing", "bodypart": "Body parts", "texture": "Textures",
    "notecard": "Notecards", "landmark": "Landmarks", "animatn": "Animations", "callcard": "Calling cards",
    "lsltext": "Scripts", "material": "Materials", "settings": "Settings", "gesture": "Gestures",
    "sound": "Sounds", "link": "Links", "link_f": "Folder links",
}
# Wearable sub-type is stored in the low byte of an item's flags.
WEARABLE = {0: "Shape", 1: "Skin", 2: "Hair", 3: "Eyes", 4: "Shirt", 5: "Pants", 6: "Shoes", 7: "Socks",
            8: "Jacket", 9: "Gloves", 10: "Undershirt", 11: "Underpants", 12: "Skirt", 13: "Alpha",
            14: "Tattoo layer", 15: "Physics", 16: "Universal"}
PACKAGING_TYPES = {"notecard", "landmark", "callcard"}
# Things inside a product that "Clean out packaging" offers to send to Trash: notecards, landmarks and scripts.
# Never textures: they're often a product's color options, HUD art or the product itself.
CLEANABLE_TYPES = PACKAGING_TYPES | {"lsltext"}


def cleanable(it):
    return it.type in CLEANABLE_TYPES
BOXED = re.compile(r"\(unpacked\)|\(box(ed)?\)|\bboxed\b|\[[^\]]*pack\]|\bfat ?pack\b|add ?me", re.I)

# System folders whose contents DO get sorted. Every other system folder (Clothing, Favorites, Calling Cards,
# Current Outfit, My Outfits, Marketplace Listings, Animations, Textures...) is left alone for sorting by hand.
# Firestorm names folder types like this ("lstndfnd"); numbers are included in case a type arrives as a number.
SORTED_SYSTEM_TYPES = {"object", "objects", "6", "lstndfnd", "lost_and_found", "lostandfound", "16",
                       "inbox", "received_items", "50",
                       "landmark", "3", "settings", "56"}      # these two only gather their own kind of thing
# System folders that are a home for one kind of thing: landmarks and environment settings (windlights).
SPECIAL_HOMES = {"landmark": "landmarks", "3": "landmarks", "settings": "settings", "56": "settings"}
SYSTEM_NAMES = {"object": "Objects", "6": "Objects", "lstndfnd": "Lost And Found", "16": "Lost And Found",
                "inbox": "Received Items", "50": "Received Items"}


def category_key(name):
    """Normalise a folder/category name: drop Buddy numbering, 'Inventory Buddy - ', trailing numbers."""
    n = name.strip().lower()
    n = re.sub(r"^\d+\s*-\s*", "", n)
    n = re.sub(r"^inventory buddy\s*-\s*", "", n)
    n = re.sub(r"\s+\d+$", "", n)
    return re.sub(r"\s+", " ", n)


PRODUCT_WORDS = re.compile(r"unpack|\bbox(ed)?\b|\(box\)|\bpack\b|fatpack|add ?me|\bhud\b|\bset\b|collection|"
                           r"bundle|\bkit\b|deluxe|basic|\[.*\]", re.I)


def s(v):
    return "" if v is None else str(v)


# --------------------------------------------------------------------------- finding caches

def _custom_cache_dirs():
    roots = []
    if os.name == "nt":
        roots += Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")).glob("Firestorm*")
    else:
        roots += Path.home().glob(".firestorm*")
        roots += (Path.home() / "Library/Application Support").glob("Firestorm*")
    out = []
    for root in roots:
        try:
            text = (root / "user_settings" / "settings.xml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"<key>CacheLocation</key>.*?<string>([^<]+)</string>", text, re.S)
        if m and m.group(1).strip():
            custom = Path(m.group(1).strip())
            out += [custom] + sorted(custom.glob("Firestorm*"))
    return out


def cache_dirs(extra=()):
    dirs = list(extra)
    if os.name == "nt":
        dirs += sorted(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")).glob("Firestorm*"))
    else:
        dirs += sorted((Path.home() / "Library/Caches").glob("Firestorm*"))
        dirs += sorted(Path.home().glob(".firestorm*/cache"))
        dirs += sorted((Path.home() / ".cache").glob("firestorm*"))
    dirs += _custom_cache_dirs()
    seen, out = set(), []
    for d in dirs:
        k = str(d).lower()
        if k not in seen and d.is_dir():
            seen.add(k)
            out.append(d)
    return out


def find_caches(extra=()):
    files = {}
    for d in cache_dirs(extra):
        try:
            for p in d.iterdir():
                if CACHE_RE.match(p.name):
                    files[str(p.resolve()).lower()] = p
        except OSError:
            pass
    return sorted(files.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def read_cache(path: Path):
    raw = gzip.decompress(path.read_bytes())
    version = struct.unpack(">I", raw[:4])[0]
    data = llsd.parse_binary(raw[4:])
    return version, data.get("categories") or [], data.get("items") or []


# --------------------------------------------------------------------------- model

@dataclass
class Folder:
    id: str
    name: str
    parent: str
    ptype: str
    thumb: str = ""
    pic: str = ""          # no thumbnail of its own: a picture texture found inside it (or remembered from before)
    folders: list = field(default_factory=list)
    items: list = field(default_factory=list)

    @property
    def system(self):
        return self.ptype not in ("", "-1", "none")

    @property
    def hands_off(self):
        """A system folder the app leaves alone (everything except Objects, Lost And Found, Received Items)."""
        return self.system and self.ptype.lower() not in SORTED_SYSTEM_TYPES and self.ptype != "root_inv"


@dataclass
class Item:
    id: str
    name: str
    parent: str
    type: str
    kind: str          # friendly type: "Object", "Tattoo layer", "Notecard"...
    creator: str
    mask: int | None
    asset: str
    created: int | None
    thumb: str
    link_target: str


def _asset_key(it):
    a = it.get("asset_id")
    if a is not None and s(a) != NULL:
        return s(a)
    sh = it.get("shadow_id")
    if sh is not None and hasattr(sh, "bytes"):
        real = uuid.UUID(bytes=bytes(x ^ y for x, y in zip(sh.bytes, MAGIC_ID)))
        return "" if s(real) == NULL else s(real)
    return ""


def _flags(v):
    """Item flags: Firestorm saves them as 4 raw bytes (big-endian), sometimes as a plain number.
    The low byte says which kind of clothing or body part it is (Alpha, Shirt, Skin...)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, (bytes, bytearray)) and v:
        return int.from_bytes(bytes(v[-4:]), "big")
    return 0


# Picking a texture inside a product to stand in as its picture.
PIC_TYPES = {"texture", "snapshot"}
PIC_GOOD = re.compile(r"\b(ad|ads|advert|vendor|poster|info|picture|pic|preview|display|promo|photo|image|"
                      r"main|cover|box|colors?|colours?|options?)\b", re.I)
# Maps and HUD art, not pictures. One-letter map endings only count as a suffix ("wood_n", "brick-s"),
# so "S&P" or "Izzie's" don't.
PIC_MAP = re.compile(r"(\b|_)(normal|norm|nrm|spec|specular|bump|mask|alpha|occlusion|rough(ness)?|metal(lic)?|"
                     r"emissive|uv ?map|height ?map|displacement)(\b|_|$)|[_-](n|s|e|d|ns|ao|nrm|spc)$", re.I)
PIC_BAD = re.compile(PIC_MAP.pattern + r"|\b(hud|button|icon|baked?)\b", re.I)


def _from_cache(path: Path):
    """(folders, items) as dicts of Folder / Item, read from Firestorm's saved inventory."""
    _, cats, items = read_cache(path)
    folders, out = {}, {}
    for c in cats:
        th = c.get("thumbnail")
        th = s(th.get("asset_id")) if isinstance(th, dict) else ""
        f = Folder(s(c.get("cat_id")), s(c.get("name")), s(c.get("parent_id")), s(c.get("preferred_type")),
                   "" if th == NULL else th)
        folders[f.id] = f
    for it in items:
        t = s(it.get("type"))
        perms = it.get("permissions") or {}
        flags = _flags(it.get("flags"))
        kind = TYPE_LABEL.get(t, t.title() or "Item")
        if t in ("clothing", "bodypart"):
            kind = WEARABLE.get(flags & 0xFF, kind)
        thumb = it.get("thumbnail")
        thumb = s(thumb.get("asset_id")) if isinstance(thumb, dict) else ""
        mask = perms.get("owner_mask")
        obj = Item(
            id=s(it.get("item_id")), name=s(it.get("name")).strip(), parent=s(it.get("parent_id")),
            type=t, kind=kind, creator="" if s(perms.get("creator_id")) == NULL else s(perms.get("creator_id")),
            mask=mask if isinstance(mask, int) else None,
            asset=_asset_key(it) if t not in ("link", "link_f") else "",
            created=it.get("created_at") if isinstance(it.get("created_at"), (int, float)) else None,
            thumb="" if thumb == NULL else thumb,
            link_target=_asset_key(it) if t in ("link", "link_f") else "")
        out[obj.id] = obj
    return folders, out


def _cache_root(folders):
    return next((f.id for f in folders.values() if f.ptype == "root_inv"), None)


class Inventory:
    """An inventory, read either live from Firestorm (normal) or from the saved cache (offline/testing).

    Live mode takes names and places from Firestorm right now, and fills in the details the live
    view doesn't give (creator, permissions, thumbnails, clothing type) from the saved cache by id."""

    def __init__(self, path: Path | None = None, live: dict | None = None, cache: Path | None = None):
        self.path = path
        self.live = live is not None
        if live is None:
            self.saved = datetime.datetime.fromtimestamp(path.stat().st_mtime)
            self.folders, self.items = _from_cache(path)
        else:
            self.saved = datetime.datetime.now()
            cf, ci = ({}, {})
            if cache is not None:
                try:
                    cf, ci = _from_cache(cache)
                    if _cache_root(cf) != live["root"]:
                        cf, ci = {}, {}            # a different avatar's cache: don't borrow details
                except Exception:  # noqa: BLE001 - details are optional
                    cf, ci = {}, {}
            self.path = cache
            self.folders, self.items = {}, {}
            self.folders[live["root"]] = Folder(live["root"], "My Inventory", NULL, "root_inv")
            for fid, f in live["folders"].items():
                ptype = s(f.get("type"))
                ptype = "-1" if ptype in ("", "none") else ptype
                old = cf.get(fid)
                if old is not None and old.system and ptype == "-1":
                    ptype = old.ptype              # the saved copy knows it's a system folder
                self.folders[fid] = Folder(fid, s(f.get("name")), s(f.get("parent")), ptype, old.thumb if old else "")
            if live.get("trash"):
                self.folders[live["trash"]] = Folder(live["trash"], "Trash", live["root"], "trash")
            for iid, it in live["items"].items():
                t = s(it.get("type")) or "object"
                old = ci.get(iid)
                created = it.get("created") if isinstance(it.get("created"), (int, float)) and it.get("created") else None
                self.items[iid] = Item(
                    id=iid, name=s(it.get("name")).strip(), parent=s(it.get("parent")), type=t,
                    kind=old.kind if old else TYPE_LABEL.get(t, t.title() or "Item"),
                    creator=old.creator if old else "", mask=old.mask if old else None,
                    asset=old.asset if old else "", created=created or (old.created if old else None),
                    thumb=old.thumb if old else "", link_target=s(it.get("linked")) if t.startswith("link") else "")
            self.trash_count = int(live.get("trash_count") or 0)
        for f in self.folders.values():
            p = self.folders.get(f.parent)
            if p:
                p.folders.append(f.id)
        for i in self.items.values():
            p = self.folders.get(i.parent)
            if p:
                p.items.append(i.id)
        self.root = next((f.id for f in self.folders.values() if f.ptype == "root_inv"), None) \
            or next((f.id for f in self.folders.values() if f.parent not in self.folders), None)
        self.trash = next((f.id for f in self.folders.values() if f.ptype == "trash"), None)
        self._paths: dict[str, list[str]] = {}
        self._subtree_cache: dict[str, tuple] = {}
        self._kits: dict[str, bool] = {}
        self._prod: dict[str, bool] = {}
        self.category_keys: set[str] = set()
        self.split: set[str] = set()      # folders you chose to open up ("Split into pieces")
        self.joined: set[str] = set()     # folders you chose to keep together ("Treat as one product")
        self.skipped: set[str] = set()    # folders you told the sorter to leave alone ("Skip this folder")
        self.creator_rank = {c: i + 1 for i, (c, _) in enumerate(
            collections.Counter(i.creator for i in self.items.values()).most_common())}

    # ---------------------------------------------------------------- paths
    def chain(self, fid):
        """Folder ids from the root down to fid (root excluded)."""
        if fid in self._paths:
            return self._paths[fid]
        out, cur, guard = [], fid, 0
        while cur in self.folders and cur != self.root and guard < 100:
            out.append(cur)
            cur = self.folders[cur].parent
            guard += 1
        out.reverse()
        self._paths[fid] = out
        return out

    def path_text(self, fid):
        return " › ".join(self.folders[f].name for f in self.chain(fid)) or "My Inventory"

    def special_folder(self, kind):
        """The system Landmarks or Settings folder (kind "landmarks" / "settings")."""
        return next((f.id for f in self.folders.values() if f.system and f.parent == self.root
                     and SPECIAL_HOMES.get(f.ptype.lower()) == kind), None)

    def special_home(self, fid):
        """"landmarks" / "settings" when fid is (inside) that system folder."""
        for f in self.chain(fid):
            k = SPECIAL_HOMES.get(self.folders[f].ptype.lower()) if self.folders[f].system else None
            if k:
                return k
        return ""

    def in_trash(self, fid):
        return self.trash is not None and (fid == self.trash or self.trash in self.chain(fid))

    def skipped_by(self, fid):
        """The folder you skipped that fid is in (or is), if any."""
        if not self.skipped:
            return None
        return next((f for f in self.chain(fid) if f in self.skipped), None)

    def hands_off(self, fid):
        """Inside a system folder the app leaves for you to sort by hand?"""
        return any(self.folders[f].hands_off for f in self.chain(fid))

    # ---------------------------------------------------------------- subtree
    def subtree(self, fid):
        """(item ids, folder count, max depth) under fid, cached."""
        if fid in self._subtree_cache:
            return self._subtree_cache[fid]
        f = self.folders[fid]
        items, nf, depth = list(f.items), 0, 0
        for c in f.folders:
            ci, cn, cd = self.subtree(c)
            items += ci
            nf += 1 + cn
            depth = max(depth, cd + 1)
        self._subtree_cache[fid] = (items, nf, depth)
        return self._subtree_cache[fid]

    # ---------------------------------------------------------------- product folders
    def set_categories(self, names):
        """Folders named like a sorting category are never treated as one product."""
        self.category_keys = {category_key(n) for n in names if n}
        self.clear_kits()

    def set_choices(self, split=(), joined=()):
        self.split, self.joined = set(split), set(joined)
        self.clear_kits()

    def clear_kits(self):
        self._kits.clear()
        self._prod.clear()

    def is_category_folder(self, fid):
        return category_key(self.folders[fid].name) in self.category_keys

    def _real(self, ids):
        return [self.items[i] for i in ids if self.items[i].type not in PACKAGING_TYPES | {"link", "link_f"}]

    def _direct_real(self, fid):
        return self._real(self.folders[fid].items)

    @staticmethod
    def _brand_share(folder_name, real):
        """Share of pieces whose name starts with the folder's first word (the store name, e.g. 'LUEUR')."""
        m = re.match(r"\W*([^\W_]{3,})", folder_name)
        if not m or not real:
            return 0.0
        brand = m.group(1).lower()
        hits = sum(1 for i in real if (re.match(r"\W*([^\W_]+)", i.name) or [None, ""])[1].lower() == brand)
        return hits / len(real)

    def _boxed_side_by_side(self, fid):
        """Several boxed / unpacked products next to each other, with nothing of its own: a container."""
        f = self.folders[fid]
        if self._direct_real(fid):
            return False
        boxed = sum(1 for c in f.folders if BOXED.search(self.folders[c].name) and self.subtree(c)[0])
        return boxed >= 2

    def _main_creator(self, fid):
        known = [i.creator for i in self._real(self.subtree(fid)[0]) if i.creator]
        return collections.Counter(known).most_common(1)[0][0] if known else ""

    def _organizer(self, fid):
        """A folder you organized: products from different creators side by side, or loose things
        from other creators sitting next to subfolders."""
        f = self.folders[fid]
        kids = [c for c in f.folders if self._product(c)]
        makers = {self._main_creator(c) for c in kids} - {""}
        if len(kids) >= 2 and len(makers) >= 2:
            return True
        # Several complete packages from one maker side by side (six heads in a "Lelutka Evo X"
        # folder): each came with its own notecards and enough pieces to be a product on its own.
        # A fatpack split into colors has small subfolders, so it still moves as one.
        full = [c for c in kids if len(self._real(self.subtree(c)[0])) >= 20
                and any(self.items[i].type in PACKAGING_TYPES for i in self.subtree(c)[0])]
        if len(full) >= 2:
            return True
        direct = [i for i in self._direct_real(fid) if i.creator]
        if f.folders and direct and not self._product_shaped(fid):
            main = self._main_creator(fid)
            if sum(1 for i in direct if i.creator == main) / len(direct) < 0.8:
                return True
        return False

    def _product_shaped(self, fid):
        """One product that comes with a few subfolders (extras, HUDs, ears): small, and mostly one
        creator or mostly pieces named after the store."""
        f = self.folders[fid]
        items, nf, _ = self.subtree(fid)
        if len(f.folders) > 5 or nf > 10 or len(items) > 250:
            return False
        real = self._real(items)
        known = [i.creator for i in real if i.creator]
        share = collections.Counter(known).most_common(1)[0][1] / len(known) if known else 0.0
        if self._brand_share(f.name, real) >= 0.5:
            return True                     # most pieces are named after the folder's store
        # A one-word name ("Clothes", "Extras") is a folder you made, not a product.
        return share >= 0.65 and len(re.findall(r"[^\W_]+", f.name)) >= 2

    def _product(self, fid):
        """Does this folder hold one product (or one store's set) that should move as a whole?"""
        if fid in self._prod:
            return self._prod[fid]
        f = self.folders[fid]
        result = False
        if f.system or fid == self.root or self.in_trash(fid) or fid in self.split:
            result = False
        elif fid in self.joined:
            result = True
        elif self.is_category_folder(fid):
            result = False
        else:
            items, nf, depth = self.subtree(fid)
            real = self._real(items)
            if not items:
                result = False                      # empty folder: nothing to move
            elif not real:
                result = True                       # only notecards / landmarks: one leftover box
            elif nf > 40 or len(items) > 1500 or self._boxed_side_by_side(fid) or self._organizer(fid):
                result = False                      # too big, or several different products: a container
            else:
                known = [i for i in real if i.creator]
                if known:
                    _, n = collections.Counter(i.creator for i in known).most_common(1)[0]
                    share = n / len(known)
                else:
                    share = 0.0                     # no creator details (not in the saved copy yet)
                named = bool(PRODUCT_WORDS.search(f.name))
                if share >= 0.5:
                    result = True                   # mostly one creator: one product or one store's set
                elif share >= 0.3 and named and depth <= 2:
                    result = True
                elif not f.folders and self._brand_share(f.name, real) >= 0.5:
                    result = True
                elif not known and not f.folders and len(items) <= 60:
                    result = True                   # a small flat folder we know nothing about: keep it together
                elif depth <= 2 and self._product_shaped(fid):
                    result = True                   # one product with a HUD or extras subfolder, pieces named after it
                else:
                    # Mixed creators. A small flat folder (a gift, a hunt prize, a collab) still moves whole;
                    # a folder with subfolders of different creators is one you organized yourself.
                    result = not f.folders and len(items) <= 25 and named
        self._prod[fid] = result
        return result

    def is_kit(self, fid):
        """True if fid is a product folder, and the outermost one (its parent isn't)."""
        if fid in self._kits:
            return self._kits[fid]
        result = False
        if fid in self.folders and self._product(fid) and not self.hands_off(fid):
            parent = self.folders[fid].parent
            result = not (parent in self.folders and self._product(parent))
        self._kits[fid] = result
        return result

    def kit_summary(self, fid):
        items, _, _ = self.subtree(fid)
        kinds = collections.Counter(self.items[i].kind for i in items)
        creators = collections.Counter(self.items[i].creator for i in items
                                       if self.items[i].type not in PACKAGING_TYPES)
        main = creators.most_common(1)[0][0] if creators else ""
        return {"pieces": len(items), "kinds": kinds.most_common(), "creator": self.creator_rank.get(main)}

    # ---------------------------------------------------------------- views
    def item_view(self, i: Item):
        m = i.mask
        perms = None if m is None else {"copy": bool(m & PERM_COPY), "mod": bool(m & PERM_MODIFY),
                                        "trans": bool(m & PERM_TRANSFER)}
        return {"id": i.id, "name": i.name, "type": i.type, "kind": i.kind, "perms": perms,
                "creator": self.creator_rank.get(i.creator), "created": i.created,
                "thumb": i.thumb or (i.asset if i.type in PIC_TYPES else ""),   # a texture can show itself
                "manual": self.hands_off(i.parent)}

    def folder_card(self, fid):
        f = self.folders[fid]
        items, nf, _ = self.subtree(fid)
        card = {"id": fid, "name": f.name, "system": f.system, "ptype": f.ptype,
                "items": len(items), "folders": nf, "kit": self.is_kit(fid), "manual": self.hands_off(fid),
                "split": fid in self.split, "joined": fid in self.joined, "skipped": fid in self.skipped}
        if card["kit"]:
            card["summary"] = self.kit_summary(fid)
        card["thumb"] = f.thumb or (self._first_thumb(items) if card["kit"] else "")
        if not card["thumb"] and f.pic and card["kit"]:
            card["thumb"], card["pic_guess"] = f.pic, True
        card["created"] = self.newest(items)
        return card

    def newest(self, item_ids):
        """When the newest thing in this set arrived in the inventory (unix time), or None."""
        dates = [self.items[i].created for i in item_ids if self.items[i].created]
        return max(dates) if dates else None

    def find_pictures(self, saved=None):
        """For products without a thumbnail, choose a picture texture inside (one Second Life will show:
        it needs a visible asset id). saved: folder id -> texture id from before; kept when it's still
        there or when the texture is gone (deleted packaging), so the picture survives cleaning out.
        Returns the updated folder id -> texture id map."""
        saved = dict(saved or {})
        out = {}
        for fid, f in self.folders.items():
            f.pic = ""
            if fid == self.root or f.thumb or f.system or self.in_trash(fid):
                continue
            # Its own textures and those one level down (where products keep them). Whether it counts as a
            # product is decided later, when it's shown, so splitting or keeping folders together is fine.
            items = list(f.items) + [i for c in f.folders if c in self.folders for i in self.folders[c].items]
            words = set(re.findall(r"[a-z0-9]{3,}", f.name.lower()))
            best, best_score = "", None
            texs = [self.items[i] for i in items if self.items[i].type in PIC_TYPES and self.items[i].asset]
            if len(texs) == 1 and not PIC_MAP.search(texs[0].name.strip()):
                # A product with just one texture: that's almost always its ad, whatever it's called.
                best, best_score = texs[0].asset, 0
                items = []
            for i in items:
                it = self.items[i]
                if it.type not in PIC_TYPES or not it.asset:
                    continue
                if it.asset == saved.get(fid):
                    best, best_score = it.asset, 99
                    break
                name = it.name.lower().strip()
                bad = bool(PIC_BAD.search(name))
                if bad and not PIC_GOOD.search(name):
                    continue
                score = 2 * bool(PIC_GOOD.search(name)) + len(words & set(re.findall(r"[a-z0-9]{3,}", name))) - bad
                if best_score is None or score > best_score:
                    best, best_score = it.asset, score
            best = best or saved.get(fid, "")
            if best:
                f.pic = best
                out[fid] = best
        # keep pictures for products that are in the trash or not in this read, in case they come back
        for fid, tid in saved.items():
            if fid not in out and (fid not in self.folders or self.in_trash(fid)):
                out[fid] = tid
        return out

    def _first_thumb(self, item_ids):
        for i in item_ids:
            t = self.items[i].thumb
            if t and self.items[i].type not in PACKAGING_TYPES:
                return t
        return ""

    def folder_view(self, fid, limit=600):
        fid = fid or self.root
        f = self.folders[fid]
        crumbs = [{"id": self.root, "name": "My Inventory"}] + \
                 [{"id": c, "name": self.folders[c].name} for c in self.chain(fid)]
        subs = sorted((self.folder_card(c) for c in f.folders),
                      key=lambda c: (not c["system"], c["name"].lower()))
        items = sorted((self.items[i] for i in f.items), key=lambda i: i.name.lower())
        view = {"id": fid, "name": "My Inventory" if fid == self.root else f.name, "crumbs": crumbs,
                "folders": subs, "items": [self.item_view(i) for i in items[:limit]],
                "item_total": len(items), "kit": self.is_kit(fid) if fid != self.root else False,
                "manual": fid != self.root and self.hands_off(fid), "split": fid in self.split,
                "joined": fid in self.joined, "system": f.system}
        skip = self.skipped_by(fid) if fid != self.root else None
        if skip:
            view["skipped"] = {"id": skip, "name": self.folders[skip].name, "self": skip == fid}
        if view["kit"]:
            view["summary"] = self.kit_summary(fid)
        view["thumb"] = f.thumb or (f.pic if view["kit"] else "")
        return view

    def search(self, q, limit=150):
        q = q.strip().lower()
        if len(q) < 2:
            return {"folders": [], "items": []}
        folders = [self.folder_card(f.id) | {"path": self.path_text(f.parent)}
                   for f in self.folders.values() if q in f.name.lower() and not self.in_trash(f.id)][:limit]
        items = [self.item_view(i) | {"path": self.path_text(i.parent), "folder": i.parent}
                 for i in self.items.values() if q in i.name.lower() and not self.in_trash(i.parent)][:limit]
        return {"folders": folders, "items": items}

    # ---------------------------------------------------------------- overview
    def overview(self):
        live = [i for i in self.items.values() if not self.in_trash(i.parent)]
        types = collections.Counter(i.type for i in live)
        trash_items = sum(1 for i in self.items.values() if self.in_trash(i.parent))
        empty = [f for f in self.folders.values()
                 if not f.system and not f.folders and not f.items and not self.in_trash(f.id) and f.id != self.root]
        kits = [f for f in self.folders if not self.in_trash(f) and self.is_kit(f)]
        # likely duplicates, split packaging vs real items
        groups = collections.defaultdict(list)
        for i in live:
            if i.type in ("link", "link_f"):
                continue
            groups[(i.name.lower(), i.type, i.creator)].append(i)
        pack_extra = item_extra = 0
        for g in groups.values():
            if len(g) < 2:
                continue
            spread = len({i.parent for i in g})
            if g[0].type in PACKAGING_TYPES or (g[0].type in ("lsltext", "sound") and len(g) >= 3
                                                and spread >= 0.8 * len(g)):
                pack_extra += len(g) - 1
            else:
                item_extra += len(g) - 1
        return {
            "saved": self.saved.strftime("%Y-%m-%d %H:%M"),
            "items": len(live), "folders": sum(1 for f in self.folders if not self.in_trash(f)),
            "creators": len({i.creator for i in live}),
            "types": [{"type": t, "label": TYPE_PLURAL.get(t, t), "count": n,
                       "packaging": t in PACKAGING_TYPES} for t, n in types.most_common()],
            "trash": getattr(self, "trash_count", 0) if self.live else trash_items,
            "empty_folders": len(empty), "kits": len(kits), "live": self.live,
            "thumbs": sum(1 for i in live if i.thumb),
            "folder_thumbs": sum(1 for f in self.folders.values() if f.thumb and not self.in_trash(f.id)),
            "packaging": sum(types[t] for t in PACKAGING_TYPES),
            "dup_packaging": pack_extra, "dup_items": item_extra,
        }


LIBRARY_OWNER = "ba2a564a-f0f1-4b82-9c61-b7520bfcd09f"   # Second Life's built-in Library


def is_library(path: Path):
    """Firestorm saves Second Life's built-in Library in its own cache file. It's read-only for
    everyone (it can't be moved or deleted), so the app never sorts it. Its root folder is
    called "Library" and, unlike a real inventory, it has no Trash folder."""
    if path.name.lower().startswith(LIBRARY_OWNER):
        return True
    try:
        raw = gzip.decompress(path.read_bytes())
    except OSError:
        return False
    head = raw[:400_000]
    has_library_root = b"s\x00\x00\x00\x07Library" in head
    has_trash = b"s\x00\x00\x00\x05trash" in raw
    return has_library_root and not has_trash


_lib_cache: dict[tuple, bool] = {}


def list_inventories(extra=()):
    out = []
    for p in find_caches(extra):
        try:
            st = p.stat()
            key = (str(p), st.st_mtime, st.st_size)
            if key not in _lib_cache:
                _lib_cache[key] = is_library(p)
        except OSError:
            continue
        if _lib_cache[key]:
            continue
        out.append({"path": str(p), "saved": datetime.datetime.fromtimestamp(st.st_mtime)
                    .strftime("%Y-%m-%d %H:%M"), "bytes": st.st_size})
    return out
