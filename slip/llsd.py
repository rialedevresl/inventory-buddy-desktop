"""Minimal, dependency-free LLSD notation codec.

Second Life viewers speak LLSD "notation" over LEAP and also use it for
some cache files. This covers the full notation grammar we need:
undef, booleans, integers, reals, UUIDs, strings (quoted and sized),
URIs, dates, binary (b64/b16/sized), maps and arrays.
"""
from __future__ import annotations

import base64
import datetime
import uuid

__all__ = ["parse", "parse_binary", "parse_any", "format", "LLSDParseError", "URI", "Binary"]


class LLSDParseError(ValueError):
    pass


class URI(str):
    """A string tagged as an LLSD URI."""


class Binary(bytes):
    """Bytes tagged as LLSD binary."""


_WS = b" \t\r\n"
_ESCAPES = {ord("a"): 7, ord("b"): 8, ord("f"): 12, ord("n"): 10, ord("r"): 13,
            ord("t"): 9, ord("v"): 11, ord("\\"): 92, ord("'"): 39, ord('"'): 34, ord("/"): 47}


class _Parser:
    def __init__(self, data: bytes):
        self.d = data
        self.i = 0

    def err(self, msg):
        raise LLSDParseError(f"{msg} at byte {self.i}")

    def ws(self):
        d, n = self.d, len(self.d)
        while self.i < n and d[self.i] in _WS:
            self.i += 1

    def peek(self):
        self.ws()
        if self.i >= len(self.d):
            self.err("Unexpected end of data")
        return self.d[self.i]

    def take(self, n=1):
        if self.i + n > len(self.d):
            self.err("Unexpected end of data")
        out = self.d[self.i:self.i + n]
        self.i += n
        return out

    def startswith(self, s: bytes):
        return self.d.startswith(s, self.i)

    def value(self):
        c = self.peek()
        ch = chr(c)
        if ch == "{":
            return self.map_()
        if ch == "[":
            return self.array()
        if ch == "!":
            self.i += 1
            return None
        if ch in "'\"":
            return self.quoted()
        if ch == "s":
            return self.sized_string()
        if ch == "i":
            self.i += 1
            return int(self.number_token() or "0")
        if ch == "r":
            self.i += 1
            tok = self.number_token(allow_alpha=True) or "0"
            try:
                return float(tok)
            except ValueError:
                self.err(f"Bad real {tok!r}")
        if ch == "u":
            self.i += 1
            raw = self.take(36).decode("ascii", "replace")
            try:
                return uuid.UUID(raw)
            except ValueError:
                self.err(f"Bad UUID {raw!r}")
        if ch == "l":
            self.i += 1
            return URI(self.quoted())
        if ch == "d":
            self.i += 1
            return self.date(self.quoted())
        if ch == "b":
            return self.binary()
        for word, val in ((b"true", True), (b"TRUE", True), (b"false", False), (b"FALSE", False)):
            if self.startswith(word):
                self.i += len(word)
                return val
        if ch in "1tT":
            self.i += 1
            return True
        if ch in "0fF":
            self.i += 1
            return False
        self.err(f"Unexpected character {ch!r}")

    def number_token(self, allow_alpha=False):
        start = self.i
        d, n = self.d, len(self.d)
        while self.i < n:
            c = chr(d[self.i])
            if c in "+-.0123456789eE" or (allow_alpha and c.isalpha()):
                self.i += 1
            else:
                break
        return d[start:self.i].decode("ascii")

    def quoted(self) -> str:
        q = self.peek()
        if q not in (39, 34):
            self.err("Expected quote")
        self.i += 1
        out = bytearray()
        d, n = self.d, len(self.d)
        while True:
            if self.i >= n:
                self.err("Unterminated string")
            c = d[self.i]
            self.i += 1
            if c == q:
                break
            if c == 92:  # backslash
                if self.i >= n:
                    self.err("Unterminated escape")
                e = d[self.i]
                self.i += 1
                if e == ord("x"):
                    out.append(int(self.take(2), 16))
                else:
                    out.append(_ESCAPES.get(e, e))
            else:
                out.append(c)
        return out.decode("utf-8", "replace")

    def sized_prefix(self):
        # after the type letter: (len)
        if self.take(1) != b"(":
            self.err("Expected '('")
        end = self.d.find(b")", self.i)
        if end < 0:
            self.err("Expected ')'")
        size = int(self.d[self.i:end])
        self.i = end + 1
        return size

    def sized_string(self) -> str:
        self.i += 1  # 's'
        size = self.sized_prefix()
        q = self.take(1)
        raw = self.take(size)
        if self.take(1) != q:
            self.err("Sized string terminator mismatch")
        return raw.decode("utf-8", "replace")

    def binary(self) -> Binary:
        self.i += 1  # 'b'
        if self.startswith(b"64"):
            self.i += 2
            return Binary(base64.b64decode(self.quoted()))
        if self.startswith(b"16"):
            self.i += 2
            return Binary(bytes.fromhex(self.quoted()))
        if self.startswith(b"85"):
            self.i += 2
            return Binary(base64.b85decode(self.quoted()))
        size = self.sized_prefix()
        q = self.take(1)
        raw = self.take(size)
        if self.take(1) != q:
            self.err("Sized binary terminator mismatch")
        return Binary(raw)

    @staticmethod
    def date(text):
        if not text:
            return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        t = text.rstrip("Z")
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                pass
        return text

    def key(self):
        c = self.peek()
        if c in (39, 34):
            return self.quoted()
        if c == ord("s"):
            return self.sized_string()
        self.err("Expected map key")

    def map_(self):
        self.i += 1
        out = {}
        if self.peek() == ord("}"):
            self.i += 1
            return out
        while True:
            k = self.key()
            if self.peek() != ord(":"):
                self.err("Expected ':'")
            self.i += 1
            out[k] = self.value()
            c = self.peek()
            self.i += 1
            if c == ord("}"):
                return out
            if c != ord(","):
                self.err("Expected ',' or '}'")

    def array(self):
        self.i += 1
        out = []
        if self.peek() == ord("]"):
            self.i += 1
            return out
        while True:
            out.append(self.value())
            c = self.peek()
            self.i += 1
            if c == ord("]"):
                return out
            if c != ord(","):
                self.err("Expected ',' or ']'")


