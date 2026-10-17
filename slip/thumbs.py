"""Thumbnail images for inventory items and folders.

Second Life inventory thumbnails are ordinary textures. Second Life's picture
service turns any texture ID into a small JPEG, so the app fetches each one
once and keeps a copy in its own cache folder. Only the thumbnail's texture
ID is sent - no account details. If the service can't be reached, the app
just shows type icons.
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BASE = os.environ.get("SLIC_PICTURE_SERVICE", "https://picture-service.secondlife.com/{id}/256x192.jpg")
MAX_BYTES = 600_000
MISS_RETRY = 24 * 3600     # don't re-ask for a missing image for a day


class Thumbs:
    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.gate = threading.Semaphore(6)          # be gentle: at most 6 downloads at once
        self.locks: dict[str, threading.Lock] = {}
        self.locks_guard = threading.Lock()
        self.offline_until = 0.0                     # back off after network failures

    def _lock(self, tid):
        with self.locks_guard:
            return self.locks.setdefault(tid, threading.Lock())

    def get(self, tid: str):
        """Return JPEG bytes for texture id, or None."""
        tid = tid.lower()
        if not UUID_RE.match(tid) or tid == "00000000-0000-0000-0000-000000000000":
            return None
        path = self.dir / f"{tid}.jpg"
        miss = self.dir / f"{tid}.miss"
        if path.exists():
            return path.read_bytes()
        if miss.exists() and time.time() - miss.stat().st_mtime < MISS_RETRY:
            return None
        if time.time() < self.offline_until:
            return None
        with self._lock(tid):
            if path.exists():
                return path.read_bytes()
            with self.gate:
                data = self._fetch(tid)
            if data is None:
                return None
            if data == b"":
                miss.write_bytes(b"")
                return None
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            return data

    def _fetch(self, tid):
        """bytes on success, b'' if the service says there's no such image, None on network trouble."""
        req = urllib.request.Request(BASE.format(id=tid), headers={"User-Agent": "SLInventoryCleanup/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return b"" if exc.code in (400, 403, 404, 410) else None
        except (urllib.error.URLError, OSError, TimeoutError):
            self.offline_until = time.time() + 60
            return None
        if len(data) > MAX_BYTES or not data.startswith(b"\xff\xd8") or "image" not in ctype:
            return b""
        return data
