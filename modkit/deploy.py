"""Deploy engine. Only deploy and remove touch game dirs.
robocopy exit codes < 8 are SUCCESS (>= 8 raises). Ledger writes go through
ledger.py exclusively (its validation + backups apply)."""
import subprocess
from pathlib import Path

from modkit import ledger_bridge, pluginstxt, state


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
