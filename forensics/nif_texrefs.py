"""nif_texrefs.py — extract texture paths referenced by .nif files.

Usage:
    py -3 C:\\Modding\\tools\\forensics\\nif_texrefs.py <file-or-dir> [...]
    py -3 ...\\nif_texrefs.py Data\\meshes\\smim --check      (verify refs vs loose+BSA)
    py -3 ...\\nif_texrefs.py <path> --json out.json

READ-ONLY. Method: byte-level ASCII scan for 'textures\\...*.dds' — the exact
technique proven load-bearing in the sagas (grep -a over .nif settled the
CM-bake family; the 2026-07-01 texture-ref sweep variant: extract every texture
reference from a scoped set of loose meshes, verify each against loose Data +
BSAs — wiki concepts/skyrim-build-wide-missing-mesh-sweep, memory
sse-cmbake-shiny-leftovers). Texture paths live in BSShaderTextureSet blocks;
this tool does NOT parse block structure (not wiki-established) — it reports
the union of texture strings in the file, which is what every recorded use
needed. Real-mesh verified (Task 3 Step 6, mrkapoth01.nif): 35 unique refs
extracted, matching the raw case-insensitive byte count of the literal
"textures\" substring (35) and ".dds" substring (35) in the file - strong
evidence (matching aggregate + positional counts on the one real mesh
tested), not a proof of zero misses in general: matching totals don't
logically establish a bijection between substring occurrences and extracted
refs. NifSkope has no non-interactive dump mode (confirmed: --help shows
only a --port remote-control listener), so the literal GUI block-tree
comparison this step describes still needs a human with NifSkope open — see
task-3-report.md for the full verification writeup and that follow-up.

--check MISSING backstop (false-triage fix, see task-3-report.md): BSArch's
-list output genuinely omits some real BSA entries (the sack01.nif
folder-pairing quirk documented in bsa_index.py — the exact reason
bsa_index.raw_confirm() exists as a backstop). A ref that is neither loose
nor in bsa_index.all_paths() is therefore NOT automatically MISSING:
check_refs() runs bsa_index.raw_confirm() (a byte-scan of each BSA's raw
name table) on exactly the refs that would otherwise be reported MISSING,
and reports a hit as BSA-RAW instead. This runs by default for `--check`
(the safe direction — a false MISSING drives a wrong quarantine decision)
and only touches already-would-be-MISSING refs, so the common all-present
case never pays the byte-scan cost.

Safety gate reminder from the wiki: before quarantining anything based on a
MISSING ref, verify BSA fallback for both texture AND mesh.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forensics import _lib

_TEX_RE = re.compile(rb"(?i)textures[\\/][ -~]{0,240}?\.dds")


def extract_texrefs(data):
    refs = set()
    for m in _TEX_RE.finditer(data):
        refs.add(_lib.norm_rel(m.group(0).decode("ascii", "replace")))
    return sorted(refs)


def check_refs(refs, data_dir, bsa_paths_set, bsa_files=(), raw_confirm=None):
    """Classify each ref LOOSE / BSA / BSA-RAW / MISSING.

    LOOSE: present in loose Data\\.
    BSA: present in bsa_index.all_paths() (the structured BSArch listing).
    BSA-RAW: not loose, not index-listed, but bsa_index.raw_confirm() finds
        the filename byte-present in one of bsa_files — backstops the
        documented BSArch -list folder-pairing quirk (bsa_index.py,
        dir_prefixes()) where a real archived entry (sack01.nif et al.)
        never appears in -list output. Only attempted for refs that are
        neither loose nor index-listed, so the common all-present case
        never pays the byte-scan cost.
    MISSING: loose, index, AND raw_confirm (if attempted) all came up empty.

    bsa_files: BSA paths to raw-scan for the backstop. Pass the default
    empty tuple to skip the backstop entirely (plain LOOSE/BSA/MISSING).
    raw_confirm: callable(bsa_path, name) -> bool; defaults to
    bsa_index.raw_confirm (lazily imported, and injectable for tests).
    """
    data_dir = Path(data_dir)
    if bsa_files and raw_confirm is None:
        from forensics import bsa_index
        raw_confirm = bsa_index.raw_confirm
    out = {}
    for ref in refs:
        if (data_dir / ref).is_file():
            out[ref] = "LOOSE"
        elif ref in bsa_paths_set:
            out[ref] = "BSA"
        elif bsa_files and any(raw_confirm(b, ref) for b in bsa_files):
            out[ref] = "BSA-RAW"
        else:
            out[ref] = "MISSING"
    return out


def collect_nifs(paths):
    nifs = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            nifs.extend(ap for ap, _rel in _lib.iter_files(p, exts=(".nif",)))
        elif p.is_file():
            nifs.append(p)
        else:
            raise _lib.ForensicsError("no such path: %s" % p)
    return nifs


def main(argv=None):
    ap = argparse.ArgumentParser(description="NIF texture-reference audit")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--check", action="store_true",
                    help="classify each ref LOOSE/BSA/BSA-RAW/MISSING (needs bsa_index "
                         "build); would-be-MISSING refs are backstopped by "
                         "bsa_index.raw_confirm() before being reported MISSING")
    ap.add_argument("--json", default=None, help="write full report JSON here")
    ap.add_argument("--game", default="skyrim")
    ap.add_argument("--config", default=None)
    ap.add_argument("--index", default=None)
    args = ap.parse_args(argv)

    nifs = collect_nifs(args.paths)
    report = {"meshes": {}, "missing": {}}
    for nif in nifs:
        report["meshes"][str(nif)] = extract_texrefs(nif.read_bytes())

    if args.check:
        from forensics import bsa_index
        cfg = _lib.load_config(args.config)
        data_dir = _lib.game_path(cfg, "dataDir", args.game)
        idx_path = Path(args.index) if args.index else bsa_index.default_index_path(cfg, args.game)
        if not idx_path.is_file():
            raise _lib.ForensicsError("no BSA index at %s - run bsa_index.py build first" % idx_path)
        bsa_paths = bsa_index.all_paths(bsa_index.load_index(idx_path))
        bsa_files = sorted(Path(data_dir).glob("*.bsa"))
        all_refs = sorted({r for refs in report["meshes"].values() for r in refs})
        verdicts = check_refs(all_refs, data_dir, bsa_paths, bsa_files=bsa_files)
        for mesh, refs in report["meshes"].items():
            missing = [r for r in refs if verdicts[r] == "MISSING"]
            if missing:
                report["missing"][mesh] = missing
        for ref in all_refs:
            _lib.say("%-8s %s" % (verdicts[ref], ref))
        raw_recovered = sum(1 for v in verdicts.values() if v == "BSA-RAW")
        _lib.say("scanned %d meshes, %d unique refs, %d MISSING"
                 " (%d recovered from would-be-MISSING via raw_confirm backstop)"
                 % (len(nifs), len(all_refs),
                    sum(1 for v in verdicts.values() if v == "MISSING"), raw_recovered))
    else:
        for mesh, refs in report["meshes"].items():
            _lib.say(mesh)
            for r in refs:
                _lib.say("    " + r)

    if args.json:
        _lib.atomic_write_json(args.json, report)
        _lib.say("wrote %s" % args.json)
    return 1 if report["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
