"""Suggest a category for everything in the inventory.

What gets sorted ("units"):
  * a product folder, as one whole (its pieces stay together) - the default for any folder
    that isn't one of your own organizing folders or a sorting-category folder
  * a loose item that isn't inside a product folder
  * "pieces": every single item inside a product, plus loose notecards, landmarks and calling
    cards. A piece is never suggested anywhere and stays with its product (or where it is);
    it only moves when you move or trash that one item yourself, or choose "Clean out
    packaging" (which marks a product's notecards, landmarks and scripts for Trash).
Links, Trash, and system folders other than Objects, Lost And Found and Received Items
are left alone (they're listed as "Left for you to sort by hand").

What a suggestion is based on - the NAME only (item name, or folder name plus its pieces'
names; descriptions are never read), from four signals:
  0. the item's own Second Life type, when it settles it (a Shape is a shape, Eyes are eyes)
  1. keyword rules attached to each category (editable)
  2. learning from what is ALREADY in the user's category folders
     (a simple word-frequency model per category)
  3. the creator: if most of a creator's sorted things are in one category
Low-confidence things go to "Not sure yet" instead of guessing.
"""
from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass, field

from .categories import app_made_folders
from .inventory import PACKAGING_TYPES, Inventory, category_key, cleanable

UNSURE = "unsure"
TRASH = "trash"
SETTINGS = "settings"          # the system Settings folder (windlights / environment settings)
LANDMARKS = "landmarks"        # the system Landmarks folder
SPECIAL = {SETTINGS: "Settings", LANDMARKS: "Landmarks"}
SKIP_FOLDER_NAMES = re.compile(r"^#(firestorm|rlv)\b", re.I)
WEARABLE_TYPES = {"clothing", "bodypart"}
TEXTURE_TYPES = {"texture", "snapshot", "material"}

# Body and head brand / model names. Clothing and makeup almost always list the bodies and heads they fit
# ("Dress [Legacy, Reborn, Maitreya]"), so these words say nothing about what a thing IS. Ignored everywhere.
FIT_WORDS = set("""legacy reborn maitreya lara kupra ebody belleza isis freya venus slink physique hourglass
inithium kiwi perky signature gianni jake geralissa meshbody lelutka genus catwa evox evo bento bom
waifu erika lilly altamura fitted fitmesh petite curvy classic""".split())

STOP = set("""the and with for from new set sets pack packs unpacked unpack box boxed fatpack fat add copy mod trans
nomod notrans demo hud huds version edition texture textures color colour colors colours mesh full perm perms
black white red blue green yellow orange pink purple brown grey gray beige cream gold silver tan navy teal
light dark small medium large big mini one two three four five six six seven eight nine ten left right
your my our this that all only per item items bundle collection rez rezz rezzable wear wearable
male female unisex men mens women womens his hers metal metals
""".split()) | FIT_WORDS

# The item's own Second Life type -> the starter category it belongs in (top name, sub name).
# Only types that settle the question; shirts, pants etc. could be many things.
TYPE_HINT = {
    "Shape": ("Body", "Shapes"),
    "Skin": ("Body", "Skins & Body Appliers"),
    "Eyes": ("Head & Face", "Eyes"),
    "Hair": ("Hair", "Hairbases"),
}
APPEARANCE_TOPS = {"clothing", "shoes", "jewelry", "accessories", "hair", "head & face", "body",
                   "held & worn accessories", "animations", "pets"}


def tokens(text):
    out = []
    for w in re.findall(r"[a-z][a-z']+", text.lower()):
        w = w.strip("'")
        if len(w) >= 3 and w not in STOP:
            out.append(w)
    return out


def norm_text(text):
    # Letters and numbers are split apart, so "hold1L" reads as "hold 1 l" and "Jeans-4" as "jeans 4".
    return " " + " ".join(re.findall(r"[a-z]+|[0-9]+", text.lower())) + " "


# Skins and appliers: what decides face vs body is which head or body the name says it's for.
# (These names are ignored everywhere else: clothing lists them too, and they say nothing about what it is.)
HEAD_FIT = re.compile(r"\b(lelutka|lelu|lel|leluevox|evo[\s._-]?x|evox|evolution|evl|genus|catwa|head|heads|face)\b", re.I)
BODY_FIT = re.compile(r"\b(legacy|maitreya|mait|reborn|kupra|ebody|belleza|slink|physique|isis|freya|venus|waifu|"
                      r"geralissa|inithium|perky|lara|body|bodies)\b", re.I)
# Textures for a body or face (applied with a HUD), not texture packs for building.
BODY_TEXTURE = re.compile(r"(neck\s*blend|blend|skin|tattoo|make\s*up|makeup|lipstick|lips|eyeshadow|eye\s*shadow|"
                          r"blush|freckles?|brows?|eyes?|applier|bom|nails?|body|face|head)", re.I)
