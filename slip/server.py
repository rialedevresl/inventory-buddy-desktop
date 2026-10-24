"""Local web server for the app. Listens on 127.0.0.1 only."""
from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .categories import CategoryStore, data_dir
from .inventory import Inventory, list_inventories
from .thumbs import Thumbs
from .sortplan import SortSession
from .bridge import Hub
from . import runner
from .scan import Scanner

WEB = Path(__file__).resolve().parent.parent / "web"


class Locked(Exception):
    """The app is waiting for Firestorm (connect, log in, fresh scan)."""


class AppState:
    def __init__(self, extra_dirs=(), categories_path=None, offline=False):
        self.extra_dirs = list(extra_dirs)
        self.offline = offline       # testing only: work from the saved cache, no Firestorm needed
        self.lock = threading.Lock()
        self.inv: Inventory | None = None
        self.sort: SortSession | None = None
        self.inv_path = None
        self.cats = CategoryStore(categories_path)
        self.token = secrets.token_urlsafe(16)
        self.thumbs = Thumbs(data_dir() / "thumbs")
        self.hub = Hub()
        self.scanner = Scanner(self.hub, self.extra_dirs)
        self.run = None
        self.app_url = ""
        self.last_ui = 0.0           # last time an app window talked to us (the desktop launcher quits when idle)
        self.window_closed = 0.0     # last time a window said it was closing
        self.quit_requested = False  # a newer copy of the app is starting and asked this one to step aside

    def inventories(self):
        return list_inventories(self.extra_dirs)

    def open(self, path=None):
        with self.lock:
            invs = self.inventories()
            if not invs:
                raise LookupError("No Firestorm inventory found on this computer. Log in with Firestorm once, "
                                  "quit it, then press Rescan.")
            if path is None:
                path = self.inv_path or max(invs, key=lambda i: i["bytes"])["path"]
            if path not in {i["path"] for i in invs}:
                raise LookupError("That inventory isn't available any more.")
            self.inv = Inventory(Path(path))
            self.inv_path = path
            self.sort = None
            self.apply_categories()
            return self.inv

    def locked(self):
        if self.offline:
            return False
        if self.run and self.run.state in ("running", "stopping") and self.inv is not None:
            return False             # a run is going: it stops by itself if Firestorm really closes
        st = self.hub.status()
        return not (st["ready"] and self.inv is not None and self.inv.root == st["root"])

    def session(self):
        """Where things stand, and kick off a fresh scan as soon as Firestorm is logged in."""
        st = self.hub.status()
        scan = self.scanner.status()   # read first: if it says finished, the new inventory is taken in just below
        if not self.offline:
            self._adopt()
            needs_scan = st["ready"] and (self.inv is None or self.inv.root != st["root"])
            fresh_link = self.scanner.state == "error" and self.scanner.session != self.hub.session
            if needs_scan and (self.scanner.state in ("idle", "ready") or fresh_link):
                self.scanner.start()   # also retries by itself after Firestorm was restarted
            self._warm(st)
        return {"offline": self.offline, "locked": self.locked(), "bridge": st, "scan": scan,
                "items": len(self.inv.items) if self.inv else 0}

    def _warm(self, st):
        """Once Firestorm is connected and the inventory is read, find Firestorm's Inventory search box in
        the background while you sort, so a run can start straight away."""
        hub = self.hub
        if not st["ready"] or self.scanner.state != "ready" or hub.warmed == hub.session:
            return
        if self.run and self.run.state in ("running", "paused", "stopping"):
            return
        hub.warmed = hub.session

        def go():
            try:
                hub.call("warmup", timeout=150)
            except Exception:  # noqa: BLE001 - only a head start: a run looks again if this didn't work
                pass
        threading.Thread(target=go, daemon=True).start()

    def _adopt(self):
        res = self.scanner.result
        if res is not None and res is not self.inv and self.scanner.state == "ready":
            with self.lock:
                self.inv = res
                self.inv_path = None
                self.sort = None
            self.apply_categories()

    def sorting(self):
        self.current()
        with self.lock:
            if self.sort is None:
                self.sort = SortSession(self.inv, self.cats.load())
            return self.sort

    def apply_categories(self, data=None):
        if self.inv is None:
            return
        data = data or self.cats.load()
        names = []
        for top in data["categories"]:
            names += [top["name"], *top.get("aliases", [])]
            for c in top["children"]:
                names += [c["name"], *c.get("aliases", [])]
        self.inv.set_categories(names)
        self.apply_pictures(data)
        if self.sort is not None:
            self.sort.set_categories(data)

    def apply_pictures(self, data):
        """Pictures for products without a thumbnail, from textures inside them. The choices are saved,
        so a product keeps its picture after its textures are cleaned out (the image itself stays in the
        thumbnail cache, and Second Life keeps serving it)."""
        inv = self.inv
        path = data_dir() / f"pictures-{inv.root}.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if not data.get("folder_pictures", True):
            for f in inv.folders.values():
                f.pic = ""
            return
        found = inv.find_pictures(saved if isinstance(saved, dict) else {})
        if found != saved:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(found), encoding="utf-8")
            tmp.replace(path)

    def current(self):
        if self.offline:
            return self.inv or self.open()
        self._adopt()
        if self.locked():
            raise Locked("Start Firestorm and log in first - the app reads your inventory fresh from Firestorm.")
        return self.inv

    def browse_ready(self):
        """My Inventory and Search show Product / Split marks, so the sort choices must be applied first."""
        inv = self.current()
        self.sorting()
        return inv


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SLInventoryCleanup"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # -------------------------------------------------------------- helpers
        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode("utf-8"))

        def _error(self, msg, code=400):
            self._json({"error": msg}, code)

        def _authed(self):
            # API calls must carry the per-launch token (stops other web pages poking the app).
            return secrets.compare_digest(self.headers.get("X-App-Token", ""), state.token)

        # -------------------------------------------------------------- routes
        def do_GET(self):
            if not self._host_ok():
                return self._error("Forbidden", 403)
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/health":
                from . import __version__
                return self._json({"app": "sl-inventory-cleanup", "version": __version__})
            if url.path == "/bridge/poll":
                if not secrets.compare_digest(self.headers.get("X-Bridge-Token", ""), state.hub.token):
                    return self._error("Forbidden", 403)
                return self._json(state.hub.poll())
            if url.path.startswith("/thumb/"):
                # <img> tags can't send headers, so the token rides in the query string.
                if not secrets.compare_digest(q.get("t", ""), state.token):
                    return self._error("Forbidden", 403)
                tid = url.path[len("/thumb/"):].removesuffix(".jpg")
                data = state.thumbs.get(tid)
                if data is None:
                    return self._send(404, b"", "text/plain")
                return self._send(200, data, "image/jpeg", {"Cache-Control": "private, max-age=86400"})
            if url.path.startswith("/api/"):
                if not self._authed():
                    return self._error("Forbidden", 403)
                state.last_ui = time.time()
                try:
                    return self._api_get(url.path, q)
                except Locked as exc:
                    return self._json({"error": str(exc), "locked": True}, 409)
                except LookupError as exc:
                    return self._error(str(exc), 404)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    return self._error(f"Something went wrong: {exc}", 500)
            return self._static(url.path)

        def do_PUT(self):
            return self._write("PUT")

        def do_POST(self):
            return self._write("POST")

        def _write(self, method):
            url = urllib.parse.urlsplit(self.path)
            if url.path.startswith("/bridge/") and self._host_ok():
                if not secrets.compare_digest(self.headers.get("X-Bridge-Token", ""), state.hub.token):
                    return self._error("Forbidden", 403)
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(min(n, 50_000_000)) or b"{}")
                except json.JSONDecodeError:
                    return self._error("Bad request")
                if url.path == "/bridge/result":
                    state.hub.post_result(body)
                elif url.path == "/bridge/hello":
                    state.hub.post_hello(body)
                elif url.path == "/bridge/bye":
                    state.hub.post_bye(body)
                return self._json({"ok": True})
            if url.path == "/api/window-closed" and self._host_ok():
                # Sent as the page closes (navigator.sendBeacon can't add headers, so the token is in the URL).
                q = dict(urllib.parse.parse_qsl(url.query))
                if secrets.compare_digest(q.get("t", ""), state.token):
                    state.window_closed = time.time()
                return self._json({"ok": True})
            if not self._host_ok() or not self._authed():
                return self._error("Forbidden", 403)
            state.last_ui = time.time()
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._error("Bad request")
            if url.path == "/api/quit" and method == "POST":
                if state.run and state.run.state in ("running", "paused", "stopping"):
                    return self._json({"ok": False, "busy": True})
                firestorm = state.hub.connected()
                state.quit_requested = True
                return self._json({"ok": True, "firestorm": firestorm})
            free = {"/api/run/connect", "/api/scan"}
            if url.path not in free and not url.path.startswith("/api/categories") and state.locked():
                return self._json({"error": "Firestorm isn't connected - nothing can be changed right now.",
                                   "locked": True}, 409)
            try:
                if url.path == "/api/scan" and method == "POST":
                    if state.offline:
                        state.open(None)
                        return self._json({"ok": True})
                    if not state.hub.status()["ready"]:
                        return self._error("Firestorm isn't connected and logged in.")
                    state.scanner.start()
                    return self._json({"ok": True, "scan": state.scanner.status()})
                if url.path == "/api/categories" and method == "PUT":
                    saved = state.cats.save(body)
                    state.apply_categories(saved)
                    return self._json(saved)
                if url.path == "/api/categories/add-missing" and method == "POST":
                    saved = state.cats.add_missing()
                    state.apply_categories(saved)
                    return self._json(saved)
                if url.path == "/api/categories/reset" and method == "POST":
                    saved = state.cats.reset()
                    state.apply_categories(saved)
                    return self._json(saved)
                if url.path == "/api/sort/move" and method == "POST":
                    ids = [str(x) for x in (body.get("units") or [])][:5000]
                    sess = state.sorting()
                    n = sess.move(ids, str(body.get("category")))
                    if body.get("learn"):
                        sess.learn()           # a whole group confirmed: learn from it now
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/sort/unassign" and method == "POST":
                    sess = state.sorting()
                    sess.unassign([str(x) for x in (body.get("units") or [])][:5000])
                    return self._json({"ok": True, "tree": sess.tree()})
                if url.path == "/api/sort/landmark-copies" and method == "POST":
                    sess = state.sorting()
                    key = body.get("place")
                    n = sess.trash_landmark_copies(str(key) if key is not None else None, bool(body.get("undo")))
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/sort/trash-copies" and method == "POST":
                    sess = state.sorting()
                    n = sess.trash_copies(str(body.get("category")))
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/sort/clean" and method == "POST":
                    sess = state.sorting()
                    if body.get("category"):
                        n = sess.clean_category(str(body.get("category")))
                    else:
                        n = sess.clean([str(x) for x in (body.get("units") or [])][:5000],
                                       undo=bool(body.get("undo")))
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/duplicates/keep" and method == "POST":
                    sess = state.sorting()
                    n = sess.keep_copy(str(body.get("keep")), undo=bool(body.get("undo")))
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/duplicates/trash-all" and method == "POST":
                    sess = state.sorting()
                    r = sess.trash_all(str(body.get("id")))
                    return self._json({"ok": True, **r, "tree": sess.tree()})
                if url.path == "/api/duplicates/hide" and method == "POST":
                    sess = state.sorting()
                    sess.hide_dup(str(body.get("key")), bool(body.get("hide", True)))
                    return self._json({"ok": True})
                if url.path == "/api/duplicates/keep-all" and method == "POST":
                    sess = state.sorting()
                    n = sess.keep_one_of_each()
                    return self._json({"ok": True, "count": n, "tree": sess.tree()})
                if url.path == "/api/sort/split" and method == "POST":
                    sess = state.sorting()
                    sess.split_unit(str(body.get("unit")))
                    return self._json({"ok": True, "tree": sess.tree()})
                if url.path == "/api/sort/choose-folders" and method == "POST":
                    sess = state.sorting()
                    sess.choose_folders([str(x) for x in (body.get("skip") or [])][:5000])
                    return self._json({"ok": True, "tree": sess.tree()})
                if url.path == "/api/sort/skip" and method == "POST":
                    sess = state.sorting()
                    sess.skip_folder(str(body.get("folder")), bool(body.get("on", True)))
                    return self._json({"ok": True, "tree": sess.tree()})
                if url.path == "/api/sort/keep" and method == "POST":
                    sess = state.sorting()
                    sess.keep_together(str(body.get("folder")), bool(body.get("on", True)))
                    return self._json({"ok": True, "tree": sess.tree()})
                if url.path == "/api/sort/approve" and method == "POST":
                    sess = state.sorting()
                    cid = str(body.get("category"))
                    sess.approve(cid, bool(body.get("approved", True)))
                    return self._json({"ok": True, "next": sess.next_category(cid), "tree": sess.tree()})
                if url.path == "/api/run/connect" and method == "POST":
                    try:
                        return self._json({"ok": True, **state.hub.launch(state.app_url)})
                    except RuntimeError as exc:
                        return self._error(str(exc))
                if url.path == "/api/run/start" and method == "POST":
                    if state.run and state.run.state in ("running", "paused", "stopping"):
                        return self._error("A run is already going.")
                    sess = state.sorting()
                    steps = runner.build_steps(sess, rename_old=bool(body.get("rename", True)))
                    if not steps:
                        return self._error("The plan is empty.")
                    state.run = runner.Run(state.hub, sess, steps)
                    state.run.start()
                    return self._json(state.run.status())
                if url.path == "/api/run/pause" and method == "POST" and state.run:
                    state.run.toggle_pause()
                    return self._json(state.run.status())
                if url.path == "/api/run/stop" and method == "POST" and state.run:
                    state.run.stop()
                    return self._json(state.run.status())
                if url.path == "/api/run/undo" and method == "POST":
                    if state.run and state.run.state in ("running", "paused", "stopping"):
                        return self._error("Wait for the current run to finish.")
                    name = Path(str(body.get("log") or "")).name
                    path = runner.runs_dir() / name
                    if not name.startswith("run-") or not path.is_file():
                        return self._error("That run log wasn't found.")
                    log = json.loads(path.read_text(encoding="utf-8"))
                    only = body.get("steps")
                    only = {int(n) for n in only} if isinstance(only, list) else None
                    steps = runner.undo_steps(log, only)
                    if not steps:
                        return self._error("Nothing in that run to undo." if only is None
                                           else "Those were already put back.")
                    state.run = runner.Run(state.hub, state.sorting(), steps, undo_of=name)
                    state.run.start()
                    return self._json(state.run.status())
                if url.path == "/api/open" and method == "POST":
                    inv = state.open(body.get("path"))
                    return self._json({"ok": True, "overview": inv.overview()})
            except ValueError as exc:
                return self._error(str(exc))
            except LookupError as exc:
                return self._error(str(exc), 404)
            return self._error("Not found", 404)

        def _api_get(self, path, q):
            if path == "/api/session":
                return self._json(state.session())
            if path == "/api/inventories":
                invs = state.inventories()
                return self._json({"inventories": invs, "current": state.inv_path})
            if path == "/api/overview":
                ov = state.current().overview()
                d = state.sorting().duplicates()
                ov.update(dup_extra=d["extra"], dup_groups=len(d["groups"]), dup_products=d["products"])
                return self._json(ov)
            if path == "/api/duplicates":
                state.browse_ready()
                return self._json(state.sorting().duplicates(hidden=q.get("hidden") == "1"))
            if path == "/api/folder":
                inv = state.browse_ready()
                fid = q.get("id") or inv.root
                if fid not in inv.folders:
                    raise LookupError("That folder isn't in this inventory.")
                view = inv.folder_view(fid)
                # What you've already moved or marked for Trash, shown on each item.
                marks = state.sorting().item_marks([i["id"] for i in view["items"]])
                for i in view["items"]:
                    if i["id"] in marks:
                        i["mark"] = marks[i["id"]]
                return self._json(view)
            if path == "/api/search":
                return self._json(state.browse_ready().search(q.get("q", "")))
            if path == "/api/sort/locate":
                kind = "folder" if q.get("kind") == "folder" else "item"
                return self._json(state.sorting().locate(kind, q.get("id", "")))
            if path == "/api/categories":
                from .categories import missing_starters
                data = state.cats.load()
                return self._json({**data, "missing": [t["name"] for t in missing_starters(data)]})
            if path == "/api/run/preview":
                sess = state.sorting()
                steps = runner.build_steps(sess, rename_old=q.get("rename", "1") != "0")
                return self._json(runner.summarize(steps, sess))
            if path == "/api/run/moved":
                name = Path(q.get("log", "")).name
                p = runner.runs_dir() / name
                if not name.startswith("run-") or not p.is_file():
                    raise LookupError("That run log wasn't found.")
                return self._json({"log": name, "moved": runner.moved_steps(json.loads(p.read_text(encoding="utf-8")))})
            if path == "/api/run/status":
                runs = sorted((p.name for p in runner.runs_dir().glob("run-*.json")), reverse=True)[:10]
                return self._json({"bridge": state.hub.status(), "run": state.run.status() if state.run else None,
                                   "inventory_root": state.inv.root if state.inv else None, "runs": runs})
            if path == "/api/sort/folders":
                return self._json(state.sorting().top_folders())
            if path == "/api/sort/tree":
                return self._json(state.sorting().tree())
            if path == "/api/sort/category":
                sess = state.sorting()
                cid = q.get("id") or sess.next_category() or "unsure"
                return self._json(sess.category(cid))
            raise LookupError("Not found")

        def _static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            target = (WEB / path.lstrip("/")).resolve()
            if WEB not in target.parents or not target.is_file():
                return self._send(404, b"Not found", "text/plain")
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.name == "index.html":
                body = body.replace(b"__APP_TOKEN__", state.token.encode())
            extra = {"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                "img-src 'self' data:; frame-ancestors 'none'"}
            return self._send(200, body, ctype + ("; charset=utf-8" if ctype.startswith("text/") or
                                                  ctype.endswith("javascript") else ""), extra)

    return Handler


def serve(state: AppState, port=0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    httpd.daemon_threads = True
    state.app_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    return httpd
