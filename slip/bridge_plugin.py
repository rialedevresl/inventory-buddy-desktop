"""Inventory Buddy Desktop - Firestorm side (a LEAP plug-in).

Firestorm starts this when the app launches Firestorm. It asks the app (on
this computer only) for one small job at a time, does it through
Firestorm's own Inventory window, checks the live inventory to confirm
what happened, and reports back. It never sees your password.

Jobs: status, info, children, move, create (a folder), rename, prepare (clear the Inventory search).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from slip.leap import LeapClient  # noqa: E402

LOG = logging.getLogger("slip.bridge")
NULL = "00000000-0000-0000-0000-000000000000"


class JobError(Exception):
    pass


# Pauses for moves, fastest first: (window reset, after select, after Cut/Paste, wait for the move).
# The last one is the original careful timing.
PACES = [(0.15, 0.35, 0.15, 4.0), (0.3, 0.7, 0.25, 8.0), (0.5, 1.2, 0.4, 20.0)]
SPEED_UP_AFTER = 10


class Firestorm:
    """Inventory actions done the way a person would, each one checked afterwards."""

    def __init__(self, client: LeapClient):
        self.c = client
        self.renamer = None
        self.pace = 0             # index into PACES; slows down after a miss, speeds up again after a streak
        self.streak = 0
        self.search_boxes = None  # paths of the Inventory window's search box(es), once found

    # ---------------------------------------------------------------- reads
    def inv(self, op, **args):
        r = self.c.request("LLInventory", {"op": op, **args}, timeout=45)
        if isinstance(r, dict) and r.get("error"):
            raise JobError(str(r["error"]))
        return r if isinstance(r, dict) else {}

    def basic(self, kind):
        names = self.inv("getFolderTypeNames").get("names") or []
        name = next((n for n in names if str(n).startswith(kind)), kind)
        fid = str(self.inv("getBasicFolderID", ft_name=name).get("id") or "")
        return "" if fid == NULL else fid

    def info(self, ids):
        r = self.inv("getItemsInfo", item_ids=list(ids))
        out = {}
        for k, v in (r.get("items") or {}).items():
            out[str(k)] = {"kind": "item", "name": v.get("name"), "parent": str(v.get("parent_id"))}
        for k, v in (r.get("categories") or {}).items():
            out[str(k)] = {"kind": "folder", "name": v.get("name"), "parent": str(v.get("parent_id")),
                           "type": v.get("type")}
        return out

    def children(self, folder):
        r = self.inv("getDirectDescendants", folder_id=folder)
        return {"items": {str(k): v.get("name") for k, v in (r.get("items") or {}).items()},
                "folders": {str(k): v.get("name") for k, v in (r.get("categories") or {}).items()}}

    @staticmethod
    def _shape(r):
        items = {}
        for k, v in (r.get("items") or {}).items():
            items[str(k)] = {"name": v.get("name"), "parent": str(v.get("parent_id")),
                             "type": "link" if v.get("is_link") else v.get("asset_type"),
                             "created": v.get("creation_date"), "linked": str(v.get("linked_id") or "")}
        folders = {str(k): {"name": v.get("name"), "parent": str(v.get("parent_id")), "type": v.get("type")}
                   for k, v in (r.get("categories") or {}).items()}
        return {"items": items, "folders": folders}

    def direct(self, folder):
        """One level of a folder, with full details."""
        return self._shape(self.inv("getDirectDescendants", folder_id=folder))

    def collect(self, folder):
        """Everything inside a folder (all levels, Trash excluded), with the details the app needs."""
        return self._shape(self.inv("collectDescendantsIf", folder_id=folder))

    def status(self):
        root = self.basic("root")
        agent = ""
        if root:
            try:
                a = self.c.request("LLAgent", {"op": "getID"}, timeout=10)
                agent = str(a.get("id") or "") if isinstance(a, dict) else ""
            except TimeoutError:
                pass
        return {"root": root, "trash": self.basic("trash") if root else "", "agent": agent, "ready": bool(root)}

    # ---------------------------------------------------------------- UI steps
    def _ui_ready(self, pause=0.5):
        try:   # a fresh Inventory window means no stale selection from earlier clicking
            r = self.c.request("LLFloaterReg", {"op": "instanceVisible", "name": "inventory"}, timeout=10)
            if isinstance(r, dict) and r.get("visible"):
                self.c.post("LLFloaterReg", {"op": "hideInstance", "name": "inventory"})
                self.c.ping()
                time.sleep(pause)
        except TimeoutError:
            pass

    def select(self, obj, pause=1.2):
        self.c.post("LLCommandDispatcher", {"op": "dispatch", "cmd": "inventory",
                                            "params": [str(obj), "select"], "query": {}})
        self.c.ping()
        time.sleep(pause)

    def edit(self, what, pause=0.4):
        assert what in ("Edit.Cut", "Edit.Copy", "Edit.Paste")   # an unknown name would crash Firestorm
        self.c.post("UI", {"op": "call", "function": what})
        self.c.ping()
        time.sleep(pause)

    def wait(self, check, seconds=20.0, step=0.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v = check()
            if v:
                return v
            time.sleep(step)
        return None

    # ---------------------------------------------------------------- jobs
    def move(self, obj, dest, expect_from=None):
        now = self.info([obj]).get(obj)
        if not now:
            raise JobError("It isn't in your inventory any more.")
        if expect_from and now["parent"] != expect_from:
            if now["parent"] == dest:
                return {"already": True}
            raise JobError("It was moved since the inventory was read, so it was left alone.")
        origin = now["parent"]
        before = self.children(dest)
        before_ids = set(before["items"]) | set(before["folders"])
        started = time.monotonic()
        while True:
            ready, sel, ed, limit = PACES[self.pace]
            self._ui_ready(ready)
            self.select(obj, sel)
            self.edit("Edit.Cut", ed)
            self.select(dest, sel)
            self.edit("Edit.Paste", ed)
            ok = self.wait(lambda: (self.info([obj]).get(obj) or {}).get("parent") == dest, limit)
            self._check_strays(dest, before_ids, obj)
            if ok:
                break
            where = (self.info([obj]).get(obj) or {}).get("parent")
            if where == dest:
                break
            if where != origin:
                raise JobError(f"STOP: \"{now['name']}\" ended up somewhere unexpected.")
            if self.pace == len(PACES) - 1:
                raise JobError("Firestorm didn't confirm the move. If you're wearing it, take it off and run again "
                               "- Firestorm won't move things you have on. Also check that Firestorm's Inventory "
                               "window has nothing in its search box and no filters on.")
            self.pace += 1               # it didn't take: slow down and try again
            self.streak = 0
            LOG.info("Move not confirmed; trying again more slowly (pace %d)", self.pace)
        self.streak += 1
        if self.pace and self.streak >= SPEED_UP_AFTER:
            self.pace -= 1
            self.streak = 0
        LOG.info("Moved in %.1fs (pace %d)", time.monotonic() - started, self.pace)
        return {"moved": True}

    def _check_strays(self, dest, before_ids, obj):
        after = self.children(dest)
        new = (set(after["items"]) | set(after["folders"])) - before_ids - {obj}
        strays = [after["items"].get(i) or after["folders"].get(i) for i in new]
        if strays:
            raise JobError("STRAY: something else also landed in the destination: " + ", ".join(map(str, strays)))

    # ---------------------------------------------------------------- before a run
    def _find_search_boxes(self):
        if self.search_boxes:
            ok = []
            for p in self.search_boxes:
                info = self.c.request("LLWindow", {"op": "getInfo", "path": p}, timeout=10)
                if isinstance(info, dict) and info.get("available"):
                    ok.append(p)
            if ok:
                return ok
        r = self.c.request("LLWindow", {"op": "getPaths"}, timeout=90)
        paths = [str(p) for p in (r.get("paths") or [])] if isinstance(r, dict) else []
        self.search_boxes = [p for p in paths if p.lower().endswith("search editor") and "inventory" in p.lower()]
        LOG.info("Inventory search boxes: %s", self.search_boxes)
        return self.search_boxes

    def warmup(self):
        """Find the Inventory window's search box ahead of time, so the first run doesn't wait for it."""
        try:
            r = self.c.request("LLFloaterReg", {"op": "instanceVisible", "name": "inventory"}, timeout=10)
            was_open = isinstance(r, dict) and r.get("visible")
            if not was_open:
                self.c.post("LLFloaterReg", {"op": "showInstance", "name": "inventory"})
                self.c.ping()
                time.sleep(0.8)
            self.search_boxes = None
            boxes = self._find_search_boxes()
            if not was_open:
                self.c.post("LLFloaterReg", {"op": "hideInstance", "name": "inventory"})
        except TimeoutError:
            return {"found": 0}
        return {"found": len(boxes)}

    def prepare(self):
        """A search typed in Firestorm's Inventory window hides things from it, and then they can't be
        selected. Clear it before a run."""
        try:
            self.c.post("LLFloaterReg", {"op": "showInstance", "name": "inventory"})
            self.c.ping()
            time.sleep(0.8)
            boxes = self._find_search_boxes()
        except TimeoutError:
            return {"checked": False}
        cleared = 0
        for path in boxes:
            text = self.c.request("UI", {"op": "getValue", "path": path}, timeout=10).get("value")
            if not text:
                continue
            self._key(keysym="End", path=path)
            back = "Backsp"            # Second Life's name for the Backspace key
            for _ in range(len(str(text)) + 2):
                try:
                    self._key(keysym=back, path=path)
                except JobError:
                    if back == "BackSpace":
                        raise
                    back = "BackSpace"
                    self._key(keysym=back, path=path)
            time.sleep(0.5)
            left = self.c.request("UI", {"op": "getValue", "path": path}, timeout=10).get("value")
            if left:
                raise JobError(f'Firestorm\'s Inventory window is searching for "{text}". Clear its search box '
                               "(and any filters), then run again - things it hides can't be moved.")
            cleared += 1
        if cleared:
            LOG.info("Cleared %d Inventory search box(es)", cleared)
            time.sleep(1.0)     # let the Inventory window show everything again
        return {"checked": bool(boxes), "cleared": cleared}

    def _renamer_path(self):
        if self.renamer:
            info = self.c.request("LLWindow", {"op": "getInfo", "path": self.renamer}, timeout=10)
            if isinstance(info, dict) and info.get("available"):
                return self.renamer
        r = self.c.request("LLWindow", {"op": "getPaths"}, timeout=90)
        for p in [p for p in (r.get("paths") or []) if str(p).endswith("/ren")] if isinstance(r, dict) else []:
            info = self.c.request("LLWindow", {"op": "getInfo", "path": p}, timeout=10)
            if isinstance(info, dict) and info.get("available"):
                self.renamer = p
                return p
        return None

    def _key(self, **evt):
        r = self.c.request("LLWindow", {"op": "keyDown", **evt}, timeout=10)
        if isinstance(r, dict) and r.get("error"):
            raise JobError("Typing was refused: " + str(r["error"]))
        self.c.post("LLWindow", {"op": "keyUp", **evt})

    def _open_renamer(self, obj, expect, attempt):
        """Select obj and press F2; wait for the rename box showing its current name. None if it didn't open."""
        self._ui_ready()
        self.select(obj)
        time.sleep(0.6 * attempt)              # a folder that was just made can take a moment to show up
        self.c.request("LLWindow", {"op": "keyDown", "keysym": "F2"}, timeout=10)
        self.c.post("LLWindow", {"op": "keyUp", "keysym": "F2"})
        end = time.monotonic() + 2.5 + 1.5 * attempt
        while time.monotonic() < end:
            time.sleep(0.4)
            path = self._renamer_path()
            if not path:
                continue
            shown = self.c.request("UI", {"op": "getValue", "path": path}, timeout=10).get("value")
            if shown == expect:
                return path
            if shown:                           # open, but on something else: cancel and try again
                self._key(keysym="Esc", path=path)
                return None
        return None

    def rename(self, obj, name):
        if not all(32 <= ord(ch) < 127 for ch in name) or "|" in name:
            raise JobError("That name has characters Firestorm's rename box won't take.")
        cur = self.info([obj]).get(obj)
        if not cur:
            raise JobError("That folder isn't in your inventory any more.")
        if cur["name"] == name:
            return {"already": True}
        path = None
        for attempt in range(3):
            path = self._open_renamer(obj, cur["name"], attempt)
            if path:
                break
        if not path:
            raise JobError("The rename box didn't open (tried 3 times).")
        for ch in name:
            self._key(char=ch, path=path)
        typed = self.c.request("UI", {"op": "getValue", "path": path}, timeout=10).get("value")
        if typed != name:
            self._key(keysym="Esc", path=path)
            raise JobError("The typed name didn't come out right, so it was cancelled.")
        self._key(keysym="Enter", path=path)
        if not self.wait(lambda: (self.info([obj]).get(obj) or {}).get("name") == name):
            raise JobError("Firestorm didn't confirm the new name.")
        return {"renamed": True}

    def create(self, parent, name, template):
        """New folder = copy of an empty folder pasted into parent, then renamed."""
        t = self.children(template)
        if t["items"] or t["folders"]:
            raise JobError("The template folder isn't empty any more.")
        tinfo = self.info([template]).get(template)
        if not tinfo:
            raise JobError("The template folder is gone.")
        kids = self.children(parent)["folders"]
        # Already there (an earlier run got this far)? Use it.
        same = [k for k, n in kids.items() if n == name and k != template]
        if same:
            return {"id": same[0], "existing": True}
        # A copy of the template left over from an attempt whose rename failed: rename that one.
        leftover = [k for k, n in kids.items() if n == tinfo["name"] and k != template
                    and not (lambda c: c["items"] or c["folders"])(self.children(k))]
        if leftover:
            self.rename(leftover[0], name)
            return {"id": leftover[0], "reused": True}
        before = set(kids)
        self._ui_ready()
        self.select(template)
        self.edit("Edit.Copy")
        self.select(parent)
        self.edit("Edit.Paste")

        def new_folder():
            kids = self.children(parent)["folders"]
            fresh = [k for k in kids if k not in before]
            return fresh[0] if len(fresh) == 1 else None
        fid = self.wait(new_folder, 25)
        if not fid:
            raise JobError("No new folder appeared.")
        self.rename(fid, name)
        return {"id": fid}


