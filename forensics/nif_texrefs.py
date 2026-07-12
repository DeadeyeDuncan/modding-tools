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
extracted, and this exactly matches the raw case-insensitive byte count of
the literal "textures\" substring (35) and ".dds" substring (35) in the file
- i.e. the regex captured every single texture-path occurrence with zero
misses. NifSkope has no non-interactive dump mode (confirmed: --help shows
only a --port remote-control listener), so the literal GUI block-tree
comparison this step describes needs a human with NifSkope open — see
task-3-report.md for the full verification writeup and that follow-up.

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


def check_refs(refs, data_dir, bsa_paths_set):
    data_dir = Path(data_dir)
    out = {}
    for ref in refs:
        if (data_dir / ref).is_file():
            out[ref] = "LOOSE"
        elif ref in bsa_paths_set:
            out[ref] = "BSA"
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
                    help="classify each ref LOOSE/BSA/MISSING (needs bsa_index build)")
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
        all_refs = sorted({r for refs in report["meshes"].values() for r in refs})
        verdicts = check_refs(all_refs, data_dir, bsa_paths)
        for mesh, refs in report["meshes"].items():
            missing = [r for r in refs if verdicts[r] == "MISSING"]
            if missing:
                report["missing"][mesh] = missing
        for ref in all_refs:
            _lib.say("%-8s %s" % (verdicts[ref], ref))
        _lib.say("scanned %d meshes, %d unique refs, %d MISSING"
                 % (len(nifs), len(all_refs), sum(1 for v in verdicts.values() if v == "MISSING")))
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
