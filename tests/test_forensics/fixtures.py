"""Byte-level fixture builders for the forensics test suite.

ESP record-header layout used here (24 bytes):
    type[4] + dataSize u32 + flags u32 + formID u32 + vc u32 + version u16 + unknown u16
dataSize@4 and the 24-byte header are wiki-established
(concepts/skyrim-gut-plugin-to-header-only: "dataSize = ToUInt32(bytes, 4)";
complete TES4 record = first 24 + dataSize bytes).
flags@8 / formID@12 / compressed-flag 0x00040000 / GRUP size-includes-header /
subrecord u16 size are ASSUMED standard TES5 layout — verified on-machine in
Task 4 Step 9 before any real-plugin verdict is trusted.
"""
import struct
import zlib

FLAG_COMPRESSED = 0x00040000  # ASSUMED - verify Task 4 Step 9
FLAG_ESL = 0x200              # modkit design doc (ESL flag 0x200)


def zstring(s):
    return s.encode("cp1252") + b"\x00"


def sub(stype, payload):
    """Subrecord: 4-char type + u16 payloadSize + payload (ASSUMED u16 size)."""
    assert len(stype) == 4
    return stype.encode("ascii") + struct.pack("<H", len(payload)) + payload


def record(rtype, formid, subrecords, flags=0, compressed=False):
    data = b"".join(subrecords)
    if compressed:
        raw_len = len(data)
        data = struct.pack("<I", raw_len) + zlib.compress(data)
        flags |= FLAG_COMPRESSED
    hdr = (rtype.encode("ascii") + struct.pack("<I", len(data))
           + struct.pack("<I", flags) + struct.pack("<I", formid)
           + struct.pack("<I", 0) + struct.pack("<HH", 44, 0))
    return hdr + data


def grup(label4, records_bytes):
    """GRUP header is 24 bytes; groupSize INCLUDES the header (ASSUMED)."""
    contents = b"".join(records_bytes)
    return (b"GRUP" + struct.pack("<I", 24 + len(contents)) + label4
            + struct.pack("<i", 0) + struct.pack("<I", 0) + struct.pack("<I", 0)) + contents


def tes4_record(masters, esl=False):
    subs = [sub("HEDR", struct.pack("<fIi", 1.71, 0, 0x800))]
    for m in masters:
        subs.append(sub("MAST", zstring(m)))
        subs.append(sub("DATA", struct.pack("<Q", 0)))
    return record("TES4", 0, subs, flags=(FLAG_ESL if esl else 0))


def build_esp(masters, stats, esl=False, compressed_formids=()):
    """Build a minimal plugin: TES4 header + one STAT GRUP.

    stats: list of (formid, edid, modl_path_or_None).
    """
    recs = []
    for formid, edid, modl in stats:
        subs = [sub("EDID", zstring(edid))]
        if modl is not None:
            subs.append(sub("MODL", zstring(modl)))
        recs.append(record("STAT", formid, subs,
                           compressed=(formid in compressed_formids)))
    out = tes4_record(masters, esl=esl)
    if recs:
        out += grup(b"STAT", recs)
    return out


def build_nif(texture_paths, extra=b"", junk=b"\x00\x01NiNode\x00\xff"):
    """Nif-LIKE bytes: binary noise with embedded ASCII texture paths.

    The extractor (Task 3) is a byte-level string scan — exactly the method the
    wiki proved load-bearing (grep -a over .nif) — so fixtures only need real
    ASCII paths inside binary noise, not a structurally valid NIF.
    """
    parts = [b"Gamebryo File Format, Version 20.2.0.7\n", junk]
    for t in texture_paths:
        parts.append(struct.pack("<I", len(t)) + t.encode("cp1252") + b"\x00\xfe")
    parts.append(extra)
    return b"".join(parts)
