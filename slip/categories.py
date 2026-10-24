"""Sorting categories: a two-level tree the user can edit.

Starts from the Inventory Buddy categories (as they appear in the user's
own sorted folders). Saved as JSON in the user's app-data folder.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .keywords import APPEARANCE, SEED

VERSION = 6


def _decor(top, prefix_map):
    """Short names for Buddy's decor categories; the old prefixed name stays as an alias."""
    return [(short, [old]) for short, old in prefix_map]


# (top category, other names its folder may have, [(subcategory, other names its folder may have)])
STARTER = [
    ("Structures & Vehicles", [], _decor("Structures & Vehicles", [
        ("Garages & Carports", "Structures - Garages & Carports"), ("Houses & Homes", "Structures - Houses & Homes"),
        ("Sheds & Utility Buildings", "Structures - Sheds & Utility Buildings"),
        ("Skyboxes", "Structures - Skyboxes"), ("Vehicles", "Vehicles")])),
    ("Decor", [], _decor("Decor", [(n, "Decor - " + n) for n in [
        "Baskets, Boxes, & Trays", "Bath Accessories", "Books", "Candles & Home Fragrance", "Clocks",
        "Closet & Dressing", "Decor Accents", "Dishes & Cookware", "Dividers", "Figurines & Sculptures", "Full Set",
        "Holiday & Seasonal", "Kitchen & Dining Decor", "Kitchen Decor", "Laundry Accessories", "Media & Electronics",
        "Mirrors", "Office Decor", "Party & Celebration", "Pillows & Throws", "Plants & Planters", "Rugs",
        "Signs & Neon", "Vases & Vessels", "Wall Decor & Frames", "Window Treatments"]]
        + [("Placesettings", "Decor - Dining - Placesettings")])),
    ("Furniture", [], _decor("Furniture", [
        ("Beds", "Bedroom - Beds"), ("Bedroom Storage", "Bedroom - Storage"), ("Dining Seating", "Dining - Seating"),
        ("Dining Tables", "Dining - Tables"), ("Dining Sets", "Furniture - Dining - Sets"),
        ("Bar & Serving", "Furniture - Bar & Serving"), ("Bathroom", "Furniture - Bathroom"),
        ("Chests & Trunks", "Furniture - Chests & Trunks"), ("Closet", "Furniture - Closet"),
        ("Fireplaces", "Furniture - Fireplaces"), ("Laundry Room", "Furniture - Laundry Room"),
        ("Media Units", "Furniture - Media Units"), ("Office Chairs", "Furniture - Office Chairs"),
        ("Office Desks", "Furniture - Office Desks"), ("Outdoor Furniture", "Furniture - Outdoor Furniture"),
        ("Set Accessories", "Furniture - Set Accessories"), ("Shelving & Storage", "Furniture - Shelving & Storage"),
        ("Tables", "Furniture - Tables"), ("Kitchen Appliances", "Kitchen - Appliances"),
        ("Kitchen Counters & Cabinets", "Kitchen - Counters & Cabinets"), ("Kitchen Sets", "Kitchen - Sets"),
        ("Chairs & Benches", "Seating - Chairs & Benches"), ("Ottomans & Poufs", "Seating - Ottomans & Poufs"),
        ("Sofas", "Seating - Sofas")])),
    ("Build Parts", [], _decor("Build Parts", [
        ("Blank Mesh Items", "Blank Mesh Items"), ("Ceiling Panels", "Build Parts - Ceiling Panels"),
        ("Floors", "Build Parts - Floors"), ("Railings", "Build Parts - Railings"),
        ("Stairs & Steps", "Build Parts - Stairs & Steps"), ("Wall Fittings", "Build Parts - Wall Fittings"),
        ("Walls", "Build Parts - Walls"), ("Wall Panels", "Build Parts - Walls Panels"),
        ("Builder Scripting Items", "Builder Scripting Items"),
        ("Textures & Materials", "Build Parts - Textures & Materials")])),
    ("Landscaping", [], [(n, [n]) for n in [
        "Animal Decor", "Animal Related Structures", "Bridges", "Bushes, Shrubs, Hedges", "Cliffs", "Docks & Piers",
        "Fences & Gates", "Garden - Ivy, Vines", "Garden Decor", "Gazebos & Pavilions", "Grass & Meadows",
        "Outdoor Decor", "Outdoor Decor - Beach", "Outdoor Decor - Mailboxes", "Paths", "Plants & Flowers",
        "Retaining & Sea Walls", "Roads", "Rocks & Terrain", "Signs", "Sim Surrounds", "Trees", "Water Features",
        "Wildlife & Animals"]]),
    ("Lighting", [], _decor("Lighting", [(n, "Lighting - " + n) for n in [
        "Ceiling", "Decorative", "Floor Lamps", "Outdoor", "Table Lamps", "Wall"]])),
    ("Food & Drink (Wear & Rez)", ["Food & Drink"], _decor("Food & Drink", [
        ("Rezzable", "Food & Drink - Rezzable"), ("Wearable", "Food & Drink - Wearable")])),
    ("Entertainment", [], _decor("Entertainment", [(n, "Entertainment - " + n) for n in [
        "Board Games", "Decor Only (Possibly with poses)", "Interactive Group (Bowling, beer pong, etc)",
        "Outdoor Activities"]])),
    ("Commercial", [], [("Commercial & Retail Furniture", ["Furniture - Commercial & Retail"]),
                        ("Shops & Commercial Buildings", ["Structures - Shops & Commerical Buildings"])]),
    # ---------------------------------------------------------------- appearance
    ("Clothing", ["Legacy Clothing", "Reborn"], [
        ("Dresses", ["Dress"]), ("Tops & Blouses", ["Tops"]), ("Sweaters & Hoodies", []),
        ("Jackets & Coats", ["Jackets"]), ("Jeans", []), ("Pants & Leggings", ["Casual Pants", "Dressy Pants"]),
        ("Shorts", []), ("Skirts", []), ("Jumpsuits & Bodysuits", ["Bodysuits"]),
        ("Matching Sets & Outfits", ["Match Sets"]), ("Swimwear", []), ("Lingerie & Underwear", []),
        ("Loungewear & Sleepwear", []), ("Socks & Tights", []), ("Activewear", [])]),
    ("Shoes", [], [("Heels", []), ("Sneakers", []), ("Boots", []), ("Sandals & Flats", []), ("Slippers", [])]),
    ("Jewelry", [], [("Earrings", ["EARRINGS"]), ("Necklaces & Chokers", ["NECKLACE/CHOKER"]), ("Rings", ["RINGS"]),
                     ("Bracelets & Watches", ["BRACELETS/WATCHES"]), ("Piercings", ["PIERCINGS/NOSE"])]),
    ("Accessories", [], [("Bags & Purses", ["PURSES/BAGS"]), ("Hats & Headbands", ["Hats"]),
                         ("Sunglasses & Glasses", ["SUNGLASSES"])]),
    ("Hair", [], [("Long Straight & Wavy", ["Long + Straight/Wavey"]), ("Long Curly", ["Long + Curly"]),
                  ("Medium & Shoulder Length", ["Medium + Shoulder Length"]), ("Short & Bobs", ["Short + Bobs"]),
                  ("Ponytails & Half-up", ["Half-up + Ponytail"]), ("Buns", []),
                  ("Hairbases", ["Hairbase + Style", "Hairbases - Newer"]), ("Hair Extras", []),
                  ("Hat Hair", [])]),
    ("Head & Face", [], [("Mesh Heads", []), ("Face Skins & Appliers", ["Face Appliers"]), ("Eyes", []),
                         ("Eyebrows", []), ("Eyelashes", []),
                         ("Makeup & Lipstick", ["Make Up", "Lipstick & Lipgloss"]), ("Face Details", []),
                         ("Ears & Neck Blends", [])]),
    ("Body", [], [("Mesh Bodies", ["Mesh Body's"]),
                  ("Skins & Body Appliers", ["Body Appliers", "Legacy - Body Appliers", "Body Skin Appliers"]),
                  ("Shapes", []), ("Tattoos", []), ("Nails", ["NAILS"])]),
    ("Held & Worn Accessories", ["Wearables - Held & Worn Accessories", "Fun Accessories"],
     [("Phones & Gadgets", []), ("Props & Toys", ["Fun Accessories"])]),
    ("Animations", [], [("AOs", ["AO's"]), ("Poses", [])]),
    ("Pets", [], [("Animesh Pets & Companions", []), ("Horses & Breedables", []),
                  ("Pet Appliers & Accessories", [])]),
]

