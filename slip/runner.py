"""Turning the plan into steps, running them through Firestorm, and undoing a run.

Steps (in this order):
  rename  - an existing category folder to its short name (e.g. "Decor - Mirrors" -> "Mirrors")
  create  - a missing category folder (copy of an empty folder, then renamed)
  move    - a product folder or loose item into its category folder
  trash   - a marked thing into Firestorm's Trash (never emptied)
Every step is checked against the live inventory. A run can be paused or
stopped between steps, and every finished step is written to a log so the
whole run can be undone.
"""
from __future__ import annotations

import datetime
import json
import threading
import time

from .bridge import Hub, JobFailed
from .categories import data_dir
from .sorter import SPECIAL, TRASH

TEMPLATE_NAME = "Inventory Cleanup Template"


def runs_dir():
    d = data_dir() / "runs"
    d.mkdir(exist_ok=True)
    return d


def build_steps(session, rename_old=True):
    """The full list of steps for the current plan (nothing is done yet)."""
    sorter, inv = session.sorter, session.inv
    plan = session.plan_units()
    sub_f, top_f = sorter.category_folders()
    steps, refs, renamed = [], {}, set()
    # Settings and landmarks go to their own system folders, which are always there.
    for k in SPECIAL:
        refs[k] = inv.special_folder(k)
    needed = sorted({c for _, c in plan if c != TRASH and c not in SPECIAL},
                    key=lambda c: (sorter.tops[sorter.subs[c]["top"]]["name"], sorter.subs[c]["name"]))

    def add(**kw):
        kw.setdefault("status", "todo")
        kw["n"] = len(steps) + 1
        steps.append(kw)

    # Optional: category folders live inside a parent folder (e.g. "Sorted"), or one of two
    # (appearance in one, everything else in the other).
    parent_ids = sorter.parent_folder_ids()
    tucked = set()

    def parent_ref(top):
        pn = sorter.parent_name_for(top)
        if not pn:
            return "@root"
        fid = sorter.parent_folder(pn)
        if fid:
            return fid
        key = "@parent:" + pn.lower()
        if key not in refs:
            refs[key] = key
            add(op="create", parent="@root", name=pn, ref=key, label=f'Create folder “{pn}”')
        return key

    def tuck(fid, top):
        """A top category folder in My Inventory (or in the wrong parent folder) goes into its parent folder."""
        pn = sorter.parent_name_for(top)
        f = inv.folders[fid]
        if not pn or fid in tucked or fid in parent_ids or f.parent not in {inv.root} | parent_ids:
            return
        dest = parent_ref(top)
        if dest == f.parent:
            return
        tucked.add(fid)
        add(op="tuck", obj=fid, frm=f.parent, dest=dest, unit=None, cat=None, uname=f.name, pname=pn,
            label=f'Move folder “{f.name}” into “{pn}”')

    def top_ref(top):
        """The top category folder (in its parent folder, or My Inventory), made if it isn't there."""
        tkey = "@top:" + top["id"]
        if tkey not in refs:
            pn = sorter.parent_name_for(top)
            tf = (top_f.get(top["id"]) or [None])[0]
            if tf:
                refs[tkey] = tf
                if rename_old and inv.folders[tf].name != top["name"] and tf not in renamed:
                    renamed.add(tf)
                    add(op="rename", obj=tf, name=top["name"], old=inv.folders[tf].name,
                        label=f'Rename folder “{inv.folders[tf].name}” to “{top["name"]}”')
                tuck(tf, top)
            else:
                refs[tkey] = tkey
                add(op="create", parent=parent_ref(top), name=top["name"], ref=tkey,
                    label=f'Create folder “{pn + " › " if pn else ""}{top["name"]}”')
        return refs[tkey]

    adopted = getattr(sorter, "adopted", {})
    # A checked category whose folder is an older one of yours gets it renamed and moved into place,
    # even when nothing new is going into it.
    needed = sorted(set(needed) | {c for c in adopted if c in session.approved},
                    key=lambda c: (sorter.tops[sorter.subs[c]["top"]]["name"], sorter.subs[c]["name"]))
    for sid in needed:
        sub = sorter.subs[sid]
        top = sorter.tops[sub["top"]]
        existing = (sub_f.get(sid) or [None])[0]
        if existing and adopted.get(sid) == existing:
            refs[sid] = existing
            f = inv.folders[existing]
            if f.name != sub["name"]:
                renamed.add(existing)
                add(op="rename", obj=existing, name=sub["name"], old=f.name,
                    label=f'Rename folder “{f.name}” to “{sub["name"]}”')
            dest = top_ref(top)
            pn = sorter.parent_name_for(top)
            add(op="tuck", obj=existing, frm=f.parent, dest=dest, unit=None, cat=None, uname=sub["name"],
                pname=f'{pn + " › " if pn else ""}{top["name"]}',
                label=f'Move folder “{sub["name"]}” (was “{f.name}” in {inv.path_text(f.parent)}) into '
                      f'“{pn + " › " if pn else ""}{top["name"]}”')
            continue
        if existing:
            refs[sid] = existing
            f = inv.folders[existing]
            if rename_old and f.name != sub["name"] and existing not in renamed:
                renamed.add(existing)
                add(op="rename", obj=existing, name=sub["name"], old=f.name,
                    label=f'Rename folder “{f.name}” to “{sub["name"]}”')
            parent = f.parent
            if rename_old and parent in inv.folders and parent != inv.root and parent not in renamed \
                    and parent in (top_f.get(top["id"]) or []) and inv.folders[parent].name != top["name"]:
                renamed.add(parent)
                add(op="rename", obj=parent, name=top["name"], old=inv.folders[parent].name,
                    label=f'Rename folder “{inv.folders[parent].name}” to “{top["name"]}”')
            if parent in (top_f.get(top["id"]) or []):
                tuck(parent, top)
            continue
        tref = top_ref(top)
        skey = "@sub:" + sid
        refs[sid] = skey
        add(op="create", parent=tref, name=sub["name"], ref=skey,
            label=f'Create folder “{top["name"]} › {sub["name"]}”')

    moves = []
    whole = _whole_folders(session, plan)
    in_whole = {uid for f in whole.values() for uid in f["units"]}
    for uid, cat in plan:
        if uid in in_whole:
            continue
        u = sorter.units[uid]
        obj = u.folder if u.kind == "product" else uid[2:]
        frm = u.parent if u.kind == "product" else u.folder
        if cat == TRASH:
            moves.append((2, "", dict(op="trash", obj=obj, frm=frm, dest="@trash", unit=uid, cat=cat, uname=u.name,
                                      label=f'Send “{u.name}” to Trash', nocopy=u.nocopy,
                                      where=inv.path_text(frm) if frm in inv.folders else "")))
        else:
            moves.append((1, cat, _move_step(sorter, refs, uid, cat, obj, frm)))
    for fid, w in whole.items():
        cat, f = w["cat"], inv.folders[fid]
        sub = sorter.subs[cat]
        split = []
        for uid in w["units"]:
            u = sorter.units[uid]
            split.append(_move_step(sorter, refs, uid, cat, uid[2:], u.folder))
        moves.append((1, cat, dict(op="move", obj=fid, frm=f.parent, dest=refs[cat], unit=None, cat=cat,
                                   units=w["units"], uname=f.name, names=[s["uname"] for s in split],
                                   split=split, label=f'Move folder “{f.name}” ({len(split)} things) to {sub["name"]}')))
    # Everything going to the same folder runs together.
    order = {c: i for i, c in enumerate(needed)}
    for _, _, m in sorted(moves, key=lambda x: (x[0], order.get(x[1], -1), x[2]["label"].lower())):
        add(**m)
    return steps


