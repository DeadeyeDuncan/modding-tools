"""Deploy engine. Only deploy and remove touch game dirs.
robocopy exit codes < 8 are SUCCESS (>= 8 raises). Ledger writes go through
ledger.py exclusively (its validation + backups apply)."""
import datetime
import json
import shutil
import subprocess
from pathlib import Path

from modkit import ledger_bridge, pluginstxt, state, tes4


class DeployError(Exception):
    """robocopy >= 8 or other hard deploy failure."""


class GameStateUnknown(Exception):
    """tasklist could not be run or returned an unusable result - whether the
    game is running is unverifiable (distinct from confirmed-not-running)."""


def game_running(preset):
    """True if any PROCESS_NAMES appears in tasklist output, False if tasklist
    ran cleanly and found none. Raises GameStateUnknown if tasklist itself
    could not be queried (launch failure, nonzero exit, empty/unusable output) -
    callers must NOT treat that as "not running"."""
    try:
        proc = subprocess.run(["tasklist"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as ex:
        raise GameStateUnknown(str(ex)) from ex
    if proc.returncode != 0:
        raise GameStateUnknown(f"tasklist exited {proc.returncode}: "
                               f"{(proc.stderr or '').strip()[:200]}")
    out = proc.stdout.lower()
    if not out.strip():
        raise GameStateUnknown("tasklist produced no output")
    return any(p.lower() in out for p in preset.PROCESS_NAMES)


def robocopy(src, dest):
    """Copy tree src -> dest. Returns the exit code; raises only when >= 8."""
    proc = subprocess.run(
        ["robocopy", str(src), str(dest), "/E", "/NJH", "/NJS", "/NDL", "/NFL"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode >= 8:
        raise DeployError(f"robocopy failed (exit {proc.returncode}):\n"
                          f"{(proc.stdout or '')[-2000:]}{(proc.stderr or '')[-2000:]}")
    return proc.returncode


def payload_files(pay_root):
    """Data-relative backslash paths of every file under the deploy root."""
    pay_root = Path(pay_root)
    return sorted(str(f.relative_to(pay_root)).replace("/", "\\")
                  for f in pay_root.rglob("*") if f.is_file())


def data_root(preset, pay_root):
    """If the payload's only top-level entry is a Data\\ dir, deploy from inside
    it (the Data\\-prefix bug class, fixed 2026-07-04 in the manifests)."""
    pay_root = Path(pay_root)
    tops = list(pay_root.iterdir())
    if len(tops) == 1 and tops[0].is_dir() and tops[0].name.lower() == "data":
        return tops[0]
    return pay_root


def run_deploy(preset, staging_dir, anchor, force, log):
    st = state.InstallState.load(str(staging_dir))
    if preset.DATA_DIR is None:
        log(f"ERROR: game {preset.NAME!r} has no data_dir configured - "
            "deploy unsupported for this preset")
        return 1
    try:
        running = game_running(preset)
    except GameStateUnknown as ex:
        if not force:
            log(f"WARN: could not verify the game is closed: {ex}; "
                "rerun with --force if you are sure it is closed")
            return 2
        log(f"WARN: could not verify the game is closed: {ex}; "
            "proceeding because --force was given")
        running = False
    if running:
        log(f"ERROR: game process running ({', '.join(preset.PROCESS_NAMES)}) - "
            "close it first (this gate has no --force)")
        return 1
    missing = st.missing_applicable()
    if missing and not force:
        for m in missing:
            log(f"WARN vet stage not run: {m}  (modkit {m} --game {preset.NAME} "
                f"--staging {staging_dir})")
        log("deploy REFUSED pending vets - re-run with --force to deploy anyway")
        return 2
    pay = data_root(preset, state.payload_root(staging_dir))
    files = payload_files(pay)
    if not files:
        log("ERROR: payload is empty - nothing to deploy")
        return 1
    rc = robocopy(pay, preset.DATA_DIR)
    log(f"robocopy exit {rc} (<8 = success): {len(files)} files -> {preset.DATA_DIR}")
    st.data["files"] = files
    st.stamp("deployed")
    plugin_exts = tuple(getattr(preset, "PLUGIN_EXTS", ()) or ())
    plugins = [f for f in files
               if "\\" not in f and f.lower().endswith(plugin_exts)] if plugin_exts else []
    for p in plugins:
        try:
            pluginstxt.enable(preset, p, anchor)
        except pluginstxt.PluginsTxtError as ex:
            log(f"ERROR: Plugins.txt enable failed for {p!r}: {ex}")
            log("files ARE already copied to Data\\ - fix the cause and re-run "
                "`modkit deploy` (robocopy is additive and enable is idempotent, "
                "so re-running is safe)")
            return 1
        log(f"enabled in Plugins.txt: {p}" + (f" (after {anchor})" if anchor else ""))
    listfile = Path(staging_dir) / "staged-files.txt"
    listfile.write_text("\n".join(files) + "\n", encoding="utf-8")
    add_args = ["add", "--name", st.data["mod"], "--files-from", str(listfile),
                *ledger_bridge.game_args(preset)]
    if st.data.get("nexusId"):
        add_args += ["--nexus-id", str(st.data["nexusId"])]
    if st.data.get("version"):
        add_args += ["--version", st.data["version"]]
    add_args += ["--source", Path(st.data["archive"]).name]
    for p in plugins:
        add_args += ["--plugin", p]
    code, out = ledger_bridge.run(add_args)
    if code != 0:
        log(f"ERROR: ledger add failed (exit {code}):\n{out.strip()}")
        log("files ARE in Data but UNRECORDED - fix the ledger entry via "
            "ledger.py add/update, then run `modkit verify`")
        return 1
    log(out.strip())
    st.stamp("recorded")
    return 0


def run_remove(preset, mod_name, reason, force, log):
    if preset.DATA_DIR is None:
        log(f"ERROR: game {preset.NAME!r} has no data_dir - remove unsupported")
        return 1
    if game_running(preset):
        log(f"ERROR: game process running ({', '.join(preset.PROCESS_NAMES)}) - "
            "close it first (this gate has no --force)")
        return 1
    code, out = ledger_bridge.run(["get", "--name", mod_name,
                                   *ledger_bridge.game_args(preset)])
    if code != 0:
        log(f"ERROR: ledger get failed (exit {code}): {out.strip()}")
        return 1
    entry = json.loads(out)
    if entry.get("removed"):
        log(f"ERROR: {entry['name']!r} already removed on {entry['removed']}")
        return 1
    manifest = entry.get("manifest")
    if not manifest:
        log("ERROR: ledger entry has no manifest pointer - manifest-driven removal "
            "impossible. Quarantine by hand, then `ledger.py remove --reason ...`")
        return 1
    mpath = Path(preset.MANIFESTS_DIR).parent / manifest
    if not mpath.is_file():
        log(f"ERROR: manifest file missing: {mpath}")
        return 1
    raw = mpath.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    paths = [l.strip() for l in raw.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    plugins = entry.get("plugin")
    plugins = [plugins] if isinstance(plugins, str) else list(plugins or [])
    dependents = []
    if plugins and preset.PLUGINS_TXT:
        ours = {p.lower() for p in plugins}
        data_dir = Path(preset.DATA_DIR)
        for line in pluginstxt.read(preset):
            if not line.startswith("*"):
                continue
            name = line.lstrip("*").strip()
            if name.lower() in ours or not (data_dir / name).is_file():
                continue
            try:
                hdr = tes4.parse_header(data_dir / name)
            except tes4.Tes4Error:
                continue
            hits = [m for m in hdr["masters"] if m.lower() in ours]
            if hits:
                dependents.append((name, hits))
    if dependents and not force:
        for name, hits in dependents:
            log(f"WARN {name} masters {', '.join(hits)} - removing would CTD it")
        log("remove REFUSED (master dependencies) - re-run with --force to override")
        return 2
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    qdir = Path(preset.BACKUPS_DIR) / f"removed-{state.slug(mod_name)}-{ts}"
    data_dir = Path(preset.DATA_DIR)
    moved, absent = 0, []
    for rel in paths:
        rel2 = rel[5:] if rel.lower().startswith("data\\") else rel
        src = data_dir / rel2
        if not src.is_file():
            absent.append(rel2)
            continue
        dest = qdir / rel2
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved += 1
    log(f"quarantined {moved}/{len(paths)} manifest files -> {qdir}")
    for a in absent[:20]:
        log(f"  already absent: {a} (overwritten by a later mod, or drift)")
    for p in plugins:
        try:
            pluginstxt.disable(preset, p)
            log(f"disabled in Plugins.txt: {p}")
        except pluginstxt.PluginsTxtError as ex:
            log(f"  note: {ex}")
    code, out = ledger_bridge.run(["remove", "--name", mod_name, "--reason", reason,
                                   "--to", str(qdir), *ledger_bridge.game_args(preset)])
    if code != 0:
        log(f"ERROR: ledger remove failed (exit {code}):\n{out.strip()}")
        log(f"files ARE quarantined at {qdir} - run ledger.py remove manually")
        return 1
    log(out.strip())
    log(f"count reconciled: {moved} moved, {len(absent)} already absent, "
        f"{len(paths)} in manifest")
    return 0