NAME_MAX = 63          # Second Life folder names are limited to 63 characters
BAD = re.compile(r"[|\x00-\x1f]")


def data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif "darwin" in os.sys.platform:
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "SL Inventory Cleanup"     # the app's old name: kept so saved choices carry over
    d.mkdir(parents=True, exist_ok=True)
    return d


def _nid():
    return uuid.uuid4().hex[:10]


def _starter_keywords(top, sub, aliases):
    for name in [sub, *aliases]:
        if name in SEED:
            return list(SEED[name])
    return APPEARANCE.get(f"{top}/{sub}")


PARENT_DEFAULT = {"on": False, "name": "Sorted"}


def _parent_folder(value):
    """The optional one folder all category folders go inside (e.g. "Sorted")."""
    value = value if isinstance(value, dict) else {}
    try:
        name = clean_name(value.get("name") or PARENT_DEFAULT["name"])
    except ValueError:
        name = PARENT_DEFAULT["name"]
    return {"on": bool(value.get("on")), "name": name}


def defaults():
    return {"version": VERSION, "source": "Starter (Inventory Buddy + appearance)",
            "parent_folder": dict(PARENT_DEFAULT), "categories": [
        {"id": _nid(), "name": top, "aliases": list(taliases), "children": [
            {"id": _nid(), "name": sub, "aliases": list(aliases),
             "keywords": list(_starter_keywords(top, sub, aliases) or [])}
            for sub, aliases in kids]}
        for top, taliases, kids in STARTER]}


