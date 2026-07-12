# modkit lodregen — LOD/Bake Regen Guard Scripts: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `modkit lodregen pre|post|status` — mechanical pre/post brackets around the manual Skyrim LOD/bake regen ritual (PGPatcher → TexGen → DynDOLOD), so the GUI runs stay with the user but every known trap (input-deleting pre-cleans, forgotten trio handling, stale/empty outputs, armed missing-master CTDs, invisible interrupted regens) is guarded by code.

**Architecture:** One new subcommand package module `modkit\lodregen.py` added to the existing modkit CLI (argparse `register(sub)` pattern). `pre` snapshots Plugins.txt, pulls the DynDOLOD trio plugin *files* out of Data into a timestamped holding dir, runs a manifest-driven quarantine clean guarded by a protected-inputs list, runs tool pre-flight checks, and prints the exact manual GUI sequence. `post --stage texgen` freshness-gates and deploys TexGen output mid-ritual; `post` (full) freshness-gates DynDOLOD output, verifies the new trio's TES4 masters BEFORE enabling anything, deploys, re-enables the trio Occlusion-last, diffs Plugins.txt against the pre snapshot, and records the regen in the ledger via ledger.py. A `lodregen-run.json` state file in the holding dir makes interrupted regens visible via `status`.

**Tech Stack:** Python 3.13 stdlib only. External processes: `robocopy`, `tasklist`, and `py -3 C:\Modding\tools\ledger.py` (via `modkit.ledger_bridge`). pytest for tests.

**DEPENDENCY:** This plan builds ON TOP of the modkit core plan (`docs\2026-07-11-modkit-plan.md`). **modkit core Tasks 1–2 and 9 must be complete first** (package scaffold + `modkit.config` loader/presets + CLI dispatch, and the `modkit.pluginstxt` manager + `modkit.ledger_bridge`). Do not start this plan until those tasks are merged.

## Dependency contract (consume these interfaces VERBATIM — do not invent others)

- `modkit.config.load() -> dict`
- `modkit.config.game(cfg, "skyrim") -> preset` with attrs `DATA_DIR`, `PLUGINS_TXT`, `PROCESS_NAMES`, `RUNTIME`, `STAGING_ROOT`, `BACKUPS_DIR`
- `modkit.pluginstxt.read(preset) -> list[str]`
- `modkit.pluginstxt.snapshot(preset, tag) -> backup path`
- `modkit.pluginstxt.diff(a, b) -> report str`
- `modkit.pluginstxt.enable(preset, plugin, anchor)` / `modkit.pluginstxt.disable(preset, plugin)`
- `modkit.ledger_bridge.run(args) -> (rc, stdout)`

Documented assumptions where the contract is silent (each one is VERIFIED at runtime rather than trusted):

1. `pluginstxt.read` returns the file's lines verbatim; enabled plugins are lines starting with `*` (standard SSE Plugins.txt). lodregen's `enabled_plugins()` helper strips the `*`; it never writes lines itself.
2. `pluginstxt.enable(preset, plugin, anchor)` inserts the enabled line after `anchor` (case-insensitive), or appends at end of file when `anchor is None`. **post does not trust this:** after enabling the trio it re-reads Plugins.txt and hard-fails unless the last three enabled plugins are exactly `DynDOLOD.esm, DynDOLOD.esp, Occlusion.esp` in that order.
3. `modkit.tes4` is NOT part of the dependency contract and `docs\2026-07-11-modkit-plan.md` did not exist when this plan was written (only the design doc `docs\2026-07-11-modkit-design.md`, which merely lists `tes4.py` as a planned module). **Therefore lodregen parses TES4 `MAST` subrecords inline** (Task 5, ~35 lines). If the core build has shipped `modkit.tes4` with a masters function by execution time, the executor MAY swap the inline parser for it in Task 5 — but only if its output is a plain list of master filename strings; otherwise keep the inline parser.

## Ground truth (wiki `concepts/skyrim-dyndolod-generation` + `concepts/skyrim-pgpatcher`, updated 2026-06-28/07-01 — newer than reflection-notes and authoritative)

- **Trio plugin names:** `DynDOLOD.esm`, `DynDOLOD.esp`, `Occlusion.esp`. Re-enable order: **`DynDOLOD.esm` → `DynDOLOD.esp` → `Occlusion.esp`, with Occlusion.esp the absolute last plugin** (per dyndolod.info/Help/Occlusion-Data; the wiki explicitly corrected an earlier reversed order).
- **Ritual sequence:** disable+pull trio → PGPatcher (writes `ParallaxGen_Diff.json` + patched meshes) → deploy PGPatcher output into Data → TexGen → **deploy TexGen_Output into Data** → DynDOLOD (reads the deployed textures + the diff, CRC32-matches LOD) → deploy DynDOLOD_Output → re-enable trio last. PGPatcher MUST run with the trio disabled (an active DynDOLOD.esp corrupts its CRC32 matching), and DynDOLOD reads `ParallaxGen_Diff.json`, so PGPatcher must be first.
- **"From scratch" requires the trio plugin FILES pulled out of Data, not just disabled** — DynDOLOD errors `"DynDOLOD.esp already exists. Either activate it for updating or remove it to generate from scratch."`
- **The clean trap (9 tallied occurrences):** `textures\DynDOLOD\lod\` and `meshes\DynDOLOD\lod\` mix Resources REQUIRED INPUT with regenerable output. Protected inputs: `dyndolodtreelod*`, `dyndolodbackgroundtreelod*`, `holycow*`, `version.ini`, `defaultdiffuse.dds`, `TexGen_SSE.ini`, `mxtundra*_dyndolod_lod.nif` (the 7 mxtundra meshes live in SUBFOLDERS — a non-recursive scan misses them). The trap extends to output manifests polluted with custom/audit stand-ins (`statics_e.dds`, `landscape\statics\rocks01*`) — cleaning off a polluted manifest deleted real assets → blue/purple collateral. Rules: clean ONLY via output-only manifests, never blanket-delete those folders, keep a protected list, no-clobber restore from the Resources staging (`C:\Modding\tmp\dyndolod-resources`) if in doubt.
- **TexGen is NEVER pre-cleaned.** The `"Found stitched object LOD textures … installed in game folder"` warning is HARMLESS — click Ignore; TexGen overwrites its own output. The wiki explicitly superseded its own earlier "clean first" advice: the *cleaning* was the cause of every "Required resource file not found" abort.
- **Outputs are NOT auto-installed.** TexGen → `TexGen_Output`, DynDOLOD → `DynDOLOD_Output` (contains the trio plugins + meshes/textures), PGPatcher → its configured output dir outside Data. Each must be copied into Data before the next consumer reads it.
- **Masters verify:** a naive regex over the TES4 header OVER-REPORTS (flags the implicit base ESMs Skyrim/Update/Dawnguard/HearthFires/Dragonborn — never listed in Plugins.txt but always loaded — plus the author field). A proper `MAST`-subrecord walk excluding implicit ESMs / `_ResourcePack*` / `cc*` is required.
- **GUI convention:** config-file-first; the USER double-clicks the exe (program-launched DynDOLOD windows have opened off-screen/unclickable); never drive or screenshot a handed-off GUI; verify disk artifacts after every GUI run. DynDOLOD gotchas: worldspace selection can reset (pick all), Grass LOD Mode must match `GrassControl.ini` (Mode 1 on this build), "Deleted large references found" hard-stop means the DLC masters need xEdit QuickAutoClean.
- **Tool paths on this machine:** `C:\Modding\DynDOLOD\DynDOLOD\TexGenx64.exe`, `C:\Modding\DynDOLOD\DynDOLOD\DynDOLODx64.exe`, ini at `C:\Modding\DynDOLOD\DynDOLOD\Edit Scripts\DynDOLOD\DynDOLOD_SSE.ini` (Wizard=0 required for the Grass LOD checkbox). Historical healthy output sizes: TexGen ~1600–1750 files, DynDOLOD ~4450–5200 files.

## Wiki vs reflection-notes conflicts (wiki is newer — wiki wins; noted per instruction)

1. **TexGen pre-clean.** Reflection §8 frames the regen pre-clean as a step to guard for all outputs. The wiki (2026-06-25 supersede) says the TexGen pre-clean should not happen AT ALL — it was the root cause, and the warning it silenced is harmless. → Plan: `pre` cleans only the old DynDOLOD output (manifest-driven, guarded); TexGen clean is OFF by default behind `--clean-texgen`, which still runs the same guard.
2. **Trio ordering.** The grass-plan memory lists the trio as "DynDOLOD.esm/Occlusion.esp/DynDOLOD.esp" (listing order) and an early wiki revision had the tail reversed. The wiki's standing correction: `DynDOLOD.esm → DynDOLOD.esp → Occlusion.esp`, Occlusion absolute last. → Plan hardcodes that order in config and verifies the tail after enable.
3. **Trio "down" semantics.** Reflection §8 says "trio down"; the wiki is stricter: for a from-scratch regen the plugin FILES must leave Data, disabling lines is not enough. → Plan does both (disable lines + move files to the holding dir).

## Reflection §8 trap → guard map (every tallied trap has a specific coded guard)

| §8 evidence | Guard | Task |
|---|---|---|
| Pre-clean deleted required INPUT files 3× (Resources tree-LOD, `statics_e` cubemap, rock textures) | `protected_inputs` patterns + `guarded_clean()` skips & reports protected paths; manifest-only file-by-file quarantine; hard refusal on wildcard/directory manifest lines (no blanket deletes possible) | 3, wired in 4 |
| Trio down/up ritual hand-orchestrated 5+ | `pre` = one command (disable lines + pull files); `post` re-enables esm→esp→Occlusion-last and verifies the tail | 4, 6 |
| Trio-down forgotten once | The printed GUI sequence only appears after `pre` has already pulled the trio; PGPatcher's own "outputs must be disabled" abort can no longer fire | 4 |
| Post-reboot Plugins.txt rewrite armed a missing-master CTD | `post` parses the new trio's TES4 masters and hard-fails BEFORE enabling anything; Plugins.txt diff vs the pre snapshot printed and saved | 5, 6 |
| Empty TexGen exit / stale outputs (§10 disk-artifact rule) | Freshness gate: output newer than the pre timestamp, minimum file counts, trio files present in DynDOLOD_Output, fresh `ParallaxGen_Diff.json` when PGPatcher ran | 6 |
| ~6 exit-fix-relaunch pre-flight gates in two runs | `pre` checks exes exist, `DynDOLOD_SSE.ini` Wizard=0, NG/Resources markers present — all before any GUI launch | 4 |
| GUI driving dead end (§10) | No code path launches a GUI; `pre` prints the handoff script; runbook encodes config-file-first | 4, 7 |
| Interrupted regen invisible / half-state undetected | `lodregen-run.json` per run; `status` lists pending runs and exits 2; `pre` refuses to start while one is pending | 2, 4 |

## Global Constraints

- **Python 3.13, stdlib only** (ledger.py/modkit precedent). External processes: `robocopy`, `tasklist`, ledger.py via `modkit.ledger_bridge` only.
- **Tests never touch real game dirs** — every path comes from a fixture `modkit.json`-shaped dict + `tmp_path`; presets in tests are `SimpleNamespace` stand-ins with the contract attrs.
- **Atomic writes** for all state files (temp file + `os.replace`).
- **BOM/CRLF-safe Plugins.txt handling via `modkit.pluginstxt` ONLY — never reimplement.** lodregen never opens Plugins.txt itself.
- **GUI tools are NEVER driven programmatically** — pre/post bracket a manual GUI session; the user launches every exe.
- **robocopy exit < 8 = success** (exit codes 1–7 are informational).
- **Quarantine, never delete.** Cleans move files into the run's holding dir; trio files are moved, not deleted.
- Config paths live in `modkit.json`, not in code (SSD/multi-machine portability).
- One commit per task, conventional commits, TDD throughout.
- Repo root for all commands: `C:\Modding\tools`. Test runner: `py -3 -m pytest`.

## File structure

- Create: `C:\Modding\tools\modkit\lodregen.py` — the whole subcommand (config section access, run state, guarded clean, TES4 masters parse, pre/post/status).
- Modify: `C:\Modding\tools\modkit.json` — add the `"lodregen"` section (schema below).
- Modify: `C:\Modding\tools\modkit\cli.py` — register the subcommand (one import + one call).
- Create: `C:\Modding\tools\docs\runbooks\lod-regen-runbook.md` — the human/Claude ritual runbook.
- Create: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` — the full test suite.