# Made for a specific body or head: worn, so appearance, never decor (a "boots" display has no Legacy version).
WORN_FIT = re.compile(r"\b(legacy|maitreya|mait|lara|reborn|kupra|ebody|belleza|isis|freya|venus|slink|physique|"
                      r"hourglass|inithium|kiwi|waifu|geralissa|perky|lelutka|lelu|lel|leluevox|evo ?x|evox|genus|"
                      r"catwa|gianni|jake|signature|fitmesh|fitted mesh|bom|evo[\s._-]?x)\b", re.I)
STORE_PREFIX = re.compile(r"^\s*(?:[\[({<].{1,40}?[\])}>]|[.:=*~#_-]+[^.:=*~#_\-]{1,40}?[.:=*~#_-]+)\s*(?:[-:|/]\s*)?")


def _without_store(name):
    """The name without a store tag at the front: "[avarosa] HD Brows" -> "HD Brows",
    ".The Honey Shop. - LeluEvoX ..." -> "LeluEvoX ...", "Pepe Skins - Starlight" -> "Starlight"."""
    rest = STORE_PREFIX.sub("", name, count=1)
    if rest == name and " - " in name:
        head, tail = name.split(" - ", 1)
        if 0 < len(head.split()) <= 3 and len(tail.strip()) >= 3:
            rest = tail
    rest = rest.strip(" -:|/")
    return rest if len(rest) >= 3 else name


def _store_phrase(name):
    """The store's name at the front of a product name ("Pepe Skins - Starlight" -> "Pepe Skins"), if any."""
    m = STORE_PREFIX.match(name)
    if m:
        return m.group(0).strip(" -:|/")
    head = name.split(" - ", 1)[0].strip()
    return head if " - " in name and 0 < len(head.split()) <= 3 else ""


def _skin_named_inside(u):
    """A skin named in the pieces inside ("Jin Ae Skin (Sunkiss)"), not counting the store's own name, in a pack
    that's mostly layers rather than mesh objects (a mesh body comes with skin layers too)."""
    if u.layers < 0.25 or u.objects > u.layers:
        return False
    text = u.text or ""
    store = _store_phrase(u.name)
    if store:
        text = re.sub(re.escape(store), " ", text, flags=re.I)
    return bool(SKIN_WORDS.search(text))


SKIN_WORDS = re.compile(r"\b(skins?|appliers?|bom tones?|tones?|tone \d+)\b", re.I)
LAYER_KINDS = {"Tattoo layer", "Universal", "Skin"}       # BOM layers: what skins and makeup are made of
# Skins usually come with a matching shape, brows or the head's own bits: those don't argue against "skin".
BUNDLED_WITH_SKINS = {("body", "shapes"), ("head & face", "eyebrows"), ("head & face", "mesh heads"),
                      ("body", "mesh bodies"), ("head & face", "face skins & appliers"), ("body", "skins & body appliers")}
SKIN_SUBS = {("head & face", "face skins & appliers"), ("body", "skins & body appliers"),
             ("head & face", "mesh heads"), ("body", "mesh bodies")}


def _perm_label(it):
    if it.mask is None:
        return ""
    return " · " + ("Copy" if it.mask & (1 << 15) else "No copy")


@dataclass
class Unit:
    id: str
    kind: str                 # "product", "item" or "piece" (one item inside a product, or loose packaging)
    name: str
    folder: str               # where it is now (its own folder for products, parent folder for items)
    parent: str               # folder that would be moved out of / item's parent
    thumb: str
    creator: str
    label: str                # "Product · 4 Objects · Notecard" / "Object · Copy"
    text: str                 # text used for matching
    words: list = field(default_factory=list)
    current: str | None = None     # category id it already sits in
    wearable: bool = False
    nocopy: bool = False
    created: int | None = None     # when it arrived in the inventory (newest piece, for products)
    hint: str = ""                 # item type that settles the category ("Shape", "Eyes"...)
    pieces: list = field(default_factory=list)   # product only: ids of its packaging pieces' units
    product: str = ""              # piece only: the product unit it's inside ("" for loose packaging)
    kname: str = ""                # the name used for keyword matching (store name taken out)
    pack: bool = False             # piece only: packaging (notecard, landmark, texture...)
    layers: float = 0.0            # share of its pieces that are BOM layers (tattoo / universal / skin)
    frozen: bool = False           # inside a folder you skipped: learned from, never suggested or moved
    skin_parts: bool = False       # holds actual skin pieces: BOM layers, a Skin or a Shape (not just a box/HUD)
    objects: float = 0.0           # share of its pieces that are objects (mesh, HUDs, boxes)
    textures: bool = False         # product only: a texture / material pack (the textures ARE the product)
    learned: str | None = None     # category of an old folder of yours it sits in (outside "Sorted"): it's
                                   # learned from and headed there, but still has to move into the sorted folder
    pic_guess: bool = False        # product only: its picture is a texture found inside, not a real thumbnail
    home: str = ""                 # sits in the Settings or Landmarks system folder ("settings" / "landmarks")
    special: str = ""              # belongs in one: a settings item or settings pack, or a landmark