def _clean_list(values, limit, maxlen):
    out = []
    for v in values or []:
        v = BAD.sub("", str(v)).strip()[:maxlen]
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    return out[:limit]


def clean_name(name):
    name = BAD.sub("", str(name or "")).strip()
    if not name:
        raise ValueError("A category needs a name.")
    if len(name) > NAME_MAX:
        raise ValueError(f"Names can be at most {NAME_MAX} characters (Second Life's folder limit).")
    if not all(32 <= ord(ch) < 127 for ch in name):
        raise ValueError("Use plain letters, numbers and punctuation (Firestorm's rename box only accepts those).")
    return name


def validate(data):
    cats = data.get("categories")
    if not isinstance(cats, list):
        raise ValueError("Bad category list.")
    out, seen_top = [], set()
    for top in cats:
        name = clean_name(top.get("name"))
        if name.lower() in seen_top:
            raise ValueError(f'There are two top categories called "{name}".')
        seen_top.add(name.lower())
        kids, seen = [], set()
        for k in top.get("children") or []:
            kn = clean_name(k.get("name"))
            if kn.lower() in seen:
                raise ValueError(f'"{name}" has two subcategories called "{kn}".')
            seen.add(kn.lower())
            kw = k.get("keywords")
            if kw is None:
                kw = _starter_keywords(name, kn, k.get("aliases") or []) or []   # new or older: starter words
            kw = [str(w).strip().lower()[:40] for w in kw if str(w).strip()][:120]
            kids.append({"id": str(k.get("id") or _nid())[:20], "name": kn, "keywords": kw,
                         "aliases": _clean_list(k.get("aliases"), 12, NAME_MAX)})
        out.append({"id": str(top.get("id") or _nid())[:20], "name": name, "children": kids,
                    "aliases": _clean_list(top.get("aliases"), 12, NAME_MAX)})
    # A top category's other name must not be another top category's own name (e.g. "Head & Face" also
    # answering to "Body"): folders would be read as the wrong category and the app would learn from that.
    tops = {t["name"].lower() for t in out}
    for t in out:
        t["aliases"] = [a for a in t["aliases"] if a.lower() not in tops - {t["name"].lower()}]
    return {"version": int(data.get("version") or 1), "source": data.get("source", "custom"),
            "parent_folder": _parent_folder(data.get("parent_folder")),
            "whole_folders": bool(data.get("whole_folders", True)),
            "folder_pictures": bool(data.get("folder_pictures", True)), "categories": out}


