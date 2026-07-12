"""esp_tools.py — plugin (ESP/ESM/ESL) forensics: masters, MODL extraction, gut.

Usage:
    py -3 C:\\Modding\\tools\\forensics\\esp_tools.py masters <plugin> [--json]
    py -3 ...\\esp_tools.py modl <plugin> [--json]
    py -3 ...\\esp_tools.py gut <plugin> -o <out-stub.esp> [--config PATH]

READ-ONLY against game dirs: 'gut' writes the header-only stub to -o, and
REFUSES a destination under the configured dataDir. Applying a stub to Data\\
(after backing up the original) stays a manual/modkit action.

Gut method (wiki concepts/skyrim-gut-plugin-to-header-only, applied twice —
PG_1.esp 640346 B -> 614 B): the complete TES4 record is the first
24 + dataSize bytes (dataSize = u32 at offset 4); the stub keeps HEDR + MAST
entries so dependents' master references still resolve (no CTD), but carries
zero records, so all its overrides vanish.

Record-walk constants: 24-byte record header + dataSize@4 are wiki-established.
flags@8, formID@12, compressed flag 0x00040000 (u32 decomp-size prefix), GRUP
size-includes-header, subrecord type[4]+u16 size, XXXX oversize extension are
ASSUMED standard TES5 layout — verified on-machine (plan Task 4 Step 9) against
Skyrim.esm and SMIM-SE-Merged-All.esp before real-plugin verdicts are trusted.
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forensics import _lib

REC_HDR = 24
FLAG_COMPRESSED = 0x00040000  # ASSUMED - verify Step 9
FLAG_ESL = 0x200


def iter_records(data, offset=0, end=None):
    end = len(data) if end is None else end
    pos = offset
    while pos + REC_HDR <= end:
        rtype = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if rtype == b"GRUP":
            inner_end = pos + size  # groupSize includes the 24-byte GRUP header (ASSUMED)
            if inner_end > end or size < REC_HDR:
                raise ValueError("malformed GRUP at 0x%X" % pos)
            yield from iter_records(data, pos + REC_HDR, inner_end)
            pos = inner_end
        else:
            if pos + REC_HDR + size > end:
                raise ValueError("record %r at 0x%X overruns file"
                                 % (rtype, pos))
            flags, formid = struct.unpack_from("<II", data, pos + 8)
            yield (rtype.decode("ascii", "replace"), flags, formid,
                   data[pos + REC_HDR: pos + REC_HDR + size])
            pos += REC_HDR + size


def record_payload(flags, raw):
    if flags & FLAG_COMPRESSED:
        decomp_size = struct.unpack_from("<I", raw, 0)[0]
        out = zlib.decompress(raw[4:])
        if len(out) != decomp_size:
            raise ValueError("decompressed size mismatch")
        return out
    return raw


def iter_subrecords(payload):
    pos = 0
    oversize = None
    while pos + 6 <= len(payload):
        stype = payload[pos:pos + 4].decode("ascii", "replace")
        ssize = struct.unpack_from("<H", payload, pos + 4)[0]
        pos += 6
        if stype == "XXXX":  # oversize extension (ASSUMED)
            oversize = struct.unpack_from("<I", payload, pos)[0]
            pos += ssize
            continue
        if oversize is not None:
            ssize, oversize = oversize, None
        yield stype, payload[pos:pos + ssize]
        pos += ssize


def modl_records(path):
    """([(formid, record_type, modl_path)], [parse-error strings]).
    Never crashes a sweep: malformed records are reported, not fatal."""
    data = Path(path).read_bytes()
    out, errors = [], []
    try:
        for rtype, flags, formid, raw in iter_records(data):
            if rtype == "TES4":
                continue
            try:
                payload = record_payload(flags, raw)
                for stype, sdata in iter_subrecords(payload):
                    if stype == "MODL":
                        modl = sdata.split(b"\x00")[0].decode("cp1252", "replace")
                        out.append((formid, rtype, modl))
            except Exception as e:
                errors.append("%s form 0x%08X: %s" % (rtype, formid, e))
    except Exception as e:
        errors.append("walk aborted: %s" % e)
    return out, errors


def gut_stub_bytes(data):
    if data[:4] != b"TES4":
        raise _lib.ForensicsError("not a TES4 plugin (starts with %r)" % data[:4])
    size = struct.unpack_from("<I", data, 4)[0]
    if 24 + size > len(data):
        raise _lib.ForensicsError("TES4 dataSize overruns file - corrupt header")
    return data[:24 + size]


def main(argv=None):
    ap = argparse.ArgumentParser(description="ESP/ESM forensics")
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("masters")
    m.add_argument("plugin")
    m.add_argument("--json", action="store_true")
    mo = sp.add_parser("modl")
    mo.add_argument("plugin")
    mo.add_argument("--json", action="store_true")
    g = sp.add_parser("gut")
    g.add_argument("plugin")
    g.add_argument("-o", "--out", required=True)
    g.add_argument("--game", default="skyrim")
    g.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "masters":
        info = _lib.tes4_header(args.plugin)
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            _lib.say("esl: %s" % info["esl"])
            for mast in info["masters"]:
                _lib.say("MAST " + mast)
        return 0

    if args.cmd == "modl":
        modls, errors = modl_records(args.plugin)
        if args.json:
            print(json.dumps({"modl": [[f, t, p] for f, t, p in modls],
                              "errors": errors}, indent=2))
        else:
            for formid, rtype, modl in modls:
                _lib.say("0x%08X %-4s %s" % (formid, rtype, modl))
            for e in errors:
                _lib.say("PARSE-ERROR " + e)
            _lib.say("%d MODL records, %d parse errors" % (len(modls), len(errors)))
        return 1 if errors else 0

    # gut
    cfg = _lib.load_config(args.config)
    data_dir = Path(_lib.game_path(cfg, "dataDir", args.game)).resolve()
    out = Path(args.out).resolve()
    if str(out).lower().startswith(str(data_dir).lower()):
        raise _lib.ForensicsError(
            "refusing to write a stub under the game Data dir (%s) - forensics "
            "tools are read-only against game dirs; deploy the stub manually "
            "after backing up the original" % data_dir)
    data = Path(args.plugin).read_bytes()
    stub = gut_stub_bytes(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(stub)
    _lib.say("gutted: %d -> %d bytes  (stub at %s)" % (len(data), len(stub), out))
    _lib.say("apply manually: backup the original, then copy the stub over it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