class Sorter:
    def __init__(self, inv: Inventory, categories: dict):
        self.inv = inv
        self.set_categories(categories)

    # ------------------------------------------------------------------ categories
    def set_categories(self, categories):
        self.cats = categories
        self.subs = {}          # id -> {"id","name","top","keywords"}
        self.tops = {}
        self.top_keys = {}      # top id -> names its folder may have
        self.sub_keys = collections.defaultdict(list)   # folder-name key -> [(sub id, distinctive)]
        self.kw_index = collections.defaultdict(list)   # first word -> [(category, phrase, words)]
        self.by_name = {}       # (top name lower, sub name lower) -> sub id
        all_names = []
        for top in categories["categories"]:
            self.tops[top["id"]] = top
            tnames = [top["name"], *top.get("aliases", [])]
            self.top_keys[top["id"]] = {category_key(n) for n in tnames}
            all_names += tnames
            for c in top["children"]:
                self.subs[c["id"]] = {"id": c["id"], "name": c["name"], "top": top["id"],
                                      "appearance": top["name"].lower() in APPEARANCE_TOPS,
                                      "keywords": [(norm_text(k), len(k.split())) for k in c.get("keywords", [])]}
                self.by_name[(top["name"].lower(), c["name"].lower())] = c["id"]
                for n in [c["name"], *c.get("aliases", [])]:
                    # A name like "Decor - Mirrors" or "PURSES/BAGS" can only mean one thing; a plain
                    # "Ceiling" or "Tops" only counts inside its parent category's folder.
                    distinctive = (bool(re.search(r" - |/|\+|'", n)) or len(n.split()) >= 3
                                   or (n.isupper() and len(n) > 3))
                    self.sub_keys[category_key(n)].append((c["id"], distinctive))
                    all_names.append(n)
                for kw, n in self.subs[c["id"]]["keywords"]:
                    first = kw.split()[0] if kw.strip() else ""
                    if first:
                        self.kw_index[first].append((c["id"], kw, n))
        self.inv.set_categories(all_names)
        self._build_units()
        self.train({})

    # ------------------------------------------------------------------ units
    def _folder_category(self, fid):
        """Category id of the nearest category folder at or above fid (matched by its place in the tree)."""
        chain = self.inv.chain(fid)
        keys = [category_key(self.inv.folders[f].name) for f in chain]
        for i in range(len(chain) - 1, -1, -1):
            cands = self.sub_keys.get(keys[i])
            if not cands:
                continue
            above = set(keys[:i])
            for sid, _ in cands:
                if self.top_keys[self.subs[sid]["top"]] & above:
                    return sid
            if len(cands) == 1 and cands[0][1]:
                return cands[0][0]
        return None

    def in_sorted(self, fid):
        """Inside the parent folder ("Sorted") or a folder this app made. Always true with the option off."""
        if not self.parent_setting():
            return True
        inv = self.inv
        homes = getattr(self, "_homes", None)
        if homes is None:
            homes = self._homes = app_made_folders() | ({self.parent_folder()} if self.parent_folder() else set())
        seen = 0
        while fid in inv.folders and fid != inv.root and seen < 200:
            if fid in homes:
                return True
            fid, seen = inv.folders[fid].parent, seen + 1
        return False

    def category_folders(self):
        """Existing folders for each subcategory and top category: ({sub id: [folder ids]}, {top id: [ids]}).
        Top folders only count directly in My Inventory, or directly inside the parent folder
        (e.g. "Sorted") when that option is on.

        With the parent folder option on, only folders already inside it, or ones this app made,
        are reused. The person's own older folders (half sorted, say) are left alone, and fresh
        category folders are made inside the parent instead."""
        subs, tops = collections.defaultdict(list), collections.defaultdict(list)
        inv = self.inv
        parent = self.parent_folder()
        top_homes = {inv.root} | ({parent} if parent else set())
        own = app_made_folders() if self.parent_setting() else None

        homes = (own or set()) | ({parent} if parent else set())

        def ours(fid):
            """Inside the parent folder or a folder this app made (or is one of those)."""
            seen = 0
            while fid in inv.folders and fid != inv.root and seen < 200:
                if fid in homes:
                    return True
                fid, seen = inv.folders[fid].parent, seen + 1
            return False

        old = collections.defaultdict(list)     # your older category folders outside the parent folder
        for fid, f in inv.folders.items():
            if fid == inv.root or f.system or inv.in_trash(fid) or inv.hands_off(fid):
                continue
            key = category_key(f.name)
            outside = own is not None and not ours(fid)
            if key in self.sub_keys and self._folder_category(fid) and \
                    any(sid == self._folder_category(fid) for sid, _ in self.sub_keys[key]):
                if outside:
                    if not inv.skipped_by(fid):
                        old[self._folder_category(fid)].append(fid)
                    continue
                subs[self._folder_category(fid)].append(fid)
            if outside:
                continue
            if f.parent in top_homes:
                for tid, keys in self.top_keys.items():
                    if key in keys:
                        tops[tid].append(fid)
        size = lambda x: len(inv.subtree(x)[0])  # noqa: E731
        # A category with no folder in the parent folder yet reuses your biggest older one: a run renames it
        # and moves it in, instead of making a new folder and moving everything one by one.
        self.adopted = {}
        for sid, fids in old.items():
            if sid not in subs:
                best = max(fids, key=size)
                subs[sid] = [best]
                self.adopted[sid] = best
        return ({k: sorted(v, key=size, reverse=True) for k, v in subs.items()},
                {k: sorted(v, key=size, reverse=True) for k, v in tops.items()})

    def parent_setting(self):
        p = self.cats.get("parent_folder") or {}
        return p.get("name") if p.get("on") and p.get("name") else None

    def whole_folders_setting(self):
        return bool(self.cats.get("whole_folders", True))

    def parent_folder(self):
        """The existing parent folder for all category folders (directly in My Inventory), if the option is on."""
        name = self.parent_setting()
        if not name:
            return None
        inv = self.inv
        hits = [fid for fid in inv.folders.get(inv.root).folders
                if not inv.folders[fid].system and inv.folders[fid].name.strip().lower() == name.lower()] \
            if inv.root in inv.folders else []
        return max(hits, key=lambda x: len(inv.subtree(x)[0])) if hits else None

    def _skip_folder(self, f):
        return f.hands_off or f.ptype == "trash" or bool(SKIP_FOLDER_NAMES.match(f.name))

    def _build_units(self):
        inv = self.inv
        self._homes = None
        self.units: dict[str, Unit] = {}
        self.manual = []        # system folders left for sorting by hand: [{"name", "count"}]
        self.skipped = []       # folders you skipped: [{"id", "name", "count"}]
        stack = [inv.root] if inv.root else []
        while stack:
            fid = stack.pop()
            f = inv.folders[fid]
            if fid != inv.root and self._skip_folder(f):
                if f.hands_off and f.parent == inv.root:
                    n = sum(1 for i in inv.subtree(fid)[0] if inv.items[i].type not in ("link", "link_f"))
                    if n:
                        self.manual.append({"id": fid, "name": f.name, "count": n})
                continue
            if fid != inv.root and inv.is_kit(fid):
                self._add_product(fid)
                continue
            for iid in f.items:
                it = inv.items[iid]
                if it.type in ("link", "link_f"):
                    continue
                if it.type in PACKAGING_TYPES:
                    # Loose notecards / landmarks are never suggested anywhere, but you can still trash
                    # (or move) one yourself.
                    self._add_piece(it, product=None)
                    continue
                self._add_item(it)
            stack.extend(f.folders)
        self.manual.sort(key=lambda m: m["name"].lower())
        # With "keep category folders inside one folder" on, only folders in there (or ones this app made)
        # are where things belong. Something in an older folder of yours with a category name (say
        # "Appearance › Jewelry › PURSES/BAGS") isn't sorted yet: it's headed to that category in "Sorted".
        # Settings and landmarks have their own system folders.
        for u in self.units.values():
            loc = u.folder if u.kind == "product" else u.parent
            u.home = inv.special_home(loc)
            if u.kind == "product":
                kinds = [inv.items[i].type for i in inv.subtree(u.folder)[0]
                         if inv.items[i].type not in PACKAGING_TYPES | {"link", "link_f", "texture", "snapshot"}]
                # A settings pack is only settings (plus notecards, landmarks, pictures). Clothing that comes
                # with a few windlights stays clothing: its windlights are pulled out to Settings on their own.
                if kinds and all(t in ("settings", "lsltext") for t in kinds) and "settings" in kinds:
                    u.special = SETTINGS
            else:
                it = inv.items.get(u.id[2:])
                t = it.type if it else ""
                u.special = SETTINGS if t == "settings" else LANDMARKS if t == "landmark" else ""
        if self.parent_setting():
            self.category_folders()                 # works out which older folders get reused
            for u in self.units.values():
                loc = u.folder if u.kind == "product" else u.parent
                if u.current and not self.in_sorted(loc) and self.adopted.get(u.current) not in inv.chain(loc):
                    u.learned, u.current = u.current, None
        # Folders you skipped: everything inside is still learned from (they're usually your best-sorted
        # folders), but it's never suggested anywhere, moved, renamed or trashed.
        if inv.skipped:
            for u in self.units.values():
                if inv.skipped_by(u.folder if u.kind == "product" else u.parent):
                    u.frozen = True
            for fid in sorted(inv.skipped & set(inv.folders), key=lambda x: inv.path_text(x).lower()):
                n = sum(1 for i in inv.subtree(fid)[0] if inv.items[i].type not in ("link", "link_f"))
                self.skipped.append({"id": fid, "name": inv.folders[fid].name, "path": inv.path_text(fid), "count": n})

    @staticmethod
    def _hint_for(kinds):
        """One item type that settles it, if every real piece is that type."""
        kinds = [k for k in kinds if k]
        if kinds and all(k == kinds[0] for k in kinds) and kinds[0] in TYPE_HINT:
            return kinds[0]
        return ""

    def _texture_pack(self, items, name=""):
        """Mostly textures and materials, with nothing to wear or rez: a texture pack.
        Not when it's for a body or face (neck blends, skin or makeup textures for appliers)."""
        inv = self.inv
        if WORN_FIT.search(name) or BODY_TEXTURE.search(name):
            return False
        kinds = [inv.items[i].type for i in items if inv.items[i].type not in PACKAGING_TYPES | {"link", "link_f", "lsltext"}]
        if not kinds or any(t in WEARABLE_TYPES or t == "object" for t in kinds):
            return False
        return sum(1 for t in kinds if t in TEXTURE_TYPES) / len(kinds) >= 0.8

    def _add_product(self, fid):
        inv = self.inv
        f = inv.folders[fid]
        items, _, _ = inv.subtree(fid)
        real = [inv.items[i] for i in items if inv.items[i].type not in PACKAGING_TYPES | {"link", "link_f"}]
        summary = inv.kit_summary(fid)
        kinds = " · ".join(f"{n} {k}{'s' if n > 1 and not k.endswith('s') else ''}" for k, n in summary["kinds"][:3])
        creator = collections.Counter(i.creator for i in real).most_common(1)[0][0] if real else ""
        # The store's name ("BLUSH", "DOUX") usually starts the folder and every piece; it says nothing
        # about what the product is (and "BLUSH" isn't makeup), so it's left out of keyword matching.
        brand = ""
        m = re.match(r"\W*([^\W_]{3,})", f.name)
        if m and inv._brand_share(f.name, real) >= 0.5:
            brand = m.group(1)
        strip = (lambda t: re.sub(rf"(?i)\b{re.escape(brand)}\b", " ", t)) if brand else (lambda t: t)
        named = [i for i in real if i.type != "lsltext"]      # a "Resize Script" says nothing about what it is
        text = strip(f.name + " " + " ".join(i.name for i in named[:40]))
        wear = sum(1 for i in real if i.type in WEARABLE_TYPES)
        uid = "f:" + fid
        u = Unit(id=uid, kind="product", name=f.name, folder=fid, parent=f.parent,
                 thumb=f.thumb or inv._first_thumb(items) or f.pic, pic_guess=not (f.thumb or inv._first_thumb(items)) and bool(f.pic),
                 creator=creator, label=f"Product · {kinds}",
                 text=text, kname=strip(f.name),
                 words=tokens(strip(f.name)) * 2 + tokens(strip(" ".join(i.name for i in named[:40]))),
                 current=self._folder_category(fid), wearable=bool(real) and wear / len(real) > 0.5,
                 nocopy=any(i.mask is not None and not i.mask & (1 << 15) for i in real),
                 created=inv.newest(items),
                 hint=self._hint_for([i.kind for i in real if i.type in WEARABLE_TYPES])
                 if real and wear == len(real) else "",
                 layers=sum(1 for i in real if i.kind in LAYER_KINDS) / len(real) if real else 0.0,
                 skin_parts=any(i.kind in LAYER_KINDS or i.kind == "Shape" for i in real),
                 objects=sum(1 for i in real if i.type == "object") / len(real) if real else 0.0,
                 textures=self._texture_pack(items, f.name))
        self.units[uid] = u
        # Every item inside gets its own handle, so you can move or trash just that one item while the
        # rest of the product stays together. Packaging (notecards, landmarks, scripts) is also what
        # "Clean out packaging" marks for Trash.
        kinds = [inv.items[i].type for i in items if inv.items[i].type not in PACKAGING_TYPES | {"link", "link_f"}]
        scripts_are_product = bool(kinds) and sum(1 for t in kinds if t == "lsltext") / len(kinds) >= 0.8
        for iid in items:
            it = inv.items[iid]
            if it.type in ("link", "link_f"):
                continue
            pid = self._add_piece(it, product=u)
            if u.textures and it.type in TEXTURE_TYPES:
                self.units[pid].pack = False     # in a texture pack the textures are what you bought
            if it.type == "lsltext" and scripts_are_product:
                self.units[pid].pack = False     # a script kit: the scripts are what you bought
            elif cleanable(it):
                u.pieces.append(pid)

    def _add_piece(self, it, product):
        pid = "p:" + it.id
        where = f" · in {product.name}" if product else ""
        self.units[pid] = Unit(id=pid, kind="piece", name=it.name, folder=it.parent, parent=it.parent,
                               thumb=it.thumb, creator=it.creator, label=f"{it.kind}{_perm_label(it)}{where}",
                               text=it.name, current=None,
                               nocopy=it.mask is not None and not it.mask & (1 << 15),
                               created=it.created, product=product.id if product else "",
                               pack=cleanable(it), wearable=it.type in WEARABLE_TYPES)
        return pid

    def _add_item(self, it):
        u = Unit(id="i:" + it.id, kind="item", name=it.name, folder=it.parent, parent=it.parent, thumb=it.thumb,
                 creator=it.creator, label=f"{it.kind}{_perm_label(it)}", text=it.name, words=tokens(it.name) * 2,
                 current=self._folder_category(it.parent), wearable=it.type in WEARABLE_TYPES,
                 nocopy=it.mask is not None and not it.mask & (1 << 15), created=it.created,
                 hint=it.kind if it.type in WEARABLE_TYPES and it.kind in TYPE_HINT else "",
                 layers=1.0 if it.kind in LAYER_KINDS else 0.0, skin_parts=it.kind in LAYER_KINDS)
        self.units[u.id] = u

    def unit_of(self, kind, oid):
        """The unit that moves when you move this item or folder, or None if it doesn't move on its own.
        An item inside a product is its own piece; a subfolder inside a product moves with the product."""
        inv = self.inv
        if kind == "item":
            if oid not in inv.items:
                return None
            for prefix in ("i:", "p:"):
                if prefix + oid in self.units:
                    return prefix + oid
            folder = inv.items[oid].parent
        else:
            if "f:" + oid in self.units:
                return "f:" + oid
            folder = inv.folders[oid].parent if oid in inv.folders else None
        while folder and folder in inv.folders and folder != inv.root:
            if "f:" + folder in self.units:
                return "f:" + folder
            folder = inv.folders[folder].parent
        return None

    # ------------------------------------------------------------------ learning
    def train(self, overrides):
        """Learn word and creator patterns from things already in category folders (+ the user's moves)."""
        word_counts = collections.defaultdict(collections.Counter)
        cat_docs = collections.Counter()
        creator_cats = collections.defaultdict(collections.Counter)
        vocab = set()
        for u in self.units.values():
            if u.kind == "piece":
                continue
            cat = overrides.get(u.id) or u.current or u.learned
            if not cat or cat == UNSURE or cat not in self.subs:
                continue
            words = set(u.words)
            word_counts[cat].update(words)
            vocab |= words
            cat_docs[cat] += 1
            if u.creator:
                creator_cats[u.creator][cat] += 1
        self.word_counts, self.cat_docs, self.creator_cats = word_counts, cat_docs, creator_cats
        # How reliable each keyword is in YOUR inventory: of the sorted things whose own name has it,
        # how many sit in the category the keyword points to. ("maple" -> Trees is wrong for "Maple Studio".)
        rel = collections.defaultdict(lambda: [0, 0])
        rel_worn = collections.defaultdict(lambda: [0, 0])
        self.unit_kw = {}
        for u in self.units.values():
            if u.kind == "piece":
                continue
            cat = overrides.get(u.id) or u.current or u.learned
            if not cat or cat == UNSURE or cat not in self.subs:
                continue
            hits = self._name_keywords(u)
            worn = bool(WORN_FIT.search(u.text or u.name))
            self.unit_kw[u.id] = (cat, hits, worn)
            for key in hits:
                rel[key][1] += 1
                rel[key][0] += key[0] == cat
                if worn:
                    rel_worn[key][1] += 1
                    rel_worn[key][0] += key[0] == cat
        self.kw_rel, self.kw_rel_worn = rel, rel_worn
        self.vocab_size = max(len(vocab), 1)
        self.total_docs = sum(cat_docs.values())
        # Precomputed so scoring a unit only touches the categories its words appear in.
        alpha = 0.1
        self.prior = {c: math.log(d / self.total_docs) for c, d in cat_docs.items()} if self.total_docs else {}
        self.miss = {c: math.log(alpha / (d + 2 * alpha)) for c, d in cat_docs.items()}
        self.postings = collections.defaultdict(list)
        self.df = collections.Counter()
        for wc in word_counts.values():
            for w, k in wc.items():
                self.df[w] += k
        for c, wc in word_counts.items():
            for w, k in wc.items():
                self.postings[w].append((c, math.log((k + alpha) / alpha)))
        self._cache = {}

    def _keyword_scores(self, u: Unit):
        text = norm_text(u.text)
        name = norm_text(u.kname or u.name)
        scores = collections.Counter()
        seen = set()
        for word in set(text.split()):
            for cid, kw, n in self.kw_index.get(word, ()):
                if (cid, kw) in seen or kw not in text:
                    continue
                seen.add((cid, kw))
                weight = 1.0 + 0.8 * (n - 1)          # phrases count more than single words
                if kw in name:
                    weight *= 1.6                     # the product/item's own name counts most
                scores[cid] += weight
        return scores

    def _nb_probs(self, u: Unit):
        if self.total_docs < 25 or not u.words:
            return {}
        words = set(u.words)
        # Only words seen at least twice in sorted folders count as evidence; rare words make wild guesses.
        hits = [self.postings[w] for w in words if self.df.get(w, 0) >= 2]
        if not hits or (len(hits) < 2 and len(words) > 2):
            return {}          # too few of these words were ever seen in sorted folders to judge
        words = {w for w in words if self.df.get(w, 0) >= 2}
        n = len(words)
        logs = {c: self.prior[c] + n * self.miss[c] for c in self.prior}
        for plist in hits:
            for c, bonus in plist:
                logs[c] += bonus
        # A category needs a few examples before its words mean anything: one sneaker with "male"/"female"
        # pieces shouldn't make every male/female thing a sneaker.
        logs = {c: v for c, v in logs.items() if self.cat_docs.get(c, 0) >= 3}
        if not logs:
            return {}
        top = max(logs.values())
        exp = {c: math.exp(0.6 * (v - top)) for c, v in logs.items()}     # soften: word counts are overconfident
        z = sum(exp.values())
        return {c: v / z for c, v in exp.items()}

    def _name_keywords(self, u: Unit):
        """{(category, keyword)} found in the thing's own name (not in its pieces' names)."""
        name = norm_text(u.kname or u.name)
        out = set()
        for word in set(name.split()):
            for cid, kw, _ in self.kw_index.get(word, ()):
                if kw in name:
                    out.add((cid, kw))
        return out

    def _kw_reliable(self, u: Unit, key, worn=False):
        """None: never seen in your sorted folders; else True/False. A thing never vouches for itself.
        For worn things, only other worn things count ("heels" displays in decor don't)."""
        table = getattr(self, "kw_rel_worn" if worn else "kw_rel", {})
        hit, total = table.get(key, (0, 0))
        mine = self.unit_kw.get(u.id) if hasattr(self, "unit_kw") else None
        if mine and key in mine[1] and (not worn or mine[2]):
            total -= 1
            hit -= mine[0] == key[0]
        if total < 3:
            return None
        return hit / total >= 0.7

    def _clear_word(self, u: Unit, kwp, worn=False):
        """The category a word in the thing's own name points to, when it points one way and your
        sorted folders confirm that word means that category for you."""
        found = self._name_keywords(u)
        own = collections.Counter()
        for c, kw_ in found:
            own[c] += len(kw_.split())
        if not own:
            return None
        (c1, v1), *rest = own.most_common(2)
        if rest and rest[0][1] >= v1:
            return None            # two different things named equally ("Heels & Bag")
        if kwp.get(c1, 0) < 0.5:
            return None
        verdicts = [self._kw_reliable(u, key, worn) for key in found if key[0] == c1]
        if any(v is False for v in verdicts):
            return None            # you've filed things with this word elsewhere before
        if any(v is True for v in verdicts) or any(len(kw_.split()) > 1 for c, kw_ in found if c == c1):
            return c1              # confirmed by your folders, or a specific phrase ("strappy heels")
        return None

    def _skin_category(self, u: Unit):
        """Skins and appliers: BOM layers, or "skin"/"applier" in the name. Face or body is decided by the
        head or body the name says it's for. Makeup, freckles, brows, tattoos... are left to their words."""
        if u.kind not in ("product", "item"):
            return None
        name = _without_store(u.name)
        named_inside = _skin_named_inside(u)                                # "Jin Ae Skin (Sunkiss)" inside
        if u.layers < 0.6 and not SKIN_WORDS.search(name) and not named_inside:
            return None
        own = self._keyword_scores(Unit(id="", kind=u.kind, name=name, folder="", parent="", thumb="", creator="",
                                        label="", text=name, kname=name))
        # The pieces inside are mostly makeup (lipsticks, liners, blush): it's makeup, whatever the store is called.
        inside = self._keyword_scores(u)
        if inside:
            top_c, top_v = inside.most_common(1)[0]
            sub = self.subs[top_c]
            if (self.tops.get(sub["top"], {}).get("name", "").lower(), sub["name"].lower()) not in BUNDLED_WITH_SKINS \
                    and top_v / sum(inside.values()) >= 0.5:
                return None
        for c in own:
            sub = self.subs[c]
            top = self.tops.get(sub["top"], {}).get("name", "").lower()
            if (top, sub["name"].lower()) not in SKIN_SUBS:
                return None        # the name says what else it is (eyeliner, freckles, nails, a dress...)
        head, body = bool(HEAD_FIT.search(u.name)), bool(BODY_FIT.search(u.name))
        if head == body:
            return None            # says neither, or both: let the other signals decide
        return (self.by_name.get(("head & face", "face skins & appliers")) if head
                else self.by_name.get(("body", "skins & body appliers")))

    def _creator_probs(self, u: Unit):
        cc = self.creator_cats.get(u.creator)
        if not cc or sum(cc.values()) < 3:
            return {}
        z = sum(cc.values())
        return {c: n / z for c, n in cc.items()}

    def _type_category(self, u: Unit):
        if not u.hint:
            return None
        top, sub = TYPE_HINT[u.hint]
        return self.by_name.get((top.lower(), sub.lower()))

    def suggest(self, u: Unit):
        """[(category id, confidence)] best first, and whether it's unsure."""
        if u.id in self._cache:
            return self._cache[u.id]
        if u.kind == "piece":
            self._cache[u.id] = ([], True)
            return self._cache[u.id]
        by_type = self._type_category(u)
        if not by_type and u.kind == "product" and u.textures:
            by_type = self.by_name.get(("build parts", "textures & materials"))
        if by_type:
            self._cache[u.id] = ([(by_type, 0.97)], False)
            return self._cache[u.id]
        kw = self._keyword_scores(u)
        named = any(kw_ in norm_text(u.kname or u.name) for c in kw for kw_, _ in self.subs[c]["keywords"])
        skin = self._skin_category(u)
        named_skin = bool(SKIN_WORDS.search(_without_store(u.name)) or _skin_named_inside(u)) \
            and bool(HEAD_FIT.search(u.name) or BODY_FIT.search(u.name))
        if skin and not (named_skin and u.skin_parts):
            # The name says "skin" but there's only a box or HUD inside (the store "Pepe Skins" sells lipstick too),
            # or only the layers suggested it: let your sorted folders overrule it.
            nb_check = self._nb_probs(u)
            top_nb = max(nb_check, key=nb_check.get) if nb_check else None
            bundled = top_nb and (self.tops.get(self.subs[top_nb]["top"], {}).get("name", "").lower(),
                                  self.subs[top_nb]["name"].lower()) in {("body", "shapes"), ("head & face", "eyebrows")}
            # Mostly skin layers, made for a named head or body: only a strong lean elsewhere overrules that.
            need = 0.6 if u.layers >= 0.6 and (HEAD_FIT.search(u.name) or BODY_FIT.search(u.name)) else 0.4
            if top_nb and top_nb != skin and not bundled and nb_check[top_nb] >= need:
                skin = None        # your folders say this kind of thing goes elsewhere ("Pepe Skins" lipsticks)
        if skin:
            # Whatever the name says, a near-certain lean from your sorted folders wins (the eBody Reborn
            # mesh body comes with skin layers, but you keep it in Mesh Bodies).
            nb_all = self._nb_probs(u)
            top_all = max(nb_all, key=nb_all.get) if nb_all else None
            if top_all and top_all != skin and nb_all[top_all] >= 0.8 and (
                    self.tops.get(self.subs[top_all]["top"], {}).get("name", "").lower(),
                    self.subs[top_all]["name"].lower()) not in {("body", "shapes"), ("head & face", "eyebrows")}:
                skin = None
        if skin:
            self._cache[u.id] = ([(skin, 0.9)], False)
            return self._cache[u.id]
        if u.kind == "product":
            own_cats = {c for c, _ in self._name_keywords(u)}
            if own_cats:
                # The product's own name says what it is ("HD Brows"): words in its pieces' names (the shape
                # that comes with a skin or brows) don't get a say.
                kw = collections.Counter({c: v for c, v in kw.items() if c in own_cats})
        kz = sum(kw.values())
        kwp = {c: v / kz for c, v in kw.items()} if kz else {}
        nb = self._nb_probs(u)
        cr = self._creator_probs(u)
        weights = [(kwp, 0.45), (nb, 0.45), (cr, 0.10)]
        active = sum(w for p, w in weights if p)
        combined = collections.Counter()
        if active:
            for p, w in weights:
                for c, v in p.items():
                    combined[c] += v * w / active
        worn = bool(WORN_FIT.search(u.text or u.name)) and not u.textures   # "Legacy Diffuse" isn't a body
        if worn:
            # Made for a body or head: only appearance categories are candidates.
            combined = collections.Counter({c: v for c, v in combined.items() if self.subs[c].get("appearance")})
            z = sum(combined.values())
            combined = collections.Counter({c: v / z for c, v in combined.items()}) if z else combined
            kwp = {c: v for c, v in kwp.items() if self.subs[c].get("appearance")}
            kz2 = sum(kwp.values())
            kwp = {c: v / kz2 for c, v in kwp.items()} if kz2 else {}
        ranked = combined.most_common(3)
        unsure = True
        if ranked:
            best_c, best = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            signals = sum(1 for p, _ in weights if p and best_c in p and p[best_c] >= 0.3)
            unsure = best < 0.5 or best - second < 0.1 or signals == 0
            if u.kind == "product" and kw and not named and not nb:
                unsure = True        # only a piece's name matched (a hairbase inside a hair pack): just a guess
            if u.wearable and not kw:
                unsure = True        # clothing/body parts with no matching words: don't guess decor
            if self.subs.get(best_c, {}).get("appearance") and (best < 0.6 or best - second < 0.2):
                unsure = True        # appearance is easy to get wrong from a name: only confident guesses
            # A clear word in its own name ("... Strappy Heels") settles it, unless your sorted folders
            # strongly say something else.
            clear = self._clear_word(u, kwp, worn)
            if clear and clear == best_c and not (nb and max(nb, key=nb.get) != clear and max(nb.values()) >= 0.6):
                unsure = False
        ranked = [(c, v) for c, v in ranked if v >= 0.15]      # don't offer wild guesses
        result = ([(c, round(v, 3)) for c, v in ranked], unsure or not ranked)
        self._cache[u.id] = result
        return result