def _move_step(sorter, refs, uid, cat, obj, frm):
    u = sorter.units[uid]
    name = SPECIAL.get(cat) or sorter.subs[cat]["name"]
    return dict(op="move", obj=obj, frm=frm, dest=refs[cat], unit=uid, cat=cat, uname=u.name,
                label=f'Move “{u.name}” to {name}')


MIN_WHOLE = 3


def _whole_folders(session, plan):
    """Plain folders (not products) where everything inside is going to the same category:
    those move as one folder instead of item by item. Anything unusual about a folder
    (subfolders, links, a system or category folder, something staying behind) rules it out."""
    sorter, inv = session.sorter, session.inv
    if not sorter.whole_folders_setting():
        return {}
    by_folder = {}
    for uid, cat in plan:
        u = sorter.units[uid]
        if u.kind not in ("item", "piece") or u.product:
            continue
        by_folder.setdefault(u.folder, []).append((uid, cat))
    out = {}
    for fid, entries in by_folder.items():
        f = inv.folders.get(fid)
        cats = {c for _, c in entries}
        if not f or len(cats) != 1 or TRASH in cats or cats & set(SPECIAL) or len(entries) < MIN_WHOLE:
            continue
        if fid == inv.root or f.parent not in inv.folders or f.system or f.folders or inv.in_trash(fid) \
                or inv.hands_off(fid) or inv.skipped_by(fid) or inv.is_category_folder(fid) \
                or fid in sorter.parent_folder_ids():
            continue
        if len(f.items) != len(entries):          # links, or something not going along
            continue
        out[fid] = {"cat": next(iter(cats)), "units": [uid for uid, _ in entries]}
    return out


