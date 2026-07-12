"""modkit CLI dispatch. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim

Exit codes: 0 clean/success, 1 error or verify findings, 2 warned (forceable gate).
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

from modkit import config


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


NEXUS_RE = re.compile(
    r"^(?P<name>.+?)-(?P<modid>\d{2,7})-(?P<ver>[0-9][0-9a-zA-Z-]*?)"
    r"(?:-(?P<ts>\d{9,11}))?\.(?P<ext>7z|zip|rar)$", re.IGNORECASE)


def parse_nexus_filename(fname):
    """Nexus download pattern `Name-<modid>-<v-e-r>[-<epoch>].<ext>` -> dict|None."""
    m = NEXUS_RE.match(fname)
    if not m:
        return None
    return {"name": m.group("name").strip(), "modid": int(m.group("modid")),
            "version": m.group("ver").replace("-", ".")}


def _intake_report(preset, path, expect):
    """Print one archive's intake block. Returns True if any WARN fired."""
    from modkit import archive as arch
    from modkit import games, ledger_bridge
    warn = False
    size = path.stat().st_size
    safe_print(f"== {path.name} ({size} bytes)")
    if size == 0:
        safe_print("  WARN 0-byte download - re-download from Nexus")
        return True
    meta = parse_nexus_filename(path.name)
    if meta:
        safe_print(f"  parsed: name={meta['name']!r} nexusId={meta['modid']} "
                   f"version={meta['version']}")
    else:
        safe_print("  parsed: (not a Nexus-pattern filename)")
    try:
        entries = arch.listing(preset.SEVENZIP, path)
    except arch.ArchiveError as ex:
        safe_print(f"  WARN unreadable archive: {ex}")
        return True
    guess = games.guess_game([e["path"] for e in entries if not e["is_dir"]])
    if guess and guess != expect:
        safe_print(f"  WARN looks like a {guess} archive, not {expect} - wrong-game "
                   f"gate (pass --expect-game {guess} if intentional)")
        warn = True
    else:
        safe_print(f"  game-guess: {guess or 'unknown'} (expected {expect})")
    if meta:
        code, _out = ledger_bridge.run(
            ["get", "--name", meta["name"], *ledger_bridge.game_args(preset)])
        if code == 0:
            safe_print(f"  WARN already in ledger: {meta['name']!r} - re-download of "
                       "an installed mod?")
            warn = True
    safe_print(f"  files: {sum(1 for e in entries if not e['is_dir'])}")
    return warn


def cmd_intake(args):
    preset = _preset(args)
    if args.path:
        p = Path(args.path)
        if not p.is_file():
            safe_print(f"ERROR: no such archive: {p}")
            return 1
        paths = [p]
    else:
        paths = []
        for d in [*preset.DOWNLOADS, preset.VORTEX_DOWNLOADS]:
            if d and Path(d).is_dir():
                paths += [x for x in Path(d).iterdir()
                          if x.suffix.lower() in (".7z", ".zip", ".rar")]
        paths.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        paths = paths[:args.limit]
    if not paths:
        safe_print("no archives found in downloads dirs")
        return 0
    expect = getattr(args, "expect_game", None) or preset.NAME
    warned = False
    for p in paths:
        warned = _intake_report(preset, p, expect) or warned
    return 2 if warned else 0


def register_intake(sub, common):
    sp = sub.add_parser("intake", parents=[common],
                        help="scan Downloads/Vortex (or one file): 0-byte check, Nexus "
                             "name/id parse, wrong-game gate, already-installed check")
    sp.add_argument("path", nargs="?", help="archive path (default: scan downloads dirs)")
    sp.add_argument("--expect-game", dest="expect_game", default=None,
                    help="override the wrong-game gate expectation")
    sp.add_argument("--limit", type=int, default=15, help="max archives when scanning")
    sp.set_defaults(func=cmd_intake)


def cmd_stage(args):
    from modkit import archive as arch
    from modkit import state
    preset = _preset(args)
    arc_path = Path(args.archive)
    if not arc_path.is_file():
        safe_print(f"ERROR: no such archive: {arc_path}")
        return 1
    meta = parse_nexus_filename(arc_path.name)
    mod_name = args.name or (meta["name"] if meta else arc_path.stem)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    staging = Path(preset.STAGING_ROOT) / f"{ts}-{state.slug(mod_name)}"
    payload = staging / "payload"
    try:
        entries = arch.listing(preset.SEVENZIP, arc_path)
        arch.extract_all(preset.SEVENZIP, arc_path, payload)
    except arch.ArchiveError as ex:
        safe_print(f"ERROR: {ex}")
        return 1
    problems = arch.verify_extraction(entries, payload)
    if problems:
        for p in problems[:20]:
            safe_print(f"  BAD {p}")
        safe_print(f"ERROR: extraction verify failed ({len(problems)} problems) - "
                   f"staging kept for inspection: {staging}")
        return 1
    st = state.InstallState.create(
        str(staging), mod=mod_name, game=preset.NAME, archive=str(arc_path),
        nexus_id=meta["modid"] if meta else None,
        version=meta["version"] if meta else None,
        applicable=preset.applicability(str(payload)))
    st.stamp("intake")
    st.stamp("staged")
    safe_print(f"staged: {staging}")
    pending = st.missing_applicable()
    safe_print("pending vets: " + (", ".join(pending) if pending else "none"))
    return 0


def register_stage(sub, common):
    sp = sub.add_parser("stage", parents=[common],
                        help="FULL-extract archive to a fresh timestamped staging dir, "
                             "verify count/size vs listing, create install.json")
    sp.add_argument("archive", help="archive file to stage")
    sp.add_argument("--name", default=None, help="mod name override (default: Nexus parse)")
    sp.set_defaults(func=cmd_stage)


def _preset(args):
    cfg = config.load(getattr(args, "config", None))
    game = getattr(args, "game", None)
    if not game:
        raise config.ConfigError("missing --game (e.g. --game skyrim)")
    return config.game(cfg, game)


def _add_globals(parser):
    # SUPPRESS: unprovided flags set no attribute, so subparser parsing never
    # clobbers a value parsed before the subcommand (ledger.py precedent).
    parser.add_argument("--game", default=argparse.SUPPRESS,
                        help="game preset from modkit.json (skyrim | cp77 | ...)")
    parser.add_argument("--config", default=argparse.SUPPRESS,
                        help="explicit modkit.json path (default: MODKIT_CONFIG env, then repo file)")


def build_parser():
    p = argparse.ArgumentParser(prog="modkit.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_globals(p)
    common = argparse.ArgumentParser(add_help=False)
    _add_globals(common)
    sub = p.add_subparsers(dest="command", required=True)
    _register_all(sub, common)
    return p


def _register_all(sub, common):
    """Each task appends its register_<cmd>(sub, common) call here."""
    register_intake(sub, common)
    register_stage(sub, common)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as ex:
        safe_print(f"ERROR: {ex}")
        return 1
