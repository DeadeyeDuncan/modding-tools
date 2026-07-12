"""Craft a minimal PE32+ DLL with an export table - just enough to exercise
modkit.peparse. One section (.rdata) at RVA 0x1000 / raw offset 0x400."""
import struct

SEC_RVA, SEC_RAW = 0x1000, 0x400


def skse_version_blob(compatible=(), independent=0, name="TestPlugin"):
    """SKSE PluginVersionData (848 bytes): dataVersion=1 @0, name @8,
    versionIndependence @776, compatibleVersions[16] @780 (0-terminated)."""
    raw = bytearray(848)
    struct.pack_into("<II", raw, 0, 1, 0x01000000)
    raw[8:8 + len(name)] = name.encode("ascii")
    struct.pack_into("<I", raw, 776, independent)
    for i, v in enumerate(list(compatible)[:16]):
        struct.pack_into("<I", raw, 780 + i * 4, v)
    return bytes(raw)


def build_dll(exports=None, extra=b"", machine=0x8664):
    """exports: {name: data_bytes} exported by name. Returns PE file bytes."""
    exports = dict(exports or {})
    blob = bytearray()

    def put(data):
        off = len(blob)
        blob.extend(data)
        return SEC_RVA + off

    edir_rva = None
    if exports:
        edir_rva = put(b"\x00" * 40)
        n = len(exports)
        data_rvas = [put(d) for d in exports.values()]
        name_rvas = [put(k.encode("ascii") + b"\x00") for k in exports]
        eat = put(b"".join(struct.pack("<I", r) for r in data_rvas))
        enpt = put(b"".join(struct.pack("<I", r) for r in name_rvas))
        eot = put(b"".join(struct.pack("<H", i) for i in range(n)))
        base = edir_rva - SEC_RVA
        struct.pack_into("<II", blob, base + 20, n, n)
        struct.pack_into("<III", blob, base + 28, eat, enpt, eot)
    if extra:
        put(extra)
    vsize = max(len(blob), 1)
    raw_size = (vsize + 0x1FF) & ~0x1FF
    dos = (b"MZ" + b"\x00" * 58 + struct.pack("<I", 0x80)).ljust(0x80, b"\x00")
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)          # PE32+ magic
    struct.pack_into("<I", opt, 108, 16)            # NumberOfRvaAndSizes
    if edir_rva is not None:
        struct.pack_into("<II", opt, 112, edir_rva, vsize)  # export data dir
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, len(opt), 0x2022)
    sect = b".rdata\x00\x00" + struct.pack(
        "<IIIIIIHHI", vsize, SEC_RVA, raw_size, SEC_RAW, 0, 0, 0, 0, 0x40000040)
    head = (dos + b"PE\x00\x00" + coff + bytes(opt) + sect).ljust(SEC_RAW, b"\x00")
    return bytes(head) + bytes(blob).ljust(raw_size, b"\x00")