## `modkit.json` `"lodregen"` section schema

Per-game object under `"lodregen"`. All keys required unless marked optional. Exact JSON added in Task 1.

| Key | Type | Meaning |
|---|---|---|
| `holding_root` | str | Root for timestamped run dirs (`<holding_root>\<YYYYMMDD-HHMMSS>\` holds `lodregen-run.json`, `trio\`, `quarantine\`, deploy lists, diff report) |
| `ledger_dir` | str | Directory containing `ledger.json` (manifest pointers like `manifests\X.txt` resolve relative to it) |
| `trio` | list[3] | Exactly `["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"]` — order IS the re-enable order, last entry loads absolute last |
| `tool_processes` | list | Generator process names that must not be running (`PGPatcher.exe`, `TexGenx64.exe`, `DynDOLODx64.exe`) |
| `tools` | object | `pgpatcher_exe`, `texgen_exe`, `dyndolod_exe`, `dyndolod_ini` — absolute paths |
| `outputs` | object | `pgpatcher`, `texgen`, `dyndolod` — the tools' output dirs (all OUTSIDE Data) |
| `min_output_files` | object | `texgen`, `dyndolod` — freshness-gate floors (healthy runs: ~1600–1750 / ~4450–5200) |
| `ledger_prefixes` | object | `texgen`, `dyndolod` — ledger entry-name prefixes for the deployed outputs (e.g. `"DynDOLOD Output"`; dated entries are `"<prefix> (regen <run_id>)"`) |
| `ng_markers` | list | Data-relative files whose absence means the DynDOLOD DLL NG / Resources install is broken (checked by `pre`) |
| `protected_inputs` | list | Case-insensitive fnmatch patterns (backslash paths, `*` spans separators) of Data-relative files the clean must NEVER touch |
| `resources_staging` | str | DynDOLOD Resources staging copy for no-clobber restores (printed in guidance when a protected hit occurs) |

---

### Task 1: Config section + schema

**Files:**
- Create: `C:\Modding\tools\modkit\lodregen.py`
- Modify: `C:\Modding\tools\modkit.json`
- Create: `C:\Modding\tools\tests\test_modkit\test_lodregen.py`

**Interfaces:**
- Consumes: nothing from core yet (pure dict access).
- Produces: `lodregen.section(cfg: dict, game: str) -> dict` (validated lodregen config for a game), `lodregen.LodregenError`, and the test fixture builder `fixture_section(tmp_path)` later tasks reuse.

- [ ] **Step 1: Write the failing tests**

Create `C:\Modding\tools\tests\test_modkit\test_lodregen.py`:

```python
"""Tests for modkit lodregen. No test touches a real game dir: every path is
built under tmp_path and injected via a fixture config dict + SimpleNamespace
preset carrying the modkit core preset attrs."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from modkit import lodregen


# ---------------------------------------------------------------- fixtures

def fixture_section(tmp_path):
    """A complete lodregen.skyrim config section rooted under tmp_path."""
    return {
        "holding_root": str(tmp_path / "holding"),
        "ledger_dir": str(tmp_path / "ledgerdir"),
        "trio": ["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"],
        "tool_processes": ["PGPatcher.exe", "TexGenx64.exe", "DynDOLODx64.exe"],
        "tools": {
            "pgpatcher_exe": str(tmp_path / "tools" / "PGPatcher.exe"),
            "texgen_exe": str(tmp_path / "tools" / "TexGenx64.exe"),
            "dyndolod_exe": str(tmp_path / "tools" / "DynDOLODx64.exe"),
            "dyndolod_ini": str(tmp_path / "tools" / "DynDOLOD_SSE.ini"),
        },
        "outputs": {
            "pgpatcher": str(tmp_path / "PGPatcher-Output"),
            "texgen": str(tmp_path / "TexGen_Output"),
            "dyndolod": str(tmp_path / "DynDOLOD_Output"),
        },
        "min_output_files": {"texgen": 3, "dyndolod": 5},
        "ledger_prefixes": {"texgen": "TexGen Output", "dyndolod": "DynDOLOD Output"},
        "ng_markers": ["SKSE\\Plugins\\DynDOLOD.DLL",
                       "textures\\DynDOLOD\\lod\\version.ini"],
        "protected_inputs": [
            "textures\\dyndolod\\lod\\dyndolodtreelod*",
            "textures\\dyndolod\\lod\\dyndolodbackgroundtreelod*",
            "textures\\dyndolod\\lod\\version.ini",
            "textures\\dyndolod\\lod\\defaultdiffuse*",
            "textures\\dyndolod\\lod\\texgen_sse.ini",
            "meshes\\dyndolod\\lod\\*holycow*",
            "meshes\\dyndolod\\lod\\*mxtundra*_dyndolod_lod.nif",
            "*statics_e.dds",
            "*landscape\\statics\\rocks01*",
        ],
        "resources_staging": str(tmp_path / "dyndolod-resources"),
    }


def fixture_cfg(tmp_path):
    return {"lodregen": {"skyrim": fixture_section(tmp_path)}}


# ---------------------------------------------------------------- Task 1

def test_section_returns_game_config(tmp_path):
    cfg = fixture_cfg(tmp_path)
    sec = lodregen.section(cfg, "skyrim")
    assert sec["trio"] == ["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"]
    assert sec["ledger_prefixes"]["dyndolod"] == "DynDOLOD Output"


def test_section_missing_game_raises(tmp_path):
    with pytest.raises(lodregen.LodregenError, match="no lodregen section"):
        lodregen.section({"lodregen": {}}, "skyrim")
    with pytest.raises(lodregen.LodregenError, match="no lodregen section"):
        lodregen.section({}, "skyrim")


def test_section_missing_keys_raises(tmp_path):
    cfg = fixture_cfg(tmp_path)
    del cfg["lodregen"]["skyrim"]["protected_inputs"]
    with pytest.raises(lodregen.LodregenError, match="protected_inputs"):
        lodregen.section(cfg, "skyrim")


def test_section_rejects_wrong_trio_shape(tmp_path):
    cfg = fixture_cfg(tmp_path)
    cfg["lodregen"]["skyrim"]["trio"] = ["DynDOLOD.esm", "Occlusion.esp"]
    with pytest.raises(lodregen.LodregenError, match="exactly 3"):
        lodregen.section(cfg, "skyrim")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: FAIL/ERROR at collection — `ImportError: cannot import name 'lodregen' from 'modkit'` (module does not exist yet).

- [ ] **Step 3: Create `modkit\lodregen.py` with the section loader**

Create `C:\Modding\tools\modkit\lodregen.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `4 passed`

- [ ] **Step 5: Add the real `lodregen` section to `modkit.json`**

Edit `C:\Modding\tools\modkit.json` (created by modkit core Task 1) and add this top-level key alongside the existing ones (adjust nothing else). These are the real machine paths from the wiki/memory record:

```json
"lodregen": {
  "skyrim": {
    "holding_root": "C:\\Modding\\skyrim-manual\\backups\\lodregen",
    "ledger_dir": "C:\\Modding\\skyrim-manual",
    "trio": ["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"],
    "tool_processes": ["PGPatcher.exe", "TexGenx64.exe", "DynDOLODx64.exe"],
    "tools": {
      "pgpatcher_exe": "C:\\Modding\\PGPatcher\\PGPatcher.exe",
      "texgen_exe": "C:\\Modding\\DynDOLOD\\DynDOLOD\\TexGenx64.exe",
      "dyndolod_exe": "C:\\Modding\\DynDOLOD\\DynDOLOD\\DynDOLODx64.exe",
      "dyndolod_ini": "C:\\Modding\\DynDOLOD\\DynDOLOD\\Edit Scripts\\DynDOLOD\\DynDOLOD_SSE.ini"
    },
    "outputs": {
      "pgpatcher": "C:\\Modding\\PGPatcher\\PGPatcher-Output",
      "texgen": "C:\\Modding\\DynDOLOD\\TexGen_Output",
      "dyndolod": "C:\\Modding\\DynDOLOD\\DynDOLOD_Output"
    },
    "min_output_files": {"texgen": 1000, "dyndolod": 3000},
    "ledger_prefixes": {"texgen": "TexGen Output", "dyndolod": "DynDOLOD Output"},
    "ng_markers": [
      "SKSE\\Plugins\\DynDOLOD.DLL",
      "textures\\DynDOLOD\\lod\\version.ini"
    ],
    "protected_inputs": [
      "textures\\dyndolod\\lod\\dyndolodtreelod*",
      "textures\\dyndolod\\lod\\dyndolodbackgroundtreelod*",
      "textures\\dyndolod\\lod\\version.ini",
      "textures\\dyndolod\\lod\\defaultdiffuse*",
      "textures\\dyndolod\\lod\\texgen_sse.ini",
      "meshes\\dyndolod\\lod\\*holycow*",
      "meshes\\dyndolod\\lod\\*mxtundra*_dyndolod_lod.nif",
      "*statics_e.dds",
      "*landscape\\statics\\rocks01*"
    ],
    "resources_staging": "C:\\Modding\\tmp\\dyndolod-resources"
  }
}
```

Notes for the executor (config data, not code): the exe/output paths match the recorded tool locations (`C:\Modding\DynDOLOD`, wiki + sse-dyndolod-rerun-rule memory); the PGPatcher dir and the two `ng_markers` should be eyeballed against the live disk / the `DynDOLOD DLL NG` ledger manifest on first real use and corrected IN modkit.json if they differ — the checks that consume them only test existence, so a wrong path shows up as one clear WARN line, never a crash.

Validate the file still parses: `py -3 -c "import json; json.load(open(r'C:\Modding\tools\modkit.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py modkit.json tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): config section loader + machine config schema"
```

---

### Task 2: Run state (`lodregen-run.json`) + `status` subcommand + CLI wiring

**Files:**
- Modify: `C:\Modding\tools\modkit\lodregen.py` (append)
- Modify: `C:\Modding\tools\modkit\cli.py` (register the subcommand)
- Test: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` (append)

**Interfaces:**
- Consumes: `lodregen.section` (Task 1).
- Produces: `new_run(sec, game) -> (run_dir: Path, state: dict)`, `load_state(run_dir) -> dict`, `save_state(run_dir, state)`, `all_runs(holding_root) -> list[(Path, dict)]`, `pending_runs(holding_root) -> list[(Path, dict)]`, `atomic_write_json(path, obj)`, `cmd_status(args, cfg=None) -> int`, `register(sub)`. State shape (versioned): `{"version": 1, "game", "run_id", "pre": None|{...}, "texgen_deployed": None|{...}, "post": None|{...}}` — `post is None` == the run is pending/interrupted.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_lodregen.py`:

```python
# ---------------------------------------------------------------- Task 2

def test_new_run_creates_state_file(tmp_path):
    sec = fixture_section(tmp_path)
    run_dir, state = lodregen.new_run(sec, "skyrim")
    assert run_dir.is_dir()
    assert run_dir.parent == Path(sec["holding_root"])
    on_disk = lodregen.load_state(run_dir)
    assert on_disk == state
    assert on_disk["game"] == "skyrim"
    assert on_disk["pre"] is None and on_disk["post"] is None
    assert on_disk["run_id"] == run_dir.name


def test_pending_runs_and_save_state(tmp_path):
    sec = fixture_section(tmp_path)
    run_dir, state = lodregen.new_run(sec, "skyrim")
    assert len(lodregen.pending_runs(sec["holding_root"])) == 1
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    state["post"] = {"stamp": "2026-07-11T12:00:00"}
    lodregen.save_state(run_dir, state)
    assert lodregen.pending_runs(sec["holding_root"]) == []
    assert len(lodregen.all_runs(sec["holding_root"])) == 1


def test_pending_runs_empty_when_no_holding_root(tmp_path):
    assert lodregen.pending_runs(str(tmp_path / "nope")) == []


def test_status_lists_pending_and_exits_2(tmp_path, capsys):
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    run_dir, state = lodregen.new_run(sec, "skyrim")
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    lodregen.save_state(run_dir, state)
    args = SimpleNamespace(game="skyrim")
    rc = lodregen.cmd_status(args, cfg=cfg)
    out = capsys.readouterr().out
    assert rc == 2
    assert "PENDING" in out
    assert "texgen NOT deployed" in out
    assert "modkit lodregen post" in out


def test_status_clean_when_complete(tmp_path, capsys):
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    run_dir, state = lodregen.new_run(sec, "skyrim")
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    state["post"] = {"stamp": "2026-07-11T12:00:00"}
    lodregen.save_state(run_dir, state)
    rc = lodregen.cmd_status(SimpleNamespace(game="skyrim"), cfg=cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "COMPLETE" in out


def test_register_wires_three_subcommands():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    lodregen.register(sub)
    args = p.parse_args(["lodregen", "status", "--game", "skyrim"])
    assert args.func is lodregen.cmd_status
    args = p.parse_args(["lodregen", "pre", "--game", "skyrim", "--no-pgpatcher"])
    assert args.func is lodregen.cmd_pre and args.no_pgpatcher
    args = p.parse_args(["lodregen", "post", "--game", "skyrim", "--stage", "texgen"])
    assert args.func is lodregen.cmd_post and args.stage == "texgen"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: Task 1's 4 tests pass; the new ones FAIL with `AttributeError: module 'modkit.lodregen' has no attribute 'new_run'` (and similar).

- [ ] **Step 3: Implement state + status + register**

Append to `modkit\lodregen.py`:

```python
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
    root = Path(holding_root)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / RUN_STATE).is_file():
            out.append((d, load_state(d)))
    return out


def pending_runs(holding_root):
    return [(d, s) for d, s in all_runs(holding_root) if s.get("post") is None]


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
```

`cmd_pre` and `cmd_post` do not exist yet — add module-level stubs so `register` and the tests import (they are replaced with real implementations in Tasks 4 and 6; a stub that raises is NOT a placeholder left in the final product, it exists only between commits and the final code for both is fully specified in this plan):

```python
def cmd_pre(args, cfg=None, preset=None):
    raise LodregenError("cmd_pre is implemented in Task 4 of the lodregen plan")


def cmd_post(args, cfg=None, preset=None):
    raise LodregenError("cmd_post is implemented in Task 6 of the lodregen plan")
```

Place the two stubs ABOVE `register` in the file (Python needs the names bound when `register` references them). When Tasks 4 and 6 land, their real defs REPLACE these stubs at the same location.

- [ ] **Step 4: Wire into `modkit\cli.py`**

Open `C:\Modding\tools\modkit\cli.py` (built by modkit core Tasks 1–2). Add the import and one registration call next to the existing subcommand registrations:

```python
from modkit import lodregen
```

and, where the other subparsers are registered on the top-level `sub` subparsers object:

```python
lodregen.register(sub)
```

The core CLI dispatches via `args.func(args)` / `set_defaults(func=...)` (argparse dispatch per the core design). If the core dispatcher instead switches on the subcommand-name string, add the equivalent branch: `elif args.cmd == "lodregen": return args.func(args)` — `register` always sets `func`, so `args.func(args)` works under either style.

Smoke-check: `cd C:\Modding\tools; py -3 modkit.py lodregen status --game skyrim`
Expected: either `lodregen[skyrim]: no regen runs recorded under C:\Modding\skyrim-manual\backups\lodregen` (exit 0) — reading a config path is not touching a game dir — or the pending list if a run exists.

- [ ] **Step 5: Run all tests**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `10 passed`

- [ ] **Step 6: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py modkit/cli.py tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): run state, status subcommand, CLI wiring"
```

---

### Task 3: Protected-inputs guard + manifest-driven quarantine clean

This is the guard for the §8 headline trap: the regen pre-clean deleted required INPUT files 3× (Resources tree-LOD textures, the `statics_e` cubemap stand-in, rock textures). The clean is manifest-driven, file-by-file, quarantine-not-delete, and every path is checked against `protected_inputs` first. Wildcard or directory lines in a manifest abort the whole clean — blanket deletes are structurally impossible.

**Files:**
- Modify: `C:\Modding\tools\modkit\lodregen.py` (append)
- Test: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` (append)

**Interfaces:**
- Consumes: `LodregenError` (Task 1).
- Produces: `normalize_rel(p: str) -> str`, `is_protected(rel: str, patterns: list[str]) -> bool`, `read_lines_bomsafe(path) -> list[str]`, `guarded_clean(data_dir, manifest_lines, patterns, quarantine_dir) -> dict` with keys `moved`, `protected`, `missing` (lists of Data-relative paths).

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_lodregen.py`:

```python
# ---------------------------------------------------------------- Task 3

PROTECTED = [
    "textures\\dyndolod\\lod\\dyndolodtreelod*",
    "textures\\dyndolod\\lod\\dyndolodbackgroundtreelod*",
    "textures\\dyndolod\\lod\\version.ini",
    "textures\\dyndolod\\lod\\defaultdiffuse*",
    "textures\\dyndolod\\lod\\texgen_sse.ini",
    "meshes\\dyndolod\\lod\\*holycow*",
    "meshes\\dyndolod\\lod\\*mxtundra*_dyndolod_lod.nif",
    "*statics_e.dds",
    "*landscape\\statics\\rocks01*",
]


def test_protected_matches_every_known_input():
    # the exact victims/inputs from the wiki clean-trap table
    hits = [
        "textures\\DynDOLOD\\lod\\DynDOLODTreeLOD.dds",
        "Textures\\dyndolod\\lod\\dyndolodbackgroundtreelod.dds",
        "textures/dyndolod/lod/version.ini",          # forward slashes tolerated
        "textures\\dyndolod\\lod\\defaultdiffuse.dds",
        "textures\\dyndolod\\lod\\TexGen_SSE.ini",
        "meshes\\dyndolod\\lod\\holycow_dyndolod_load.nif",
        # the 7 mxtundra meshes live in SUBFOLDERS -- pattern must span dirs
        "meshes\\dyndolod\\lod\\effects\\mxtundrastreamtransition01_0100A123_dyndolod_lod.nif",
        "textures\\cubemaps\\statics_e.dds",
        "textures\\landscape\\statics\\rocks01.dds",
        "textures\\landscape\\statics\\rocks01_n.dds",
    ]
    for rel in hits:
        assert lodregen.is_protected(rel, PROTECTED), rel


def test_protected_does_not_match_regenerable_output():
    misses = [
        "meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto",
        "textures\\dyndolod\\lod\\dyndolod_tamriel.dds",   # generated atlas
        "meshes\\dyndolod\\lod\\somecity_aaa_dyndolod_lod.nif",
        "DynDOLOD.esm",
    ]
    for rel in misses:
        assert not lodregen.is_protected(rel, PROTECTED), rel


def _mk(data, rel):
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_guarded_clean_moves_skips_reports(tmp_path):
    data = tmp_path / "Data"
    quarantine = tmp_path / "q"
    out_file = _mk(data, "meshes/terrain/tamriel/objects/tamriel.4.0.-1.bto")
    prot_file = _mk(data, "textures/dyndolod/lod/dyndolodtreelod.dds")
    manifest = [
        "meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto",
        "textures\\dyndolod\\lod\\dyndolodtreelod.dds",   # polluted manifest!
        "textures\\dyndolod\\lod\\long_gone.dds",         # already missing
    ]
    rep = lodregen.guarded_clean(str(data), manifest, PROTECTED, str(quarantine))
    assert rep["moved"] == ["meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto"]
    assert rep["protected"] == ["textures\\dyndolod\\lod\\dyndolodtreelod.dds"]
    assert rep["missing"] == ["textures\\dyndolod\\lod\\long_gone.dds"]
    assert not out_file.exists()
    assert (quarantine / "meshes/terrain/tamriel/objects/tamriel.4.0.-1.bto").is_file()
    assert prot_file.is_file()   # the input SURVIVED the polluted manifest


def test_guarded_clean_refuses_wildcards_and_dirs(tmp_path):
    data = tmp_path / "Data"
    (data / "meshes").mkdir(parents=True)
    with pytest.raises(lodregen.LodregenError, match="wildcard"):
        lodregen.guarded_clean(str(data), ["meshes\\*.nif"], PROTECTED,
                               str(tmp_path / "q"))
    with pytest.raises(lodregen.LodregenError, match="directory"):
        lodregen.guarded_clean(str(data), ["meshes"], PROTECTED,
                               str(tmp_path / "q"))


def test_read_lines_bomsafe(tmp_path):
    f = tmp_path / "m.txt"
    f.write_bytes(b"\xef\xbb\xbf" + b"a.dds\r\nb.dds\r\n\r\n")
    assert lodregen.read_lines_bomsafe(f) == ["a.dds", "b.dds"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: previous 10 pass; new 5 FAIL with `AttributeError: module 'modkit.lodregen' has no attribute 'is_protected'` (and similar).

- [ ] **Step 3: Implement the guard + clean**

Append to `modkit\lodregen.py`:

```python
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

    Guards, in order:
      * a manifest line containing a wildcard aborts the whole clean
      * a manifest line naming a directory aborts the whole clean
      * a line matching protected_inputs is SKIPPED and reported
        (polluted manifests are the recorded failure mode -- the manifest
        asked for an input's head, we refuse)
    Returns {"moved": [...], "protected": [...], "missing": [...]}.
    """
    report = {"moved": [], "protected": [], "missing": []}
    data_dir = Path(data_dir)
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
        if not src.is_file():
            report["missing"].append(rel)
            continue
        dst = Path(quarantine_dir) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        report["moved"].append(rel)
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): protected-inputs guard + manifest-driven quarantine clean"
```

---

### Task 4: `modkit lodregen pre`

**Files:**
- Modify: `C:\Modding\tools\modkit\lodregen.py` (replace the `cmd_pre` stub; append helpers)
- Test: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` (append)

