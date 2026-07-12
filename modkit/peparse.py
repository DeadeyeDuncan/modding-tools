"""Minimal PE (DLL) parser for dllvet: machine, exports, SKSE PluginVersionData.
Not a general PE library - just what the vet needs.
SKSE encoding: runtime 1.6.1170 -> (1<<24)|(6<<16)|(1170<<4)."""
import struct
from pathlib import Path

ADDRESS_INDEPENDENT = 0x1  # kVersionIndependent_AddressLibraryPostAE


class PeError(Exception):
    """Not a PE file / truncated / bad RVA."""


def _need(raw, offset, size, what):
    """Bounds-check a read before struct.unpack_from/slicing touches it, so a
    truncated/malformed DLL raises PeError instead of struct.error/IndexError."""
    if offset < 0 or offset + size > len(raw):
        raise PeError(
            f"{what} truncated (need {size} bytes at {offset:#x}, file is "
            f"{len(raw)} bytes)")


def encode_runtime(version):
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    major, minor, patch, beta = parts[:4]
    return (major << 24) | (minor << 16) | (patch << 4) | beta


def decode_runtime(value):
    return f"{value >> 24}.{(value >> 16) & 0xFF}.{(value >> 4) & 0xFFF}"


class PEFile:
    def __init__(self, path):
        self.raw = Path(path).read_bytes()
        if len(self.raw) < 0x40 or self.raw[:2] != b"MZ":
            raise PeError("not a PE file (no MZ)")
        _need(self.raw, 0x3C, 4, "e_lfanew")
        pe_off = struct.unpack_from("<I", self.raw, 0x3C)[0]
        _need(self.raw, pe_off, 4, "PE signature")
        if self.raw[pe_off:pe_off + 4] != b"PE\x00\x00":
            raise PeError("not a PE file (no PE signature)")
        _need(self.raw, pe_off + 4, 4, "COFF header (machine/nsects)")
        machine, nsects = struct.unpack_from("<HH", self.raw, pe_off + 4)
        _need(self.raw, pe_off + 20, 2, "COFF header (opt header size)")
        opt_size = struct.unpack_from("<H", self.raw, pe_off + 20)[0]
        self.machine = {0x8664: "x64", 0x14C: "x86"}.get(machine, hex(machine))
        opt_off = pe_off + 24
        _need(self.raw, opt_off, 2, "optional header magic")
        magic = struct.unpack_from("<H", self.raw, opt_off)[0]
        plus = magic == 0x20B
        dd_off = opt_off + (112 if plus else 96)
        _need(self.raw, dd_off, 8, "export data directory")
        self.export_rva, self.export_size = struct.unpack_from("<II", self.raw, dd_off)
        sec_off = opt_off + opt_size
        self.sections = []
        for i in range(nsects):
            base = sec_off + i * 40
            _need(self.raw, base + 8, 16, f"section header {i}")
            vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", self.raw, base + 8)
            self.sections.append((vaddr, max(vsize, rsize), raddr))

    def _off(self, rva):
        for vaddr, size, raddr in self.sections:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        raise PeError(f"rva {rva:#x} not in any section")

    def read(self, rva, size):
        o = self._off(rva)
        _need(self.raw, o, size, f"data at rva {rva:#x}")
        return self.raw[o:o + size]

    def _cstr(self, rva):
        o = self._off(rva)
        if o < 0 or o >= len(self.raw):
            raise PeError(f"cstr rva {rva:#x} out of bounds")
        end = self.raw.find(b"\x00", o)
        if end == -1:
            raise PeError(f"cstr rva {rva:#x} not null-terminated within file")
        return self.raw[o:end].decode("ascii", "replace")

    def exports(self):
        """{export_name: rva}; {} when the DLL exports nothing by name."""
        if not self.export_rva:
            return {}
        d = self.read(self.export_rva, 40)
        if len(d) < 40:
            raise PeError("export directory truncated")
        _nfuncs, nnames = struct.unpack_from("<II", d, 20)
        addr_funcs, addr_names, addr_ords = struct.unpack_from("<III", d, 28)
        out = {}
        for i in range(nnames):
            name_rva = struct.unpack_from("<I", self.read(addr_names + i * 4, 4))[0]
            ordinal = struct.unpack_from("<H", self.read(addr_ords + i * 2, 2))[0]
            func_rva = struct.unpack_from("<I", self.read(addr_funcs + ordinal * 4, 4))[0]
            out[self._cstr(name_rva)] = func_rva
        return out


def skse_version_data(pe):
    """Decode the exported SKSEPlugin_Version struct; None if not exported.
    Layout (SKSE64 PluginAPI.h PluginVersionData): dataVersion u32 @0,
    pluginVersion u32 @4, name[256] @8, author[256] @264, supportEmail[252] @520,
    versionIndependenceEx u32 @772, versionIndependence u32 @776,
    compatibleVersions[16] u32 @780 (0-terminated), xseMinimum u32 @844."""
    rva = pe.exports().get("SKSEPlugin_Version")
    if rva is None:
        return None
    raw = pe.read(rva, 848)
    if len(raw) < 848:
        raise PeError("SKSEPlugin_Version data truncated")
    name = raw[8:264].split(b"\x00")[0].decode("ascii", "replace")
    indep = struct.unpack_from("<I", raw, 776)[0]
    compat = []
    for i in range(16):
        v = struct.unpack_from("<I", raw, 780 + i * 4)[0]
        if v == 0:
            break
        compat.append(v)
    return {"name": name, "address_independent": bool(indep & ADDRESS_INDEPENDENT),
            "compatible": compat}


def scan_markers(path):
    """Raw byte scan for Address Library dependency markers."""
    raw = Path(path).read_bytes()
    return {"address_library": (b"versionlib-" in raw) or (b"version-1-5-97" in raw)}