def parse(data: bytes | str):
    """Parse one LLSD notation value. Accepts an optional <? LLSD/Notation ?> header."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    p = _Parser(data)
    p.ws()
    if p.startswith(b"<?"):
        end = data.find(b"?>", p.i)
        if end < 0:
            p.err("Bad header")
        p.i = end + 2
    return p.value()


def parse_binary(data: bytes):
    """Parse LLSD binary (used by the viewer's inventory cache file)."""
    import struct
    mv = memoryview(data)
    pos = 0
    n = len(data)

    def need(k):
        if pos + k > n:
            raise LLSDParseError(f"Unexpected end of binary LLSD at byte {pos}")

    def u32():
        nonlocal pos
        need(4)
        v = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        return v

    def raw(k):
        nonlocal pos
        need(k)
        out = bytes(mv[pos:pos + k])
        pos += k
        return out

    def val():
        nonlocal pos
        need(1)
        c = data[pos]
        pos += 1
        if c == 0x7B:  # {
            count = u32()
            out = {}
            for _ in range(count):
                need(1)
                kc = data[pos]
                pos += 1
                if kc in (0x6B, 0x73):  # 'k' or 's'
                    key = raw(u32()).decode("utf-8", "replace")
                else:
                    raise LLSDParseError(f"Bad map key marker {chr(kc)!r} at byte {pos - 1}")
                out[key] = val()
            need(1)
            if data[pos] != 0x7D:
                raise LLSDParseError(f"Expected '}}' at byte {pos}")
            pos += 1
            return out
        if c == 0x5B:  # [
            count = u32()
            out = [val() for _ in range(count)]
            need(1)
            if data[pos] != 0x5D:
                raise LLSDParseError(f"Expected ']' at byte {pos}")
            pos += 1
            return out
        if c == 0x21:
            return None
        if c == 0x31:
            return True
        if c == 0x30:
            return False
        if c == 0x69:
            need(4)
            v = struct.unpack_from(">i", data, pos)[0]
            pos += 4
            return v
        if c == 0x72:
            need(8)
            v = struct.unpack_from(">d", data, pos)[0]
            pos += 8
            return v
        if c == 0x75:
            return uuid.UUID(bytes=raw(16))
        if c in (0x73, 0x27, 0x22):
            return raw(u32()).decode("utf-8", "replace")
        if c == 0x6C:
            return URI(raw(u32()).decode("utf-8", "replace"))
        if c == 0x64:  # dates are little-endian in binary LLSD
            need(8)
            v = struct.unpack_from("<d", data, pos)[0]
            pos += 8
            return datetime.datetime.fromtimestamp(v, datetime.timezone.utc) if v > 0 else None
        if c == 0x62:
            return Binary(raw(u32()))
        raise LLSDParseError(f"Unknown binary LLSD marker {chr(c)!r} at byte {pos - 1}")

    return val()


def parse_any(data: bytes):
    """Parse LLSD that may start with a format header.

    The viewer sends LEAP messages as "<? LLSD/Binary ?>\\n" + binary LLSD;
    without a header (or with an LLSD/Notation one) it's notation.
    """
    if data.startswith(b"<?"):
        end = data.find(b"?>")
        if end < 0:
            raise LLSDParseError("Bad LLSD header")
        header = data[2:end].strip().lower()
        rest = data[end + 2:]
        if rest[:1] == b"\n":
            rest = rest[1:]
        elif rest[:2] == b"\r\n":
            rest = rest[2:]
        if b"binary" in header:
            return parse_binary(rest)
        if b"xml" in header:
            raise LLSDParseError("LLSD XML is not supported here")
        return parse(rest)
    return parse(data)


def _quote(s: str, q: bytes = b"'") -> bytes:
    return q + s.encode("utf-8").replace(b"\\", b"\\\\").replace(q, b"\\" + q) + q


def format(value) -> bytes:  # noqa: A001 - mirrors the llsd library name
    if value is None:
        return b"!"
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, int):
        return b"i" + str(value).encode()
    if isinstance(value, float):
        return b"r" + repr(value).encode()
    if isinstance(value, uuid.UUID):
        return b"u" + str(value).encode()
    if isinstance(value, URI):
        return b"l" + _quote(value, b'"')
    if isinstance(value, (Binary, bytes, bytearray)):
        return b'b64"' + base64.b64encode(bytes(value)) + b'"'
    if isinstance(value, datetime.datetime):
        return b'd"' + value.strftime("%Y-%m-%dT%H:%M:%S.%fZ").encode() + b'"'
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, dict):
        return b"{" + b",".join(_quote(str(k)) + b":" + format(v) for k, v in value.items()) + b"}"
    if isinstance(value, (list, tuple)):
        return b"[" + b",".join(format(v) for v in value) + b"]"
    raise TypeError(f"Cannot format {type(value).__name__} as LLSD")
