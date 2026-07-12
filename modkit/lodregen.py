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

from modkit import config, ledger_bridge, pluginstxt


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