**Interfaces:**
- Consumes: `section`, `new_run`/`save_state`/`pending_runs` (Task 2), `guarded_clean`/`read_lines_bomsafe` (Task 3), `modkit.pluginstxt.snapshot/disable` (core), `modkit.ledger_bridge.run` (core), preset attrs `DATA_DIR`, `PLUGINS_TXT`, `PROCESS_NAMES`.
- Produces: `running_processes(names, csv_text=None) -> list[str]`, `active_output_entry(game, prefix) -> str|None`, `entry_manifest_path(game, name, ledger_dir) -> Path|None`, `gui_sequence(sec, game, no_pgpatcher, data_dir) -> str`, `cmd_pre(args, cfg=None, preset=None) -> int` (0 clean / 2 warned / 1 refused). Exit-code 2 means "stop and read" (matches the core deploy convention).

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_lodregen.py`:

```python
# ---------------------------------------------------------------- Task 4

TASKLIST_IDLE = ('"svchost.exe","1234","Services","0","10,000 K"\n'
                 '"explorer.exe","5678","Console","1","90,000 K"\n')
TASKLIST_GAME = TASKLIST_IDLE + '"SkyrimSE.exe","9999","Console","1","2,000,000 K"\n'


def test_running_processes_parses_tasklist_csv():
    names = ["SkyrimSE.exe", "TexGenx64.exe"]
    assert lodregen.running_processes(names, csv_text=TASKLIST_IDLE) == []
    assert lodregen.running_processes(names, csv_text=TASKLIST_GAME) == ["SkyrimSE.exe"]


