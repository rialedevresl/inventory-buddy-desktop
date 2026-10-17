"""App side of the Firestorm connection.

The app starts Firestorm with the bridge plug-in attached (for that launch
only). The plug-in long-polls the app for one job at a time; `call()` hands
it a job and waits for the result.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .categories import data_dir

PLUGIN = Path(__file__).resolve().parent / "bridge_plugin.py"
BRIDGE_EXE = "SLInventoryCleanupBridge" + (".exe" if os.name == "nt" else "")


def plugin_command():
    """How Firestorm starts the bridge: the bundled bridge program in the installed app,
    or Python running bridge_plugin.py when run from the source folder."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).with_name(BRIDGE_EXE)
        if not exe.is_file():
            raise RuntimeError(f"The app is missing {BRIDGE_EXE}. Reinstall it, please.")
        return [exe]
    python = Path(sys.executable)
    if os.name == "nt" and python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    return [python, PLUGIN]


# ------------------------------------------------------------------ finding / starting Firestorm
def firestorm_running():
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout          # CREATE_NO_WINDOW: no console flash
            return any("firestorm" in line.lower() for line in out.splitlines())
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True).stdout
        return any("firestorm" in line.lower() for line in out.splitlines())
    except OSError:
        return False


def find_viewer():
    env = os.environ.get("FIRESTORM_VIEWER")
    if env and Path(env).is_file():
        return Path(env)
    candidates = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                candidates += Path(base).glob("*Firestorm*/Firestorm*.exe")
                candidates += Path(base).glob("Programs/*Firestorm*/Firestorm*.exe")
        candidates = [c for c in candidates if "uninst" not in c.name.lower() and "crash" not in c.name.lower()]
    elif sys.platform == "darwin":
        candidates += [a / "Contents/MacOS/Firestorm" for a in Path("/Applications").glob("Firestorm*.app")]
    else:
        candidates += list(Path.home().glob("*irestorm*/firestorm")) + list(Path("/opt").glob("*irestorm*/firestorm"))
    candidates = sorted({c.resolve() for c in candidates if c.is_file()}, key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def session_settings(command: str):
    return ('<?xml version="1.0" ?>\n<llsd>\n<map>\n  <key>LeapCommand</key>\n  <map>\n'
            "    <key>Comment</key><string>Set for one launch by Inventory Buddy Desktop</string>\n"
            "    <key>Persist</key><integer>0</integer>\n    <key>Type</key><string>LLSD</string>\n"
            f"    <key>Value</key><array><string>{escape(command)}</string></array>\n"
            "  </map>\n</map>\n</llsd>\n")


class Hub:
    def __init__(self):
        self.token = os.environ.get("SLIC_BRIDGE_TOKEN") or secrets.token_urlsafe(18)   # env: tests only
        self.lock = threading.Condition()
        self.job = None              # job waiting to be picked up
        self.results = {}
        self.seq = 0
        self.last_seen = 0.0
        self.hello = {}
        self.proc = None
        self.busy = None             # id of the job the plug-in is working on right now
        self.busy_since = 0.0
        self.busy_limit = 0.0
        self.session = None          # changes each time Firestorm starts the plug-in
        self.lost = False            # the plug-in said goodbye while Firestorm may still be open
        self.one_at_a_time = threading.Lock()   # the plug-in takes one job at a time: callers queue here
        self.warmed = None           # the Firestorm connection the look-around was done for

    # ---------------------------------------------------------------- state
    def connected(self):
        if self.proc is not None and self.proc.poll() is not None:
            return False          # the Firestorm we started has closed
        # While the plug-in is working on a job (a new folder can take a while) it can't check in,
        # so a job in progress counts as connected - up to the longest a job may take.
        if self.busy is not None and time.time() - self.busy_since < self.busy_limit:
            return True
        return time.time() - self.last_seen < 30

    def status(self):
        st = {"connected": self.connected(), "ready": bool(self.hello.get("ready")) and self.connected(),
              "root": self.hello.get("root"), "trash": self.hello.get("trash"), "agent": self.hello.get("agent"),
              "launched": self.proc is not None and self.proc.poll() is None}
        st["lost"] = self.lost and not st["connected"]
        return st

    def _fail_busy(self, why):
        """The job the plug-in had can never be answered (it restarted or quit): say so now."""
        if self.busy is not None and self.busy not in self.results:
            self.results[self.busy] = {"id": self.busy, "ok": False, "error": why}
        self.busy = None
        self.lock.notify_all()

    # ---------------------------------------------------------------- launching
    def launch(self, app_url):
        if firestorm_running():
            raise RuntimeError("Firestorm is already running. Quit it first - the app can only connect when it "
                               "starts Firestorm itself.")
        viewer = find_viewer()
        if not viewer:
            raise RuntimeError("Couldn't find Firestorm on this computer.")
        log = data_dir() / "bridge.log"
        parts = [str(p).replace("\\", "/") for p in (*plugin_command(), log)]
        if any('"' in p for p in parts):
            raise RuntimeError("A folder path contains a quote mark, which Firestorm can't handle.")
        prog = " ".join(f'"{p}"' for p in parts[:-1])
        cmd = f'{prog} --app {app_url} --token {self.token} --log "{parts[-1]}"'
        settings = data_dir() / "firestorm-session.xml"
        settings.write_text(session_settings(cmd), encoding="utf-8")
        self.lost = False
        self.proc = subprocess.Popen([str(viewer), "--sessionsettings", str(settings)], cwd=str(viewer.parent))
        return {"viewer": str(viewer)}

    # ---------------------------------------------------------------- plug-in side
    def poll(self, wait=12):
        self.last_seen = time.time()
        with self.lock:
            # The plug-in only asks for a new job after reporting the last one, so a job still
            # marked busy here was lost (e.g. a garbled reply). Fail it instead of waiting minutes.
            self._fail_busy("Firestorm lost track of that step.")
            end = time.time() + wait
            while self.job is None and time.time() < end:
                self.lock.wait(timeout=max(0.1, end - time.time()))
            job, self.job = self.job, None
            self.last_seen = time.time()
            if job:
                self.busy, self.busy_since = job["id"], time.time()
                self.busy_limit = float(job.get("_timeout", 120)) + 15
            return job or {"op": "none"}

    def post_result(self, res):
        self.last_seen = time.time()
        with self.lock:
            self.results[res.get("id")] = res
            if self.busy == res.get("id"):
                self.busy = None
            self.lock.notify_all()

    def post_hello(self, hello):
        self.last_seen = time.time()
        hello = hello or {}
        with self.lock:
            if hello.get("session") and hello.get("session") != self.session:
                if self.session is not None:
                    self._fail_busy("Firestorm's connection restarted.")
                self.session = hello.get("session")
            self.lost = False
            self.hello = hello

    def post_bye(self, bye):
        """The plug-in is stopping: either Firestorm closed or the link to it broke."""
        with self.lock:
            if (bye or {}).get("session") not in (None, self.session):
                return
            self._fail_busy("The link to Firestorm dropped.")
            self.last_seen = 0.0
            self.hello = {}
            self.lost = True

    # ---------------------------------------------------------------- app side
    def call(self, op, timeout=120, **args):
        with self.one_at_a_time:
            return self._call(op, timeout, **args)

    def _call(self, op, timeout=120, **args):
        if not self.connected():
            raise ConnectionError("Firestorm isn't connected.")
        with self.lock:
            self.seq += 1
            jid = self.seq
            self.job = {"id": jid, "op": op, "_timeout": timeout, **args}
            self.lock.notify_all()
            end = time.time() + timeout
            while jid not in self.results:
                if not self.connected():
                    self.job = None if self.job and self.job.get("id") == jid else self.job
                    raise ConnectionError("The link to Firestorm dropped.")
                left = end - time.time()
                if left <= 0:
                    self.job = None if self.job and self.job.get("id") == jid else self.job
                    if self.busy == jid:
                        self.busy = None
                    raise TimeoutError("Firestorm took too long to answer.")
                self.lock.wait(timeout=min(left, 1.0))
            res = self.results.pop(jid)
        if not res.get("ok"):
            raise JobFailed(res.get("error") or "It didn't work.")
        return res.get("result")


class JobFailed(Exception):
    pass
