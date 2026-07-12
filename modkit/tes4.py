"""TES4 (ESP/ESM/ESL) header parse: masters, ESL flag (0x200), version, author.
File-is-ground-truth: masters come from the header, never the Nexus page.
Record header (SSE): type(4) size(4) flags(4) formid(4) vc(4) version(2) unk(2) = 24."""
import struct
from pathlib import Path

ESM_FLAG = 0x00000001
ESL_FLAG = 0x00000200


class Tes4Error(Exception):
    """Not a TES4 plugin or truncated header."""


def parse_header(path):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:4] != b"TES4":
        raise Tes4Error(f"not a TES4 plugin: {path.name}")
    size = struct.unpack_from("<I", raw, 4)[0]
    flags = struct.unpack_from("<I", raw, 8)[0]
    body = raw[24:24 + size]
    masters, author, version = [], "", None
    off = 0
    while off + 6 <= len(body):
        stype = body[off:off + 4]
        ssize = struct.unpack_from("<H", body, off + 4)[0]
        data = body[off + 6:off + 6 + ssize]
        if stype == b"MAST":
            masters.append(data.rstrip(b"\x00").decode("cp1252", "replace"))
        elif stype == b"CNAM":
            author = data.rstrip(b"\x00").decode("cp1252", "replace")
        elif stype == b"HEDR" and ssize >= 4:
            version = round(struct.unpack_from("<f", data, 0)[0], 2)
        off += 6 + ssize
    return {"plugin": path.name, "masters": masters,
            "esl": bool(flags & ESL_FLAG), "esm": bool(flags & ESM_FLAG),
            "version": version, "author": author}