def missing_starters(data):
    """Starter top categories (from the current starter list) that this list doesn't have."""
    have = {t["name"].lower() for t in data["categories"]}
    for t in data["categories"]:
        have |= {a.lower() for a in t.get("aliases", [])}
    return [t for t in defaults()["categories"] if t["name"].lower() not in have]


def upgrade(data):
    """Version-1 lists were Buddy decor only, with 'Decor - Mirrors' style names: if never edited, swap in
    the new starter list. Version-2 lists get the v0.8 starter keywords (keywords aren't editable in the app,
    so they're always the starter ones) for every category that has a starter list."""
    version = data.get("version", 1)
    if version >= VERSION:
        return data, False
    if version < 2:
        old_names = {(t["name"], c["name"]) for t in data["categories"] for c in t["children"]}
        v1_names = {(top, aliases[0]) for top, _, kids in STARTER[:9] for _, aliases in kids}
        if old_names <= v1_names:          # still the untouched (or only trimmed) Buddy list
            return defaults(), True
    for top in data["categories"]:
        for c in top["children"]:
            kw = _starter_keywords(top["name"], c["name"], c.get("aliases", []))
            if kw is None:
                for t, _, kids in STARTER:          # a renamed top: find the sub by its own name
                    for sub, aliases in kids:
                        if kw is None and (sub == c["name"] or c["name"] in aliases):
                            kw = _starter_keywords(t, sub, aliases)
            if kw is not None:
                c["keywords"] = list(kw)
    if version < 5:
        # v0.13: texture and material packs get a home under Build Parts.
        for top in data["categories"]:
            if top["name"].lower() == "build parts" and not any(
                    c["name"].lower() in ("textures & materials", "textures") for c in top["children"]):
                top["children"].append({"id": _nid(), "name": "Textures & Materials",
                                        "aliases": ["Build Parts - Textures & Materials"],
                                        "keywords": list(SEED.get("Textures & Materials", ["texture", "textures", "pbr"]))})
    data["version"] = VERSION
    return data, True


class CategoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "categories.json"

    def load(self):
        try:
            data = validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return defaults()
        data, changed = upgrade(data)
        if changed:
            self.save(data)
        return data

    def add_missing(self):
        data = self.load()
        data["categories"] += missing_starters(data)
        return self.save(data)

    def save(self, data):
        data = validate(data)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return data

    def reset(self):
        old = self.load()      # resetting the categories keeps the folder options
        return self.save({**defaults(), "parent_folder": old.get("parent_folder") or dict(PARENT_DEFAULT),
                          "whole_folders": old.get("whole_folders", True),
                          "folder_pictures": old.get("folder_pictures", True)})


def app_made_folders():
    """Ids of every folder an earlier run of this app created (read from the run logs)."""
    made = set()
    runs = data_dir() / "runs"
    for p in runs.glob("run-*.json") if runs.is_dir() else []:
        try:
            log = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for st in log.get("steps") or []:
            if st.get("op") == "create" and st.get("status") == "done" and st.get("created"):
                made.add(str(st["created"]))
    return made
