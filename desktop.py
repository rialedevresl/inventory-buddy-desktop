"""Inventory Buddy Desktop - the desktop app (what the installer's shortcut starts).

Starts the app on this computer and opens it in its own window. Only one copy
runs at a time: starting it again just opens another window on the copy
that's already running. The app quits by itself a little while after its
last window closes, unless Firestorm is connected or a run is going.

    python desktop.py            # same as double-clicking the installed app
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from slip import __version__  # noqa: E402
from slip.categories import data_dir  # noqa: E402

AFTER_CLOSE = 45        # a window said it closed and no other window has spoken since: quit after this long
IDLE_QUIT = 240         # no word from any window at all (a minimized window only checks in about once a minute)
FIRST_WINDOW = 120      # how long to wait for the first window to show up
RUN_ORPHAN = 900        # a run with no window heard from for this long is stopped


def instance_file():
    return data_dir() / "running.json"


def code_stamp():
    """Changes whenever the app's files change (an update, or a different copy of the app)."""
    if getattr(sys, "frozen", False):
        files = [Path(sys.executable)]
    else:
        here = Path(__file__).resolve().parent
        files = [here / "desktop.py", *sorted((here / "slip").glob("*.py")), *sorted((here / "web").glob("*"))]
    h = hashlib.sha1()
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def running_instance():
    """What's saved about a copy of the app that's already running (url, stamp, token), if any."""
    try:
        info = json.loads(instance_file().read_text(encoding="utf-8"))
        url = str(info["url"])
        with urllib.request.urlopen(url + "/health", timeout=2) as r:
            if json.loads(r.read()).get("app") == "sl-inventory-cleanup":
                return info
    except (OSError, ValueError, KeyError):
        pass
    return None


def replace_old(info):
    """Ask an older running copy to quit. Returns None when it's gone, else why it couldn't."""
    req = urllib.request.Request(info["url"] + "/api/quit", data=b"{}", method="POST",
                                 headers={"X-App-Token": str(info.get("token", "")), "Content-Type": "application/json",
                                          "Host": urllib.parse.urlsplit(info["url"]).netloc})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            res = json.loads(r.read())
    except (OSError, ValueError):
        return "unknown"
    if not res.get("ok"):
        return "busy" if res.get("busy") else "unknown"
    end = time.time() + 15
    while time.time() < end:
        time.sleep(0.5)
        if running_instance() is None:
            return "firestorm" if res.get("firestorm") else None
    return "unknown"


def _windows_paths(*parts):
    out = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            out.append(Path(base, *parts))
    return out


def find_app_browser():
    """A browser that can show the app in its own window (no tabs or address bar)."""
    if os.name == "nt":
        cands = (_windows_paths("Microsoft", "Edge", "Application", "msedge.exe")
                 + _windows_paths("Google", "Chrome", "Application", "chrome.exe"))
        for c in cands:
            if c.is_file():
                return str(c)
        return shutil.which("msedge") or shutil.which("chrome")
    if sys.platform == "darwin":
        for app in ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
            if Path(app).is_file():
                return app
        return None
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def open_window(url):
    exe = find_app_browser()
    if exe:
        try:
            flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
            subprocess.Popen([exe, f"--app={url}", "--window-size=1320,900", "--no-first-run"],
                             creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


SHORTCUT_NAME = "Inventory Buddy Desktop"


def ensure_shortcut():
    """Windows, zip version: put an "Inventory Buddy Desktop" shortcut with the app's icon on the desktop the
    first time the app starts, and keep it pointing here if the folder is moved later. If you delete the
    shortcut, it isn't made again. (The installed version gets its shortcuts from the installer.)"""
    if os.name != "nt" or getattr(sys, "frozen", False):
        return
    here = Path(__file__).resolve().parent
    target = next((p for p in here.glob("Start*.pyw")), None)
    icon = next((p for p in (here / "app.ico", here / "packaging" / "app.ico") if p.is_file()), None)
    if not target or not icon:
        return
    marker = data_dir() / "shortcut.json"
    try:
        made = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        made = None
    if made and made.get("target") == str(target):
        return                                   # already made for this folder
    q = lambda s: str(s).replace("'", "''")      # noqa: E731 - quoting for PowerShell
    # An existing shortcut is only updated after a move; a new one only on the very first start.
    only_if_there = "$true" if made else "$false"
    script = (
        "$d = [Environment]::GetFolderPath('Desktop'); "
        f"$lnk = Join-Path $d '{q(SHORTCUT_NAME)}.lnk'; "
        f"if ({only_if_there} -and -not (Test-Path $lnk)) {{ exit 0 }}; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk); "
        f"$s.TargetPath = '{q(target)}'; $s.WorkingDirectory = '{q(here)}'; "
        f"$s.IconLocation = '{q(icon)},0'; $s.Description = 'Inventory Buddy Desktop'; $s.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           creationflags=0x08000000, capture_output=True, timeout=30)   # CREATE_NO_WINDOW
        if r.returncode == 0:
            marker.write_text(json.dumps({"target": str(target)}), encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        pass


def message_box(text):
    """Tell the person something when there's no window to show it in (Windows only)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Inventory Buddy Desktop", 0x40)
            return
        except Exception:  # noqa: BLE001
            pass
    print(text)


def main():
    stamp = code_stamp()
    info = running_instance()
    note = None
    if info and info.get("stamp") == stamp:
        open_window(str(info["url"]) + "/")
        return 0
    if info:
        # A copy from before an update (or from another folder) is still running: start fresh.
        why = replace_old(info)
        if why in ("busy", "unknown"):
            if why == "busy":
                message_box("The app was updated, but a run is still going in the copy that's open. "
                            "Let it finish (or press Stop), close the app, then start it again to get the update.")
            open_window(str(info["url"]) + "/")
            return 0
        if why == "firestorm":
            note = ("The app was updated and restarted. Firestorm was connected to the old copy, so quit "
                    "Firestorm, then press Start Firestorm in the app to connect again.")

    from slip.server import AppState, serve
    state = AppState()
    try:
        httpd = serve(state, 0)
    except OSError as exc:
        message_box(f"Inventory Buddy Desktop couldn't start: {exc}")
        return 1
    url = state.app_url
    instance_file().write_text(json.dumps({"url": url, "pid": os.getpid(), "version": __version__,
                                           "stamp": stamp, "token": state.token}), encoding="utf-8")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    open_window(url + "/")
    threading.Thread(target=ensure_shortcut, daemon=True).start()
    if note:
        threading.Thread(target=message_box, args=(note,), daemon=True).start()

    started = time.time()
    try:
        while True:
            time.sleep(3)
            run_on = bool(state.run and state.run.state in ("running", "paused", "stopping"))
            busy = state.hub.connected() or run_on
            now, seen = time.time(), state.last_ui or started
            closed = state.last_ui and state.window_closed >= seen
            if run_on and state.run.state != "stopping" and (
                    (closed and now - state.window_closed > AFTER_CLOSE) or now - seen > RUN_ORPHAN):
                state.run.stop()          # the window was closed: don't keep moving things unseen
            if not state.last_ui:
                limit = FIRST_WINDOW
            elif state.window_closed >= seen:
                limit = AFTER_CLOSE       # the last thing we heard was a window closing
            else:
                limit = IDLE_QUIT
            if state.quit_requested:
                break             # a newer copy is taking over
            if not busy and now - max(seen, state.window_closed) > limit:
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            info = json.loads(instance_file().read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                instance_file().unlink()
        except (OSError, ValueError):
            pass
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
