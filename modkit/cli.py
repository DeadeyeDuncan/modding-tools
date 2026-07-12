"""modkit CLI dispatch. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim

Exit codes: 0 clean/success, 1 error or verify findings, 2 warned (forceable gate).
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from modkit import config, lodregen

PIPELINE = """typical install pipeline (skyrim):
  intake -> stage -> fomod (if present) -> dllvet -> esp -> conflicts -> deploy -> verify
judgment gates (dllvet verdicts, FOMOD picks, conflict decisions) are yours between steps.
run `modkit status --game <game>` at session start and after crashes.
exit codes: 0 clean, 1 error/findings, 2 warned or refused-pending-vets (--force)."""


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


def cmd_conflicts(args):
    from modkit import conflicts, deploy, state
    preset = _preset(args)
    if preset.DATA_DIR is None:
        safe_print(f"ERROR: game {preset.NAME!r} has no data_dir - "
                   "conflicts unsupported for this preset")
        return 1
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = deploy.data_root(preset, state.payload_root(staging))
    hits = conflicts.sweep(preset, pay)
    if not hits:
        safe_print("no file overlaps vs Data")
    for h in hits:
        owner = (f"currently owned by {h['owner']}" if h["owner"]
                 else "owner unknown (no manifest claims it)")
        safe_print(f"OVERLAP {h['path']} - {owner}; deploying makes this mod win")
    order_fn = getattr(preset, "archive_order_report", None)
    if order_fn:
        for line in order_fn(preset, pay):
            safe_print(f"ORDER {line}")
    st.data["vet_results"]["conflicts"] = {
        "overlaps": len(hits), "paths": [h["path"] for h in hits][:200]}
    st.stamp("conflicts")
    return 2 if hits else 0


def register_conflicts(sub, common):
    sp = sub.add_parser("conflicts", parents=[common],
                        help="file-overlap sweep: payload vs Data + manifests; "
                             "names the losing mod per overlap")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.set_defaults(func=cmd_conflicts)


def _staging_for(args, preset):
    from modkit import state
    if getattr(args, "staging", None):
        return Path(args.staging)
    latest = state.latest_staging(preset)
    if latest is None:
        raise config.ConfigError(
            f"no staging dirs under {preset.STAGING_ROOT} - run `modkit stage` first")
    return latest


def cmd_fomod(args):
    from modkit import fomod, state
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    payload = staging / "payload"
    if args.apply:
        try:
            picks = json.loads(Path(args.apply).read_bytes().decode("utf-8-sig"))
            count = fomod.apply(payload, staging, picks)
        except (OSError, json.JSONDecodeError, fomod.FomodError) as ex:
            safe_print(f"ERROR: {ex}")
            return 1
        st.data["vet_results"]["fomod"] = {"picks": picks, "files": count}
        st.stamp("fomod")
        safe_print(f"fomod applied: {count} files -> {staging / 'payload_final'}")
        return 0
    try:
        tree = fomod.parse(payload)
    except fomod.FomodError as ex:
        safe_print(f"ERROR: {ex}")
        return 1
    safe_print(json.dumps(tree, indent=2, ensure_ascii=False))
    return 0


def register_fomod(sub, common):
    sp = sub.add_parser("fomod", parents=[common],
                        help="print ModuleConfig option tree as JSON; --apply picks.json "
                             "materializes the chosen files into payload_final\\")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.add_argument("--apply", default=None, metavar="PICKS_JSON",
                    help='picks file: {"<step>::<group>": ["Plugin", ...]}')
    sp.set_defaults(func=cmd_fomod)


def cmd_esp(args):
    from modkit import deploy, state, tes4
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = deploy.data_root(preset, state.payload_root(staging))
    exts = getattr(preset, "PLUGIN_EXTS", ()) or (".esp", ".esm", ".esl")
    plugins = sorted(p for p in pay.rglob("*") if p.suffix.lower() in exts)
    if not plugins:
        safe_print("no plugins in payload - nothing to vet")
        st.stamp("esp")
        return 0
    data_dir = Path(preset.DATA_DIR) if preset.DATA_DIR else None
    payload_names = {p.name.lower() for p in plugins}
    results, warned = {}, False
    for p in plugins:
        try:
            hdr = tes4.parse_header(p)
        except tes4.Tes4Error as ex:
            safe_print(f"WARN {p.name}: {ex}")
            results[p.name] = {"error": str(ex)}
            warned = True
            continue
        missing = [m for m in hdr["masters"]
                   if m.lower() not in payload_names
                   and not (data_dir and (data_dir / m).is_file())]
        tag = " [ESL]" if hdr["esl"] else ""
        safe_print(f"{p.name}{tag}: masters = {', '.join(hdr['masters']) or '(none)'}")
        for m in missing:
            safe_print(f"  WARN missing master: {m} (not in Data or payload) - "
                       "install it first or expect a CTD")
            warned = True
        results[p.name] = {"masters": hdr["masters"], "esl": hdr["esl"],
                           "missing": missing}
    st.data["vet_results"]["esp"] = results
    st.stamp("esp")
    return 2 if warned else 0


def register_esp(sub, common):
    sp = sub.add_parser("esp", parents=[common],
                        help="TES4 header vet: masters list, ESL flag, "
                             "missing-master check vs Data + payload")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.set_defaults(func=cmd_esp)


def cmd_dllvet(args):
    from modkit import deploy, peparse, state
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = deploy.data_root(preset, state.payload_root(staging))
    dlls = sorted(p for p in pay.rglob("*") if p.suffix.lower() == ".dll")
    if not dlls:
        safe_print("no DLLs in payload - nothing to vet")
        st.stamp("dllvet")
        return 0
    runtime = peparse.encode_runtime(preset.RUNTIME) if preset.RUNTIME else None
    results, warned = {}, False
    for dll in dlls:
        rel = str(dll.relative_to(pay))
        verdict, notes = "OK", []
        try:
            pe = peparse.PEFile(dll)
            if pe.machine != "x64":
                verdict = "BAD_ARCH"
                notes.append(f"machine={pe.machine}, need x64")
            else:
                vd = peparse.skse_version_data(pe)
                if vd is None:
                    if "SKSEPlugin_Query" in pe.exports():
                        verdict = "RESEARCH"
                        notes.append("pre-AE SKSEPlugin_Query interface (1.5.97-era "
                                     "unless proven NG) - research the build first")
                    else:
                        verdict = "INFO"
                        notes.append("no SKSE exports (ENB/preloader/other) - vet by source")
                else:
                    if vd["address_independent"]:
                        notes.append("version-independent via Address Library")
                    elif runtime and runtime in vd["compatible"]:
                        notes.append(f"declares runtime {preset.RUNTIME}")
                    elif runtime:
                        verdict = "WRONG_RUNTIME"
                        declared = ", ".join(peparse.decode_runtime(v)
                                             for v in vd["compatible"]) or "(none)"
                        notes.append(f"declares [{declared}], config runtime "
                                     f"{preset.RUNTIME}")
                if peparse.scan_markers(dll)["address_library"]:
                    notes.append("needs Address Library (versionlib marker found)")
        except peparse.PeError as ex:
            verdict = "UNPARSEABLE"
            notes = [str(ex)]
        if verdict in ("WRONG_RUNTIME", "BAD_ARCH", "RESEARCH", "UNPARSEABLE"):
            warned = True
        results[rel] = {"verdict": verdict, "notes": notes}
        safe_print(f"{verdict:14} {rel}" + (f" - {'; '.join(notes)}" if notes else ""))
    st.data["vet_results"]["dllvet"] = results
    st.stamp("dllvet")
    return 2 if warned else 0


def register_dllvet(sub, common):
    sp = sub.add_parser("dllvet", parents=[common],
                        help="PE-parse payload DLLs: declared runtime vs config "
                             "runtime, Address Library independence, pre-AE detect")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.set_defaults(func=cmd_dllvet)


def cmd_plugins(args):
    from modkit import pluginstxt
    preset = _preset(args)
    try:
        if args.action == "list":
            for line in pluginstxt.read(preset):
                safe_print(line)
            return 0
        if args.action == "snapshot":
            safe_print(f"snapshot: {pluginstxt.snapshot(preset, args.tag)}")
            return 0
        if args.action == "diff":
            if len(args.paths) != 2:
                safe_print("ERROR: diff needs two paths: "
                           "modkit plugins diff <snapshot> <snapshot-or-live>")
                return 1
            safe_print(pluginstxt.diff(args.paths[0], args.paths[1]))
            return 0
        if not args.plugin:
            safe_print(f"ERROR: {args.action} needs --plugin <Name.esp>")
            return 1
        if args.action == "enable":
            pluginstxt.enable(preset, args.plugin, args.anchor)
            safe_print(f"enabled: {args.plugin}")
        else:
            pluginstxt.disable(preset, args.plugin)
            safe_print(f"disabled: {args.plugin}")
        return 0
    except pluginstxt.PluginsTxtError as ex:
        safe_print(f"ERROR: {ex}")
        return 1


def register_plugins(sub, common):
    sp = sub.add_parser("plugins", parents=[common],
                        help="Plugins.txt manager: list | enable | disable | "
                             "snapshot | diff (BOM/CRLF-safe, DynDOLOD block stays last)")
    sp.add_argument("action", choices=["list", "enable", "disable", "snapshot", "diff"])
    sp.add_argument("paths", nargs="*", help="diff: two snapshot/live paths")
    sp.add_argument("--plugin", default=None, help="plugin filename for enable/disable")
    sp.add_argument("--anchor", default=None,
                    help="enable: insert after this plugin (case-insensitive)")
    sp.add_argument("--tag", default="manual", help="snapshot tag (default: manual)")
    sp.set_defaults(func=cmd_plugins)


def cmd_deploy(args):
    from modkit import deploy, pluginstxt
    preset = _preset(args)
    staging = _staging_for(args, preset)
    try:
        return deploy.run_deploy(preset, staging, args.anchor, args.force, safe_print)
    except (deploy.DeployError, pluginstxt.PluginsTxtError) as ex:
        safe_print(f"ERROR: {ex}")
        return 1


def register_deploy(sub, common):
    sp = sub.add_parser("deploy", parents=[common],
                        help="game-not-running check, robocopy payload -> Data "
                             "(exit <8 ok), Plugins.txt enable, ledger add. "
                             "Exit 0 clean / 2 refused-pending-vets (--force overrides)")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.add_argument("--anchor", default=None,
                    help="Plugins.txt: insert new plugins after this one")
    sp.add_argument("--force", action="store_true",
                    help="deploy even with missing vet stamps")
    sp.set_defaults(func=cmd_deploy)


def cmd_remove(args):
    from modkit import deploy, pluginstxt
    preset = _preset(args)
    try:
        return deploy.run_remove(preset, args.mod, args.reason, args.force, safe_print)
    except (deploy.DeployError, pluginstxt.PluginsTxtError) as ex:
        safe_print(f"ERROR: {ex}")
        return 1


def register_remove(sub, common):
    sp = sub.add_parser("remove", parents=[common],
                        help="manifest-driven removal: quarantine (never delete), "
                             "masters-check-before-disable, ledger.py remove")
    sp.add_argument("mod", help="ledger entry name")
    sp.add_argument("--reason", required=True, help="recorded as removedReason")
    sp.add_argument("--force", action="store_true",
                    help="override the master-dependency refusal")
    sp.set_defaults(func=cmd_remove)


def cmd_verify(args):
    from modkit import verify
    preset = _preset(args)
    staging = _staging_for(args, preset)
    return verify.run_verify(preset, staging, safe_print)


def register_verify(sub, common):
    sp = sub.add_parser("verify", parents=[common],
                        help="payload-vs-Data diff (NO extension filtering), "
                             "_SWAP/_DISTR plugin-exists check, ledger check tail")
    sp.add_argument("--staging", default=None, help="staging dir (default: latest)")
    sp.set_defaults(func=cmd_verify)


def cmd_status(args):
    from modkit import state
    preset = _preset(args)
    root = Path(preset.STAGING_ROOT)
    stagings = sorted(d for d in root.iterdir()
                      if d.is_dir() and (d / "install.json").is_file()) \
        if root.is_dir() else []
    if not stagings:
        safe_print(f"no staging dirs for {preset.NAME} ({root})")
        return 0
    incomplete = 0
    for d in stagings:
        try:
            st = state.InstallState.load(str(d))
            pending = st.missing_applicable()
            undone = [s for s in ("deployed", "recorded", "verified")
                      if not st.data["stages"].get(s)]
            vres = st.data["vet_results"].get("verify")
            mod_name = st.data["mod"]
        except state.StateError as ex:
            safe_print(f"?? {d.name}: {ex}")
            incomplete += 1
            continue
        except (KeyError, TypeError):
            safe_print(f"  {d.name}: unreadable install.json (skipped)")
            incomplete += 1
            continue
        vtxt = (f"verify {'OK' if vres['ok'] else 'FAILED'} at {vres['ts']}"
                if vres else "never verified")
        if pending or undone:
            incomplete += 1
            safe_print(f"INCOMPLETE {d.name} [{mod_name}]")
            if pending:
                safe_print(f"  pending vets: {', '.join(pending)}")
            if undone:
                safe_print(f"  not done: {', '.join(undone)}")
            safe_print(f"  {vtxt}")
        elif args.all:
            safe_print(f"complete   {d.name} [{mod_name}] - {vtxt}")
    safe_print(f"{len(stagings)} staging dir(s), {incomplete} incomplete")
    return 0


def register_status(sub, common):
    sp = sub.add_parser("status", parents=[common],
                        help="staging dirs with incomplete stage chains + last "
                             "verify result (run at session start / after crashes)")
    sp.add_argument("--all", action="store_true", help="also list complete installs")
    sp.set_defaults(func=cmd_status)


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
                                epilog=PIPELINE,
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
    register_fomod(sub, common)
    register_esp(sub, common)
    register_dllvet(sub, common)
    register_plugins(sub, common)
    register_conflicts(sub, common)
    register_deploy(sub, common)
    register_remove(sub, common)
    register_verify(sub, common)
    register_status(sub, common)
    lodregen.register(sub)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (config.ConfigError, lodregen.LodregenError) as ex:
        safe_print(f"ERROR: {ex}")
        return 1
