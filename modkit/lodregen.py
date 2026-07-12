"""modkit lodregen -- pre/post guards around the manual LOD/bake regen ritual.

The ritual this module brackets (GUI runs are ALWAYS manual, never driven):

    modkit lodregen pre --game skyrim
      -> [user: PGPatcher]  -> deploy PG output into Data (runbook step)
      -> [user: TexGen]     -> modkit lodregen post --game skyrim --stage texgen
      -> [user: DynDOLOD]   -> modkit lodregen post --game skyrim

Ground truth: wiki concepts/skyrim-dyndolod-generation + concepts/skyrim-pgpatcher.
Trio = DynDOLOD.esm -> DynDOLOD.esp -> Occlusion.esp, Occlusion absolute last.
Plugins.txt is touched ONLY through modkit.pluginstxt. The ledger is touched
ONLY through modkit.ledger_bridge (ledger.py stays the sole ledger writer).
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from modkit import config, deploy, ledger_bridge, pluginstxt


class LodregenError(Exception):
    pass


REQUIRED_KEYS = [
    "holding_root", "ledger_dir", "trio", "tool_processes", "tools",
    "outputs", "min_output_files", "ledger_prefixes", "ng_markers",
    "protected_inputs", "resources_staging",
]


def section(cfg, game):
    """Validated lodregen config section for `game` out of the modkit.json dict."""
    lr = cfg.get("lodregen") or {}
    if game not in lr:
        raise LodregenError(
            f"modkit.json has no lodregen section for game {game!r} "
            f"(add one -- see docs\\2026-07-11-lod-regen-plan.md schema)")
    sec = lr[game]
    missing = [k for k in REQUIRED_KEYS if k not in sec]
    if missing:
        raise LodregenError(f"lodregen.{game} missing keys: {', '.join(missing)}")
    if not (isinstance(sec["trio"], list) and len(sec["trio"]) == 3):
        raise LodregenError(
            f"lodregen.{game}.trio must list exactly 3 plugins in re-enable "
            f"order (last = loads absolute last), got {sec['trio']!r}")
    return sec


# ------------------------------------------------------------ run state

RUN_STATE = "lodregen-run.json"


def _now():
    return datetime.datetime.now()


def atomic_write_json(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def new_run(sec, game):
    """Create <holding_root>\\<run_id>\\lodregen-run.json and return it."""
    run_id = _now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(sec["holding_root"]) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    state = {"version": 1, "game": game, "run_id": run_id,
             "pre": None, "texgen_deployed": None, "post": None}
    atomic_write_json(run_dir / RUN_STATE, state)
    return run_dir, state


def load_state(run_dir):
    return json.loads((Path(run_dir) / RUN_STATE).read_text(encoding="utf-8"))


def save_state(run_dir, state):
    atomic_write_json(Path(run_dir) / RUN_STATE, state)


def all_runs(holding_root):
    """[(run_dir, state), ...] sorted by dir name. A run dir whose
    lodregen-run.json is unreadable/malformed/foreign yields state=None
    instead of raising, so one corrupt run never aborts the whole listing
    (and therefore never aborts `status` for every run and game)."""
    root = Path(holding_root)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not (d.is_dir() and (d / RUN_STATE).is_file()):
            continue
        try:
            state = load_state(d)
        except (OSError, ValueError):
            out.append((d, None))
            continue
        if not isinstance(state, dict):
            out.append((d, None))
            continue
        out.append((d, state))
    return out


def pending_runs(holding_root):
    return [(d, s) for d, s in all_runs(holding_root)
            if s is not None and s.get("post") is None]


# ------------------------------------------------------------ status

def cmd_status(args, cfg=None):
    cfg = cfg if cfg is not None else config.load()
    sec = section(cfg, args.game)
    runs = all_runs(sec["holding_root"])
    if not runs:
        print(f"lodregen[{args.game}]: no regen runs recorded under "
              f"{sec['holding_root']}")
        return 0
    pending = 0
    for d, s in runs:
        if s is None:
            print(f"  {d.name}  BROKEN    unreadable lodregen-run.json -- inspect {d}")
            continue
        if s.get("post") is not None:
            print(f"  {s['run_id']}  COMPLETE  post {s['post']['stamp']}")
        elif s.get("pre") is None:
            pending += 1
            print(f"  {s['run_id']}  BROKEN    pre never finished -- inspect {d}")
        else:
            pending += 1
            tex = ("texgen deployed" if s.get("texgen_deployed")
                   else "texgen NOT deployed")
            print(f"  {s['run_id']}  PENDING   pre {s['pre']['stamp']}  ({tex})"
                  f"  -- finish with: modkit lodregen post --game {s['game']}")
    if pending:
        print(f"{pending} PENDING regen run(s): the game is mid-regen "
              f"(trio plugins held aside) -- do NOT launch it until post runs.")
        return 2
    return 0


# ------------------------------------------------------------ CLI wiring

def cmd_pre(args, cfg=None, preset=None):
    cfg = cfg if cfg is not None else config.load()
    preset = preset if preset is not None else config.game(cfg, args.game)
    sec = section(cfg, args.game)
    warnings = []

    pending = pending_runs(sec["holding_root"])
    if pending and not args.force:
        ids = ", ".join(s["run_id"] for _d, s in pending)
        print(f"REFUSED: pending regen run(s) exist: {ids}")
        print("Finish with `modkit lodregen post` (see `modkit lodregen "
              "status`), or --force to start a new bracket anyway.")
        return 1

    # game/tool-process check mirrors deploy.game_running's 3-state contract:
    # confirmed-running is a hard refusal (no --force), an unverifiable
    # tasklist warns and refuses UNLESS --force, only a clean read proceeds.
    try:
        procs = running_processes(list(preset.PROCESS_NAMES)
                                  + list(sec["tool_processes"]))
    except deploy.GameStateUnknown as ex:
        if not args.force:
            print(f"WARN: could not verify the game/tool processes are "
                  f"closed: {ex}")
            print("Rerun with --force if you are sure everything is closed.")
            return 2
        print(f"WARN: could not verify the game/tool processes are closed: "
              f"{ex}; proceeding because --force was given")
        procs = []
    if procs:
        print("REFUSED: process(es) running: " + ", ".join(procs))
        print("Close them (game AND generator GUIs) before bracketing a regen.")
        return 1

    # tool pre-flight (kills the exit-fix-relaunch loop before any GUI opens)
    tools = sec["tools"]
    need = ["texgen_exe", "dyndolod_exe"] + ([] if args.no_pgpatcher
                                             else ["pgpatcher_exe"])
    missing_tools = [k for k in need if not Path(tools[k]).is_file()]
    if missing_tools and not args.force:
        for k in missing_tools:
            print(f"REFUSED: tool exe missing: {k} = {tools[k]}")
        print("Fix modkit.json lodregen paths (or install the tool); "
              "--force to bracket anyway.")
        return 1
    warnings += [f"tool exe missing (forced past): {tools[k]}"
                 for k in missing_tools]

    ini = Path(tools["dyndolod_ini"])
    if ini.is_file():
        for line in ini.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            if line.strip().lower().startswith("wizard="):
                if line.strip().lower() != "wizard=0":
                    warnings.append(
                        f"DynDOLOD_SSE.ini has '{line.strip()}' -- Advanced "
                        f"mode (Wizard=0) is required for the Grass LOD "
                        f"checkbox")
                break
    else:
        warnings.append(f"DynDOLOD_SSE.ini not found at {ini}")

    for marker in sec["ng_markers"]:
        if not (Path(preset.DATA_DIR) / marker).is_file():
            warnings.append(f"NG/Resources marker missing under Data: {marker} "
                            f"(DLL NG / Resources install broken? no-clobber "
                            f"restore from {sec['resources_staging']})")

    diff_json = Path(preset.DATA_DIR) / "ParallaxGen_Diff.json"
    if diff_json.is_file():
        age = datetime.datetime.fromtimestamp(
            diff_json.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if args.no_pgpatcher:
            warnings.append(
                f"Data\\ParallaxGen_Diff.json present (mtime {age}) but this "
                f"is a --no-pgpatcher run -- renaming it to .bak is the "
                f"cleaner play (wiki 2026-06-21); stale entries are harmless "
                f"if left")
        else:
            warnings.append(
                f"Data\\ParallaxGen_Diff.json present (mtime {age}) -- the "
                f"PGPatcher run will regenerate it; post checks freshness")

    # ---- bracket opens: state dir, snapshot, trio down, guarded clean ----
    try:
        run_dir, state = new_run(sec, args.game)
    except FileExistsError:
        print("REFUSED: a regen run already claims this second's run-id "
              "under " + sec["holding_root"] + " -- try again in a moment.")
        return 1
    stamp = _now()
    snapshot = pluginstxt.snapshot(preset, f"lodregen-pre-{state['run_id']}")

    trio_dir = run_dir / "trio"
    trio_dir.mkdir()
    moved, absent = [], []
    for name in sec["trio"]:
        try:
            pluginstxt.disable(preset, name)
        except pluginstxt.PluginsTxtError:
            # no line at all (first-ever DynDOLOD setup: the trio plugins are
            # tool-generated and genuinely have no Plugins.txt entry yet) --
            # fold into the same absent/warning path as a missing Data file,
            # never crash mid-bracket.
            absent.append(name)
        src = Path(preset.DATA_DIR) / name
        if src.is_file():
            shutil.move(str(src), str(trio_dir / name))
            moved.append(name)
        elif name not in absent:
            absent.append(name)
    if absent:
        warnings.append("trio file(s) not in Data (first regen, or already "
                        "pulled): " + ", ".join(absent))

    clean = {"moved": [], "protected": [], "missing": [], "skipped": []}
    targets = [("dyndolod", True), ("texgen", bool(args.clean_texgen))]
    for key, do_clean in targets:
        prefix = sec["ledger_prefixes"][key]
        if not do_clean:
            clean["skipped"].append(
                f"{key}: not cleaned (wiki 2026-06-25: never pre-clean "
                f"TexGen; --clean-texgen to override)")
            continue
        entry = active_output_entry(args.game, prefix)
        if entry is None:
            warnings.append(f"no active ledger entry matching {prefix!r} -- "
                            f"skipping {key} clean (nothing manifest-tracked)")
            continue
        mpath = entry_manifest_path(args.game, entry, sec["ledger_dir"])
        if mpath is None or not mpath.is_file():
            warnings.append(f"ledger entry {entry!r} has no readable manifest "
                            f"-- skipping {key} clean")
            continue
        rep = guarded_clean(preset.DATA_DIR, read_lines_bomsafe(mpath),
                            sec["protected_inputs"], run_dir / "quarantine")
        for k in ("moved", "protected", "missing"):
            clean[k] += [f"{key}: {p}" for p in rep[k]]

    state["pre"] = {
        "stamp": stamp.isoformat(timespec="seconds"),
        "epoch": stamp.timestamp(),
        "plugins_snapshot": str(snapshot),
        "trio_moved": moved,
        "trio_absent": absent,
        "no_pgpatcher": bool(args.no_pgpatcher),
        "clean": {"quarantined": len(clean["moved"]),
                  "protected_skipped": clean["protected"],
                  "missing": clean["missing"],
                  "skipped": clean["skipped"]},
        "warnings": warnings,
    }
    save_state(run_dir, state)

    print(f"lodregen pre complete -- run {state['run_id']}  ({run_dir})")
    print(f"  Plugins.txt snapshot: {snapshot}")
    print(f"  trio pulled to {trio_dir}: {', '.join(moved) or 'none'}")
    print(f"  quarantined {len(clean['moved'])} old output file(s) -> "
          f"{run_dir / 'quarantine'}")
    for p in clean["protected"]:
        print(f"  PROTECTED (kept; the manifest is polluted -- re-author it "
              f"from actual tool output): {p}")
    for w in warnings:
        print(f"  WARN: {w}")
    print()
    print(gui_sequence(sec, args.game, args.no_pgpatcher, preset.DATA_DIR))
    return 2 if warnings else 0


def cmd_post(args, cfg=None, preset=None):
    raise LodregenError("cmd_post is implemented in Task 6 of the lodregen plan")


def register(sub):
    """Attach the lodregen subcommand tree to the modkit CLI subparsers."""
    p = sub.add_parser(
        "lodregen",
        help="pre/post guards around a manual PGPatcher->TexGen->DynDOLOD regen")
    lsub = p.add_subparsers(dest="lodregen_cmd", required=True)

    pre = lsub.add_parser(
        "pre", help="bracket start: snapshot, trio aside, guarded clean, "
                    "print the manual GUI ritual")
    pre.add_argument("--game", required=True)
    pre.add_argument("--no-pgpatcher", action="store_true",
                     help="this regen skips the PGPatcher stage")
    pre.add_argument("--clean-texgen", action="store_true",
                     help="ALSO quarantine old TexGen output (default: never "
                          "-- wiki supersede 2026-06-25: the TexGen pre-clean "
                          "was the recurring failure; the stitched warning is "
                          "harmless, click Ignore)")
    pre.add_argument("--force", action="store_true",
                     help="proceed past a pending run / missing tool exes")
    pre.set_defaults(func=cmd_pre)

    post = lsub.add_parser(
        "post", help="bracket end: freshness gate, deploy, trio re-enable, "
                     "masters verify, Plugins.txt diff, ledger record")
    post.add_argument("--game", required=True)
    post.add_argument("--stage", choices=["texgen", "full"], default="full",
                      help="'texgen' = mid-ritual TexGen_Output deploy; "
                           "'full' (default) = after DynDOLOD")
    post.add_argument("--run", help="run dir to finish (default: latest pending)")
    post.add_argument("--force", action="store_true",
                      help="proceed past freshness/masters failures (records "
                           "them as warnings)")
    post.set_defaults(func=cmd_post)

    st = lsub.add_parser("status", help="list pending/complete regen runs")
    st.add_argument("--game", required=True)
    st.set_defaults(func=cmd_status)


# ------------------------------------------------------------ clean guard

def normalize_rel(p):
    """Data-relative path -> canonical compare form: backslashes, lowercase,
    no leading separators."""
    return p.strip().lstrip("\\/").replace("/", "\\").lower()


def is_protected(rel, patterns):
    """True if a Data-relative path matches any protected-inputs pattern.
    fnmatch '*' spans path separators, so 'meshes\\dyndolod\\lod\\*mxtundra*'
    reaches files in subfolders (the wiki's non-recursive-scan trap)."""
    r = normalize_rel(rel)
    return any(fnmatch.fnmatchcase(r, normalize_rel(pat)) for pat in patterns)


def read_lines_bomsafe(path):
    """Manifest lines, BOM/CRLF tolerant, blanks dropped."""
    raw = Path(path).read_bytes().decode("utf-8-sig")
    return [x.strip() for x in raw.replace("\r\n", "\n").split("\n") if x.strip()]


def guarded_clean(data_dir, manifest_lines, patterns, quarantine_dir):
    """Quarantine (never delete) the files a manifest lists out of Data.

    Two passes. Pass 1 VALIDATES every manifest line -- wildcard/directory
    abort checks, protected-input skip, missing-file detection -- and stages
    a move plan, WITHOUT touching the filesystem. Pass 2 EXECUTES the staged
    moves, and is only reached if pass 1 finished without raising. This
    makes the whole-clean abort actually all-or-nothing: previously the loop
    moved a file to quarantine the moment it saw a valid line, so a wildcard
    or directory poison-pill line LATER in the same manifest still raised,
    but any valid line that preceded it had already been moved -- breaking
    the "wildcard/directory lines abort the whole clean -- nothing touched"
    guarantee. Now every line is checked before a single shutil.move runs.

    Guards, in order:
      * a manifest line containing a wildcard aborts the whole clean
      * a manifest line naming a directory aborts the whole clean
      * a line matching protected_inputs is SKIPPED and reported
        (polluted manifests are the recorded failure mode -- the manifest
        asked for an input's head, we refuse)
      * a line whose (normalized) path repeats an already-queued movable
        line is reported missing, same outcome the old single-pass loop
        produced for duplicate lines (the first occurrence "claims" the
        file; the repeat finds nothing left to move)
    Returns {"moved": [...], "protected": [...], "missing": [...]}.
    """
    report = {"moved": [], "protected": [], "missing": []}
    data_dir = Path(data_dir)
    quarantine_dir = Path(quarantine_dir)
    plan = []       # [(src, dst), ...] -- populated only if validation fully passes
    queued = set()  # normalized rel keys already staged to move

    # ---- pass 1: validate every line and stage the plan; no file ops ----
    for raw in manifest_lines:
        rel = raw.strip()
        if not rel:
            continue
        if any(ch in rel for ch in "*?"):
            raise LodregenError(
                f"manifest line contains a wildcard -- refusing the whole "
                f"clean (no blanket deletes): {rel}")
        src = data_dir / rel
        if src.is_dir():
            raise LodregenError(
                f"manifest line names a directory -- refusing the whole "
                f"clean (no blanket deletes): {rel}")
        if is_protected(rel, patterns):
            report["protected"].append(rel)
            continue
        key = normalize_rel(rel)
        if key in queued or not src.is_file():
            report["missing"].append(rel)
            continue
        queued.add(key)
        plan.append((src, quarantine_dir / rel))
        report["moved"].append(rel)

    # ---- pass 2: execute -- only reached once pass 1 raised nothing ----
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    return report


# ------------------------------------------------------------ processes

def running_processes(names, csv_text=None):
    """Which of `names` are live? Parses `tasklist /FO CSV /NH` (injectable
    for tests via csv_text). Raises deploy.GameStateUnknown if tasklist
    itself could not be queried (launch failure, nonzero exit, empty/
    unusable output) -- mirrors deploy.game_running's 3-state contract:
    callers must NOT treat "could not verify" as "nothing running"."""
    if csv_text is None:
        try:
            p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except OSError as ex:
            raise deploy.GameStateUnknown(str(ex)) from ex
        if p.returncode != 0:
            raise deploy.GameStateUnknown(
                f"tasklist exited {p.returncode}: "
                f"{(p.stderr or '').strip()[:200]}")
        csv_text = p.stdout or ""
        if not csv_text.strip():
            raise deploy.GameStateUnknown("tasklist produced no output")
    live = set()
    for line in csv_text.splitlines():
        if line.startswith('"'):
            live.add(line.split('","')[0].strip('"').lower())
    return [n for n in names if n.lower() in live]


# ------------------------------------------------------------ ledger lookups

def active_output_entry(game, prefix):
    """Name of the active ledger entry for an output family, or None.
    Matches `<prefix>` exactly or the dated form `<prefix> (regen ...)`.
    ledger.py `list` prints `_entry_line` fields joined by two spaces, so
    the name is everything before the first double-space."""
    rc, out = ledger_bridge.run(["list", "--active", "--game", game])
    if rc != 0:
        return None
    for line in out.splitlines():
        name = line.split("  ", 1)[0].strip()
        if name == prefix or name.startswith(prefix + " ("):
            return name
    return None


def entry_manifest_path(game, name, ledger_dir):
    """Absolute path of an entry's manifest file (ledger.py `get` prints the
    entry as JSON; the `manifest` field is relative to the ledger dir)."""
    rc, out = ledger_bridge.run(["get", "--game", game, "--name", name])
    if rc != 0:
        return None
    ptr = json.loads(out).get("manifest")
    return (Path(ledger_dir) / ptr) if ptr else None


# ------------------------------------------------------------ plugin lines

def enabled_plugins(lines):
    """Lowercased enabled plugin names, in order, from pluginstxt.read()
    lines ('*' prefix = enabled; SSE Plugins.txt convention). Pulled forward
    from Task 5 (verbatim) because Task 4's own tests need it -- lodregen
    never writes Plugins.txt lines itself, only reads via this helper."""
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("*"):
            out.append(s[1:].strip().lower())
    return out


# ------------------------------------------------------------ GUI ritual

def gui_sequence(sec, game, no_pgpatcher, data_dir):
    t = sec["tools"]
    lines = [
        "=== MANUAL GUI SESSION -- Claude must NEVER launch, drive, click, or",
        "    screenshot these tools. Config-file-first; the USER double-clicks",
        "    each exe (program-launched windows can open off-screen -- wiki",
        "    2026-06-28). Verify disk artifacts after every GUI run. ===",
        "",
    ]
    step = 1
    if not no_pgpatcher:
        lines += [
            f"{step}) PGPatcher -- USER launches: {t['pgpatcher_exe']}",
            "   - Before Start: check <PGPatcher>\\cfg\\settings.json -- output dir",
            "     OUTSIDE Data, Mod Manager = None, no leading TAB in the output",
            "     path (wiki 2026-06-20 gotcha).",
            "   - The 'DynDOLOD and TexGen outputs must be disabled' abort cannot",
            "     fire now (pre pulled the trio).",
            "   - Abort 'PGPatcher meshes exist in your data directory' = an old",
            "     bake is still deployed. STOP -- that is per-mesh-revert",
            "     territory (runbook), never bulk-delete baked meshes.",
            "   - When it finishes, deploy the output into Data BEFORE TexGen:",
            f"     robocopy \"{sec['outputs']['pgpatcher']}\" \"{data_dir}\" /E",
            "     (robocopy exit <8 = success)",
            "",
        ]
        step += 1
    lines += [
        f"{step}) TexGen -- USER launches: {t['texgen_exe']}",
        "   - 'Found stitched object LOD textures ... installed in game folder'",
        "     warning -> click IGNORE. It is HARMLESS; TexGen overwrites its own",
        "     output. NEVER pre-clean to silence it (the cleaning WAS the",
        "     recurring failure -- wiki supersede 2026-06-25).",
        f"   - When TexGen exits, run:  modkit lodregen post --game {game} --stage texgen",
        "     (freshness-gates + deploys TexGen_Output; DynDOLOD must read the",
        "      DEPLOYED textures, not the output folder)",
        "",
        f"{step + 1}) DynDOLOD -- USER launches: {t['dyndolod_exe']}",
        "   - Advanced mode (pre checked Wizard=0). Select ALL worldspaces --",
        "     the selection can RESET between runs (wiki gotcha).",
        "   - Grass LOD: tick it and set Grass LOD Mode to MATCH GrassControl.ini",
        "     (this build: Mode 1; a mismatch or GUI-left-at-0 = no/seamed grass",
        "     LOD). Hover the checkbox to confirm it found the .cgid cache.",
        "   - 'Deleted large references found' hard-stop = DLC masters need",
        "     xEdit QuickAutoClean copies restored (runbook).",
        f"   - When DynDOLOD exits, run:  modkit lodregen post --game {game}",
        "     (freshness gate, masters verify, deploy, trio re-enable",
        "      esm -> esp -> Occlusion LAST, Plugins.txt diff, ledger record)",
    ]
    return "\n".join(lines)
