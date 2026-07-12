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
    raise LodregenError("cmd_pre is implemented in Task 4 of the lodregen plan")


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
