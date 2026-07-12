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

POSTMORTEM (Task 2 review, feat/forensics): the original `parse_bsarch_listing`
gated BSArch's `-list` output through a hardcoded extension allowlist
(`ASSET_EXTS`). BSArch's listing is authoritative — every line after the
banner is a real archived path — so filtering it by extension silently
dropped whole vanilla categories (e.g. `.strings`/`.dlstrings`/`.ilstrings` in
`Skyrim - Interface.bsa`, `.btt`/`.lst` in `Skyrim - Meshes1.bsa`: 889 entries
across 12 real Data\\ BSAs). Fixed by (1) keeping every path-shaped line
regardless of extension — a line is a path iff, after stripping, it contains
no ':' and fully matches "(segment\\/)+segment.ext" (the ':' exclusion is
what keeps banner lines like "Archive Name: E:/.../Whatever.bsa" or the MPL
license URL from being mistaken for entries — every genuine relative BSA
path is colon-free, drive letters and URLs are not), and (2) cross-checking
the parsed count against BSArch's own banner "Files: N" line, broadening the
unpack+walk fallback to trigger on ANY mismatch (not just a fully-empty
listing) so a future parsing gap is loud (a WARN + fallback), not silent.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forensics import _lib

# NOTE: no extension allowlist. BSArch's -list output is authoritative — every
# line after the banner is a real archived path, whatever its extension. This
# regex's job is only to tell a path line apart from banner/summary noise; it
# must NOT gate on what kind of asset it is (that was the Task 2 review bug:
# an old ASSET_EXTS allowlist here silently dropped 889 real entries across
# 12 real Data\ BSAs). It is fullmatch'd (not search'd) against the whole
# stripped line, and every character class excludes ':' — so any line with a
# colon anywhere (BSArch's "Archive Name: ...", "Files: N", etc., and even
# banner prose containing a "https://..." URL) can never fully match, without
# needing a separate colon check. Genuine relative BSA paths never contain ':'.
_PATH_RE = re.compile(
    r"""(?P<path>(?:[^\\/:*?"<>|\r\n]+[\\/])+[^\\/:*?"<>|\r\n]+\.[^\\/:*?"<>|\r\n]+)""")

# BSArch's -list banner reports a total, e.g. "         Files: 386". Used as a
# completeness cross-check against the parsed path count (see list_bsa).
_FILES_COUNT_RE = re.compile(r"^\s*Files:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def parse_bsarch_listing(text):
    """Keep every path-shaped line (see _PATH_RE); drop banner/summary noise.
    No extension filtering — BSArch's -list output is authoritative for
    whatever it lists. The extended tiny-BSA round-trip test (mixed
    extensions, some outside the old ASSET_EXTS set) is the authority that
    this parse is complete; list_bsa's banner-count cross-check is the
    authority for real-world archives this test doesn't cover."""
    out = []
    for line in text.splitlines():
        m = _PATH_RE.fullmatch(line.strip())
        if m:
            out.append(_lib.norm_rel(m.group("path")))
    return out


def parse_banner_file_count(text):
    """Extract BSArch's own 'Files: N' banner total, or None if absent
    (e.g. malformed/non-BSArch output) — see list_bsa's cross-check."""
    m = _FILES_COUNT_RE.search(text)
    return int(m.group(1)) if m else None


def bsarch_list_cmd(bsarch, bsa_path):
    return [bsarch, str(bsa_path), "-list"]


def bsarch_pack_cmd(bsarch, folder, bsa_path):
    return [bsarch, "pack", str(folder), str(bsa_path), "-sse"]


def bsarch_unpack_cmd(bsarch, bsa_path, folder):
    return [bsarch, "unpack", str(bsa_path), str(folder)]


def list_bsa(bsarch, bsa_path, tmp_root):
    """List one BSA. Primary: BSArch listing, cross-checked against BSArch's
    own 'Files: N' banner count so a parse gap is loud (WARN + fallback), not
    silent. Fallback (still BSArch-only, correct by construction, slow):
    unpack to a temp dir and walk it — triggered by an empty listing OR a
    parsed-count/banner-count mismatch (previously only the fully-empty case
    triggered it, which is how the old ASSET_EXTS bug went undetected on
    mixed-extension archives: only the one archive that was 100% non-listed
    extensions ever hit the fallback)."""
    rc, text = _lib.run(bsarch_list_cmd(bsarch, bsa_path))
    paths = parse_bsarch_listing(text)
    banner_count = parse_banner_file_count(text)
    mismatch = banner_count is not None and len(paths) != banner_count
    if paths and not mismatch:
        return paths
    if mismatch:
        _lib.say("  WARN: %s parsed %d path(s) but BSArch banner says "
                 "Files: %d (delta %d) - falling back to unpack+walk"
                 % (Path(bsa_path).name, len(paths), banner_count,
                    banner_count - len(paths)))
    else:
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
    """Every directory prefix BSArch's -list output reports for any BSA — the
    mod-specific-path signal: a miss under a prefix no BSA's authoritative
    listing carries cannot have a BSA-listing fallback.

    This reflects BSArch's own -list output exactly (as of the Task 2 review
    fix: no extension filter narrows it anymore, so e.g. 'strings\\' now
    appears here whenever a BSA lists .strings files). It is NOT a claim that
    every real archived path is covered: BSArch's -list itself rarely omits
    a genuine entry (e.g. sack01.nif is byte-present in Skyrim - Meshes1.bsa
    but never appears in its own -list output) — raw_confirm is the backstop
    for that gap, not this function."""
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