def make_env(tmp_path, monkeypatch, trio_in_data=True, ledger_list_out=None):
    """Fixture game env: fake Data + real Plugins.txt handled by the REAL
    modkit.pluginstxt, fake ledger_bridge, idle tasklist."""
    data = tmp_path / "Data"
    data.mkdir(exist_ok=True)
    plugins = tmp_path / "Plugins.txt"
    lines = ["*Unofficial Skyrim Special Edition Patch.esp", "*SomeMod.esp",
             "*DynDOLOD.esm", "*DynDOLOD.esp", "*Occlusion.esp"]
    plugins.write_bytes(b"\xef\xbb\xbf"
                        + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    (tmp_path / "backups").mkdir(exist_ok=True)
    preset = SimpleNamespace(
        DATA_DIR=str(data), PLUGINS_TXT=str(plugins),
        PROCESS_NAMES=["SkyrimSE.exe"], RUNTIME="1.6.1170",
        STAGING_ROOT=str(tmp_path / "staging"),
        BACKUPS_DIR=str(tmp_path / "backups"))
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    # tool exes + ini exist
    for key, p in sec["tools"].items():
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("Wizard=0\nExpert=0\n" if key == "dyndolod_ini" else "MZ")
    # NG markers exist
    for m in sec["ng_markers"]:
        _mk(data, m.replace("\\", "/"))
    if trio_in_data:
        for name in sec["trio"]:
            (data / name).write_bytes(make_tes4(["Skyrim.esm"]))
    # ledger fake
    calls = []
    list_out = ledger_list_out if ledger_list_out is not None else (
        "DynDOLOD Output  installed 2026-06-28  DynDOLOD.esm\n"
        "TexGen Output  installed 2026-06-28\n")

    def fake_run(argv):
        calls.append(list(argv))
        if argv[0] == "list":
            return 0, list_out
        if argv[0] == "get":
            name = argv[argv.index("--name") + 1]
            safe = name.replace(" ", "-").replace("(", "").replace(")", "")
            return 0, json.dumps({"name": name,
                                  "manifest": f"manifests\\{safe}.txt"})
        return 0, "ok"

    monkeypatch.setattr(lodregen.ledger_bridge, "run", fake_run)
    monkeypatch.setattr(lodregen, "running_processes", lambda names: [])
    return SimpleNamespace(cfg=cfg, sec=sec, preset=preset, data=data,
                           plugins=plugins, ledger_calls=calls)


def write_manifest_fixture(env, name, rels):
    mdir = Path(env.sec["ledger_dir"]) / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    safe = name.replace(" ", "-").replace("(", "").replace(")", "")
    (mdir / f"{safe}.txt").write_bytes(
        b"\xef\xbb\xbf" + ("\r\n".join(rels) + "\r\n").encode("utf-8"))


def _pre_args(**kw):
    d = dict(game="skyrim", no_pgpatcher=False, clean_texgen=False, force=False)
    d.update(kw)
    return SimpleNamespace(**d)


def test_pre_pulls_trio_disables_lines_writes_state(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output",
                           ["meshes\\terrain\\tamriel\\objects\\old.bto"])
    _mk(env.data, "meshes/terrain/tamriel/objects/old.bto")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc in (0, 2)
    runs = lodregen.pending_runs(env.sec["holding_root"])
    assert len(runs) == 1
    run_dir, state = runs[0]
    # trio FILES left Data (from-scratch requirement), held in run_dir\trio
    for name in env.sec["trio"]:
        assert not (env.data / name).exists()
        assert (run_dir / "trio" / name).is_file()
    assert state["pre"]["trio_moved"] == env.sec["trio"]
    # trio lines disabled -- via the real pluginstxt
    from modkit import pluginstxt
    enabled = lodregen.enabled_plugins(pluginstxt.read(env.preset))
    for name in env.sec["trio"]:
        assert name.lower() not in enabled
    # old output quarantined
    assert (run_dir / "quarantine" / "meshes/terrain/tamriel/objects/old.bto").is_file()
    # snapshot recorded and exists
    assert Path(state["pre"]["plugins_snapshot"]).is_file()
    # GUI ritual printed, never-drive stated, TexGen Ignore noted
    assert "NEVER launch" in out
    assert "TexGenx64.exe" in out and "IGNORE" in out
    assert "post --game skyrim --stage texgen" in out


def test_pre_protected_input_survives_polluted_manifest(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output", [
        "meshes\\terrain\\tamriel\\objects\\old.bto",
        "textures\\dyndolod\\lod\\dyndolodtreelod.dds",   # pollution
    ])
    _mk(env.data, "meshes/terrain/tamriel/objects/old.bto")
    tree = _mk(env.data, "textures/dyndolod/lod/dyndolodtreelod.dds")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert tree.is_file()               # THE guard: input never left Data
    assert "PROTECTED" in out
    assert rc in (0, 2)


