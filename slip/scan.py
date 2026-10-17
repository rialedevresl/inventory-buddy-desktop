"""Reading the inventory live from Firestorm (a "fresh scan").

Firestorm already holds the whole inventory once you're logged in; the scan
asks for it one top-level folder at a time so it can show progress, then
fills in details (creator, permissions, thumbnails) from the saved copy on
disk by item id.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .bridge import JobFailed
from .inventory import Inventory, find_caches


class Scanner:
    def __init__(self, hub, extra_dirs=()):
        self.hub = hub
        self.extra_dirs = list(extra_dirs)
        self.state = "idle"          # idle, scanning, ready, error
        self.done = 0
        self.total = 0
        self.message = ""
        self.result: Inventory | None = None
        self.lock = threading.Lock()
        self.session = None          # which Firestorm connection the last scan used

    def status(self):
        return {"state": self.state, "done": self.done, "total": self.total, "message": self.message}

    def start(self):
        with self.lock:
            if self.state == "scanning":
                return False
            self.state, self.done, self.total, self.message = "scanning", 0, 0, "Reading your inventory…"
            self.session = self.hub.session
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _cache_for(self, agent):
        for p in find_caches(self.extra_dirs):
            if agent and p.name.lower().startswith(agent.lower()):
                return p
        return None

    def _ask(self, op, tries, **args):
        """One read job, tried again if Firestorm's answer got lost or garbled."""
        last = None
        for n in range(tries):
            try:
                return self.hub.call(op, **args)
            except ConnectionError:
                raise                      # the link itself is gone: retrying won't help
            except (JobFailed, TimeoutError) as exc:
                last = exc
                time.sleep(1 + n)
        raise last

    def _read_folder(self, fid, name, depth=0):
        """Everything inside one folder. Big folders make big replies, and those are the ones
        Firestorm sometimes garbles - so if it fails twice, read it one level at a time."""
        try:
            return self._ask("collect", 2, folder=fid, timeout=300)
        except ConnectionError:
            raise
        except (JobFailed, TimeoutError):
            if depth > 40:
                raise
        self.message = f"Reading “{name}” in smaller pieces…"
        top = self._ask("direct", 3, folder=fid, timeout=120)
        folders, items = dict(top["folders"]), dict(top["items"])
        for sub, info in top["folders"].items():
            part = self._read_folder(sub, info.get("name") or name, depth + 1)
            folders.update(part["folders"])
            items.update(part["items"])
        return {"folders": folders, "items": items}

    def _run(self):
        try:
            st = self.hub.status()
            if not st["ready"]:
                raise RuntimeError("Firestorm isn't logged in yet.")
            root, trash = st["root"], st["trash"]
            top = self._ask("direct", 3, folder=root, timeout=120)
            folders, items = dict(top["folders"]), dict(top["items"])
            tops = [fid for fid, f in top["folders"].items() if fid != trash]
            self.total = len(tops)
            for fid in tops:
                part = self._read_folder(fid, top["folders"][fid].get("name") or "a folder")
                folders.update(part["folders"])
                items.update(part["items"])
                self.done += 1
                self.message = f"Reading your inventory… {len(items):,} items so far"
            folders.pop(trash, None)
            trash_count = 0
            if trash:
                t = self._ask("direct", 3, folder=trash, timeout=120)
                trash_count = len(t["items"]) + len(t["folders"])
            live = {"root": root, "trash": trash, "folders": folders, "items": items, "trash_count": trash_count}
            cache = self._cache_for(st.get("agent"))
            self.result = Inventory(live=live, cache=cache)
            self.state = "ready"
            self.message = f"Read {len(items):,} items in {len(folders):,} folders."
        except ConnectionError:
            self.state, self.message = "error", ("The link to Firestorm dropped while reading. Quit Firestorm, "
                                                 "then press Start Firestorm again.")
        except Exception as exc:  # noqa: BLE001
            self.state, self.message = "error", f"Couldn't read the inventory: {exc}"
