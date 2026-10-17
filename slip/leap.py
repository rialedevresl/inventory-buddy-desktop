"""LEAP: talking to Firestorm over stdin/stdout (framing + a small request/reply client)."""
from __future__ import annotations

import logging
import threading
import time
import uuid

from . import llsd

LOG = logging.getLogger("slip.leap")
MAX_FRAME = 256 * 1024 * 1024
BLOCK = 4096


# --------------------------------------------------------------------------- framing

def _read_exact(stream, size):
    parts = []
    while size:
        chunk = stream.read(size)
        if not chunk:
            raise EOFError("Viewer closed the LEAP connection")
        parts.append(chunk)
        size -= len(chunk)
    return b"".join(parts)


def _find_repeated_block(body: bytes):
    """Some viewer builds occasionally write the same 4 KiB chunk twice to the
    pipe. Find an exact back-to-back duplicate block so we can drop it."""
    for off in range(BLOCK, len(body) - BLOCK + 1):
        if body[off:off + 64] == body[off - BLOCK:off - BLOCK + 64] and \
                body[off:off + BLOCK] == body[off - BLOCK:off]:
            return off
    return None


HEADER = b"<? LLSD/Binary ?>\n"
_MARK = b":" + HEADER


class _OutOfStep(Exception):
    def __init__(self, seen):
        super().__init__(seen)
        self.seen = seen


def _read_prefix(stream):
    prefix = b""
    while True:
        ch = _read_exact(stream, 1)
        if ch == b":":
            break
        if not ch.isdigit() or len(prefix) > 10:
            raise _OutOfStep(prefix + ch)
        prefix += ch
    size = int(prefix or b"0")
    if not 0 < size <= MAX_FRAME:
        raise _OutOfStep(prefix + b":")
    return size


def _resync(stream, seen: bytes):
    """A garbled message left stray bytes in the pipe. Skip ahead to the start of
    the next real message ("<length>:<? LLSD/Binary ?>") instead of giving up."""
    win = bytearray(seen[-64:])
    skipped = len(seen)
    while True:
        win += _read_exact(stream, 1)
        skipped += 1
        if len(win) > 64:
            del win[:-64]
        if win.endswith(_MARK):
            head = bytes(win[:-len(_MARK)])
            digits = b""
            while head and head[-1:].isdigit() and len(digits) < 10:
                digits = head[-1:] + digits
                head = head[:-1]
            if digits and len(HEADER) <= int(digits) <= MAX_FRAME:
                LOG.warning("Skipped %d stray bytes to get back in step with the viewer", skipped - len(_MARK) - len(digits))
                return int(digits), HEADER


def read_frame(stream):
    try:
        size, head = _read_prefix(stream), b""
    except _OutOfStep as exc:
        size, head = _resync(stream, exc.seen)
    body = head + _read_exact(stream, size - len(head))
    for attempt in range(9):
        try:
            return llsd.parse_any(body)
        except llsd.LLSDParseError as exc:
            off = _find_repeated_block(body) if attempt < 8 else None
            if off is None:
                raise llsd.LLSDParseError(f"{exc} (message starts {body[:48]!r})") from None
            LOG.warning("Repaired a duplicated 4 KiB block in a viewer message")
            body = body[:off] + body[off + BLOCK:] + _read_exact(stream, BLOCK)


def write_frame(stream, pump, data):
    body = llsd.format({"pump": pump, "data": data})
    stream.write(str(len(body)).encode("ascii") + b":" + body)
    stream.flush()


# --------------------------------------------------------------------------- client

class LeapClient:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
        hello = read_frame(incoming)
        self.reply_pump = str(hello["pump"])
        self.command_pump = str(hello["data"]["command"])
        self.features = hello["data"].get("features", {})
        self.connected = True
        self._pending: dict[str, dict] = {}
        self._cv = threading.Condition()
        self._write = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            while True:
                try:
                    msg = read_frame(self.incoming)
                except llsd.LLSDParseError as exc:
                    LOG.warning("Ignored an unreadable viewer message: %s", exc)
                    continue
                data = msg.get("data") if isinstance(msg, dict) else None
                reqid = str(data.get("reqid")) if isinstance(data, dict) and "reqid" in data else None
                if reqid:
                    with self._cv:
                        self._pending[reqid] = data
                        self._cv.notify_all()
        except (EOFError, OSError, ValueError) as exc:
            LOG.info("Viewer connection ended: %s", exc)
        finally:
            with self._cv:
                self.connected = False
                self._cv.notify_all()

    def post(self, pump, data):
        """Fire-and-forget message (for viewer ops that never reply)."""
        if not self.connected:
            raise ConnectionError("Viewer is gone")
        with self._write:
            write_frame(self.outgoing, pump, data)

    def ping(self, timeout=15.0):
        """Round trip through the viewer; returns once earlier messages were handled."""
        return self.request(self.command_pump, {"op": "ping"}, timeout)

    def request(self, pump, data, timeout=15.0):
        if not self.connected:
            raise ConnectionError("Viewer is gone")
        reqid = uuid.uuid4().hex
        with self._write:
            write_frame(self.outgoing, pump, {**data, "reply": self.reply_pump, "reqid": reqid})
        deadline = time.monotonic() + timeout
        with self._cv:
            while reqid not in self._pending:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"No reply to {data.get('op')!r} within {timeout:.0f}s")
                if not self.connected:
                    raise ConnectionError("Viewer is gone")
                self._cv.wait(left)
            reply = self._pending.pop(reqid)
        reply = {k: v for k, v in reply.items() if k != "reqid"} if isinstance(reply, dict) else reply
        return reply

    # Read-only discovery. These two ops only describe the viewer.
    def discover(self):
        names = self.request(self.command_pump, {"op": "getAPIs"})
        apis = {}
        for name in sorted(names if isinstance(names, dict) else []):
            if name in ("reply", "error") or not isinstance(names[name], dict):
                continue
            try:
                apis[name] = self.request(self.command_pump, {"op": "getAPI", "api": name})
            except TimeoutError as exc:
                apis[name] = {"probe_error": str(exc), **names[name]}
        if not self.connected:
            raise ConnectionError("Viewer closed during discovery")
        return apis


