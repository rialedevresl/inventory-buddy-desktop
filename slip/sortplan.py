"""The user's sorting decisions for one inventory, and the views built on them.

Decisions are saved per inventory in the app-data folder:
  assign   - unit id -> category id (or "unsure"/"trash") the user chose
  approved - category ids the user has checked ("Looks good")
  seen     - for each checked category, what was in it when you checked it; anything new since
             shows the category as unchecked again until you look
  split    - folders the user opened up ("Split into pieces")
  joined   - folders the user said are one product ("Keep together")
Nothing here touches Second Life; it only builds the plan.

v0.9: every item inside a product is its own "piece". Moving or trashing one item inside a product
acts on that item only; the rest of the product stays together. A piece's choice carries over if
the product is later split (the piece becomes a loose item) or kept together again.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from .categories import data_dir
from .inventory import SORTED_SYSTEM_TYPES
from .sorter import LANDMARKS, SETTINGS, SPECIAL, TRASH, UNSURE, Sorter


class SortSession:
    def __init__(self, inv, categories):
        self.inv = inv
        self.lock = threading.RLock()
        # One saved set of choices per avatar (keyed by the avatar's inventory root).
        self.path = data_dir() / f"sort-{inv.root}.json"
        if not self.path.exists() and inv.path:
            old = data_dir() / f"sort-{hashlib.sha1(str(inv.path).lower().encode()).hexdigest()[:12]}.json"
            if old.exists():
                old.replace(self.path)
        self.assign: dict[str, str] = {}
        self.approved: set[str] = set()
        self.locked: dict[str, str] = {}     # suggestions frozen when you checked their category
        self.seen: dict[str, set] = {}        # category id -> unit ids it held when you checked it
        self.done: dict[str, str] = {}       # things a run already moved (unit id -> category or trash)
        self.done_at = 0.0                   # when a run last added to that
        self.split: set[str] = set()
        self.joined: set[str] = set()
        self.hidden: set[str] = set()        # duplicate sets you said aren't duplicates
        self.skipped: set[str] = set()       # folders you told the sorter to leave alone
        self.chosen = False                  # you've picked which folders to sort (asked once, on Sort)
        self._copies = None
        self._trashed = {}
        self._dest = None
        self._lm = None
        self._load()
        self.inv.set_choices(self.split & set(inv.folders), self.joined & set(inv.folders))
        self.inv.skipped = self.skipped & set(inv.folders)
        self.sorter = Sorter(inv, categories)
        self._settle()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.assign = {str(k): str(v) for k, v in (d.get("assign") or {}).items()}
            self.approved = {str(x) for x in d.get("approved") or []}
            self.locked = {str(k): str(v) for k, v in (d.get("locked") or {}).items()}
            self._seen_saved = "seen" in d
            self.seen = {str(k): {str(x) for x in v} for k, v in (d.get("seen") or {}).items()}
            self.done = {str(k): str(v) for k, v in (d.get("done") or {}).items()}
            self.done_at = float(d.get("done_at") or 0)
            self.split = {str(x) for x in d.get("split") or []}
            self.joined = {str(x) for x in d.get("joined") or []}
            self.hidden = {str(x) for x in d.get("hidden_dups") or []}
            self.skipped = {str(x) for x in d.get("skipped_folders") or []}
            self.chosen = bool(d.get("folders_chosen"))
        except (OSError, ValueError):
            pass

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 3, "assign": self.assign, "locked": self.locked,
                                   "approved": sorted(self.approved), "done": self.done, "done_at": self.done_at,
                                   "seen": {k: sorted(v) for k, v in self.seen.items() if k in self.approved},
                                   "split": sorted(self.split), "joined": sorted(self.joined),
                                   "hidden_dups": sorted(self.hidden), "skipped_folders": sorted(self.skipped),
                                   "folders_chosen": self.chosen}),
                       encoding="utf-8")
        tmp.replace(self.path)

    def _remap(self, d):
        """An item's id prefix changes when its product is split ("p:" -> "i:") or kept together again
        ("i:" -> "p:"). Carry the choice over to whichever one exists now."""
        units = self.sorter.units
        out = {}
        for k, v in d.items():
            if k not in units and k[:2] in ("p:", "i:"):
                other = ("i:" if k[:2] == "p:" else "p:") + k[2:]
                if other in units:
                    k = other
            out[k] = v
        return out

    def _settle(self):
        """After the units were (re)built: reflect finished runs, forget choices that no longer apply."""
        self._trashed = {}
        self.assign = self._remap(self.assign)
        self.done = self._remap(self.done)
        self._apply_done()
        valid = set(self.sorter.subs) | {UNSURE, TRASH} | set(SPECIAL)   # forget choices for categories that no longer exist
        units = self.sorter.units
        self.assign = {k: v for k, v in self.assign.items() if v in valid and (k in units or k in self._trashed)}
        self.locked = {k: v for k, v in self.locked.items() if v in valid and k in units}
        self.approved &= set(self.sorter.subs) | set(SPECIAL)
        self._lm = None
        self.seen = {c: set(self._remap(dict.fromkeys(v, 1))) for c, v in self.seen.items() if c in self.approved}
        self._copies = None
        self._lm = None
        self._retrain()
        if not getattr(self, "_seen_saved", True):
            # Choices saved by an older version: count what's there now (except the app's new guesses) as seen.
            self._seen_saved = True
            for uid, (cat, how) in self.destinations().items():
                if cat in self.approved and how != "suggested":
                    self.seen.setdefault(cat, set()).add(uid)

    def _retrain(self):
        learn = {k: v for k, v in self.locked.items() if v in self.approved}
        learn.update({k: v for k, v in self.assign.items() if v not in (UNSURE, TRASH)})
        self.sorter.train(learn)
        self._dest = None

    def _apply_done(self):
        """The saved inventory doesn't know about moves a run made since; reflect them."""
        if self.inv.live and self.inv.saved.timestamp() > self.done_at:
            self._forget_moved_since()
        for uid, cat in self.done.items():
            u = self.sorter.units.get(uid)
            if u is None:
                continue
            if cat == TRASH:
                self._trashed[uid] = self.sorter.units.pop(uid)
            elif cat in SPECIAL:
                u.home = cat
            else:
                u.current = cat
        self._copies = None

    def _forget_moved_since(self):
        """A scan newer than the last run shows where things really are: anything you moved by hand
        since (or pulled back out of Trash) stays where you put it."""
        units = self.sorter.units
        for uid, cat in list(self.done.items()):
            u = units.get(uid)
            if u is None:
                if cat != TRASH:
                    self.done.pop(uid)
            elif cat == TRASH or (u.home if cat in SPECIAL else u.current) != cat:
                self.done.pop(uid)

    def after_run(self, steps, undo=False):
        with self.lock:
            self.done_at = time.time()
            self._lm = None
            self.sorter._homes = None        # folders this run made count as sorted ones
            for s in steps:
                if s.get("status") != "done" or s["op"] not in ("move", "trash"):
                    continue
                for uid in s.get("units") or [s.get("unit")]:
                    if uid:
                        self._after_step(s, uid, undo)
            self._apply_done()
            self._save()
            self._dest = None

    def _after_step(self, s, uid, undo):
        if undo:
            self.done.pop(uid, None)
            if uid in self._trashed:
                self.sorter.units[uid] = self._trashed.pop(uid)
            u = self.sorter.units.get(uid)
            if u:
                where = s["obj"] if s.get("units") else s["dest"]   # a whole folder: its things are in it
                u.current = self.sorter._folder_category(where) if where in self.inv.folders else None
                if u.current and not self.sorter.in_sorted(where):
                    u.learned, u.current = u.current, None
        else:
            self.done[uid] = s["cat"]
            self.assign.pop(uid, None)
            self.locked.pop(uid, None)

    def set_categories(self, categories):
        with self.lock:
            self.sorter.set_categories(categories)
            self._settle()

    def _rebuild(self):
        self.inv.set_choices(self.split & set(self.inv.folders), self.joined & set(self.inv.folders))
        self.inv.skipped = self.skipped & set(self.inv.folders)
        self.sorter.set_categories(self.sorter.cats)
        self._settle()
        self._save()

    # ------------------------------------------------------------------ destinations
    # ------------------------------------------------------------------ landmarks
    @staticmethod
    def _place_key(name):
        n = name.lower()
        n = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", n)
        n = re.sub(r"\b(main ?store|mainstore|store|shop|new|lm|landmark|location|official|sim|region|teleport|tp|"
                   r"here|click|visit|us|our|the|at|to)\b", " ", n)
        n = " ".join(re.sub(r"[^a-z0-9]+", " ", n).split()[:3])
        return n

    def places(self):
        """Landmarks to the same store or place, grouped: [{"key", "keep", "copies"}], newest copy first.
        The same spot (same landmark) always groups; otherwise the store's name does."""
        if self._lm is not None:
            return self._lm
        units = self.sorter.units
        lms = [u for u in units.values() if u.special == LANDMARKS and not u.frozen and u.id not in self._trashed]
        by_asset, groups = {}, collections.defaultdict(list)
        for u in lms:
            it = self.inv.items.get(u.id[2:])
            key = self._place_key(u.name) or (it.asset if it else u.id)
            if it and it.asset in by_asset:
                key = by_asset[it.asset]
            elif it and it.asset:
                by_asset[it.asset] = key
            groups[key].append(u.id)
        out = {}
        for key, g in groups.items():
            # newest first, but never one you've marked for Trash
            g.sort(key=lambda x: (self.assign.get(x) == TRASH, -(units[x].created or 0)))
            out[key] = {"key": key, "keep": g[0], "copies": g[1:]}
        self._lm = out
        return out

    def _landmarks_view(self, d):
        """The Landmarks page: one entry per store or place, the newest landmark first, older copies under it."""
        units, inv = self.sorter.units, self.inv
        def where(u):
            return "In Landmarks" if u.home == LANDMARKS else inv.path_text(u.folder)
        def row(uid):
            u = units[uid]
            return {"id": uid, "name": u.name, "created": u.created, "where": where(u),
                    "in_product": bool(u.product), "trash": self.assign.get(uid) == TRASH,
                    "kept": uid in self.assign and self.assign[uid] != TRASH}
        places, extra, pulling = [], 0, 0
        for p in self.places().values():
            keep = units[p["keep"]]
            copies = [row(x) for x in p["copies"]]
            dest = d.get(p["keep"], (None, ""))[0]
            moving = dest == LANDMARKS and keep.home != LANDMARKS
            pulling += moving
            left = sum(1 for c in copies if not c["trash"] and not c["kept"])
            extra += left
            places.append({"key": p["key"], "keep": row(p["keep"]), "moving": moving, "copies": copies, "left": left})
        places.sort(key=lambda x: (-x["left"], -len(x["copies"]), x["keep"]["name"].lower()))
        return {"id": LANDMARKS, "name": "Landmarks", "top": None, "landmarks": True, "places": places,
                "total": len(places), "pulling": pulling, "extra": extra,
                "marked": sum(1 for p in places for c in p["copies"] if c["trash"]),
                "approved": self.is_checked(LANDMARKS), "new": len(self.new_since_check(d).get(LANDMARKS, ())),
                "here": sum(1 for p in places if p["keep"]["where"] == "In Landmarks"), "units": [],
                "copies": 0, "packaging": 0, "unsure_count": 0}

    def trash_landmark_copies(self, key=None, undo=False):
        """Mark the older copies of one place's landmark (or of every place) for Trash, or take that back."""
        with self.lock:
            n = 0
            for p in self.places().values():
                if key is not None and p["key"] != key:
                    continue
                for uid in p["copies"]:
                    if undo:
                        if self.assign.get(uid) == TRASH:
                            del self.assign[uid]
                            n += 1
                    elif uid not in self.assign:
                        self.assign[uid] = TRASH
                        n += 1
            self._save()
            self._dest = None
            return n

    def _lm_keepers(self):
        return {p["keep"] for p in self.places().values()}

    def destinations(self):
        """unit id -> (category id or UNSURE, how: 'you' | 'checked' | 'already' | 'suggested')."""
        if self._dest is not None:
            return self._dest
        out = {}
        keepers = self._lm_keepers()
        for uid, u in self.sorter.units.items():
            if u.frozen:
                continue                      # in a folder you skipped: left exactly as it is
            if uid in self.assign:
                out[uid] = (self.assign[uid], "you")
            elif u.home and (u.kind != "piece" or u.special == u.home):
                out[uid] = (u.home, "already")         # in the Settings / Landmarks folder already
            elif u.special == SETTINGS or (u.special == LANDMARKS and uid in keepers):
                # Settings go to the Settings folder (pulled out of other products too); the newest landmark
                # to each place goes to Landmarks. Older copies stay put unless you trash them.
                checked = self.locked.get(uid) == u.special and u.special in self.approved
                out[uid] = (u.special, "checked" if checked else "suggested")
            elif u.kind == "piece":
                continue                      # a piece stays with its product (or where it is) unless you move it
            elif uid in self.locked and self.locked[uid] in self.approved:
                out[uid] = (self.locked[uid], "checked")
            elif u.current:
                out[uid] = (u.current, "already")
            elif u.learned:
                out[uid] = (u.learned, "filed")    # in an old folder of yours for this category
            else:
                ranked, unsure = self.sorter.suggest(u)
                out[uid] = (UNSURE if unsure or not ranked else ranked[0][0], "suggested")
        self._dest = out
        return out

    def plan_units(self):
        """What a Run would move. Only two kinds of things ever go in the plan:
        things you moved yourself, and things in categories you checked ("Looks good").
        A suggestion is only acted on if it was in the category when you checked it."""
        out = []
        dest = self.destinations()
        for uid, (cat, how) in dest.items():
            u = self.sorter.units[uid]
            if cat == UNSURE or u.current == cat or u.home == cat:
                continue
            if how == "you" or (how in ("checked", "filed") and cat in self.approved):
                out.append((uid, cat))
        # A piece marked for Trash inside a product that's going to Trash anyway needs no step of its own.
        products_to_trash = {uid for uid, cat in out if cat == TRASH and uid.startswith("f:")}
        return [(uid, cat) for uid, cat in out
                if not (cat == TRASH and self.sorter.units[uid].product in products_to_trash)]

    def new_since_check(self, d=None):
        """Checked category id -> things in it now that weren't when you checked it."""
        d = d if d is not None else self.destinations()
        out = collections.defaultdict(set)
        for uid, (cat, _) in d.items():
            if cat in self.approved and uid not in self.seen.get(cat, ()) and self.done.get(uid) != cat:
                out[cat].add(uid)
        return out

    def is_checked(self, cid, new=None):
        new = new if new is not None else self.new_since_check()
        return cid in self.approved and not new.get(cid)

    def plan_count(self):
        return len(self.plan_units())

    # ------------------------------------------------------------------ views
    def tree(self):
        with self.lock:
            d = self.destinations()
            new = self.new_since_check(d)
            counts = collections.Counter(cat for cat, _ in d.values())
            incoming = collections.Counter(cat for uid, (cat, _) in d.items()
                                           if self.sorter.units[uid].current != cat)
            tops = []
            for top in self.sorter.cats["categories"]:
                kids = [{"id": c["id"], "name": c["name"], "count": counts[c["id"]],
                         "incoming": incoming[c["id"]], "approved": self.is_checked(c["id"], new),
                         "new": len(new.get(c["id"], ()))}
                        for c in top["children"]]
                tops.append({"id": top["id"], "name": top["name"], "children": kids,
                             "count": sum(k["count"] for k in kids),
                             "checked": sum(1 for k in kids if k["approved"])})
            subs_total = sum(len(t["children"]) for t in tops)
            homes = [{"id": k, "name": v, "count": counts[k], "approved": self.is_checked(k, new),
                      "incoming": sum(1 for uid, (cat, _) in d.items() if cat == k and self.sorter.units[uid].home != k),
                      "new": len(new.get(k, ()))} for k, v in SPECIAL.items()]
            return {"tops": tops, "homes": homes, "unsure": counts[UNSURE], "trash": counts[TRASH], "units": len(d),
                    "plan": self.plan_count(), "manual": self.sorter.manual, "skipped": self.sorter.skipped,
                    "chosen": self.chosen,
                    "checked": sum(t["checked"] for t in tops), "categories": subs_total}

    def unit_view(self, uid, dest, how):
        u = self.sorter.units[uid]
        ranked, unsure = self.sorter.suggest(u)
        subs = self.sorter.subs
        here = u.current == dest or (dest in SPECIAL and u.home == dest)
        copy_here = (not here) and dest not in (UNSURE, TRASH, *SPECIAL) and self._copy_in(u, dest)
        if here:
            where = "Already here"
        elif dest == TRASH:
            where = "Now in: " + self.inv.path_text(u.parent if u.kind == "product" else u.folder)
        else:
            where = "Coming from: " + self.inv.path_text(u.parent if u.kind == "product" else u.folder)
        pieces = self._packaging(u, dest) if u.kind == "product" else []
        return {
            "id": uid, "kind": u.kind, "name": u.name, "thumb": u.thumb, "pic_guess": u.pic_guess,
            "label": u.label, "ktype": self._ktype(u),
            "where": where, "here": here, "how": how, "nocopy": u.nocopy, "created": u.created,
            "suggestions": [{"id": c, "name": subs[c]["name"], "p": p} for c, p in ranked
                            if c in subs and (p >= 0.25 or dest != UNSURE)][:3],
            "copy_here": copy_here, "by_type": bool(u.hint and not unsure),
            "unsure": dest == UNSURE, "appearance": u.wearable,
            "packaging": len(pieces), "cleaned": sum(1 for p in pieces if self.assign.get(p) == TRASH),
            "folder": u.folder if u.kind in ("product", "piece") else None,
        }

    def why(self, raw):
        """Why a thing is headed where it is: the reasons shown in its "Why?" box."""
        with self.lock:
            uid = raw if raw in self.sorter.units else self._resolve(raw)
            if not uid:
                raise LookupError("That isn't in the sort list any more.")
            u = self.sorter.units[uid]
            dest, how = self.destinations().get(uid, (UNSURE, "suggested"))
            subs = self.sorter.subs
            name = lambda c: SPECIAL.get(c) or (subs[c]["name"] if c in subs else  # noqa: E731
                                                "Trash" if c == TRASH else "Not sure yet")
            out = self.sorter.explain(u)
            lead = {
                "you": f"You put it in {name(dest)} yourself.",
                "checked": f"It was in {name(dest)} when you checked that category, so it stays.",
                "already": f"It's already in your {name(dest)} folder.",
                "filed": f"It's in an older folder of yours for {name(dest)}: {self.inv.path_text(u.folder if u.kind == 'product' else u.parent)}.",
            }.get(how)
            out["dest"], out["how"], out["lead"] = name(dest), how, lead
            out["guess_name"] = name(out["guess"]) if out["guess"] else None
            out["others"] = [name(c) for c in out["others"]]
            out["learns"] = how in ("you", "checked", "already", "filed")
            return out

    def _copy_in(self, u, cat):
        """Is a same-named thing from the same creator already sitting in that category's folder?"""
        if self._copies is None:
            idx = collections.defaultdict(set)
            for x in self.sorter.units.values():
                if x.current:
                    idx[(x.name.strip().lower(), x.creator)].add(x.current)
            self._copies = idx
        return cat in self._copies.get((u.name.strip().lower(), u.creator), ())

    def _ktype(self, u):
        """What kind of thing it is, for grouping the To Trash list: Product, Object, Notecard..."""
        if u.kind == "product":
            return "Product"
        it = self.inv.items.get(u.id[2:])
        if not it:
            return "Other"
        if it.type in ("clothing", "bodypart"):
            return "Clothing & body parts"
        return {"object": "Object", "notecard": "Notecard", "landmark": "Landmark", "texture": "Texture",
                "snapshot": "Texture", "lsltext": "Script", "animatn": "Animation", "gesture": "Gesture",
                "callcard": "Calling card", "sound": "Sound", "material": "Material"}.get(it.type, it.kind or "Other")

    def learn(self):
        """Learn from your moves right away (used after confirming a whole group from Not sure yet)."""
        with self.lock:
            self._retrain()

    def category(self, cid, limit=400):
        with self.lock:
            if cid not in (UNSURE, TRASH, *SPECIAL) and cid not in self.sorter.subs:
                raise LookupError("That category doesn't exist any more.")
            d = self.destinations()
            if cid == LANDMARKS:
                return self._landmarks_view(d)
            uids = [uid for uid, (cat, _) in d.items() if cat == cid]
            if cid in (UNSURE, TRASH):
                limit = max(limit, 3000)       # shown grouped (by best guess / by type), so show them all
            views = [self.unit_view(uid, cid, d[uid][1]) for uid in uids]
            fresh = self.new_since_check(d).get(cid, set())
            for v in views:
                v["new"] = v["id"] in fresh
            # pictures first, then the rest; within each, things coming in before things already here
            if cid == UNSURE:
                # one-click wins first (good guesses), clothing & body parts last
                views.sort(key=lambda v: (v["appearance"], not v["suggestions"], not v["thumb"], v["name"].lower()))
            else:
                views.sort(key=lambda v: (not v["new"], not v["thumb"], v["here"], v["name"].lower()))
            if cid == UNSURE:
                name, top = "Not sure yet", None
            elif cid == TRASH:
                name, top = "To Trash", None
            elif cid in SPECIAL:
                name, top = SPECIAL[cid], None
            else:
                sub = self.sorter.subs[cid]
                name, top = sub["name"], self.sorter.tops[sub["top"]]["name"]
            return {"id": cid, "name": name, "top": top, "total": len(views),
                    "copies": sum(1 for v in views if v["copy_here"]),
                    "packaging": sum(v["packaging"] - v["cleaned"] for v in views if v["kind"] == "product"),
                    "here": sum(1 for v in views if v["here"]), "unsure_count": sum(1 for v in views if v["unsure"]),
                    "approved": self.is_checked(cid), "new": len(fresh), "units": views[:limit]}

    # ------------------------------------------------------------------ duplicates
    def _loose_home(self, fid):
        """Somewhere things land loose: My Inventory itself, Objects, Received Items, Lost And Found."""
        f = self.inv.folders.get(fid)
        return fid == self.inv.root or bool(f and f.system and f.ptype.lower() in SORTED_SYSTEM_TYPES)

    def _folder_sig(self, fid):
        f = self.inv.folders.get(fid)
        if not f:
            return None
        return frozenset((self.inv.items[i].name.strip().lower(), self.inv.items[i].type)
                         for i in f.items if i in self.inv.items and self.inv.items[i].type not in ("link", "link_f"))

    def _dup_groups(self):
        """Sets of copies: [{"key", "uids", "fixed"}]. "fixed" copies came inside different packages
        and always stay; only the other copies can be marked for Trash.

        Products count as copies when the folder name and everything inside match (same item names,
        types and creators). A loose item only counts when its copies are interchangeable: in the same
        folder, sitting loose (My Inventory, Objects, Received Items, Lost And Found), or in folders
        holding the same things. The alpha that came with each head in its own folder isn't a copy."""
        inv, units = self.inv, self.sorter.units
        groups = collections.defaultdict(list)
        for uid, u in units.items():
            if u.frozen:
                continue                      # skipped folders are left alone, duplicates included
            if u.kind == "product":
                items = [inv.items[i] for i in inv.subtree(u.folder)[0] if i in inv.items]
                inside = tuple(sorted((i.name.strip().lower(), i.type, i.creator or "")
                                      for i in items if i.type not in ("link", "link_f")))
                if not inside:
                    continue
                groups[("p", u.name.strip().lower(), inside)].append(uid)
            elif u.kind == "item":
                it = inv.items.get(uid[2:])
                if not it or it.type in ("link", "link_f"):
                    continue
                groups[("i", it.name.strip().lower(), it.type, it.creator or "")].append(uid)
        out = []
        for key, g in groups.items():
            if len(g) < 2:
                continue
            fixed = set()
            if key[0] == "i":
                parents = collections.Counter(units[x].folder for x in g)
                sigs = collections.Counter(self._folder_sig(fid) for fid in parents)
                for x in g:
                    fid = units[x].folder
                    if self._loose_home(fid) or parents[fid] > 1 or sigs[self._folder_sig(fid)] > 1:
                        continue                  # interchangeable copy
                    fixed.add(x)                  # part of its own package
                if len(g) - len(fixed) < 1 or (not fixed and len(g) < 2):
                    continue
            out.append({"key": hashlib.sha1(repr(key).encode()).hexdigest()[:16], "uids": g, "fixed": fixed})
        return out

    def _tier(self, uid, fixed=()):
        """0: a copy already in a category folder; 1: one you filed in a folder of your own;
        2: one that came inside its own package; 3: one sitting loose (Lost And Found, Objects...)"""
        u = self.sorter.units[uid]
        if uid not in fixed and u.current is not None:
            return 0
        if uid not in fixed and not self._loose_home(u.parent if u.kind == "product" else u.folder):
            return 1
        return 2 if uid in fixed else 3

    def _keeper(self, uids, fixed=()):
        """Which copy to keep when you haven't picked: one already in a category folder, then one you
        filed yourself, then one that came in its own package; among equals, the newest (a redelivery
        may carry fixes the creator made without renaming it)."""
        units = self.sorter.units
        def rank(uid):
            u = units[uid]
            mine = self.assign.get(uid)
            return (self._tier(uid, fixed), mine is None or mine in (TRASH, UNSURE), -(u.created or 0), u.name)
        return min(uids, key=rank)

    def _keep_reason(self, keep, uids, fixed=()):
        """Why this copy is the suggested keep, in a few words."""
        u = self.sorter.units[keep]
        tier = self._tier(keep, fixed)
        why = (f"already in {self.sorter.subs[u.current]['name']}" if u.current in self.sorter.subs else
               "in your own folder" if tier == 1 else "stays with what's in its folder" if tier == 2 else "")
        rivals = [x for x in uids if x != keep and self._tier(x, fixed) == tier]
        if rivals and (u.created or 0) > max((self.sorter.units[x].created or 0) for x in rivals):
            why = f"{why}, newest" if why else "newest"
        return why

    def duplicates(self, hidden=False):
        with self.lock:
            units = self.sorter.units
            out, n_hidden = [], 0
            for grp in self._dup_groups():
                g, fixed = grp["uids"], grp["fixed"]
                if (grp["key"] in self.hidden) != hidden:
                    n_hidden += grp["key"] in self.hidden
                    continue
                trashed = [uid for uid in g if self.assign.get(uid) == TRASH]
                decided = bool(trashed)
                gone = len(trashed) == len(g) - len(fixed & set(g)) and not (set(trashed) & fixed)
                keep = self._keeper([uid for uid in g if uid not in trashed] or g, fixed)
                copies = []
                why = self._keep_reason(keep, g, fixed)
                for uid in sorted(g, key=lambda x: (x != keep, x not in fixed, -(units[x].created or 0))):
                    u = units[uid]
                    copies.append({
                        "id": uid, "folder": u.folder, "where": self.inv.path_text(u.parent if u.kind == "product" else u.folder),
                        "created": u.created, "thumb": u.thumb, "nocopy": u.nocopy, "package": uid in fixed,
                        "sorted": self.sorter.subs[u.current]["name"] if u.current in self.sorter.subs else None,
                        "state": "trash" if uid in trashed else "keep" if (decided or uid == keep or uid in fixed) else "",
                        "suggested": uid == keep and not decided, "why": why if uid == keep else ""})
                first = units[g[0]]
                it = self.inv.items.get(g[0][2:]) if first.kind == "item" else None
                out.append({"key": grp["key"], "kind": first.kind, "name": first.name, "label": first.label,
                            "type": it.type if it else "", "packages": len(fixed), "hidden": hidden,
                            "thumb": next((units[x].thumb for x in g if units[x].thumb), ""),
                            "count": len(g), "decided": decided, "all_gone": gone and len(trashed) > 0,
                            "copies": copies})
            out.sort(key=lambda d: (d["decided"], d["kind"] != "product", -d["count"], d["name"].lower()))
            if hidden:
                n_hidden = len(out)
            # extra copies = the ones that could go: all loose copies when packages keep theirs, else all but one
            return {"groups": out, "extra": sum(d["count"] - d["packages"] - (0 if d["packages"] else 1) for d in out),
                    "products": sum(1 for d in out if d["kind"] == "product"),
                    "undecided": sum(1 for d in out if not d["decided"]), "hidden": n_hidden}

    def keep_copy(self, keep, undo=False):
        """Keep this copy and mark the other copies of it for Trash (or, with undo, take that back).
        Copies that came inside their own packages are never marked."""
        with self.lock:
            grp = next((g for g in self._dup_groups() if keep in g["uids"]), None)
            if not grp:
                raise LookupError("Those copies aren't there any more.")
            n = 0
            for uid in grp["uids"]:
                if undo or uid == keep or uid in grp["fixed"]:
                    if self.assign.get(uid) == TRASH:
                        self.assign.pop(uid)
                        n += uid != keep
                elif self.assign.get(uid) != TRASH:
                    self.assign[uid] = TRASH
                    n += 1
            self._save()
            self._dest = None
            return n

    def keep_one_of_each(self):
        """For every set of copies you haven't decided on or hidden: keep the suggested one, trash the rest."""
        with self.lock:
            n = 0
            for grp in self._dup_groups():
                g = grp["uids"]
                if grp["key"] in self.hidden or any(self.assign.get(uid) == TRASH for uid in g):
                    continue
                if all(self.sorter.units[uid].nocopy for uid in g):
                    continue                      # several no-copy copies is how you rez more than one: your call
                keep = self._keeper(g, grp["fixed"])
                for uid in g:
                    if uid != keep and uid not in grp["fixed"]:
                        self.assign[uid] = TRASH
                        n += 1
            self._save()
            self._dest = None
            return n

    def trash_all(self, any_copy):
        """You don't want this at all: mark every copy for Trash. Copies that sit with the rest of
        another folder's contents (part of a package) stay; trash those from their own folder."""
        with self.lock:
            grp = next((g for g in self._dup_groups() if any_copy in g["uids"]), None)
            if not grp:
                raise LookupError("Those copies aren't there any more.")
            n = 0
            for uid in grp["uids"]:
                if uid not in grp["fixed"] and self.assign.get(uid) != TRASH:
                    self.assign[uid] = TRASH
                    n += 1
            self._save()
            self._dest = None
            return {"count": n, "kept": len(grp["fixed"])}

    def hide_dup(self, key, hide=True):
        """"Not duplicates": take a set off the list (remembered), or put it back."""
        with self.lock:
            (self.hidden.add if hide else self.hidden.discard)(str(key))
            self._save()

    def item_marks(self, item_ids):
        """For My Inventory: {item id: {"cat", "name"}} for the items you moved or marked yourself."""
        with self.lock:
            subs = self.sorter.subs
            out = {}
            for iid in item_ids:
                uid = self.sorter.unit_of("item", iid)
                if not uid or uid.startswith("f:") or uid not in self.assign:
                    continue
                cat = self.assign[uid]
                out[iid] = {"cat": cat, "name": "To Trash" if cat == TRASH else "Not sure yet" if cat == UNSURE
                            else subs[cat]["name"] if cat in subs else ""}
            return out

    # ------------------------------------------------------------------ changes
    def _resolve(self, uid):
        """Unit ids as sent by the page. "item:<id>" means "whatever moves when you move this one item"."""
        if uid.startswith("item:"):
            r = self.sorter.unit_of("item", uid[5:])
            uid = r if r and not r.startswith("f:") else None
        elif uid.startswith("folder:"):
            # A folder picked from search: only a product folder moves as a whole on its own.
            uid = "f:" + uid[7:] if "f:" + uid[7:] in self.sorter.units else None
        u = self.sorter.units.get(uid) if uid else None
        return uid if u is not None and not u.frozen else None       # skipped folders can't be changed

    def move(self, uids, cid):
        with self.lock:
            if cid not in (UNSURE, TRASH, *SPECIAL) and cid not in self.sorter.subs:
                raise ValueError("Unknown category.")
            n = 0
            resolved = [(raw, self._resolve(raw)) for raw in uids]
            chosen = {u for _, u in resolved if u}
            for raw, uid in resolved:
                if not uid:
                    continue
                if self.sorter.units[uid].product in chosen:
                    n += 1        # its product folder is moving too: it goes along with it, not on its own
                    continue
                self.assign[uid] = cid
                n += 1
                if self._dest is not None:
                    self._dest[uid] = (cid, "you")
            self._save()
            # Learning from your moves happens when you check a category ("Looks good"), so dragging stays quick.
            return n

    def unassign(self, uids):
        """Undo your own choice for these (back to the app's suggestion / where they are)."""
        with self.lock:
            for raw in uids:
                uid = self._resolve(raw)
                if uid:
                    self.assign.pop(uid, None)
            self._save()
            self._dest = None

    def trash_copies(self, cid):
        """Mark every 'Copy already here' thing headed to this category for Trash."""
        with self.lock:
            view = self.category(cid, limit=10**9)
            ids = [v["id"] for v in view["units"] if v["copy_here"]]
            for uid in ids:
                self.assign[uid] = TRASH
            self._save()
            self._dest = None
            return len(ids)

    def _packaging(self, u, dest=None):
        """What Clean out packaging marks in this product. Never the textures of something headed to
        (or sitting in) Textures & Materials, even if the app didn't spot it as a texture pack, and never
        the landmark that's the newest one to its store (it goes to your Landmarks folder instead)."""
        keep = self._lm_keepers()
        pieces = [p for p in u.pieces if p in self.sorter.units and p not in keep]
        tex_cat = self.sorter.by_name.get(("build parts", "textures & materials"))
        dest = dest if dest is not None else self.destinations().get(u.id, (None,))[0]
        if tex_cat and tex_cat in (dest, u.current):
            pieces = [p for p in pieces if (self.inv.items.get(p[2:]) or None) is None
                      or self.inv.items[p[2:]].type not in ("texture", "snapshot", "material")]
        return pieces

    def clean(self, uids, undo=False):
        """Mark the packaging (notecards, landmarks, scripts) inside these products for Trash.
        The products themselves stay where they're going."""
        with self.lock:
            n = 0
            for uid in uids:
                u = self.sorter.units.get(uid)
                if not u or u.kind != "product":
                    continue
                for p in (u.pieces if undo else self._packaging(u)):
                    if p not in self.sorter.units:
                        continue
                    if undo:
                        if self.assign.pop(p, None) is not None:
                            n += 1
                    elif self.assign.get(p) != TRASH:
                        self.assign[p] = TRASH
                        n += 1
            self._save()
            self._dest = None
            return n

    def clean_category(self, cid):
        view = self.category(cid, limit=10**9)
        return self.clean([v["id"] for v in view["units"] if v["kind"] == "product" and v["packaging"]])

    def split_unit(self, uid):
        """Open a product folder up: its pieces (and subfolders) get sorted one by one.
        Anything you already moved or marked for Trash inside it keeps that choice."""
        with self.lock:
            u = self.sorter.units.get(uid)
            if not u or u.kind != "product":
                raise ValueError("Only a product folder can be split.")
            fid = u.folder
            self.joined.discard(fid)
            self.split.add(fid)
            self.assign.pop(uid, None)
            self.locked.pop(uid, None)
            self._rebuild()
            return fid

    def top_folders(self):
        """Your top-level folders, for "Which folders should the sorter go through?" Folders that are
        mostly things already in your category folders are flagged as looking organized."""
        with self.lock:
            inv, S = self.inv, self.sorter
            out = []
            for fid in inv.folders[inv.root].folders:
                f = inv.folders[fid]
                if inv.in_trash(fid):
                    continue
                items = [i for i in inv.subtree(fid)[0] if inv.items[i].type not in ("link", "link_f")]
                if not items:
                    continue
                fixed = S._skip_folder(f)           # system folders, #Firestorm, #RLV: always left alone
                in_cats = sum(1 for i in items if S._folder_category(inv.items[i].parent)) if not fixed else 0
                organized = not fixed and (inv.is_category_folder(fid) or in_cats / len(items) >= 0.6)
                out.append({"id": fid, "name": f.name, "count": len(items), "system": f.system,
                            "fixed": fixed, "organized": organized, "sorted_share": round(in_cats / len(items), 2),
                            "skipped": fid in self.skipped})
            out.sort(key=lambda x: (x["fixed"], x["name"].lower()))
            return {"folders": out, "chosen": self.chosen}

    def choose_folders(self, skip_ids):
        """Save which top-level folders to leave alone (deeper folders you skipped stay skipped)."""
        with self.lock:
            tops = set(self.inv.folders[self.inv.root].folders)
            skip = {f for f in skip_ids if f in tops and not self.inv.hands_off(f)}
            self.skipped = (self.skipped - tops) | skip
            self.chosen = True
            self._rebuild()

    def skip_folder(self, fid, on=True):
        """Leave this folder (and everything in it) alone, or sort it again."""
        with self.lock:
            inv = self.inv
            if fid not in inv.folders or fid == inv.root:
                raise LookupError("That folder isn't in this inventory.")
            f = inv.folders[fid]
            if on and (f.system or inv.in_trash(fid)):
                raise ValueError("System folders are already left alone.")
            (self.skipped.add if on else self.skipped.discard)(fid)
            self._rebuild()
            return len([u for u in self.sorter.units.values() if u.frozen])

    def keep_together(self, fid, on=True):
        """Treat this folder as one product (on) or go back to the app's own judgement (off)."""
        with self.lock:
            if fid not in self.inv.folders or fid == self.inv.root:
                raise LookupError("That folder isn't in this inventory.")
            f = self.inv.folders[fid]
            if on and (f.system or self.inv.hands_off(fid)):
                raise ValueError("System folders are left for you to sort by hand.")
            if on and self.inv.is_category_folder(fid):
                raise ValueError("That's one of your category folders - it can't be moved as one product.")
            self.split.discard(fid)
            if on:
                self.joined.add(fid)
            else:
                self.joined.discard(fid)
            self._rebuild()

    def _dest_name(self, dest):
        return ("Not sure yet" if dest == UNSURE else "To Trash" if dest == TRASH else SPECIAL[dest] if dest in SPECIAL
                else self.sorter.subs[dest]["name"])

    def locate(self, kind, oid):
        """What moves when you act on this item or folder in My Inventory or Search, and where it's headed."""
        with self.lock:
            inv = self.inv
            if kind == "item" and oid not in inv.items or kind == "folder" and oid not in inv.folders:
                raise LookupError("That isn't in this inventory any more.")
            fid = inv.items[oid].parent if kind == "item" else oid
            if kind == "folder" and fid == inv.root:
                return {"movable": False, "reason": "This is your whole inventory."}
            if inv.hands_off(fid):
                return {"movable": False, "manual": True,
                        "reason": "This is in a system folder, which is left for you to sort by hand."}
            skip = inv.skipped_by(fid)
            if skip:
                return {"movable": False, "skipped": True, "skip_root": skip, "skip_name": inv.folders[skip].name,
                        "reason": "You skipped this folder: nothing in it is sorted, moved or trashed."
                        if skip == fid else f"This is inside “{inv.folders[skip].name}”, a folder you skipped."}
            if kind == "item" and inv.items[oid].type in ("link", "link_f"):
                return {"movable": False, "reason": "This is a link - links are left where they are."}
            if kind == "folder" and inv.folders[oid].system:
                return {"movable": False, "reason": "System folders can't be moved."}
            uid = self.sorter.unit_of(kind, oid)
            if not uid:
                why = ("This is one of your category folders." if inv.is_category_folder(oid)
                       else "This looks like a folder you organized yourself, so what's inside is sorted one by one.")
                return {"movable": False, "can_join": not inv.is_category_folder(oid), "reason": why}
            u = self.sorter.units[uid]
            d = self.destinations()
            product = self.sorter.units.get(u.product) if u.kind == "piece" and u.product else None
            if uid in d:
                dest, how = d[uid]
            elif product is not None:
                dest, how = d.get(product.id, (UNSURE, "suggested"))
                how = "with_product"          # no choice of its own: it goes wherever its product goes
            else:
                dest, how = UNSURE, "stays"   # loose packaging you haven't touched: stays where it is
            inside = (product.name if product is not None
                      else u.name if u.kind == "product" and not (kind == "folder" and oid == u.folder) else None)
            return {"movable": True, "unit": uid, "kind": u.kind, "name": u.name, "dest": dest, "how": how,
                    "dest_name": self._dest_name(dest), "inside": inside,
                    "product_unit": product.id if product is not None else None,
                    "joined": u.folder in self.joined if u.kind == "product" else False,
                    "here": (product.current if how == "with_product" else u.current) == dest,
                    "nocopy": u.nocopy}

    def approve(self, cid, approved=True):
        with self.lock:
            if cid not in self.sorter.subs and cid not in SPECIAL:
                raise ValueError("Unknown category.")
            if approved:
                self.approved.add(cid)
                # Lock in what you just checked, so later learning can't quietly change it,
                # and remember everything that was there.
                seen = set()
                for uid, (cat, how) in self.destinations().items():
                    if cat == cid:
                        seen.add(uid)
                        if how == "suggested":
                            self.locked[uid] = cid
                self.seen[cid] = seen
            else:
                self.approved.discard(cid)
                self.seen.pop(cid, None)
                self.locked = {k: v for k, v in self.locked.items() if v != cid}
            self._save()
            if approved:
                self._retrain()      # learn from what you just confirmed
            else:
                self._dest = None

    def next_category(self, after=None):
        """The next unchecked category with something in it, in list order."""
        tree = self.tree()
        order = [c for t in tree["tops"] for c in t["children"]]
        start = 0
        if after:
            for i, c in enumerate(order):
                if c["id"] == after:
                    start = i + 1
        for c in order[start:] + order[:start]:
            if not c["approved"] and c["count"]:
                return c["id"]
        return UNSURE if tree["unsure"] else None
