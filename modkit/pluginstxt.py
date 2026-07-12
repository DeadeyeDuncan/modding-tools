"""Plugins.txt manager: BOM/CRLF-preserving, case-insensitive anchors,
DynDOLOD-block-stays-last, snapshot/diff to bracket external GUI tools
(the Wrye Bash silent-scramble class). Convention: '*' prefix = enabled."""
import datetime
import shutil
from pathlib import Path

from modkit.state import atomic_write_bytes


class PluginsTxtError(Exception):
    """Missing file, unknown anchor, or post-write validation failure."""


def _plugins_path(preset):
    p = getattr(preset, "PLUGINS_TXT", None)
    if not p:
        raise PluginsTxtError(f"game {preset.NAME!r} has no plugins_txt configured")
    if not Path(p).is_file():
        raise PluginsTxtError(f"Plugins.txt not found: {p}")
    return Path(p)


def _read_raw(path):
    raw = Path(path).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return bom, lines


def _write_raw(preset, bom, lines):
    body = "\r\n".join(lines) + "\r\n"
    atomic_write_bytes(_plugins_path(preset),
                       (b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))


def _name(line):
    return line.lstrip("*").strip().lower()


def read(preset):
    """Plugin lines verbatim ('*' = enabled); comments/blank lines skipped."""
    _bom, lines = _read_raw(_plugins_path(preset))
    return [l for l in lines if l.strip() and not l.lstrip().startswith("#")]


def snapshot(preset, tag):
    """Byte-copy Plugins.txt to BACKUPS_DIR\\plugins-<tag>-<ts>.txt; returns path."""
    src = _plugins_path(preset)
    bdir = Path(preset.BACKUPS_DIR)
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = bdir / f"plugins-{tag}-{ts}.txt"
    shutil.copy2(src, dest)
    return str(dest)


def diff(path_a, path_b):
    """Human report: ADDED/REMOVED lines, STATE flips, ORDER changes."""
    def load(p):
        _b, lines = _read_raw(p)
        return [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    a, b = load(path_a), load(path_b)
    amap = {_name(l): l for l in a}
    bmap = {_name(l): l for l in b}
    out = []
    for n, line in bmap.items():
        if n not in amap:
            out.append(f"ADDED   {line}")
    for n, line in amap.items():
        if n not in bmap:
            out.append(f"REMOVED {line}")
    for n in amap:
        if n in bmap and amap[n] != bmap[n]:
            sa = "enabled" if amap[n].startswith("*") else "disabled"
            sb = "enabled" if bmap[n].startswith("*") else "disabled"
            if sa != sb:
                out.append(f"STATE   {bmap[n].lstrip('*')}: {sa} -> {sb}")
    order_a = [n for n in map(_name, a) if n in bmap]
    order_b = [n for n in map(_name, b) if n in amap]
    if order_a != order_b:
        out.append("ORDER   load order changed for pre-existing plugins")
    return "\n".join(out) if out else "no differences"


def enable(preset, plugin, anchor):
    """Enable (insert or star-in-place). Snapshot-first, atomic, validated after."""
    path = _plugins_path(preset)
    target = plugin.lstrip("*").strip()
    tname = target.lower()
    bom, lines = _read_raw(path)
    idx_of = {_name(l): i for i, l in enumerate(lines) if l.strip()}
    if anchor and _name(anchor) not in idx_of:
        raise PluginsTxtError(f"anchor {anchor!r} not found in Plugins.txt "
                              "(anchors are case-insensitive, '*' optional)")
    snapshot(preset, "pre-enable")
    if tname in idx_of:
        i = idx_of[tname]
        lines[i] = "*" + lines[i].lstrip("*")
    else:
        block = tuple(n.lower() for n in getattr(preset, "DYNDOLOD_BLOCK", ()) or ())
        block_start = len(lines)
        for i, l in enumerate(lines):
            if _name(l) in block:
                block_start = i
                break
        index = idx_of[_name(anchor)] + 1 if anchor else block_start
        if tname not in block and index > block_start:
            index = block_start  # DynDOLOD block stays last
        lines.insert(index, "*" + target)
    _write_raw(preset, bom, lines)
    after = read(preset)
    if not any(_name(l) == tname and l.startswith("*") for l in after):
        raise PluginsTxtError(f"post-write validation failed: {target} not enabled")


def disable(preset, plugin):
    """Strip the '*' but KEEP the line (order preserved). Snapshot-first, validated."""
    path = _plugins_path(preset)
    tname = plugin.lstrip("*").strip().lower()
    bom, lines = _read_raw(path)
    if not any(_name(l) == tname for l in lines if l.strip()):
        raise PluginsTxtError(f"{plugin!r} not in Plugins.txt")
    snapshot(preset, "pre-disable")
    lines = [l.lstrip("*") if _name(l) == tname else l for l in lines]
    _write_raw(preset, bom, lines)
    _b, after = _read_raw(path)
    if any(l.startswith("*") and _name(l) == tname for l in after):
        raise PluginsTxtError(f"post-write validation failed: {plugin} still enabled")