def summarize(steps, session):
    groups = {}
    for s in steps:
        if s["op"] == "move" and s.get("cat") in SPECIAL:
            g = groups.setdefault(s["cat"], {"id": s["cat"], "name": SPECIAL[s["cat"]], "top": "", "items": []})
            g["items"].append(s["uname"])
            continue
        if s["op"] == "move":
            sub = session.sorter.subs[s["cat"]]
            g = groups.setdefault(s["cat"], {"id": s["cat"], "name": sub["name"],
                                             "top": session.sorter.tops[sub["top"]]["name"], "items": []})
            g["items"].extend(s.get("names") or [s["uname"]])
    return {
        "total": len(steps),
        "moves": sum(1 for s in steps if s["op"] == "move"),
        "folders": sum(1 for s in steps if s["op"] == "move" and s.get("units")),
        "creates": [s["label"].replace("Create folder ", "").strip('“”') for s in steps if s["op"] == "create"],
        "renames": [{"old": s["old"], "new": s["name"]} for s in steps if s["op"] == "rename"],
        "tucks": [f'{s["uname"]} → {s["pname"]}' if s.get("pname") else s["uname"] for s in steps if s["op"] == "tuck"],
        "parent": " / ".join(session.sorter.parent_names()[1:] or session.sorter.parent_names()),
        "trash": [{"name": s["uname"], "where": s.get("where", ""), "nocopy": s.get("nocopy", False),
                   "unit": s["unit"], "ktype": session._ktype(session.sorter.units[s["unit"]])
                   if s["unit"] in session.sorter.units else "Other"} for s in steps if s["op"] == "trash"],
        "groups": sorted(groups.values(), key=lambda g: (g["top"], g["name"])),
    }


