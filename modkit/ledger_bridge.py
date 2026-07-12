"""Subprocess wrapper around ledger.py - the SOLE ledger/manifest writer.
modkit never writes ledger.json or manifests\\ itself; ledger.py's own
validation, backups, and atomic writes therefore always apply."""
import os
import subprocess
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "ledger.py"


def run(args):
    """Run `ledger.py <args>` with this interpreter. Returns (exit_code, output).
    MODKIT_LEDGER env overrides the script path (tests may stub it)."""
    script = Path(os.environ.get("MODKIT_LEDGER") or LEDGER)
    proc = subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def game_args(preset):
    """Ledger game-selection args. A preset with LEDGER set (fixture configs)
    bypasses ledger.py's baked-in game->path map via --ledger."""
    if getattr(preset, "LEDGER", None):
        return ["--ledger", str(preset.LEDGER)]
    return ["--game", preset.NAME]