def test_pre_refuses_when_game_running(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(lodregen, "running_processes",
                        lambda names: ["SkyrimSE.exe"])
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().out
    assert lodregen.pending_runs(env.sec["holding_root"]) == []


def test_pre_refuses_when_pending_run_exists(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    lodregen.new_run(env.sec, "skyrim")   # simulate an interrupted run
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "pending" in capsys.readouterr().out.lower()


def test_pre_texgen_not_cleaned_by_default(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output", [])
    write_manifest_fixture(env, "TexGen Output",
                           ["textures\\lod\\some_old_texgen.dds"])
    old_tex = _mk(env.data, "textures/lod/some_old_texgen.dds")
    lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert old_tex.is_file()   # wiki 2026-06-25: never pre-clean TexGen


def test_pre_first_run_tolerates_missing_trio_and_entries(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch, trio_in_data=False, ledger_list_out="")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 2          # warnings, not failure
    assert "trio file(s) not in Data" in out
```

Note: `make_tes4` is defined in Task 5's tests; to keep this task self-contained, add it NOW near the top of the test file (it is pure struct-packing, no game data):

```python
def make_tes4(masters, esl=False):
    """Minimal valid SSE plugin: a TES4 record with HEDR + MAST/DATA pairs.
    Header: sig(4) dataSize(4) flags(4) formid(4) vc(4) version(2) unk(2)."""
    subs = b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 0, 0x800)
    for m in masters:
        name = m.encode("cp1252") + b"\x00"
        subs += b"MAST" + struct.pack("<H", len(name)) + name
        subs += b"DATA" + struct.pack("<H", 8) + b"\x00" * 8
    flags = 0x200 if esl else 0
    return (b"TES4" + struct.pack("<IIII", len(subs), flags, 0, 0)
            + struct.pack("<HH", 44, 0) + subs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: earlier 15 pass; new ones FAIL — `running_processes` missing, then `cmd_pre` raising the Task-2 stub error.

- [ ] **Step 3: Implement helpers + `cmd_pre`**

Append the helpers to `modkit\lodregen.py`, and REPLACE the Task-2 `cmd_pre` stub with the real implementation:

```python
# ------------------------------------------------------------ processes

def running_processes(names, csv_text=None):
    """Which of `names` are live? Parses `tasklist /FO CSV /NH` (injectable
    for tests via csv_text)."""
    if csv_text is None:
        p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True)
        csv_text = p.stdout or ""
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


# ------------------------------------------------------------ pre

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

    procs = running_processes(list(preset.PROCESS_NAMES)
                              + list(sec["tool_processes"]))
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
    run_dir, state = new_run(sec, args.game)
    stamp = _now()
    snapshot = pluginstxt.snapshot(preset, f"lodregen-pre-{state['run_id']}")

    trio_dir = run_dir / "trio"
    trio_dir.mkdir()
    moved, absent = [], []
    for name in sec["trio"]:
        pluginstxt.disable(preset, name)
        src = Path(preset.DATA_DIR) / name
        if src.is_file():
            shutil.move(str(src), str(trio_dir / name))
            moved.append(name)
        else:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `22 passed`

- [ ] **Step 5: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): pre bracket (snapshot, trio aside, guarded clean, GUI ritual)"
```

---

### Task 5: Inline TES4 masters parse + masters verify

`modkit.tes4` is not in the dependency contract and the core plan file did not exist when this plan was written, so the `MAST` walk lives here (see contract note 3 — the wiki's 5th-regen lesson: a naive header regex over-reports; a proper subrecord walk excluding implicit base ESMs / `_ResourcePack*` / `cc*` reported 0 false positives).

**Files:**
- Modify: `C:\Modding\tools\modkit\lodregen.py` (append)
- Test: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` (append)

**Interfaces:**
- Consumes: `make_tes4` test builder (added in Task 4's Step 1).
- Produces: `read_masters(plugin_path) -> list[str]`, `master_problems(plugin_path, data_dir, enabled_ordered, also_present=()) -> list[str]`, `enabled_plugins(lines) -> list[str]` (lowercased, in file order), `IMPLICIT_MASTERS` constant. Task 6 consumes all of these.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_lodregen.py`:

```python
# ---------------------------------------------------------------- Task 5

def test_read_masters_roundtrip(tmp_path):
    p = tmp_path / "DynDOLOD.esp"
    p.write_bytes(make_tes4(["Skyrim.esm", "Update.esm", "JKs Skyrim.esp",
                             "DynDOLOD.esm"]))
    assert lodregen.read_masters(p) == ["Skyrim.esm", "Update.esm",
                                        "JKs Skyrim.esp", "DynDOLOD.esm"]


def test_read_masters_rejects_non_plugin(tmp_path):
    p = tmp_path / "not_a_plugin.esp"
    p.write_bytes(b"MZ\x90\x00 definitely not TES4")
    with pytest.raises(ValueError, match="TES4"):
        lodregen.read_masters(p)


def test_read_masters_handles_xxxx_oversize(tmp_path):
    # An XXXX subrecord promotes the NEXT subrecord's size to 32 bits
    # (DynDOLOD.esm headers carry huge ONAM arrays). MAST after it must
    # still parse.
    onam = b"\x00" * 70000
    subs = (b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 0, 0)
            + b"XXXX" + struct.pack("<H", 4) + struct.pack("<I", len(onam))
            + b"ONAM" + struct.pack("<H", 0) + onam
            + b"MAST" + struct.pack("<H", 11) + b"Skyrim.esm\x00"
            + b"DATA" + struct.pack("<H", 8) + b"\x00" * 8)
    p = tmp_path / "big.esm"
    p.write_bytes(b"TES4" + struct.pack("<IIII", len(subs), 1, 0, 0)
                  + struct.pack("<HH", 44, 0) + subs)
    assert lodregen.read_masters(p) == ["Skyrim.esm"]


def test_master_problems_classifies(tmp_path):
    data = tmp_path / "Data"
    data.mkdir()
    # masters on disk
    (data / "JKs Skyrim.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    (data / "LateMod.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    plugin = data / "Occlusion.esp"
    plugin.write_bytes(make_tes4([
        "Skyrim.esm",          # implicit -> never reported
        "ccBGSSSE037-Curios.esl",   # cc* -> never reported
        "_ResourcePack.esl",   # implicit -> never reported
        "JKs Skyrim.esp",      # on disk + enabled earlier -> fine
        "GoneMod.esp",         # not on disk -> MISSING
        "DisabledMod.esp",     # on disk but not enabled -> NOT ENABLED
        "LateMod.esp",         # enabled AFTER the plugin -> loads AFTER
    ]))
    (data / "DisabledMod.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    enabled = ["jks skyrim.esp", "occlusion.esp", "latemod.esp"]
    probs = lodregen.master_problems(plugin, data, enabled)
    text = "\n".join(probs)
    assert "GoneMod.esp" in text and "MISSING" in text
    assert "DisabledMod.esp" in text and "NOT ENABLED" in text
    assert "LateMod.esp" in text and "AFTER" in text
    assert "Skyrim.esm" not in text
    assert "ccBGSSSE037" not in text
    assert "_ResourcePack" not in text
    assert len(probs) == 3


def test_master_problems_also_present_covers_undeployed_trio(tmp_path):
    # DynDOLOD.esp masters DynDOLOD.esm; during post's verify the esm is
    # still in the OUTPUT dir, not Data -- also_present covers it.
    data = tmp_path / "Data"
    data.mkdir()
    out = tmp_path / "DynDOLOD_Output"
    out.mkdir()
    esp = out / "DynDOLOD.esp"
    esp.write_bytes(make_tes4(["Skyrim.esm", "DynDOLOD.esm"]))
    future = ["dyndolod.esm", "dyndolod.esp", "occlusion.esp"]
    assert lodregen.master_problems(esp, data, future,
                                    also_present=["DynDOLOD.esm"]) == []
    # without also_present it is MISSING
    probs = lodregen.master_problems(esp, data, future)
    assert len(probs) == 1 and "MISSING" in probs[0]


def test_enabled_plugins_strips_stars_and_comments():
    lines = ["# comment", "*Foo.esp", "Disabled.esp", "*Bar.esm", ""]
    assert lodregen.enabled_plugins(lines) == ["foo.esp", "bar.esm"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: earlier 22 pass; new 6 FAIL with `AttributeError: module 'modkit.lodregen' has no attribute 'read_masters'` (and similar).

- [ ] **Step 3: Implement the parser + verify**

Append to `modkit\lodregen.py`:

```python
# ------------------------------------------------------------ TES4 masters
# Inline on purpose: modkit.tes4 is not in this build's dependency contract
# (core plan Tasks 1-2/9 only). If a later core build ships modkit.tes4 with
# a masters() returning list[str], read_masters may delegate to it.

IMPLICIT_MASTERS = {"skyrim.esm", "update.esm", "dawnguard.esm",
                    "hearthfires.esm", "dragonborn.esm"}


def read_masters(plugin_path):
    """MAST-subrecord walk of a plugin's TES4 header -> master filenames.

    Header layout (SSE): sig(4) dataSize(4) flags(4) formID(4) vc(4)
    version(2) unknown(2) = 24 bytes, then subrecords sig(4)+size(2)+data.
    An XXXX subrecord promotes the NEXT subrecord's size to its uint32
    payload (DynDOLOD.esm headers carry huge ONAM arrays)."""
    data = Path(plugin_path).read_bytes()
    if len(data) < 24 or data[:4] != b"TES4":
        raise ValueError(f"not a TES4 plugin: {plugin_path}")
    data_size = struct.unpack_from("<I", data, 4)[0]
    end = min(24 + data_size, len(data))
    masters, off, oversize = [], 24, None
    while off + 6 <= end:
        sig = data[off:off + 4]
        size = struct.unpack_from("<H", data, off + 4)[0]
        off += 6
        if oversize is not None:
            size, oversize = oversize, None
        if sig == b"XXXX" and size == 4:
            oversize = struct.unpack_from("<I", data, off)[0]
        elif sig == b"MAST":
            masters.append(data[off:off + size].rstrip(b"\x00")
                           .decode("cp1252"))
        off += size
    return masters


def enabled_plugins(lines):
    """Lowercased enabled plugin names, in order, from pluginstxt.read()
    lines ('*' prefix = enabled; SSE Plugins.txt convention)."""
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("*"):
            out.append(s[1:].strip().lower())
    return out


def master_problems(plugin_path, data_dir, enabled_ordered, also_present=()):
    """Real load-order problems for one plugin's masters. Excludes the
    implicit base ESMs, cc*, and _ResourcePack* (the wiki's naive-regex
    over-report lesson). `also_present` = names counted as on-disk+enabled-
    in-given-order even if not in Data yet (the about-to-be-deployed trio)."""
    plugin_path = Path(plugin_path)
    pname = plugin_path.name.lower()
    extra = {x.lower() for x in also_present}
    problems = []
    try:
        pos = enabled_ordered.index(pname)
    except ValueError:
        pos = len(enabled_ordered)
    for m in read_masters(plugin_path):
        ml = m.lower()
        if (ml in IMPLICIT_MASTERS or ml.startswith("cc")
                or ml.startswith("_resourcepack")):
            continue
        if not ((Path(data_dir) / m).is_file() or ml in extra):
            problems.append(f"{plugin_path.name}: master {m} MISSING from Data")
            continue
        if ml not in enabled_ordered:
            problems.append(f"{plugin_path.name}: master {m} on disk but "
                            f"NOT ENABLED in Plugins.txt")
        elif enabled_ordered.index(ml) > pos:
            problems.append(f"{plugin_path.name}: master {m} loads AFTER "
                            f"{plugin_path.name}")
    return problems
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `28 passed`

- [ ] **Step 5: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): inline TES4 MAST parse + masters verify"
```

---

### Task 6: `modkit lodregen post` (freshness gate, deploy, trio re-enable, ledger)

Ledger mechanism (decided after reading `C:\Modding\tools\ledger.py`'s actual flags): `update --append-note` exists (appends a `[YYYY-MM-DD] ...` line) but `update` has NO `--files-from`, and manifests are written ONLY by `add --files-from`; `find_entry` also matches removed entries, so remove-then-re-`add` under the SAME name fails with "already exists - use `update`". A stable entry whose manifest goes stale would make `ledger.py check` complain forever. **Chosen mechanism:** dated entries. post `remove`s the current active output entry (reason `superseded by lodregen <run_id>`, `--to` the quarantine dir) and `add`s a fresh `"<prefix> (regen <run_id>)"` entry with `--files-from` (accurate manifest + fileCount) and a `--note` carrying the regen event. Discovery of "the current entry" is by prefix match over `list --active` output (`_entry_line` joins fields with two spaces, so the name is the text before the first double space). Ledger failures WARN (exit 2) with the exact manual command — the deploy is already live and bookkeeping must stay fixable, never block disk truth.

**Files:**
- Modify: `C:\Modding\tools\modkit\lodregen.py` (replace the `cmd_post` stub; append helpers)
- Test: `C:\Modding\tools\tests\test_modkit\test_lodregen.py` (append)

**Interfaces:**
- Consumes: Task 2 state fns, Task 4 `running_processes`/`active_output_entry`, Task 5 `read_masters`/`master_problems`/`enabled_plugins`, core `pluginstxt.read/snapshot/diff/enable/disable`, core `ledger_bridge.run`.
- Produces: `tree_stats(root) -> (count, newest_mtime)`, `data_relative_files(root) -> list[str]`, `robocopy_tree(src, dst) -> int`, `write_list(path, rels)`, `freshness_problems(kind, root, min_files, pre_epoch, require=()) -> list[str]`, `cmd_post(args, cfg=None, preset=None) -> int` (0/2/1).

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_lodregen.py`:

```python
# ---------------------------------------------------------------- Task 6

def _post_args(**kw):
    d = dict(game="skyrim", stage="full", run=None, force=False)
    d.update(kw)
    return SimpleNamespace(**d)


def run_pre(env):
    write_manifest_fixture(env, "DynDOLOD Output", [])
    rc = lodregen.cmd_pre(_pre_args(no_pgpatcher=True), cfg=env.cfg,
                          preset=env.preset)
    assert rc in (0, 2)
    return lodregen.pending_runs(env.sec["holding_root"])[0]


def fill_output(sec, kind, n, trio=(), master_lists=None):
    """Populate a fake tool-output dir with n dummy files (+ trio plugins)."""
    root = Path(sec["outputs"][kind])
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        f = root / "textures" / f"gen_{i}.dds"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"new")
    for name in trio:
        masters = (master_lists or {}).get(name, ["Skyrim.esm"])
        (root / name).write_bytes(make_tes4(masters))
    return root


def test_freshness_fails_on_missing_empty_stale(tmp_path):
    sec = fixture_section(tmp_path)
    probs = lodregen.freshness_problems("texgen", sec["outputs"]["texgen"],
                                        3, pre_epoch=0.0)
    assert probs and "missing" in probs[0]
    fill_output(sec, "texgen", 1)
    probs = lodregen.freshness_problems("texgen", sec["outputs"]["texgen"],
                                        3, pre_epoch=0.0)
    assert any("only 1" in p for p in probs)
    fill_output(sec, "texgen", 5)
    future = 4102444800.0  # year 2100: everything is older -> stale
    probs = lodregen.freshness_problems("texgen", sec["outputs"]["texgen"],
                                        3, pre_epoch=future)
    assert any("STALE" in p for p in probs)
    probs = lodregen.freshness_problems("texgen", sec["outputs"]["texgen"],
                                        3, pre_epoch=0.0)
    assert probs == []


def test_post_texgen_stage_gates_then_deploys(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    run_dir, state = run_pre(env)
    # empty output -> refuse, nothing deployed
    rc = lodregen.cmd_post(_post_args(stage="texgen"), cfg=env.cfg,
                           preset=env.preset)
    assert rc == 1
    assert "FRESHNESS FAIL" in capsys.readouterr().out
    # fresh output -> deploys into Data, records state
    fill_output(env.sec, "texgen", 5)
    rc = lodregen.cmd_post(_post_args(stage="texgen"), cfg=env.cfg,
                           preset=env.preset)
    assert rc == 0
    assert (env.data / "textures" / "gen_0.dds").is_file()
    _d, s = lodregen.pending_runs(env.sec["holding_root"])[0]
    assert s["texgen_deployed"]["files"] == 5
    assert (run_dir / "deploy-texgen.txt").is_file()


def test_post_full_happy_path(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    run_dir, state = run_pre(env)
    fill_output(env.sec, "texgen", 5)
    assert lodregen.cmd_post(_post_args(stage="texgen"), cfg=env.cfg,
                             preset=env.preset) == 0
    trio = env.sec["trio"]
    fill_output(env.sec, "dyndolod", 8, trio=trio, master_lists={
        "DynDOLOD.esm": ["Skyrim.esm"],
        "DynDOLOD.esp": ["Skyrim.esm", "DynDOLOD.esm"],
        "Occlusion.esp": ["Skyrim.esm", "DynDOLOD.esm"],
    })
    rc = lodregen.cmd_post(_post_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc in (0, 2)
    # trio deployed + re-enabled at the tail, esm -> esp -> Occlusion LAST
    from modkit import pluginstxt
    for name in trio:
        assert (env.data / name).is_file()
    enabled = lodregen.enabled_plugins(pluginstxt.read(env.preset))
    assert enabled[-3:] == [t.lower() for t in trio]
    # run finalized, diff written, no longer pending
    assert lodregen.pending_runs(env.sec["holding_root"]) == []
    assert (run_dir / "plugins-diff.txt").is_file()
    assert (run_dir / "deploy-dyndolod.txt").is_file()
    # ledger: superseded entry removed, dated entry added with files-from
    removes = [c for c in env.ledger_calls if c[0] == "remove"]
    assert any(c[c.index("--name") + 1] == "DynDOLOD Output" for c in removes)
    adds = [c for c in env.ledger_calls if c[0] == "add"]
    dyn_adds = [c for c in adds if c[c.index("--name") + 1]
                .startswith("DynDOLOD Output (regen")]
    assert dyn_adds and "--files-from" in dyn_adds[0]
    tex_adds = [c for c in adds if c[c.index("--name") + 1]
                .startswith("TexGen Output (regen")]
    assert tex_adds and "--files-from" in tex_adds[0]


def test_post_full_masters_fail_blocks_enable(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    run_pre(env)
    fill_output(env.sec, "texgen", 5)
    assert lodregen.cmd_post(_post_args(stage="texgen"), cfg=env.cfg,
                             preset=env.preset) == 0
    trio = env.sec["trio"]
    # Occlusion masters a mod that is NOT in Data/Plugins.txt -> the
    # post-reboot-rewrite CTD scenario, must hard-fail BEFORE enabling
    fill_output(env.sec, "dyndolod", 8, trio=trio, master_lists={
        "DynDOLOD.esm": ["Skyrim.esm"],
        "DynDOLOD.esp": ["Skyrim.esm", "DynDOLOD.esm"],
        "Occlusion.esp": ["Skyrim.esm", "RemovedWorldMod.esp"],
    })
    rc = lodregen.cmd_post(_post_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 1
    assert "MASTERS FAIL" in out and "RemovedWorldMod.esp" in out
    from modkit import pluginstxt
    enabled = lodregen.enabled_plugins(pluginstxt.read(env.preset))
    for name in trio:
        assert name.lower() not in enabled     # nothing was armed
    assert lodregen.pending_runs(env.sec["holding_root"]) != []  # still open


def test_post_full_refuses_without_texgen_deploy(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    run_pre(env)
    fill_output(env.sec, "dyndolod", 8, trio=env.sec["trio"])
    rc = lodregen.cmd_post(_post_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "TexGen output was never deployed" in capsys.readouterr().out


def test_post_refuses_with_no_pending_run(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    rc = lodregen.cmd_post(_post_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "no pending regen run" in capsys.readouterr().out


def test_write_list_and_data_relative_files(tmp_path):
    root = tmp_path / "out"
    (root / "meshes").mkdir(parents=True)
    (root / "meshes" / "b.nif").write_bytes(b"x")
    (root / "a.esp").write_bytes(b"x")
    rels = lodregen.data_relative_files(root)
    assert rels == ["a.esp", os.path.join("meshes", "b.nif")]
    lst = tmp_path / "list.txt"
    lodregen.write_list(lst, rels)
    assert lodregen.read_lines_bomsafe(lst) == rels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: earlier 28 pass; new ones FAIL — `freshness_problems` missing, then the `cmd_post` Task-2 stub error.

- [ ] **Step 3: Implement helpers + `cmd_post`**

Append the helpers to `modkit\lodregen.py`, and REPLACE the Task-2 `cmd_post` stub with the real implementation:

```python
# ------------------------------------------------------------ post helpers

def tree_stats(root):
    n, newest = 0, 0.0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            n += 1
            newest = max(newest, os.path.getmtime(os.path.join(dirpath, f)))
    return n, newest


def data_relative_files(root):
    root = str(root)
    rels = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            rels.append(os.path.relpath(os.path.join(dirpath, f), root))
    rels.sort()
    return rels


def write_list(path, rels):
    """UTF-8 BOM + CRLF, same shape ledger.py read_staged_list accepts."""
    Path(path).write_bytes(b"\xef\xbb\xbf"
                           + ("\r\n".join(rels) + "\r\n").encode("utf-8"))


def robocopy_tree(src, dst):
    """robocopy /E copy; caller applies the exit<8=success rule."""
    p = subprocess.run(
        ["robocopy", str(src), str(dst), "/E", "/R:2", "/W:2",
         "/NJH", "/NJS", "/NP", "/NDL", "/NFL"],
        capture_output=True, text=True)
    return p.returncode


def freshness_problems(kind, root, min_files, pre_epoch, require=()):
    """The empty-TexGen-exit / stale-output gate (§10 disk-artifact rule)."""
    root = Path(root)
    if not root.is_dir():
        return [f"{kind}: output dir missing: {root}"]
    n, newest = tree_stats(root)
    problems = []
    if n < min_files:
        problems.append(f"{kind}: only {n} file(s) in {root} (< {min_files})"
                        f" -- empty/partial run?")
    if n and newest <= pre_epoch:
        problems.append(f"{kind}: newest file predates `lodregen pre` -- "
                        f"STALE output (tool did not run, or wrote elsewhere)")
    for name in require:
        if not (root / name).is_file():
            problems.append(f"{kind}: expected file missing from output: {name}")
    return problems


def _resolve_run(args, sec):
    if args.run:
        d = Path(args.run)
        return d, load_state(d)
    pend = pending_runs(sec["holding_root"])
    if not pend:
        raise LodregenError(
            "no pending regen run -- run `modkit lodregen pre` first "
            "(see `modkit lodregen status`)")
    return pend[-1]


# ------------------------------------------------------------ post

def cmd_post(args, cfg=None, preset=None):
    cfg = cfg if cfg is not None else config.load()
    preset = preset if preset is not None else config.game(cfg, args.game)
    sec = section(cfg, args.game)
    try:
        run_dir, state = _resolve_run(args, sec)
    except LodregenError as e:
        print(f"REFUSED: {e}")
        return 1
    if state.get("pre") is None:
        print(f"REFUSED: run {run_dir} has no completed pre stage -- "
              f"inspect it by hand")
        return 1

    procs = running_processes(list(preset.PROCESS_NAMES)
                              + list(sec["tool_processes"]))
    if procs:
        print("REFUSED: process(es) running: " + ", ".join(procs))
        return 1

    if args.stage == "texgen":
        return _post_texgen(args, preset, sec, run_dir, state)
    return _post_full(args, preset, sec, run_dir, state)


def _post_texgen(args, preset, sec, run_dir, state):
    pre_epoch = state["pre"]["epoch"]
    out = sec["outputs"]["texgen"]
    problems = freshness_problems("texgen", out,
                                  sec["min_output_files"]["texgen"], pre_epoch)
    if problems and not args.force:
        for p in problems:
            print("FRESHNESS FAIL: " + p)
        print("TexGen output did NOT pass the gate -- re-run TexGen; do NOT "
              "proceed to DynDOLOD on stale textures.")
        return 1
    rc = robocopy_tree(out, preset.DATA_DIR)
    if rc >= 8:
        print(f"DEPLOY FAILED: robocopy exit {rc} (>=8 = failure) copying "
              f"{out} -> {preset.DATA_DIR}")
        return 1
    files = data_relative_files(out)
    write_list(Path(run_dir) / "deploy-texgen.txt", files)
    state["texgen_deployed"] = {
        "stamp": _now().isoformat(timespec="seconds"),
        "files": len(files),
        "robocopy_rc": rc,
        "forced_past": problems,
    }
    save_state(run_dir, state)
    print(f"TexGen output deployed: {len(files)} file(s), robocopy exit {rc} "
          f"(<8 = success).")
    print("NEXT: USER launches DynDOLOD (see the ritual `pre` printed), then "
          f"run: modkit lodregen post --game {args.game}")
    return 0


def _post_full(args, preset, sec, run_dir, state):
    pre_epoch = state["pre"]["epoch"]
    warnings = []
    trio = sec["trio"]

    if state.get("texgen_deployed") is None:
        msg = ("TexGen output was never deployed via `post --stage texgen`. "
               "If DynDOLOD already ran, it read STALE LOD textures -- "
               "correct fix: deploy TexGen output, re-run DynDOLOD.")
        if not args.force:
            print("REFUSED: " + msg)
            return 1
        warnings.append("forced past missing texgen deploy: " + msg)

    out = sec["outputs"]["dyndolod"]
    problems = freshness_problems("dyndolod", out,
                                  sec["min_output_files"]["dyndolod"],
                                  pre_epoch, require=tuple(trio))
    if not state["pre"]["no_pgpatcher"]:
        dj = Path(preset.DATA_DIR) / "ParallaxGen_Diff.json"
        if not dj.is_file() or dj.stat().st_mtime <= pre_epoch:
            problems.append(
                "pgpatcher: Data\\ParallaxGen_Diff.json missing or older "
                "than pre -- was the PGPatcher output deployed before TexGen?")
    if problems:
        if not args.force:
            for p in problems:
                print("FRESHNESS FAIL: " + p)
            print("Nothing deployed; trio still held aside. Fix the run and "
                  "re-invoke post.")
            return 1
        warnings += ["forced past: " + p for p in problems]

    # masters verify BEFORE anything is enabled (the armed-CTD guard):
    # verify the OUTPUT copies against the CURRENT Plugins.txt plus the
    # trio itself (deployed & enabled in order below).
    lines = pluginstxt.read(preset)
    future_enabled = enabled_plugins(lines) + [t.lower() for t in trio]
    trio_problems = []
    for name in trio:
        candidate = Path(out) / name
        if candidate.is_file():
            trio_problems += master_problems(candidate, preset.DATA_DIR,
                                             future_enabled,
                                             also_present=trio)
    if trio_problems and not args.force:
        for p in trio_problems:
            print("MASTERS FAIL: " + p)
        print("Trio NOT deployed or enabled -- launching now would CTD. "
              "A master was removed/disabled mid-regen, or Plugins.txt was "
              "rewritten behind the bracket (the post-reboot trap). Diff:")
        print(pluginstxt.diff(state["pre"]["plugins_snapshot"],
                              pluginstxt.snapshot(preset,
                                                  "lodregen-masterfail")))
        return 1
    warnings += ["forced past: " + p for p in trio_problems]

    rc = robocopy_tree(out, preset.DATA_DIR)
    if rc >= 8:
        print(f"DEPLOY FAILED: robocopy exit {rc} (>=8 = failure); trio not "
              f"re-enabled.")
        return 1
    files = data_relative_files(out)
    write_list(Path(run_dir) / "deploy-dyndolod.txt", files)

    # trio re-enable: esm -> esp -> Occlusion, block LAST (wiki correction:
    # Occlusion.esp absolute last, per dyndolod.info/Help/Occlusion-Data)
    pluginstxt.enable(preset, trio[0], None)
    pluginstxt.enable(preset, trio[1], trio[0])
    pluginstxt.enable(preset, trio[2], trio[1])
    tail = enabled_plugins(pluginstxt.read(preset))[-3:]
    if tail != [t.lower() for t in trio]:
        print(f"TAIL VERIFY FAIL: last enabled plugins are {tail}, expected "
              f"{[t.lower() for t in trio]}.")
        print("Fix the order with `modkit plugins` (never hand-edit), then "
              "re-run post.")
        return 1

    post_snap = pluginstxt.snapshot(preset, f"lodregen-post-{state['run_id']}")
    report = pluginstxt.diff(state["pre"]["plugins_snapshot"], post_snap)
    (Path(run_dir) / "plugins-diff.txt").write_text(report, encoding="utf-8")
    print("Plugins.txt diff vs pre snapshot (expected: only the trio cycled "
          "disabled -> re-enabled at the tail; anything else = investigate):")
    print(report)

    # ledger record: supersede old entries, add dated entries (see the
    # mechanism note at the top of Task 6)
    ledger_entries = {}
    for key, list_name, extra in (
            ("texgen", "deploy-texgen.txt", []),
            ("dyndolod", "deploy-dyndolod.txt",
             ["--plugin", trio[0], "--plugin", trio[1], "--plugin", trio[2]])):
        list_file = Path(run_dir) / list_name
        if not list_file.is_file():
            warnings.append(f"no deploy list for {key} -- ledger not updated "
                            f"for it")
            continue
        prefix = sec["ledger_prefixes"][key]
        new_name = f"{prefix} (regen {state['run_id']})"
        old = active_output_entry(args.game, prefix)
        if old:
            rc1, out1 = ledger_bridge.run(
                ["remove", "--game", args.game, "--name", old,
                 "--reason", f"superseded by lodregen {state['run_id']}",
                 "--to", str(Path(run_dir) / "quarantine")])
            if rc1 != 0:
                warnings.append(f"ledger remove failed for {old!r}: "
                                f"{out1.strip()}")
        note = (f"lodregen {state['run_id']}: regen recorded by `modkit "
                f"lodregen post`; trio re-enabled {trio[0]} -> {trio[1]} -> "
                f"{trio[2]} (Occlusion last); masters verified")
        rc2, out2 = ledger_bridge.run(
            ["add", "--game", args.game, "--name", new_name,
             "--files-from", str(list_file), "--role", "lod-output",
             "--note", note] + extra)
        if rc2 != 0:
            warnings.append(
                f"ledger add failed for {new_name!r}: {out2.strip()} -- "
                f"record manually: py -3 C:\\Modding\\tools\\ledger.py add "
                f"--game {args.game} --name \"{new_name}\" --files-from "
                f"\"{list_file}\"")
        ledger_entries[key] = new_name

    state["post"] = {
        "stamp": _now().isoformat(timespec="seconds"),
        "deployed": {"dyndolod": len(files)},
        "robocopy_rc": rc,
        "ledger_entries": ledger_entries,
        "warnings": warnings,
    }
    save_state(run_dir, state)
    print(f"lodregen post complete -- run {state['run_id']}: {len(files)} "
          f"DynDOLOD file(s) deployed, trio live "
          f"({trio[0]} -> {trio[1]} -> {trio[2]}).")
    print("Trio pre-regen copies + quarantined old output remain in "
          f"{run_dir} (quarantine-never-delete).")
    for w in warnings:
        print("  WARN: " + w)
    return 2 if warnings else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\test_lodregen.py -v`
Expected: `35 passed` (28 prior + 7 new). Note `test_post_texgen_stage_gates_then_deploys` and `test_post_full_happy_path` invoke real `robocopy` against tmp dirs — that is fine (not a game dir) and exercises the exit<8 rule for real.

- [ ] **Step 5: Commit**

```bash
git -C C:\Modding\tools add modkit/lodregen.py tests/test_modkit/test_lodregen.py
git -C C:\Modding\tools commit -m "feat(lodregen): post bracket (freshness gate, deploy, trio re-enable, masters verify, ledger)"
```

---

### Task 7: The runbook + final verification

**Files:**
- Create: `C:\Modding\tools\docs\runbooks\lod-regen-runbook.md`
- Test: full suite re-run + CLI smoke (no new test code)

**Interfaces:**
- Consumes: the finished `lodregen` subcommand surface (Tasks 1–6).
- Produces: the human/Claude ritual document the `pre` output points at.

- [ ] **Step 1: Write the runbook**

Create `C:\Modding\tools\docs\runbooks\lod-regen-runbook.md` with exactly this content:

````markdown
# LOD/Bake Regen Runbook (Skyrim SE) — `modkit lodregen`

The regen ritual is PGPatcher → TexGen → DynDOLOD with the DynDOLOD trio
(`DynDOLOD.esm`, `DynDOLOD.esp`, `Occlusion.esp`) OUT of the game for the
duration. `modkit lodregen` brackets it: **all GUI runs are manual — Claude
never launches, drives, clicks, or screenshots a generator GUI.** Claude's
jobs are the brackets, config-file prep, and disk-artifact verification.

Ground truth: wiki `concepts/skyrim-dyndolod-generation`,
`concepts/skyrim-pgpatcher`, `connections/skyrim-pgpatcher-dyndolod-order`.

## When is a regen needed?

Per the standing rule (sse-dyndolod-rerun-rule memory), every mod install
gets a DynDOLOD verdict. Triggers: tree/flora overhauls, grass LOD changes,
new worldspaces/cities/large exterior statics, mountain/landscape mesh
overhauls, water LOD. Non-triggers: textures, LOD-neutral meshes, sound,
UI, gameplay, NPC face/body, interiors, SKSE DLLs.

## Pre-requisites (check BEFORE bracketing)

- ~30–60+ min of user time; do NOT start at the tail of an all-nighter
  (the stale-LOD-up-close incident was an all-nighter regen).
- Load order FINALIZED — the regen bakes against it.
- Cleaned DLC masters in place (xEdit QuickAutoClean), or DynDOLOD
  hard-stops with "Deleted large references found".
- If PGPatcher is part of this pass: the post-deploy re-run wall — PGPatcher
  refuses with `PGPatcher meshes exist in your data directory, please delete
  before re-running.` if a previous bake is deployed. Clearing that wall
  means wiping all baked meshes and re-opens the orphaned-loose-mesh trap;
  residual visual fixes are usually per-mesh reverts, NOT re-bakes. Decide
  deliberately; when in doubt run `--no-pgpatcher`.
- Grass cache: an existing `Data\grass\*.cgid` cache is reused; only grass
  mesh/record/iMinGrassSize changes force a re-bake (separate procedure,
  sse-grass-lod-plan memory).

## The ritual

1. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen pre --game skyrim`
   (add `--no-pgpatcher` if this pass skips PGPatcher).
   This: refuses if game/tools are running or a regen is already pending;
   snapshots Plugins.txt; DISABLES the trio lines AND MOVES the trio plugin
   files to the holding dir (from-scratch requires the files gone, or
   DynDOLOD errors "DynDOLOD.esp already exists"); quarantines the old
   DynDOLOD output via its ledger manifest — **anything matching the
   protected-inputs list is skipped and reported** (the 9×-recurring clean
   trap: `dyndolodtreelod*`, `holycow*`, `mxtundra*`, `version.ini`,
   `defaultdiffuse*`, `TexGen_SSE.ini`, `statics_e.dds`,
   `landscape\statics\rocks01*`); checks exes, `DynDOLOD_SSE.ini` Wizard=0,
   NG markers; prints the GUI handoff script.
   TexGen output is NEVER pre-cleaned (wiki supersede 2026-06-25).
2. **[if PGPatcher] Claude:** verify `<PGPatcher>\cfg\settings.json`
   (output dir OUTSIDE Data; Mod Manager = None; no leading TAB in the
   output path). Config-file-first: the user only clicks Start.
3. **[if PGPatcher] USER:** double-clicks `PGPatcher.exe`, clicks Patch,
   reports completion.
4. **[if PGPatcher] Claude:** inspect the output (a run is a de-facto
   dry-run — the output dir is outside Data), then deploy it:
   `robocopy "C:\Modding\PGPatcher\PGPatcher-Output" "<DATA_DIR>" /E`
   (exit <8 = success). The bake does NOTHING until deployed — the June
   0/6610 failure. Record it in the ledger (dated entry, same pattern
   `lodregen post` uses for the LOD outputs).
5. **USER:** double-clicks `TexGenx64.exe`, runs it. The "Found stitched
   object LOD textures" warning is HARMLESS → click **Ignore**.
6. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen post --game skyrim --stage texgen`
   — freshness-gates TexGen_Output (non-empty, newer than pre; the
   empty-TexGen-exit trap) and deploys it. DynDOLOD must read the DEPLOYED
   textures.
7. **USER:** double-clicks `DynDOLODx64.exe` (user-launched — programmatic
   launches have opened the window off-screen/unclickable). Advanced mode;
   select ALL worldspaces (the selection can reset); Grass LOD ticked with
   Mode matching `GrassControl.ini` (this build: Mode 1) — hover the
   checkbox to confirm it found the .cgid cache; generate.
8. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen post --game skyrim`
   — freshness-gates DynDOLOD_Output (min file count, newer than pre, trio
   plugins present, fresh `ParallaxGen_Diff.json` if PGPatcher ran);
   verifies the new trio's TES4 masters BEFORE enabling anything (a failure
   here means launching would CTD — this is the guard for the post-reboot
   Plugins.txt-rewrite incident); deploys; re-enables the trio
   `DynDOLOD.esm → DynDOLOD.esp → Occlusion.esp` with Occlusion absolute
   last and verifies the tail; prints the Plugins.txt diff vs the pre
   snapshot (expected: ONLY the trio cycled — anything else = investigate
   before launch); records dated ledger entries.
9. **USER:** launches the game, checks distant LOD (mountains, trees,
   city silhouettes) and reports. Claude tails `ledger.py check --game
   skyrim` for new errors.

## Failure playbook

- **`pre` reports PROTECTED hits** — the old output manifest is polluted
  with input/stand-in files. The files were kept. Re-author the manifest
  from actual tool output only; if an input is missing anyway, no-clobber
  restore from `C:\Modding\tmp\dyndolod-resources` (fills gaps, overwrites
  nothing).
- **`post` FRESHNESS FAIL** — the tool didn't run / wrote elsewhere / exited
  empty. Re-run that GUI stage. Never `--force` past a texgen freshness
  fail into DynDOLOD.
- **`post` MASTERS FAIL** — a master of the new trio is missing/disabled.
  The trio was NOT enabled; the game is safe to leave alone but NOT
  regen-complete. Restore the master (or regen again without it), re-run
  post. Read the printed diff for what changed behind the bracket.
- **TAIL VERIFY FAIL** — something reordered Plugins.txt mid-bracket
  (Wrye Bash scramble class). Fix order with `modkit plugins`, re-run post.
- **Interrupted mid-ritual (crash/reboot/session death)** — the run stays
  PENDING: `modkit lodregen status --game skyrim` at session start shows
  it (exit 2). Do NOT launch the game while pending (trio held aside =
  no distant LOD; a launcher/reboot Plugins.txt rewrite while pending is
  the armed-CTD scenario `post` exists to catch). Resume at the step the
  state shows: `texgen_deployed: null` → resume at step 5/6, else step 7/8.
- **Abandoning a regen** — copy the trio files back from
  `<run_dir>\trio\` into Data, re-enable via `modkit plugins` in trio
  order, restore quarantined output from `<run_dir>\quarantine\`, then
  mark the run: it stays in history; record the abandonment as a ledger
  note on the still-active output entries. (Everything was moved, never
  deleted, so full rollback is always possible.)

## Post-regen leftovers

`<holding_root>\<run_id>\` keeps: the pre/post Plugins.txt snapshots
(via pluginstxt backups), `trio\` (pre-regen plugin files), `quarantine\`
(old output files), `deploy-*.txt` lists, `plugins-diff.txt`, and
`lodregen-run.json`. Prune old run dirs manually once a regen is verified
in-game — never automatically.
````

- [ ] **Step 2: Full suite + smoke**

Run: `cd C:\Modding\tools; py -3 -m pytest tests\test_modkit\ -v`
Expected: all modkit tests pass (35 lodregen + the core suite, 0 failures).

Run: `cd C:\Modding\tools; py -3 modkit.py lodregen --help; py -3 modkit.py lodregen status --game skyrim`
Expected: help lists `pre`, `post`, `status`; status prints the no-runs line or pending list (exit 0/2). Do NOT run `pre` against the real game as part of this plan — the first real bracket happens with the user present, per the acceptance note below.

- [ ] **Step 3: Commit**

```bash
git -C C:\Modding\tools add docs/runbooks/lod-regen-runbook.md
git -C C:\Modding\tools commit -m "docs(lodregen): LOD regen runbook (ritual, GUI handoffs, failure playbook)"
```

---

## Acceptance (beyond the suite)

The real acceptance is the next live regen, driven only by `lodregen pre` → GUI handoffs → `post --stage texgen` → `post`, with the user launching every GUI. Before that: a dress rehearsal against a scratch copy of `Data\` + `Plugins.txt` (point a copy of `modkit.json`'s preset + lodregen paths at the scratch tree) — the ledger-CLI precedent's final gate. Success = `status` shows COMPLETE, the Plugins.txt diff shows only the trio cycle, `ledger.py check --game skyrim` shows no new errors, and the user confirms distant LOD in-game.

## Execution Handoff

Plan complete and saved to `C:\Modding\tools\docs\2026-07-11-lod-regen-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach? (Reminder: modkit core Tasks 1–2 and 9 must be merged first — this plan imports `modkit.config`, `modkit.pluginstxt`, and `modkit.ledger_bridge` from the very first task's module import.)