class Run:
    """One run of the plan, in a background thread."""

    def __init__(self, hub: Hub, session, steps, undo_of=None):
        self.hub, self.session, self.steps = hub, session, steps
        self.state = "ready"          # ready, running, paused, stopping, done, stopped, failed
        self.message = ""
        self.current = None
        self.pause = threading.Event()
        self.stop_flag = threading.Event()
        self.refs = {}
        self.undo_of = undo_of
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = runs_dir() / (f"undo-{stamp}.json" if undo_of else f"run-{stamp}.json")
        self.thread = None

    # ---------------------------------------------------------------- control
    def start(self):
        self.state = "running"
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def toggle_pause(self):
        if self.state == "running":
            self.pause.set()
            self.state = "paused"
        elif self.state == "paused":
            self.pause.clear()
            self.state = "running"

    def stop(self):
        self.stop_flag.set()
        self.pause.clear()
        if self.state in ("running", "paused"):
            self.state = "stopping"

    def status(self):
        done = sum(1 for s in self.steps if s["status"] == "done")
        bad = [s for s in self.steps if s["status"] in ("failed", "skipped")]
        total = sum(1 for s in self.steps if s["status"] != "split")
        return {"state": self.state, "message": self.message, "total": total, "done": done,
                "problems": [{"label": s["label"], "note": s.get("note", ""), "status": s["status"]} for s in bad][-50:],
                "current": self.current, "log": self.log_path.name, "undo": bool(self.undo_of),
                "recent": [s["label"] for s in self.steps if s["status"] == "done"][-8:],
                "undo_of": self.undo_of}

    # ---------------------------------------------------------------- running
    def _save(self):
        tmp = self.log_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"inventory": self.session.inv.root, "undo_of": self.undo_of,
                                   "refs": self.refs, "steps": self.steps}, indent=1), encoding="utf-8")
        tmp.replace(self.log_path)

    def _resolve(self, ref):
        if ref == "@root":
            return self.session.inv.root
        if ref == "@trash":
            return self.trash
        if ref and ref.startswith("@"):
            if ref not in self.refs:
                raise JobFailed("Its folder couldn't be created, so this was skipped.")
            return self.refs[ref]
        return ref

    def _template(self):
        """An empty folder to copy when a new folder is needed."""
        inv = self.session.inv
        pnames = {n.lower() for n in self.session.sorter.parent_names()}
        cands = [f for f in inv.folders.values()
                 if not f.system and not inv.in_trash(f.id) and f.id != inv.root and not f.folders and not f.items
                 and not inv.hands_off(f.id) and not inv.skipped_by(f.id) and not inv.is_category_folder(f.id)
                 and f.name.strip().lower() not in pnames]
        cands.sort(key=lambda f: (f.name != TEMPLATE_NAME, f.name.lower()))
        for f in cands[:25]:
            try:
                kids = self.hub.call("children", folder=f.id)
            except JobFailed:
                continue
            if not kids["items"] and not kids["folders"]:
                return f.id
        return None

    def _run(self):
        try:
            st = self.hub.status()
            if not st["ready"]:
                raise RuntimeError("Firestorm isn't connected and logged in.")
            if st["root"] != self.session.inv.root:
                raise RuntimeError("Firestorm is logged in to a different avatar than the inventory you sorted.")
            self.trash = st["trash"]
            self.template = None
            if any(s["op"] == "create" and s["status"] == "todo" for s in self.steps):
                self.template = self._template()
                if not self.template:
                    raise RuntimeError(f'New folders are needed, but there\'s no empty folder to copy. In Firestorm, '
                                       f'make one empty folder called "{TEMPLATE_NAME}", then Rescan and run again.')
            if any(s["status"] == "todo" and s["op"] in ("move", "trash", "tuck", "create", "rename")
                   for s in self.steps):
                self.current = "Getting Firestorm's Inventory window ready"
                try:
                    self.hub.call("prepare", timeout=150)
                except JobFailed as exc:
                    raise RuntimeError(str(exc)) from None
            for step in self.steps:
                if self.stop_flag.is_set():
                    break
                while self.pause.is_set() and not self.stop_flag.is_set():
                    if not self.hub.connected():
                        self.stop_flag.set()      # Firestorm closed while paused
                        break
                    time.sleep(0.3)
                if self.stop_flag.is_set():
                    break
                if step["status"] != "todo":
                    continue
                self.current = step["label"]
                try:
                    self._do(step)
                    step["status"] = "done"
                except JobFailed as exc:
                    note = str(exc)
                    step["status"], step["note"] = "failed", note
                    if step.get("split") and not note.startswith(("STRAY", "STOP")):
                        # The folder wouldn't move as a whole: move what's in it one by one instead.
                        step["status"], step["note"] = "split", "Moved the things inside one by one instead."
                        at = self.steps.index(step) + 1
                        self.steps[at:at] = [dict(s, status="todo") for s in step["split"]]
                        for i, s in enumerate(self.steps):
                            s["n"] = i + 1
                        self._save()
                        continue
                    if note.startswith(("STRAY", "STOP")):
                        what = ("something unexpected landed in a folder. " if note.startswith("STRAY")
                                else "")
                        self.message = ("Stopped: " + what + note.split(":", 1)[1].strip()
                                        + " - please check it in Firestorm.")
                        self._save()
                        self.state = "failed"
                        return
                except (TimeoutError, ConnectionError) as exc:
                    step["status"], step["note"] = "failed", str(exc)
                    self.message = f"Stopped: {exc}"
                    self._save()
                    self.state = "failed"
                    return
                self._save()
            self.current = None
            self.state = "stopped" if self.stop_flag.is_set() else "done"
            n = sum(1 for s in self.steps if s["status"] == "done")
            total = sum(1 for s in self.steps if s["status"] != "split")
            self.message = f"{'Stopped' if self.stop_flag.is_set() else 'Finished'}: {n} of {total} steps done."
        except Exception as exc:  # noqa: BLE001
            self.state, self.message = "failed", str(exc)
        finally:
            self._save()
            self._mark_undone()
            self.session.after_run(self.steps, undo=bool(self.undo_of))

    def _mark_undone(self):
        """In the original run's log, steps that were put back aren't put back twice by a later Undo."""
        undone = {s["of"] for s in self.steps if s.get("status") == "done" and s.get("of")}
        if not self.undo_of or not undone:
            return
        path = runs_dir() / self.undo_of
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
            for s in log["steps"]:
                if s.get("n") in undone and s.get("status") == "done":
                    s["status"] = "undone"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(log, indent=1), encoding="utf-8")
            tmp.replace(path)
        except (OSError, ValueError, KeyError):
            pass

    def _do(self, step):
        op = step["op"]
        if op == "rename":
            self.hub.call("rename", obj=step["obj"], name=step["name"])
        elif op == "create":
            res = self.hub.call("create", parent=self._resolve(step["parent"]), name=step["name"],
                                template=self.template, timeout=180)
            self.refs[step["ref"]] = res["id"]
            if res.get("existing"):
                step["note"] = "It was already there."
            else:
                step["created"] = res["id"]     # only folders this run made are trashed by Undo
        elif op in ("move", "trash", "tuck"):
            if step.get("empty_only"):
                kids = self.hub.call("children", folder=step["obj"])
                if kids["items"] or kids["folders"]:
                    raise JobFailed("It isn't empty any more, so it was kept.")
            dest = self._resolve(step["dest"])
            step["dest_id"] = dest
            res = self.hub.call("move", obj=step["obj"], dest=dest, **{"from": step.get("frm")})
            if res and res.get("already"):
                step["note"] = "Was already there."