def http(method, url, token, body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Bridge-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def detach_console():
    """Firestorm starts this as a console program, so Windows opens an empty terminal window for it.
    Nothing is shown there (Firestorm talks to it through pipes), so let go of it: the window closes.
    Returns True if there was a console window (then stderr went to it and is no use any more)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        if not k.GetConsoleWindow():
            return False
        k.FreeConsole()
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    on_console = detach_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--log", type=Path)
    args = ap.parse_args()
    handlers = [] if on_console or sys.stderr is None else [logging.StreamHandler(sys.stderr)]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s bridge %(levelname)s %(message)s", handlers=handlers)
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    client = LeapClient(sys.stdin.buffer, sys.stdout.buffer)
    fs = Firestorm(client)
    base = args.app.rstrip("/")
    session = uuid.uuid4().hex
    LOG.info("Connected to Firestorm")
    try:
        serve(client, fs, base, args.token, session)
    finally:
        try:   # let the app know straight away, so it doesn't wait on a job that can't finish
            http("POST", base + "/bridge/bye", args.token, {"session": session}, timeout=5)
        except Exception:  # noqa: BLE001
            pass
    LOG.info("Firestorm closed")
    return 0


def serve(client, fs, base, token, session):
    last_status = 0.0
    while client.connected:
        try:
            if time.monotonic() - last_status > 5:
                try:
                    http("POST", base + "/bridge/hello", token, {**fs.status(), "session": session}, timeout=10)
                except (TimeoutError, ConnectionError):
                    pass
                last_status = time.monotonic()
            if not client.connected:
                break
            job = http("GET", base + "/bridge/poll", token, timeout=25)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            LOG.info("App not reachable (%s); retrying", exc)
            time.sleep(3)
            continue
        if not job or job.get("op") in (None, "none"):
            continue
        result = {"id": job.get("id"), "ok": True}
        try:
            op = job["op"]
            if op == "status":
                result["result"] = fs.status()
            elif op == "info":
                result["result"] = fs.info(job["ids"])
            elif op == "direct":
                result["result"] = fs.direct(job["folder"])
            elif op == "collect":
                result["result"] = fs.collect(job["folder"])
            elif op == "children":
                result["result"] = fs.children(job["folder"])
            elif op == "move":
                result["result"] = fs.move(job["obj"], job["dest"], job.get("from"))
            elif op == "rename":
                result["result"] = fs.rename(job["obj"], job["name"])
            elif op == "warmup":
                result["result"] = fs.warmup()
            elif op == "prepare":
                result["result"] = fs.prepare()
            elif op == "create":
                result["result"] = fs.create(job["parent"], job["name"], job["template"])
            else:
                raise JobError(f"Unknown job {op!r}")
        except JobError as exc:
            result.update(ok=False, error=str(exc))
        except (TimeoutError, ConnectionError) as exc:
            result.update(ok=False, error=f"Firestorm didn't answer ({exc}).")
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Job failed")
            result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        try:
            http("POST", base + "/bridge/result", token, result, timeout=15)
        except (urllib.error.URLError, OSError) as exc:
            LOG.warning("Couldn't report a result: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
