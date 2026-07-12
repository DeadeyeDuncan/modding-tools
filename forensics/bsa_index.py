"""bsa_index.py — list BSA contents into a queryable JSON index.

Usage:
    py -3 C:\\Modding\\tools\\forensics\\bsa_index.py build [--game skyrim] [--config PATH] [--out PATH]
    py -3 C:\\Modding\\tools\\forensics\\bsa_index.py query <relpath-or-filename> [--raw-confirm] [--index PATH]
    py -3 C:\\Modding\\tools\\forensics\\bsa_index.py stats [--index PATH]

READ-ONLY: reads Data\\*.bsa; writes only the index JSON under forensics.cacheDir.

Why BSArch and not a Python parser: two hand-rolled SSE-BSA readers failed in
load-bearing ways — a folder-record offset bug (biased by totalFileNameLength@28,
not totalFolderNameLength@24; hours of false-positive triage) and a format-level
folder/file-pairing quirk that made even fixed 48216-entry parsers miss real
vanilla entries (sack01, coinbaglarge, farmwall01, beehive01, byohhouse\\*).
See wiki concepts/skyrim-build-wide-missing-mesh-sweep and memory
sse-over-revert-invisible-holes. The reliable vanilla-path confirmation is the
raw filename byte-scan (raw_confirm below).

BSArch CLI shapes (captured on-machine, Task 2 Step 1, `BSArch64.exe` with no
args, and cross-checked with a live `-list` run against a real Data\\ BSA —
exit code 0, plain lowercase relative paths one per line after the info
banner, no trailing summary line):
    list:   BSArch64.exe <archive.bsa> -list
    pack:   BSArch64.exe pack <folder> <archive.bsa> -sse
    unpack: BSArch64.exe unpack <archive.bsa> <folder>
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forensics import _lib

ASSET_EXTS = ("nif", "dds", "tri", "hkx", "wav", "fuz", "xwm", "pex", "psc",
              "seq", "txt", "ini", "json", "swf", "gid", "lip", "btr", "bto",
              "lod", "egm", "egt", "dlodsettings", "bgem", "bgsm", "dtl")

_PATH_RE = re.compile(
    r"""(?P<path>(?:[^\\/:*?"<>|\r\n]+[\\/])+[^\\/:*?"<>|\r\n]+\.(?:%s))\s*$"""
    % "|".join(ASSET_EXTS), re.IGNORECASE)


def parse_bsarch_listing(text):
    """Keep lines that end in a relative asset path; drop banner/summary noise.
    The tiny-BSA round-trip test is the authority that this parse is complete."""
    out = []
    for line in text.splitlines():
        m = _PATH_RE.search(line.strip())
        if m:
            out.append(_lib.norm_rel(m.group("path")))
    return out


def bsarch_list_cmd(bsarch, bsa_path):
    return [bsarch, str(bsa_path), "-list"]


def bsarch_pack_cmd(bsarch, folder, bsa_path):
    return [bsarch, "pack", str(folder), str(bsa_path), "-sse"]


def bsarch_unpack_cmd(bsarch, bsa_path, folder):
    return [bsarch, "unpack", str(bsa_path), str(folder)]


def list_bsa(bsarch, bsa_path, tmp_root):
    """List one BSA. Primary: BSArch listing. Fallback (still BSArch-only,
    correct by construction, slow): unpack to a temp dir and walk it."""
    rc, text = _lib.run(bsarch_list_cmd(bsarch, bsa_path))
    paths = parse_bsarch_listing(text)
    if paths:
        return paths
    _lib.say("  listing yielded no paths (rc=%d) - falling back to unpack+walk "
             "for %s (fix bsarch_list_cmd per usage text if this persists)"
             % (rc, Path(bsa_path).name))
    out = Path(tmp_root) / ("bsa-unpack-" + Path(bsa_path).stem)
    out.mkdir(parents=True, exist_ok=True)
    rc, text = _lib.run(bsarch_unpack_cmd(bsarch, bsa_path, out))
    if rc != 0:
        raise _lib.ForensicsError("BSArch could not list or unpack %s:\n%s"
                                  % (bsa_path, text))
    return sorted(rel for _ap, rel in _lib.iter_files(out))


def build_index(cfg, game="skyrim"):
    data_dir = Path(_lib.game_path(cfg, "dataDir", game))
    bsarch = _lib.tool_path(cfg, "bsarch")
    tmp_root = _lib.cache_dir(cfg) / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    bsas = sorted(data_dir.glob("*.bsa"), key=lambda p: p.name.lower())
    if not bsas:
        raise _lib.ForensicsError("no .bsa files under %s" % data_dir)
    index = {"dataDir": str(data_dir), "bsas": {}}
    for bsa in bsas:
        paths = list_bsa(bsarch, bsa, tmp_root)
        index["bsas"][bsa.name] = sorted(set(paths))
        _lib.say("%-40s %6d entries" % (bsa.name, len(paths)))
    return index


def default_index_path(cfg, game="skyrim"):
    return _lib.cache_dir(cfg) / ("bsa-index-%s.json" % game)


def load_index(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def all_paths(index):
    out = set()
    for paths in index["bsas"].values():
        out.update(paths)
    return out


def contains(index, rel):
    rel = _lib.norm_rel(rel)
    return [name for name, paths in index["bsas"].items() if rel in set(paths)]


def dir_prefixes(index):
    """Every directory prefix present in any BSA — the mod-specific-path signal:
    a miss under a prefix NO BSA carries cannot have a BSA fallback (wiki:
    the only fully reliable genuine-hole signal)."""
    out = set()
    for paths in index["bsas"].values():
        for p in paths:
            parts = p.split("\\")[:-1]
            for i in range(1, len(parts) + 1):
                out.add("\\".join(parts[:i]))
    return out


def raw_confirm(bsa_path, name, chunk=1 << 24):
    """Case-insensitive byte scan of the BSA for a filename — the wiki's
    reliable confirmation for vanilla paths the structured index may miss
    (grep -a equivalent; used 6+ times in session dba84d3e)."""
    needle = _lib.norm_rel(name).split("\\")[-1].encode("cp1252", "replace").lower()
    if not needle:
        return False
    keep = len(needle) - 1
    carry = b""
    with open(bsa_path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                return False
            hay = (carry + block).lower()
            if needle in hay:
                return True
            carry = block[-keep:] if keep else b""


def main(argv=None):
    ap = argparse.ArgumentParser(description="BSA content index (BSArch-backed)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--game", default="skyrim")
    b.add_argument("--config", default=None)
    b.add_argument("--out", default=None)
    q = sp.add_parser("query")
    q.add_argument("name")
    q.add_argument("--raw-confirm", action="store_true")
    q.add_argument("--game", default="skyrim")
    q.add_argument("--config", default=None)
    q.add_argument("--index", default=None)
    s = sp.add_parser("stats")
    s.add_argument("--game", default="skyrim")
    s.add_argument("--config", default=None)
    s.add_argument("--index", default=None)
    args = ap.parse_args(argv)

    cfg = _lib.load_config(args.config)
    if args.cmd == "build":
        index = build_index(cfg, args.game)
        out = Path(args.out) if args.out else default_index_path(cfg, args.game)
        _lib.atomic_write_json(out, index)
        total = sum(len(v) for v in index["bsas"].values())
        _lib.say("wrote %s (%d BSAs, %d entries)" % (out, len(index["bsas"]), total))
        return 0
    idx_path = Path(args.index) if args.index else default_index_path(cfg, args.game)
    if not idx_path.is_file():
        raise _lib.ForensicsError("no index at %s - run: bsa_index.py build" % idx_path)
    index = load_index(idx_path)
    if args.cmd == "stats":
        for name in sorted(index["bsas"]):
            _lib.say("%-40s %6d" % (name, len(index["bsas"][name])))
        _lib.say("TOTAL %d entries" % len(all_paths(index)))
        return 0
    # query
    rel = _lib.norm_rel(args.name)
    hits = contains(index, rel)
    if hits:
        for h in hits:
            _lib.say("INDEX-HIT %s :: %s" % (h, rel))
        return 0
    base = rel.split("\\")[-1]
    name_hits = [(n, p) for n, paths in index["bsas"].items()
                 for p in paths if p.endswith("\\" + base) or p == base]
    for n, p in name_hits[:20]:
        _lib.say("NAME-HIT  %s :: %s" % (n, p))
    if args.raw_confirm and not name_hits:
        data_dir = Path(index["dataDir"])
        found = False
        for bsa in sorted(data_dir.glob("*.bsa")):
            if raw_confirm(bsa, base):
                _lib.say("RAW-HIT   %s :: %s (name-table byte scan; index gap "
                         "= known folder-pairing quirk)" % (bsa.name, base))
                found = True
        if found:
            return 0
    if not name_hits:
        _lib.say("MISS      %s (not in index%s)"
                 % (rel, ", raw scan negative" if args.raw_confirm else
                    "; re-run with --raw-confirm before trusting a vanilla-path miss"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