def moved_steps(log):
    """What a run moved that can still be put back one by one, newest first."""
    return [{"n": s["n"], "label": s["label"], "trash": s["op"] == "trash"} for s in reversed(log["steps"])
            if s.get("status") == "done" and s["op"] in ("move", "trash", "tuck")]


def undo_steps(log, only=None):
    """Steps that reverse a finished run (or just the steps numbered in `only`), newest first."""
    out = []
    for s in reversed(log["steps"]):
        if s.get("status") != "done" or (only is not None and s.get("n") not in only):
            continue
        if s["op"] in ("move", "trash", "tuck"):
            out.append(dict(op="move", obj=s["obj"], frm=s.get("dest_id"), dest=s["frm"], unit=s.get("unit"),
                            units=s.get("units"), cat=s.get("cat"), label="Put back: " + s["label"], status="todo",
                            of=s.get("n")))
        elif s["op"] == "rename":
            out.append(dict(op="rename", obj=s["obj"], name=s["old"], old=s["name"],
                            label=f'Rename “{s["name"]}” back to “{s["old"]}”', status="todo", of=s.get("n")))
        elif s["op"] == "create" and s.get("created"):
            out.append(dict(op="trash", obj=s["created"], frm=None, dest="@trash", unit=None, cat=None,
                            label=f'Send the new empty folder “{s["name"]}” to Trash', status="todo", empty_only=True,
                            of=s.get("n")))
    for i, s in enumerate(out):
        s["n"] = i + 1
    return out
