# modkit — Cross-Game Mod Install Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdlib-only Python CLI (`py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim`) that owns the whole mod-install pipeline — intake, stage, FOMOD, DLL vet, ESP vet, conflicts, deploy, verify, remove, plugins, status — plus its adoption stack (memory pins, `mod-install` skill, advisory PreToolUse hook).

**Architecture:** A `modkit\` package next to the existing `ledger.py` in the `C:\Modding\tools` git repo. Stepwise subcommands write per-install state to `install.json` in a timestamped staging dir (approach C: judgment gates stay with Claude/user between mechanical steps). Game specifics live in preset modules (`modkit\games\`) whose paths are populated from `modkit.json` at load time — nothing machine-specific is hardcoded. All ledger/manifest writes go through `ledger.py` via subprocess (`ledger_bridge`); modkit never re-implements it.

**Tech Stack:** Python 3.13 via `py -3` (never the `python` Store alias), stdlib only at runtime (`argparse`, `json`, `pathlib`, `subprocess`, `struct`, `xml.etree`, `zipfile` in tests). External processes: `7z.exe`, `robocopy`, `tasklist`, `py -3 ledger.py`. Tests: **pytest** (sole dev-only dependency) under `tests\test_modkit\`.

**Spec:** `C:\Modding\tools\docs\2026-07-11-modkit-design.md` (approved 2026-07-11). Every behavior below implements that spec; where the spec is silent, the resolution is noted inline.

## Global Constraints

- **stdlib-only Python 3.13** for all `modkit` runtime code; pytest is the only dev dependency (tests only). Always invoke via `py -3`, never `python` (Store alias).
- **No test touches real game dirs.** Every preset path is injectable through a fixture `modkit.json` (via the `MODKIT_CONFIG` env var). Tests build synthetic Data\, Plugins.txt, staging, manifests in `tmp_path`.
- **Atomic writes** (temp file + `os.replace`) for every `install.json` and Plugins.txt write; Plugins.txt writes are additionally **backup-first** (snapshot before edit) and re-read + validated after.
- **robocopy exit codes < 8 are success** — modkit's deploy/remove must map them, never surface 1–7 as errors.
- **Plugins.txt is BOM/CRLF-sensitive** — detect the BOM on read and preserve it on write; always write CRLF line endings.
- **PowerShell 5.1 host**: no `&&`/`||` in any PS example. Shell commands in this plan are written to run in **Git Bash** where possible (`git -C`, `py -3`, `ls`); the few PS-only lines are marked.
- **Never heredoc inline Python** — any Python (impl, test, one-off check) is written to a `.py` file with the Write tool, then run.
- **Only `deploy` and `remove` touch game dirs** (Data\, Plugins.txt, game root). Every other command reads.
- **Warn-not-block gates with `--force`**: gates print warnings and refuse, `--force` pushes through. `deploy` exits **0 clean / 2 warned**; the only un-forceable refusal is game-running (never safe).
- **ledger.py is the sole ledger/manifest writer** — modkit calls it via `ledger_bridge.run()`, never writes `ledger.json` or `manifests\` itself.
- **Console output ASCII-safe** (cp1252 console; use the `safe_print` pattern from ledger.py).
- Repo: `C:\Modding\tools` (existing git repo). One commit per task, conventional-commit messages, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
- Exit-code convention (whole CLI): **0** success/clean, **1** hard error or verify findings, **2** warned/refused-pending-vets (forceable gates). (Deliberately diverges from ledger.py's `2 = usage error`; documented in `--help`.)

## Ground-truth notes for the implementer (verified 2026-07-11)

- `7z.exe`: `C:\Program Files\7-Zip\7z.exe` (exists).
- Skyrim Data: `E:\SteamLibrary\steamapps\common\Skyrim Special Edition\Data`; Plugins.txt: `C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt` (exists, `*` prefix = enabled); runtime **1.6.1170**; processes `SkyrimSE.exe` + `skse64_loader.exe`; manifests `C:\Modding\skyrim-manual\manifests`; backups/quarantine `C:\Modding\skyrim-manual\backups`.
- CP77 root: `E:\SteamLibrary\steamapps\common\Cyberpunk 2077` (deploy targets `archive\pc\mod`, `red4ext`, `r6`, `bin`); process `Cyberpunk2077.exe`; manual dir `C:\Modding\cyberpunk-manual`.
- Downloads: `C:\Users\auand\Downloads`; Vortex spillover: `C:\Users\auand\AppData\Roaming\Vortex\downloads\skyrimse` and `...\cyberpunk2077`.
- Staging root `C:\Modding\staging` exists (empty).
- pytest is **not yet installed** for `py -3` (Task 1 installs it).
- `ledger.py` argument shapes (verified against `build_parser()` in `C:\Modding\tools\ledger.py`): `add --name --nexus-id --version --source --plugin (repeatable) --esl --role --note --installed --files-from`; `update --name [--append-note ...]`; `remove --name --reason [--to]`; `get --name`; `list [--active|--removed|--since|--count]`; `check`; all take `--game skyrim|cp77` or `--ledger <path>`. Exit codes: 0 clean, 1 findings, 2 error.
- User `settings.json` (`C:\Users\auand\.claude\settings.json`) currently has **no PreToolUse** hooks; it has SessionStart / PreCompact / SessionEnd / UserPromptSubmit / PostToolUse entries for dmm-memory-compiler which MUST be preserved (Task 18).
- Game project memory dirs: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\`, `...\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\`, `...\E--SteamLibrary-steamapps-common-Kenshi\memory\`. Skyrim MEMORY.md starts with a `# Project Memory — Skyrim SE Modding` heading; CP77 MEMORY.md has **no heading** (list starts at line 1); Kenshi starts with `# Memory Index`.

## File structure

```
C:\Modding\tools\
  modkit.py                      entry shim (sys.path bootstrap -> modkit.cli.main)
  modkit.json                    machine config (paths, runtimes) — created Task 1, committed
  modkit\
    __init__.py
    cli.py                       argparse dispatch; cmd_* functions for intake/stage/status/... 
    config.py                    load() + game()                          [Task 1]
    state.py                     InstallState + atomic_write_bytes        [Task 2]
    archive.py                   7z list/extract/verify                   [Task 3]
    fomod.py                     ModuleConfig.xml parse + apply           [Task 6]
    tes4.py                      TES4 header parse                        [Task 7]
    peparse.py                   PE/DLL parse + SKSE version data         [Task 8]
    pluginstxt.py                Plugins.txt manager                      [Task 9]
    conflicts.py                 overlap sweep                            [Task 10]
    ledger_bridge.py             subprocess wrapper around ledger.py      [Task 11]
    deploy.py                    deploy + remove engines                  [Tasks 11, 13]
    verify.py                    payload-vs-Data diff, _SWAP/_DISTR       [Task 12]
    games\
      __init__.py                registry: load(cfg, name), guess_game()  [Task 1]
      generic.py                 fallback preset (kenshi: intake/stage)   [Task 1]
      skyrim.py                  full preset                              [Task 1]
      cp77.py                    thin preset                              [Task 15]
  adoption\
    mod-install-SKILL.md         reference copy of the live skill         [Task 16]
    modkit-guard.py              PreToolUse hook - settings.json points   [Task 18]
                                 HERE (single copy, no drift; C: drive)
    memory-pins.md               provenance copy of the memory-pin texts  [Task 17]
  tests\test_modkit\
    conftest.py                  game_env + preset fixtures               [Task 1]
    test_config.py ... test_status.py   one test file per module/command
C:\Modding\staging\<game>\<YYYYMMDD-HHMMSS>-<modslug>\payload\ + install.json
C:\Users\auand\.claude\skills\mod-install\SKILL.md  (live skill = master) [Task 16]
```

Run all tests with: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q` (scoped to `test_modkit` so the existing unittest-based `test_ledger.py` suite stays on its own runner).

---

### Task 1: Package skeleton, modkit.json, config loader, games preset registry

**Files:**
- Create: `C:\Modding\tools\modkit.py`
- Create: `C:\Modding\tools\modkit.json`
- Create: `C:\Modding\tools\modkit\__init__.py`
- Create: `C:\Modding\tools\modkit\config.py`
- Create: `C:\Modding\tools\modkit\cli.py`
- Create: `C:\Modding\tools\modkit\games\__init__.py`
- Create: `C:\Modding\tools\modkit\games\generic.py`
- Create: `C:\Modding\tools\modkit\games\skyrim.py`
- Create: `C:\Modding\tools\tests\test_modkit\conftest.py`
- Test: `C:\Modding\tools\tests\test_modkit\test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (pinned — later tasks depend on these exact names):
  - `modkit.config.load() -> dict` — reads `modkit.json` (explicit `path` arg > `MODKIT_CONFIG` env > `C:\Modding\tools\modkit.json`); raises `config.ConfigError` on missing/unparseable/missing-required-keys.
  - `modkit.config.game(cfg: dict, name: str) -> preset module` — returns the populated preset module for `name`.
  - Preset module attributes, all read from modkit.json at load, not hardcoded: `DATA_DIR` (str or None), `PLUGINS_TXT` (str or None), `PROCESS_NAMES` (list[str]), `RUNTIME` (str or None), `STAGING_ROOT` (str, `<staging_root>\<name>`), `BACKUPS_DIR` (str).
  - Additional preset attributes (same mechanism): `NAME`, `MANIFESTS_DIR`, `VORTEX_DOWNLOADS`, `DOWNLOADS` (list[str]), `SEVENZIP`.
  - Preset function every game module defines: `applicability(payload_dir) -> dict` with keys `fomod`/`dllvet`/`esp` (bools).
  - `modkit.games.guess_game(paths: list[str]) -> str|None` — archive-listing heuristic ("skyrim"/"cp77"/"fallout4"/None).
  - `modkit.cli.main(argv=None) -> int`, `modkit.cli.safe_print(s)`, and the parser-registration pattern later tasks extend.

- [ ] **Step 1: Install pytest (dev-only dependency)**

Run: `py -3 -m pip install pytest`
Expected: `Successfully installed ... pytest-8.x` (any 8.x). Verify: `py -3 -m pytest --version` prints a version line.

- [ ] **Step 2: Write the failing test**

`C:\Modding\tools\tests\test_modkit\conftest.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # C:\Modding\tools


@pytest.fixture
def game_env(tmp_path, monkeypatch):
    """Synthetic machine: fake Data\\, Plugins.txt (BOM+CRLF), staging, backups,
    manifests, downloads — and a modkit.json pointing at all of it.
    No test ever touches real game dirs."""
    root = tmp_path
    (root / "Data").mkdir()
    (root / "staging").mkdir()
    (root / "backups").mkdir()
    (root / "manifests").mkdir()
    (root / "downloads").mkdir()
    plugins = root / "Plugins.txt"
    plugins.write_bytes(
        b"\xef\xbb\xbf"
        b"*Unofficial Skyrim Special Edition Patch.esp\r\n"
        b"*SkyUI_SE.esp\r\n"
        b"DisabledMod.esp\r\n"
        b"*DynDOLOD.esm\r\n"
        b"*DynDOLOD.esp\r\n"
        b"*Occlusion.esp\r\n")
    cfg = {
        "sevenzip": r"C:\Program Files\7-Zip\7z.exe",
        "downloads": [str(root / "downloads")],
        "staging_root": str(root / "staging"),
        "games": {
            "skyrim": {
                "data_dir": str(root / "Data"),
                "plugins_txt": str(plugins),
                "process_names": ["FakeGame.exe"],
                "runtime": "1.6.1170",
                "backups_dir": str(root / "backups"),
                "manifests_dir": str(root / "manifests"),
                "vortex_downloads": None,
            }
        },
    }
    cfg_path = root / "modkit.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("MODKIT_CONFIG", str(cfg_path))
    return root


@pytest.fixture
def preset(game_env):
    from modkit import config
    return config.game(config.load(), "skyrim")
```

`C:\Modding\tools\tests\test_modkit\test_config.py`:

```python
from pathlib import Path

import pytest

from modkit import config


def test_load_reads_env_config(game_env):
    cfg = config.load()
    assert cfg["games"]["skyrim"]["runtime"] == "1.6.1170"


def test_load_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("MODKIT_CONFIG", str(tmp_path / "nope.json"))
    with pytest.raises(config.ConfigError):
        config.load()


def test_game_preset_attributes_from_config(game_env):
    p = config.game(config.load(), "skyrim")
    assert Path(p.DATA_DIR) == game_env / "Data"
    assert Path(p.PLUGINS_TXT) == game_env / "Plugins.txt"
    assert p.PROCESS_NAMES == ["FakeGame.exe"]
    assert p.RUNTIME == "1.6.1170"
    assert Path(p.STAGING_ROOT) == game_env / "staging" / "skyrim"
    assert Path(p.BACKUPS_DIR) == game_env / "backups"
    assert p.NAME == "skyrim"
    assert Path(p.SEVENZIP).name == "7z.exe"


def test_game_unconfigured_raises(game_env):
    with pytest.raises(config.ConfigError):
        config.game(config.load(), "rdr2")


def test_generic_preset_for_moduleless_game(game_env, tmp_path):
    cfg = config.load()
    cfg["games"]["kenshi"] = {"data_dir": None, "plugins_txt": None,
                              "process_names": ["kenshi_x64.exe"], "runtime": None,
                              "backups_dir": str(tmp_path / "kb")}
    p = config.game(cfg, "kenshi")
    assert p.NAME == "kenshi"
    assert p.DATA_DIR is None
    assert p.applicability(str(tmp_path)) == {"fomod": False, "dllvet": False, "esp": False}


def test_skyrim_applicability(preset, tmp_path):
    pay = tmp_path / "payload"
    (pay / "fomod").mkdir(parents=True)
    (pay / "fomod" / "ModuleConfig.xml").write_text("<config/>")
    (pay / "SKSE" / "Plugins").mkdir(parents=True)
    (pay / "SKSE" / "Plugins" / "thing.dll").write_bytes(b"MZ")
    (pay / "Mod.esp").write_bytes(b"TES4")
    assert preset.applicability(str(pay)) == {"fomod": True, "dllvet": True, "esp": True}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert preset.applicability(str(empty)) == {"fomod": False, "dllvet": False, "esp": False}


def test_guess_game_fallout_outranks_skyrim():
    from modkit import games
    assert games.guess_game(["Data/F4SE/Plugins/x.dll", "Data/Mod.esp"]) == "fallout4"
    assert games.guess_game(["textures/a.ba2"]) == "fallout4"
    assert games.guess_game(["SKSE/Plugins/x.dll", "Mod.esp"]) == "skyrim"
    assert games.guess_game(["archive/pc/mod/cool.archive"]) == "cp77"
    assert games.guess_game(["readme.txt"]) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'modkit'`

- [ ] **Step 4: Write the package**

`C:\Modding\tools\modkit\__init__.py`:

```python
"""modkit - cross-game mod install toolkit (Skyrim SE full, CP77 thin).

Spec: docs/2026-07-11-modkit-design.md. Ledger writes go through ledger.py only.
"""
```

`C:\Modding\tools\modkit\config.py`:

```python
"""modkit.json loader. Machine paths live in config, never in code
(SSD/multi-machine portability)."""
import json
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "modkit.json"


class ConfigError(Exception):
    """Bad or missing configuration / unknown game."""


def load(path=None):
    """Load modkit.json -> dict. Order: explicit path, MODKIT_CONFIG env, repo default."""
    p = Path(path or os.environ.get("MODKIT_CONFIG") or DEFAULT_PATH)
    if not p.is_file():
        raise ConfigError(f"config not found: {p}")
    try:
        cfg = json.loads(p.read_bytes().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise ConfigError(f"config unparseable: {p}: {ex}")
    for key in ("sevenzip", "staging_root", "games"):
        if key not in cfg:
            raise ConfigError(f"config missing required key {key!r}: {p}")
    return cfg


def game(cfg, name):
    """Return the populated preset module for `name`."""
    from modkit import games
    return games.load(cfg, name)
```

`C:\Modding\tools\modkit\games\__init__.py`:

```python
"""Preset registry. config.game() populates a preset module's path attributes
from modkit.json at load time - presets hardcode behavior, never paths."""
import importlib
from pathlib import Path

from modkit.config import ConfigError

# archive-listing markers -> game guess (intake wrong-game gate).
# fallout4 markers outrank skyrim: .ba2/F4SE never appear in SSE mods,
# while .esp/.esm appear in both (the FO4-mixup trap, 3 incidents).
_MARKERS = (
    ("f4se/", "fallout4"), (".ba2", "fallout4"),
    ("skse/", "skyrim"), (".bsa", "skyrim"),
    (".esp", "skyrim"), (".esm", "skyrim"), (".esl", "skyrim"),
    ("archive/pc/mod/", "cp77"), (".archive", "cp77"),
    ("red4ext/", "cp77"), ("r6/scripts", "cp77"),
)


def guess_game(paths):
    """Best-guess game from archive-relative paths; None = unknown."""
    votes = {}
    for p in paths:
        low = p.replace("\\", "/").lower()
        for marker, g in _MARKERS:
            hit = low.endswith(marker) if marker.startswith(".") else marker in low
            if hit:
                votes[g] = votes.get(g, 0) + 1
    if not votes:
        return None
    if votes.get("fallout4"):
        return "fallout4"
    return max(votes, key=lambda k: votes[k])


def load(cfg, name):
    if name not in cfg.get("games", {}):
        known = ", ".join(sorted(cfg.get("games", {})))
        raise ConfigError(f"game {name!r} not in modkit.json (configured: {known})")
    try:
        mod = importlib.import_module(f"modkit.games.{name}")
    except ModuleNotFoundError:
        mod = importlib.import_module("modkit.games.generic")
    g = cfg["games"][name]
    if "process_names" not in g or "backups_dir" not in g:
        raise ConfigError(f"game {name!r} config needs process_names + backups_dir")
    mod.NAME = name
    mod.DATA_DIR = g.get("data_dir")
    mod.PLUGINS_TXT = g.get("plugins_txt")
    mod.PROCESS_NAMES = list(g["process_names"])
    mod.RUNTIME = g.get("runtime")
    mod.STAGING_ROOT = str(Path(cfg["staging_root"]) / name)
    mod.BACKUPS_DIR = g["backups_dir"]
    mod.MANIFESTS_DIR = g.get("manifests_dir")
    mod.VORTEX_DOWNLOADS = g.get("vortex_downloads")
    mod.DOWNLOADS = list(cfg.get("downloads", []))
    mod.SEVENZIP = cfg["sevenzip"]
    return mod
```

`C:\Modding\tools\modkit\games\generic.py`:

```python
"""Fallback preset for games without a dedicated module (e.g. kenshi).
intake/stage/status work; anything that would touch game dirs is refused
by the commands themselves (DATA_DIR is None / no deploy support)."""
PLUGIN_EXTS = ()


def applicability(payload_dir):
    return {"fomod": False, "dllvet": False, "esp": False}
```

`C:\Modding\tools\modkit\games\skyrim.py`:

```python
"""Skyrim SE preset (full). Paths (DATA_DIR etc.) are populated by
modkit.games.load() from modkit.json - never hardcode them here."""
from pathlib import Path

PLUGIN_EXTS = (".esp", ".esm", ".esl")
# Plugins.txt lines that must stay last (batch-append-after-DynDOLOD bug):
DYNDOLOD_BLOCK = ("dyndolod.esm", "dyndolod.esp", "occlusion.esp")


def applicability(payload_dir):
    """Computed at stage time from payload contents (design: state machine).
    dllvet fires on ANY .dll (superset of the spec's SKSE-path wording -
    wrong-layout archives drop DLLs at payload root; gate is warn-only)."""
    root = Path(payload_dir)
    rel = [str(p.relative_to(root)).lower().replace("\\", "/")
           for p in root.rglob("*") if p.is_file()]
    return {
        "fomod": any(r.endswith("fomod/moduleconfig.xml") for r in rel),
        "dllvet": any(r.endswith(".dll") for r in rel),
        "esp": any(r.endswith(PLUGIN_EXTS) for r in rel),
    }
```

`C:\Modding\tools\modkit\cli.py` (skeleton; each command task extends `build_parser` and adds its `cmd_*`):

```python
"""modkit CLI dispatch. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim

Exit codes: 0 clean/success, 1 error or verify findings, 2 warned (forceable gate).
"""
import argparse
import sys

from modkit import config


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


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


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as ex:
        safe_print(f"ERROR: {ex}")
        return 1
```

`C:\Modding\tools\modkit.py`:

```python
#!/usr/bin/env python3
"""modkit entry shim. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modkit.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

`C:\Modding\tools\modkit.json` (real machine values, verified in Ground-truth notes; committed — it is THE portability seam):

```json
{
    "sevenzip": "C:\\Program Files\\7-Zip\\7z.exe",
    "downloads": ["C:\\Users\\auand\\Downloads"],
    "staging_root": "C:\\Modding\\staging",
    "games": {
        "skyrim": {
            "data_dir": "E:\\SteamLibrary\\steamapps\\common\\Skyrim Special Edition\\Data",
            "plugins_txt": "C:\\Users\\auand\\AppData\\Local\\Skyrim Special Edition\\Plugins.txt",
            "process_names": ["SkyrimSE.exe", "skse64_loader.exe"],
            "runtime": "1.6.1170",
            "backups_dir": "C:\\Modding\\skyrim-manual\\backups",
            "manifests_dir": "C:\\Modding\\skyrim-manual\\manifests",
            "vortex_downloads": "C:\\Users\\auand\\AppData\\Roaming\\Vortex\\downloads\\skyrimse"
        },
        "cp77": {
            "data_dir": "E:\\SteamLibrary\\steamapps\\common\\Cyberpunk 2077",
            "plugins_txt": null,
            "process_names": ["Cyberpunk2077.exe"],
            "runtime": null,
            "backups_dir": "C:\\Modding\\cyberpunk-manual\\backups",
            "manifests_dir": "C:\\Modding\\cyberpunk-manual\\manifests",
            "vortex_downloads": "C:\\Users\\auand\\AppData\\Roaming\\Vortex\\downloads\\cyberpunk2077"
        },
        "kenshi": {
            "data_dir": null,
            "plugins_txt": null,
            "process_names": ["kenshi_x64.exe"],
            "runtime": null,
            "backups_dir": "C:\\Modding\\kenshi-manual\\backups",
            "manifests_dir": null,
            "vortex_downloads": null
        }
    }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `7 passed`

- [ ] **Step 6: Sanity-check the shim's help**

Run: `py -3 C:/Modding/tools/modkit.py --help`
Expected: usage text listing the global flags and (for now) an empty command set; exit 2 from argparse if no command given — acceptable until Task 4 registers the first command.

- [ ] **Step 7: Commit**

```bash
git -C "C:\Modding\tools" add modkit.py modkit.json modkit tests/test_modkit docs/2026-07-11-modkit-design.md docs/2026-07-11-modkit-plan.md
git -C "C:\Modding\tools" commit -m "feat(modkit): package skeleton, config loader, games preset registry" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: install.json state machine (`state.py`) with atomic writes

**Files:**
- Create: `C:\Modding\tools\modkit\state.py`
- Test: `C:\Modding\tools\tests\test_modkit\test_state.py`

**Interfaces:**
- Consumes: nothing from other modules (pure stdlib).
- Produces (pinned — later tasks depend on these exact names):
  - `modkit.state.InstallState.load(staging_dir: str) -> InstallState` — raises `state.StateError` if `install.json` missing/corrupt.
  - `InstallState.stamp(stage: str) -> None` — sets ISO timestamp on the stage + atomic save.
  - `InstallState.missing_applicable() -> list[str]` — applicable vet stages (`fomod`/`dllvet`/`esp`, per the `applicable` dict) plus always-applicable `conflicts`, that have no timestamp yet.
  - Also produced (used by Tasks 4–15): `InstallState.create(staging_dir, mod, game, archive, nexus_id=None, version=None, applicable=None) -> InstallState`, `InstallState.save()`, `.data` (the install.json dict), `state.STAGES`, `state.VET_STAGES`, `state.atomic_write_bytes(path, data: bytes) -> None`, `state.now_iso() -> str`, `state.payload_root(staging_dir) -> Path`, `state.latest_staging(preset) -> Path|None`, `state.slug(name: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_state.py`:

```python
import json
from pathlib import Path

import pytest

from modkit import state


def make_state(tmp_path, applicable=None):
    sd = tmp_path / "20260711-120000-test-mod"
    sd.mkdir()
    return state.InstallState.create(
        str(sd), mod="Test Mod", game="skyrim", archive=r"C:\dl\Test Mod-1-1-0.7z",
        nexus_id=1, version="1.0", applicable=applicable)


def test_create_writes_design_shape_and_load_roundtrips(tmp_path):
    st = make_state(tmp_path, {"fomod": False, "dllvet": True, "esp": True})
    raw = json.loads((st.staging_dir / "install.json").read_text(encoding="utf-8"))
    assert raw["mod"] == "Test Mod" and raw["game"] == "skyrim"
    assert set(raw["stages"]) == set(state.STAGES)
    assert all(v is None for v in raw["stages"].values())
    assert raw["applicable"] == {"fomod": False, "dllvet": True, "esp": True}
    assert raw["vet_results"] == {} and raw["files"] == []
    st2 = state.InstallState.load(str(st.staging_dir))
    assert st2.data == st.data


def test_stamp_sets_iso_timestamp_and_persists(tmp_path):
    st = make_state(tmp_path)
    st.stamp("staged")
    reloaded = state.InstallState.load(str(st.staging_dir))
    ts = reloaded.data["stages"]["staged"]
    assert ts and ts[:4].isdigit() and "T" in ts
    with pytest.raises(state.StateError):
        st.stamp("nonsense")


def test_missing_applicable_conflicts_always(tmp_path):
    st = make_state(tmp_path, {"fomod": False, "dllvet": True, "esp": True})
    assert st.missing_applicable() == ["dllvet", "esp", "conflicts"]
    st.stamp("dllvet")
    st.stamp("conflicts")
    assert st.missing_applicable() == ["esp"]
    st.stamp("esp")
    assert st.missing_applicable() == []


def test_atomic_write_leaves_no_temp(tmp_path):
    st = make_state(tmp_path)
    st.stamp("intake")
    leftovers = [p.name for p in st.staging_dir.iterdir() if ".tmp-" in p.name]
    assert leftovers == []


def test_load_missing_raises(tmp_path):
    with pytest.raises(state.StateError):
        state.InstallState.load(str(tmp_path))


def test_payload_root_prefers_payload_final(tmp_path):
    (tmp_path / "payload").mkdir()
    assert state.payload_root(tmp_path).name == "payload"
    (tmp_path / "payload_final").mkdir()
    assert state.payload_root(tmp_path).name == "payload_final"


def test_latest_staging_and_slug(tmp_path, preset):
    root = Path(preset.STAGING_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("20260701-010101-old-mod", "20260711-090909-new-mod"):
        d = root / name
        d.mkdir()
        (d / "install.json").write_text("{}", encoding="utf-8")
    (root / "not-a-staging").mkdir()
    assert state.latest_staging(preset).name == "20260711-090909-new-mod"
    assert state.slug("Simple Dual Sheath (v1.5) [SE]") == "Simple-Dual-Sheath-v1.5-SE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_state.py -q`
Expected: collection ERROR — `No module named 'modkit.state'`

- [ ] **Step 3: Implement `state.py`**

`C:\Modding\tools\modkit\state.py`:

```python
"""install.json state machine (design spec: approach C - stepwise subcommands +
per-install state). One InstallState per staging dir. All writes atomic."""
import datetime
import json
import os
import re
from pathlib import Path

STAGES = ("intake", "staged", "fomod", "dllvet", "esp", "conflicts",
          "deployed", "recorded", "verified")
VET_STAGES = ("fomod", "dllvet", "esp", "conflicts")


class StateError(Exception):
    """Missing/corrupt install.json or invalid stage name."""


def atomic_write_bytes(path, data):
    """temp + os.replace in the same dir - never a partial file."""
    path = Path(path)
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}"
    tmp.write_bytes(data)
    os.replace(tmp, path)


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def slug(name):
    out = re.sub(r"[^A-Za-z0-9.+-]+", "-", name.strip()).strip("-")
    return out or "mod"


def payload_root(staging_dir):
    """Deployable tree: payload_final\\ (FOMOD apply output, Task 6) wins over payload\\."""
    staging_dir = Path(staging_dir)
    final = staging_dir / "payload_final"
    return final if final.is_dir() else staging_dir / "payload"


def latest_staging(preset):
    """Most recent staging dir for the game (name-sorted; names start YYYYMMDD-HHMMSS)."""
    root = Path(preset.STAGING_ROOT)
    if not root.is_dir():
        return None
    dirs = sorted(d for d in root.iterdir()
                  if d.is_dir() and (d / "install.json").is_file())
    return dirs[-1] if dirs else None


class InstallState:
    def __init__(self, staging_dir, data):
        self.staging_dir = Path(staging_dir)
        self.data = data

    @classmethod
    def create(cls, staging_dir, mod, game, archive, nexus_id=None,
               version=None, applicable=None):
        data = {
            "mod": mod,
            "game": game,
            "archive": str(archive),
            "nexusId": nexus_id,
            "version": version,
            "stages": {s: None for s in STAGES},
            "applicable": applicable or {"fomod": False, "dllvet": False, "esp": False},
            "vet_results": {},
            "files": [],
        }
        st = cls(staging_dir, data)
        st.save()
        return st

    @classmethod
    def load(cls, staging_dir):
        p = Path(staging_dir) / "install.json"
        if not p.is_file():
            raise StateError(f"no install.json in {staging_dir} - run `modkit stage` first")
        try:
            data = json.loads(p.read_bytes().decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as ex:
            raise StateError(f"install.json unparseable: {p}: {ex}")
        return cls(staging_dir, data)

    def save(self):
        text = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        atomic_write_bytes(self.staging_dir / "install.json", text.encode("utf-8"))

    def stamp(self, stage):
        if stage not in STAGES:
            raise StateError(f"unknown stage {stage!r} (stages: {', '.join(STAGES)})")
        self.data["stages"][stage] = now_iso()
        self.save()

    def missing_applicable(self):
        """Applicable vet stages not yet stamped. `conflicts` is always applicable."""
        out = []
        for s in VET_STAGES:
            applicable = True if s == "conflicts" else bool(self.data["applicable"].get(s))
            if applicable and not self.data["stages"].get(s):
                out.append(s)
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `14 passed` (7 from Task 1 + 7 new)

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/state.py tests/test_modkit/test_state.py
git -C "C:\Modding\tools" commit -m "feat(modkit): install.json state machine with atomic writes" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `archive.py` — 7z wrapper (list / full-extract / count+size verify)

**Files:**
- Create: `C:\Modding\tools\modkit\archive.py`
- Test: `C:\Modding\tools\tests\test_modkit\test_archive.py`

**Interfaces:**
- Consumes: `preset.SEVENZIP` (Task 1) as the `sevenzip` argument.
- Produces (used by Tasks 4, 5): `archive.listing(sevenzip, archive_path) -> list[dict]` (each `{"path": str, "size": int, "is_dir": bool}`), `archive.extract_all(sevenzip, archive_path, dest) -> None`, `archive.verify_extraction(entries: list[dict], dest) -> list[str]` (problems; `[]` = OK), `archive.parse_slt(text) -> list[dict]`, `archive.ArchiveError`.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_archive.py`:

```python
import zipfile
from pathlib import Path

import pytest

from modkit import archive

SEVENZIP = Path(r"C:\Program Files\7-Zip\7z.exe")
needs_7z = pytest.mark.skipif(not SEVENZIP.is_file(), reason="7z.exe not installed")

CANNED_SLT = (
    "Path = readme.txt\nSize = 5\nAttributes = A\n\n"
    "Path = meshes\nSize = 0\nAttributes = D\n\n"
    "Path = meshes\\a.nif\nSize = 10\nAttributes = A\n"
)


def make_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "hello")
        z.writestr("meshes/a.nif", "0123456789")
    return path


def test_parse_slt_files_and_dirs():
    entries = archive.parse_slt(CANNED_SLT)
    assert len(entries) == 3
    files = [e for e in entries if not e["is_dir"]]
    assert [(e["path"], e["size"]) for e in files] == [
        ("readme.txt", 5), ("meshes\\a.nif", 10)]


@needs_7z
def test_listing_extract_verify_roundtrip(tmp_path):
    arc = make_zip(tmp_path / "Mod-1-1-0.zip")
    entries = archive.listing(SEVENZIP, arc)
    assert sorted(e["path"].replace("\\", "/") for e in entries if not e["is_dir"]) == [
        "meshes/a.nif", "readme.txt"]
    dest = tmp_path / "payload"
    archive.extract_all(SEVENZIP, arc, dest)
    assert archive.verify_extraction(entries, dest) == []


@needs_7z
def test_verify_detects_missing_and_size_mismatch(tmp_path):
    arc = make_zip(tmp_path / "Mod-1-1-0.zip")
    entries = archive.listing(SEVENZIP, arc)
    dest = tmp_path / "payload"
    archive.extract_all(SEVENZIP, arc, dest)
    (dest / "readme.txt").unlink()
    (dest / "meshes" / "a.nif").write_bytes(b"xx")
    problems = archive.verify_extraction(entries, dest)
    assert any("missing" in p and "readme.txt" in p for p in problems)
    assert any("size mismatch" in p for p in problems)


def test_missing_7z_raises(tmp_path):
    with pytest.raises(archive.ArchiveError):
        archive.listing(tmp_path / "no7z.exe", tmp_path / "x.zip")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_archive.py -q`
Expected: collection ERROR — `No module named 'modkit.archive'`

- [ ] **Step 3: Implement `archive.py`**

`C:\Modding\tools\modkit\archive.py`:

```python
"""7z wrapper: list / FULL extract / count+size verify.
Never include-pattern extracts (4 recorded include-pattern failures; the
Genesis 1-file-stub burn is exactly what verify_extraction() catches)."""
import subprocess
from pathlib import Path


class ArchiveError(Exception):
    """7z missing, non-zero exit, or unreadable archive."""


def _run(sevenzip, args):
    if not Path(sevenzip).is_file():
        raise ArchiveError(f"7z.exe not found: {sevenzip} (fix modkit.json 'sevenzip')")
    proc = subprocess.run([str(sevenzip), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_slt(text):
    """Parse `7z l -slt -ba` blocks -> [{"path", "size", "is_dir"}]."""
    entries, cur = [], {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if cur.get("Path"):
                entries.append(cur)
            cur = {}
            continue
        if " = " in line:
            k, _, v = line.partition(" = ")
            cur[k] = v
    if cur.get("Path"):
        entries.append(cur)
    out = []
    for e in entries:
        is_dir = "D" in e.get("Attributes", "") or e.get("Folder") == "+"
        size = int(e["Size"]) if e.get("Size", "").isdigit() else 0
        out.append({"path": e["Path"], "size": size, "is_dir": is_dir})
    return out


def listing(sevenzip, archive_path):
    code, out = _run(sevenzip, ["l", "-slt", "-ba", str(archive_path)])
    if code != 0:
        raise ArchiveError(f"7z l failed ({code}) on {archive_path}:\n{out[-2000:]}")
    return parse_slt(out)


def extract_all(sevenzip, archive_path, dest):
    """FULL extract to dest. Callers pass a FRESH timestamped staging payload dir."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    code, out = _run(sevenzip, ["x", "-y", f"-o{dest}", str(archive_path)])
    if code != 0:
        raise ArchiveError(f"7z x failed ({code}) on {archive_path}:\n{out[-2000:]}")


def verify_extraction(entries, dest):
    """Every listed file must exist at dest with the listed size. [] = OK."""
    dest = Path(dest)
    problems = []
    for e in entries:
        if e["is_dir"]:
            continue
        target = dest / e["path"]
        if not target.is_file():
            problems.append(f"missing after extract: {e['path']}")
        elif target.stat().st_size != e["size"]:
            problems.append(f"size mismatch: {e['path']} (archive {e['size']}, "
                            f"disk {target.stat().st_size})")
    return problems
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `18 passed` (on this machine 7z exists, so nothing skips)

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/archive.py tests/test_modkit/test_archive.py
git -C "C:\Modding\tools" commit -m "feat(modkit): 7z wrapper with full-extract and count/size verify" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `intake` command (+ `ledger_bridge.py`, pulled forward)

> Adjustment vs. the rough breakdown: `ledger_bridge.py` is created here (not Task 11) because intake's already-installed check needs it. Task 11 consumes it unchanged.

**Files:**
- Create: `C:\Modding\tools\modkit\ledger_bridge.py`
- Modify: `C:\Modding\tools\modkit\games\__init__.py` (one attribute line)
- Modify: `C:\Modding\tools\modkit\cli.py` (add `parse_nexus_filename`, `cmd_intake`, registration)
- Modify: `C:\Modding\tools\tests\test_modkit\conftest.py` (ledger fixture + `run_cli`)
- Test: `C:\Modding\tools\tests\test_modkit\test_intake.py`

**Interfaces:**
- Consumes: `config`/preset attrs (Task 1), `archive.listing` (Task 3), `games.guess_game` (Task 1).
- Produces (pinned signature): `modkit.ledger_bridge.run(args: list[str]) -> tuple[int, str]` — runs `ledger.py` as a subprocess, returns (exit_code, combined stdout+stderr). `MODKIT_LEDGER` env overrides the script path.
- Also produces: `ledger_bridge.game_args(preset) -> list[str]` (returns `["--ledger", preset.LEDGER]` when the game config sets `"ledger"`, else `["--game", preset.NAME]` — this is how tests point at a fixture ledger without touching the real one); `cli.parse_nexus_filename(fname: str) -> dict|None` (`{"name", "modid": int, "version"}`); preset attr `LEDGER` (str or None).

- [ ] **Step 1: Extend the conftest fixtures**

In `C:\Modding\tools\tests\test_modkit\conftest.py`, inside `game_env` after the `plugins.write_bytes(...)` call, add a fixture ledger the real `ledger.py` can read (header paths point at the synthetic tree):

```python
    ledger_json = root / "ledger.json"
    ledger_json.write_text(json.dumps({
        "game": "Skyrim Special Edition",
        "dataDir": str(root / "Data"),
        "pluginsTxt": str(plugins),
        "mods": [{"name": "Already Installed Mod", "installed": "2026-07-01"}],
    }), encoding="utf-8")
```

In the same function add `"ledger": str(ledger_json),` to the `"skyrim"` game dict (any position). Then append two module-level additions at the end of conftest.py:

```python
SEVENZIP = Path(r"C:\Program Files\7-Zip\7z.exe")
needs_7z = pytest.mark.skipif(not SEVENZIP.is_file(), reason="7z.exe not installed")


@pytest.fixture
def run_cli(capsys):
    from modkit import cli

    def _run(*argv):
        code = cli.main(list(argv))
        return code, capsys.readouterr().out
    return _run
```

- [ ] **Step 2: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_intake.py`:

```python
import zipfile
from pathlib import Path

from conftest import needs_7z

from modkit.cli import parse_nexus_filename


def dl_zip(game_env, fname, members):
    p = game_env / "downloads" / fname
    with zipfile.ZipFile(p, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return p


def test_parse_nexus_filename():
    m = parse_nexus_filename("Simple Dual Sheath-50049-1-5-2-1170.7z")
    assert m == {"name": "Simple Dual Sheath", "modid": 50049, "version": "1.5.2.1170"}
    m = parse_nexus_filename("Some Mod-123-2-0-1712345678.zip")
    assert m["modid"] == 123 and m["version"] == "2.0"
    assert parse_nexus_filename("random-archive.zip") is None


def test_intake_flags_zero_byte(game_env, run_cli):
    (game_env / "downloads" / "Broken Mod-99-1-0.7z").write_bytes(b"")
    code, out = run_cli("intake", "--game", "skyrim")
    assert code == 2
    assert "0-byte" in out


@needs_7z
def test_intake_wrong_game_gate(game_env, run_cli):
    dl_zip(game_env, "Totally Skyrim-777-1-0.zip",
           {"Data/F4SE/Plugins/thing.dll": "MZ", "Data/Mod.esp": "TES4"})
    code, out = run_cli("intake", "--game", "skyrim")
    assert code == 2
    assert "fallout4" in out and "wrong-game" in out


@needs_7z
def test_intake_already_installed_flags_warn(game_env, run_cli):
    arc = dl_zip(game_env, "Already Installed Mod-123-1-0.zip", {"Mod.esp": "TES4"})
    code, out = run_cli("intake", str(arc), "--game", "skyrim")
    assert code == 2
    assert "already in ledger" in out


@needs_7z
def test_intake_clean_single_path_exits_zero(game_env, run_cli):
    fresh = dl_zip(game_env, "Fresh Mod-456-2-0.zip", {"Fresh.esp": "TES4"})
    code, out = run_cli("intake", str(fresh), "--game", "skyrim")
    assert code == 0
    assert "Fresh Mod" in out and "skyrim" in out
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_intake.py -q`
Expected: ImportError — `cannot import name 'parse_nexus_filename' from 'modkit.cli'`

- [ ] **Step 4: Implement**

`C:\Modding\tools\modkit\ledger_bridge.py`:

```python
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
```

In `C:\Modding\tools\modkit\games\__init__.py`, inside `load()` after the `mod.SEVENZIP = cfg["sevenzip"]` line, add:

```python
    mod.LEDGER = g.get("ledger")
```

In `C:\Modding\tools\modkit\cli.py`, add imports at top (`import re`, `import datetime`, `from pathlib import Path`) and add:

```python
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
```

And make `_register_all` read:

```python
def _register_all(sub, common):
    """Each task appends its register_<cmd>(sub, common) call here."""
    register_intake(sub, common)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `23 passed`

- [ ] **Step 6: Commit**

```bash
git -C "C:\Modding\tools" add modkit tests/test_modkit
git -C "C:\Modding\tools" commit -m "feat(modkit): intake command with wrong-game gate + ledger bridge" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `stage` command (full-extract to fresh staging + verify + install.json)

**Files:**
- Modify: `C:\Modding\tools\modkit\cli.py`
- Test: `C:\Modding\tools\tests\test_modkit\test_stage.py`

**Interfaces:**
- Consumes: `archive.listing/extract_all/verify_extraction` (Task 3), `state.InstallState.create/stamp`, `state.slug` (Task 2), `preset.applicability` + `STAGING_ROOT` (Task 1), `cli.parse_nexus_filename` (Task 4).
- Produces: `cli.cmd_stage` — creates `<STAGING_ROOT>\<YYYYMMDD-HHMMSS>-<modslug>\payload\` + `install.json` with stages `intake` and `staged` stamped; prints the staging path on the `staged:` line (Tasks 6–14 operate on this dir).

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_stage.py`:

```python
import json
import zipfile
from pathlib import Path

from conftest import needs_7z


def make_archive(game_env, fname, members):
    p = game_env / "downloads" / fname
    with zipfile.ZipFile(p, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return p


@needs_7z
def test_stage_creates_staging_with_state(game_env, run_cli):
    arc = make_archive(game_env, "Cool Mod-42-1-2.zip", {
        "Cool.esp": "TES4xxxx",
        "SKSE/Plugins/cool.dll": "MZxxxx",
        "fomod/ModuleConfig.xml": "<config/>",
        "meshes/c.nif": "NIF",
    })
    code, out = run_cli("stage", str(arc), "--game", "skyrim")
    assert code == 0
    staged_line = [l for l in out.splitlines() if l.startswith("staged: ")][0]
    staging = Path(staged_line.split("staged: ", 1)[1])
    assert staging.parent == game_env / "staging" / "skyrim"
    assert staging.name.endswith("-Cool-Mod")
    st = json.loads((staging / "install.json").read_text(encoding="utf-8"))
    assert st["mod"] == "Cool Mod" and st["nexusId"] == 42 and st["version"] == "1.2"
    assert st["applicable"] == {"fomod": True, "dllvet": True, "esp": True}
    assert st["stages"]["intake"] and st["stages"]["staged"]
    assert st["stages"]["deployed"] is None
    assert (staging / "payload" / "meshes" / "c.nif").is_file()


@needs_7z
def test_stage_name_override_and_plain_archive(game_env, run_cli):
    arc = make_archive(game_env, "weird-name.zip", {"textures/t.dds": "DDS"})
    code, out = run_cli("stage", str(arc), "--game", "skyrim", "--name", "Weird Mod")
    assert code == 0
    staging = Path(out.split("staged: ", 1)[1].splitlines()[0])
    st = json.loads((staging / "install.json").read_text(encoding="utf-8"))
    assert st["mod"] == "Weird Mod" and st["nexusId"] is None
    assert st["applicable"] == {"fomod": False, "dllvet": False, "esp": False}


def test_stage_missing_archive_errors(game_env, run_cli):
    code, out = run_cli("stage", str(game_env / "nope.7z"), "--game", "skyrim")
    assert code == 1
    assert "no such archive" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_stage.py -q`
Expected: FAIL — argparse error `invalid choice: 'stage'` (exits 2 via SystemExit; pytest reports the failure)

- [ ] **Step 3: Implement `cmd_stage`**

Add to `C:\Modding\tools\modkit\cli.py`:

```python
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
```

Append `register_stage(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `26 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/cli.py tests/test_modkit/test_stage.py
git -C "C:\Modding\tools" commit -m "feat(modkit): stage command - full extract, verify, install.json" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `fomod.py` — ModuleConfig.xml parse + picks apply

FOMOD is a judgment gate: modkit **parses** the option tree (JSON to stdout for Claude/user to choose from) and **materializes** the chosen picks; it never chooses. Picks land in `payload_final\` so the raw extract stays untouched; `state.payload_root()` (Task 2) makes every later command prefer `payload_final\`.

**Files:**
- Create: `C:\Modding\tools\modkit\fomod.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `_staging_for`, `cmd_fomod`, registration, `import json`)
- Test: `C:\Modding\tools\tests\test_modkit\test_fomod.py`

**Interfaces:**
- Consumes: `state.InstallState.load/stamp`, `state.latest_staging`, `state.payload_root` (Task 2).
- Produces (used by Task 16's skill text and later commands): `fomod.parse(payload_dir) -> dict` (tree: `moduleName`, `required`, `steps[].groups[].plugins[]`, `conditional`), `fomod.apply(payload_dir, staging_dir, picks: dict) -> int` (file count materialized into `<staging>\payload_final\`), `fomod.FomodError`, `cli._staging_for(args, preset) -> Path` (`--staging` flag or latest staging dir — every staging-scoped command from here on uses it). Picks format: `{"<step name>::<group name>": ["Plugin Name", ...]}`.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_fomod.py`:

```python
import json
from pathlib import Path

import pytest

from modkit import fomod

MODULE_XML = """<config xmlns="http://qconsulting.ca/fo3/ModConfig5.0.xsd">
  <moduleName>Cool Mod</moduleName>
  <requiredInstallFiles>
    <folder source="core" destination="" />
  </requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Main">
      <optionalFileGroups order="Explicit">
        <group name="Variant" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Red">
              <description>red one</description>
              <files><folder source="opt-red" destination="textures" /></files>
              <conditionFlags><flag name="red">On</flag></conditionFlags>
            </plugin>
            <plugin name="Blue">
              <description>blue one</description>
              <files><folder source="opt-blue" destination="textures" /></files>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
  <conditionalFileInstalls>
    <patterns>
      <pattern>
        <dependencies operator="And">
          <flagDependency flag="red" value="On" />
        </dependencies>
        <files><file source="extras/red-extra.ini" destination="red-extra.ini" /></files>
      </pattern>
    </patterns>
  </conditionalFileInstalls>
</config>"""


@pytest.fixture
def fomod_staging(tmp_path):
    staging = tmp_path / "20260711-000000-cool-mod"
    pay = staging / "payload"
    (pay / "fomod").mkdir(parents=True)
    (pay / "fomod" / "ModuleConfig.xml").write_text(MODULE_XML, encoding="utf-8")
    (pay / "core").mkdir()
    (pay / "core" / "Cool.esp").write_text("TES4")
    (pay / "opt-red").mkdir()
    (pay / "opt-red" / "red.dds").write_text("RED")
    (pay / "opt-blue").mkdir()
    (pay / "opt-blue" / "blue.dds").write_text("BLUE")
    (pay / "extras").mkdir()
    (pay / "extras" / "red-extra.ini").write_text("[x]")
    return staging, pay


def test_parse_tree_shape(fomod_staging):
    _, pay = fomod_staging
    tree = fomod.parse(pay)
    assert tree["moduleName"] == "Cool Mod"
    assert tree["required"][0] == {"kind": "folder", "source": "core", "destination": ""}
    grp = tree["steps"][0]["groups"][0]
    assert grp["type"] == "SelectExactlyOne"
    assert [p["name"] for p in grp["plugins"]] == ["Red", "Blue"]
    assert grp["plugins"][0]["flags"] == {"red": "On"}
    assert tree["conditional"][0]["flags"] == {"red": "On"}


def test_apply_red_materializes_required_pick_and_conditional(fomod_staging):
    staging, pay = fomod_staging
    count = fomod.apply(pay, staging, {"Main::Variant": ["Red"]})
    final = staging / "payload_final"
    assert (final / "Cool.esp").is_file()
    assert (final / "textures" / "red.dds").is_file()
    assert (final / "red-extra.ini").is_file()
    assert not (final / "textures" / "blue.dds").exists()
    assert count == 3


def test_apply_blue_skips_conditional(fomod_staging):
    staging, pay = fomod_staging
    fomod.apply(pay, staging, {"Main::Variant": ["Blue"]})
    final = staging / "payload_final"
    assert (final / "textures" / "blue.dds").is_file()
    assert not (final / "red-extra.ini").exists()


def test_apply_validates_picks(fomod_staging):
    staging, pay = fomod_staging
    with pytest.raises(fomod.FomodError):
        fomod.apply(pay, staging, {"Main::Variant": ["Green"]})
    with pytest.raises(fomod.FomodError):
        fomod.apply(pay, staging, {"Main::Variant": []})  # SelectExactlyOne needs 1


def test_parse_missing_config_raises(tmp_path):
    with pytest.raises(fomod.FomodError):
        fomod.parse(tmp_path)


def test_cli_fomod_print_and_apply(game_env, preset, run_cli, fomod_staging, tmp_path):
    import shutil
    from modkit import state as mstate
    src_staging, src_pay = fomod_staging
    root = Path(preset.STAGING_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / "20260711-000000-cool-mod"
    shutil.copytree(src_staging, staging)
    mstate.InstallState.create(str(staging), mod="Cool Mod", game="skyrim",
                               archive=r"C:\dl\Cool Mod-1-1-0.7z",
                               applicable={"fomod": True, "dllvet": False, "esp": True})
    code, out = run_cli("fomod", "--game", "skyrim", "--staging", str(staging))
    assert code == 0
    assert json.loads(out)["moduleName"] == "Cool Mod"
    picks = tmp_path / "picks.json"
    picks.write_text(json.dumps({"Main::Variant": ["Red"]}), encoding="utf-8")
    code, out = run_cli("fomod", "--game", "skyrim", "--staging", str(staging),
                        "--apply", str(picks))
    assert code == 0
    st = mstate.InstallState.load(str(staging))
    assert st.data["stages"]["fomod"]
    assert st.data["vet_results"]["fomod"]["files"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_fomod.py -q`
Expected: collection ERROR — `No module named 'modkit.fomod'`

- [ ] **Step 3: Implement `fomod.py`**

`C:\Modding\tools\modkit\fomod.py`:

```python
"""FOMOD ModuleConfig.xml parse + picks apply. Covers the real-world subset:
requiredInstallFiles, installSteps/optionalFileGroups/plugins (files, folders,
conditionFlags), conditionalFileInstalls flag patterns. Namespace-tolerant.
Choosing picks is a judgment gate - Claude/user decide, modkit materializes."""
import shutil
from pathlib import Path
from xml.etree import ElementTree


class FomodError(Exception):
    """No/invalid ModuleConfig.xml, or picks that don't fit the tree."""


def find_config(payload_dir):
    """Locate fomod/ModuleConfig.xml under payload (case-insensitive)."""
    for p in Path(payload_dir).rglob("*"):
        if (p.is_file() and p.name.lower() == "moduleconfig.xml"
                and p.parent.name.lower() == "fomod"):
            return p
    return None


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _files_of(node):
    out = []
    if node is None:
        return out
    for child in node:
        kind = _local(child.tag)
        if kind in ("file", "folder"):
            out.append({"kind": kind, "source": child.get("source", ""),
                        "destination": child.get("destination", "")})
    return out


def parse(payload_dir):
    cfg_path = find_config(payload_dir)
    if cfg_path is None:
        raise FomodError(f"no fomod/ModuleConfig.xml under {payload_dir}")
    try:
        root = ElementTree.parse(cfg_path).getroot()
    except ElementTree.ParseError as ex:
        raise FomodError(f"ModuleConfig.xml unparseable: {ex}")
    tree = {"moduleName": "", "required": [], "steps": [], "conditional": []}
    for node in root:
        tag = _local(node.tag)
        if tag == "modulename":
            tree["moduleName"] = (node.text or "").strip()
        elif tag == "requiredinstallfiles":
            tree["required"] = _files_of(node)
        elif tag == "installsteps":
            for step in node:
                if _local(step.tag) != "installstep":
                    continue
                s = {"name": step.get("name", ""), "groups": []}
                for ofg in step:
                    if _local(ofg.tag) != "optionalfilegroups":
                        continue
                    for grp in ofg:
                        if _local(grp.tag) != "group":
                            continue
                        g = {"name": grp.get("name", ""),
                             "type": grp.get("type", "SelectAny"), "plugins": []}
                        for plugs in grp:
                            if _local(plugs.tag) != "plugins":
                                continue
                            for plug in plugs:
                                if _local(plug.tag) != "plugin":
                                    continue
                                pl = {"name": plug.get("name", ""), "description": "",
                                      "files": [], "flags": {}}
                                for item in plug:
                                    it = _local(item.tag)
                                    if it == "description":
                                        pl["description"] = (item.text or "").strip()
                                    elif it == "files":
                                        pl["files"] = _files_of(item)
                                    elif it == "conditionflags":
                                        for fl in item:
                                            if _local(fl.tag) == "flag":
                                                pl["flags"][fl.get("name", "")] = \
                                                    (fl.text or "").strip()
                                g["plugins"].append(pl)
                        s["groups"].append(g)
                tree["steps"].append(s)
        elif tag == "conditionalfileinstalls":
            for patterns in node:
                if _local(patterns.tag) != "patterns":
                    continue
                for pat in patterns:
                    if _local(pat.tag) != "pattern":
                        continue
                    entry = {"flags": {}, "files": []}
                    for part in pat:
                        pt = _local(part.tag)
                        if pt == "dependencies":
                            for dep in part.iter():
                                if _local(dep.tag) == "flagdependency":
                                    entry["flags"][dep.get("flag", "")] = dep.get("value", "")
                        elif pt == "files":
                            entry["files"] = _files_of(part)
                    tree["conditional"].append(entry)
    return tree


def selected_plugins(tree, picks):
    """Resolve picks -> plugin dicts. Enforces group-type cardinality."""
    chosen = []
    for step in tree["steps"]:
        for group in step["groups"]:
            key = f"{step['name']}::{group['name']}"
            names = list(picks.get(key, []))
            by_name = {p["name"]: p for p in group["plugins"]}
            for n in names:
                if n not in by_name:
                    raise FomodError(f"pick {n!r} not in group {key!r} "
                                     f"(options: {', '.join(by_name)})")
            gtype = group["type"].lower()
            if gtype == "selectexactlyone" and len(names) != 1:
                raise FomodError(f"group {key!r} is SelectExactlyOne - got {len(names)} picks")
            if gtype == "selectatmostone" and len(names) > 1:
                raise FomodError(f"group {key!r} is SelectAtMostOne - got {len(names)} picks")
            if gtype == "selectall":
                names = list(by_name)
            chosen += [by_name[n] for n in names]
    return chosen


def apply(payload_dir, staging_dir, picks):
    """Materialize required + picked + flag-matched conditional files into
    <staging_dir>\\payload_final\\ (Data-relative). Returns file count."""
    payload_dir = Path(payload_dir)
    tree = parse(payload_dir)
    chosen = selected_plugins(tree, picks)
    flags = {}
    for p in chosen:
        flags.update(p["flags"])
    file_specs = list(tree["required"])
    for p in chosen:
        file_specs += p["files"]
    for cond in tree["conditional"]:
        if cond["flags"] and all(flags.get(k) == v for k, v in cond["flags"].items()):
            file_specs += cond["files"]
    dest_root = Path(staging_dir) / "payload_final"
    if dest_root.exists():
        shutil.rmtree(dest_root)  # staging-only tree; safe to rebuild on re-apply
    dest_root.mkdir(parents=True)
    src_base = find_config(payload_dir).parent.parent
    count = 0
    for spec in file_specs:
        src = src_base / spec["source"].replace("\\", "/").rstrip("/")
        dst_rel = spec["destination"].replace("\\", "/").lstrip("/")
        if spec["kind"] == "folder":
            if not src.is_dir():
                raise FomodError(f"folder source missing: {spec['source']}")
            for f in src.rglob("*"):
                if f.is_file():
                    target = dest_root / dst_rel / f.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
                    count += 1
        else:
            if not src.is_file():
                raise FomodError(f"file source missing: {spec['source']}")
            target = (dest_root / dst_rel) if dst_rel else (dest_root / src.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            count += 1
    return count
```

- [ ] **Step 4: Implement the CLI command**

In `C:\Modding\tools\modkit\cli.py` add `import json` at the top, then:

```python
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
```

Append `register_fomod(sub, common)` to `_register_all`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `32 passed`

- [ ] **Step 6: Commit**

```bash
git -C "C:\Modding\tools" add modkit/fomod.py modkit/cli.py tests/test_modkit/test_fomod.py
git -C "C:\Modding\tools" commit -m "feat(modkit): FOMOD parse + picks apply into payload_final" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `tes4.py` — ESP/ESM/ESL header parse + `esp` command

**Files:**
- Create: `C:\Modding\tools\modkit\tes4.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_esp`, registration)
- Modify: `C:\Modding\tools\tests\test_modkit\conftest.py` (add `make_staging` fixture)
- Test: `C:\Modding\tools\tests\test_modkit\test_tes4.py`

**Interfaces:**
- Consumes: `state` (Task 2), `cli._staging_for` (Task 6), preset `DATA_DIR`/`PLUGIN_EXTS`.
- Produces (used by Tasks 13, 19): `tes4.parse_header(path) -> dict` with keys `plugin` (filename), `masters` (list[str]), `esl` (bool, flag 0x200), `esm` (bool, flag 0x1), `version` (float|None, HEDR), `author` (str); `tes4.Tes4Error`.
- Resolution of a spec gap: the missing-master check tests **file presence** in Data\ (or in the payload itself). Enable-state of masters lives in Plugins.txt and is covered by `plugins list` (Task 9), `verify`, and `ledger.py check` — the esp gate is warn-only either way.

- [ ] **Step 1: Add the shared `make_staging` fixture**

Append to `C:\Modding\tools\tests\test_modkit\conftest.py` (Tasks 8/10/11/12/13 reuse it):

```python
@pytest.fixture
def make_staging(preset):
    from modkit import state as mstate

    def _make(files, mod="Test Mod", applicable=None, nexus_id=77, version="1.0"):
        root = Path(preset.STAGING_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        sd = root / f"20260711-000000-{mstate.slug(mod)}"
        sd.mkdir()
        pay = sd / "payload"
        pay.mkdir()
        for rel, content in files.items():
            f = pay / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content if isinstance(content, bytes) else content.encode())
        st = mstate.InstallState.create(
            str(sd), mod=mod, game="skyrim", archive=r"C:\dl\x-77-1-0.7z",
            nexus_id=nexus_id, version=version,
            applicable=applicable if applicable is not None
            else preset.applicability(str(pay)))
        st.stamp("intake")
        st.stamp("staged")
        return sd
    return _make
```

- [ ] **Step 2: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_tes4.py`:

```python
import struct

import pytest

from modkit import tes4


def make_tes4(masters=(), esl=False, esm=False):
    """Minimal TES4 record: 24-byte record header + HEDR/MAST/DATA subrecords."""
    body = b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 1, 0x800)
    for m in masters:
        mb = m.encode("cp1252") + b"\x00"
        body += b"MAST" + struct.pack("<H", len(mb)) + mb
        body += b"DATA" + struct.pack("<H", 8) + b"\x00" * 8
    flags = (0x200 if esl else 0) | (0x1 if esm else 0)
    return (b"TES4" + struct.pack("<I", len(body)) + struct.pack("<I", flags)
            + b"\x00" * 12 + body)


def test_parse_masters_and_flags(tmp_path):
    p = tmp_path / "Mod.esp"
    p.write_bytes(make_tes4(masters=("Skyrim.esm", "Update.esm"), esl=True))
    hdr = tes4.parse_header(p)
    assert hdr["masters"] == ["Skyrim.esm", "Update.esm"]
    assert hdr["esl"] is True and hdr["esm"] is False
    assert hdr["version"] == 1.71


def test_parse_rejects_non_plugin(tmp_path):
    p = tmp_path / "notaplugin.esp"
    p.write_bytes(b"JUNKJUNKJUNK")
    with pytest.raises(tes4.Tes4Error):
        tes4.parse_header(p)


def test_esp_cmd_clean_when_masters_present(game_env, preset, make_staging, run_cli):
    (game_env / "Data" / "Skyrim.esm").write_bytes(b"x")
    sd = make_staging({"Mod.esp": make_tes4(masters=("Skyrim.esm",))}, mod="Clean Esp")
    code, out = run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "Skyrim.esm" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["esp"]
    assert st.data["vet_results"]["esp"]["Mod.esp"]["missing"] == []


def test_esp_cmd_warns_on_missing_master(game_env, preset, make_staging, run_cli):
    sd = make_staging({"Mod.esp": make_tes4(masters=("NotInstalled.esm",))},
                      mod="Broken Esp")
    code, out = run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "missing master" in out and "NotInstalled.esm" in out
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_tes4.py -q`
Expected: collection ERROR — `No module named 'modkit.tes4'`

- [ ] **Step 4: Implement**

`C:\Modding\tools\modkit\tes4.py`:

```python
"""TES4 (ESP/ESM/ESL) header parse: masters, ESL flag (0x200), version, author.
File-is-ground-truth: masters come from the header, never the Nexus page.
Record header (SSE): type(4) size(4) flags(4) formid(4) vc(4) version(2) unk(2) = 24."""
import struct
from pathlib import Path

ESM_FLAG = 0x00000001
ESL_FLAG = 0x00000200


class Tes4Error(Exception):
    """Not a TES4 plugin or truncated header."""


def parse_header(path):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:4] != b"TES4":
        raise Tes4Error(f"not a TES4 plugin: {path.name}")
    size = struct.unpack_from("<I", raw, 4)[0]
    flags = struct.unpack_from("<I", raw, 8)[0]
    body = raw[24:24 + size]
    masters, author, version = [], "", None
    off = 0
    while off + 6 <= len(body):
        stype = body[off:off + 4]
        ssize = struct.unpack_from("<H", body, off + 4)[0]
        data = body[off + 6:off + 6 + ssize]
        if stype == b"MAST":
            masters.append(data.rstrip(b"\x00").decode("cp1252", "replace"))
        elif stype == b"CNAM":
            author = data.rstrip(b"\x00").decode("cp1252", "replace")
        elif stype == b"HEDR" and ssize >= 4:
            version = round(struct.unpack_from("<f", data, 0)[0], 2)
        off += 6 + ssize
    return {"plugin": path.name, "masters": masters,
            "esl": bool(flags & ESL_FLAG), "esm": bool(flags & ESM_FLAG),
            "version": version, "author": author}
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
def cmd_esp(args):
    from modkit import state, tes4
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = state.payload_root(staging)
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
```

Append `register_esp(sub, common)` to `_register_all`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `36 passed`

- [ ] **Step 6: Commit**

```bash
git -C "C:\Modding\tools" add modkit/tes4.py modkit/cli.py tests/test_modkit
git -C "C:\Modding\tools" commit -m "feat(modkit): TES4 header parse + esp vet command" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `peparse.py` — PE/DLL parse + `dllvet` command

The AE-era SKSE plugin interface exports a static `SKSEPlugin_Version` struct declaring compatible runtimes and Address-Library independence — parse it directly. Pre-AE plugins export only `SKSEPlugin_Query` (typically 1.5.97-era) — those get a RESEARCH verdict (judgment gate: Claude researches an NG/AE build before deploy). Non-SKSE DLLs (ENB, preloaders) get INFO.

**Files:**
- Create: `C:\Modding\tools\modkit\peparse.py`
- Create: `C:\Modding\tools\tests\test_modkit\pebuild.py` (test-only PE fixture builder)
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_dllvet`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_dllvet.py`

**Interfaces:**
- Consumes: `state`, `cli._staging_for`, preset `RUNTIME`.
- Produces (used by Task 16 skill text): `peparse.PEFile(path)` with `.machine` (`"x64"`/`"x86"`/hex str), `.exports() -> dict[str, int]` (name -> RVA), `.read(rva, size) -> bytes`; `peparse.skse_version_data(pe) -> dict|None` (`{"name", "address_independent": bool, "compatible": list[int]}`); `peparse.encode_runtime(version: str) -> int`; `peparse.decode_runtime(value: int) -> str`; `peparse.scan_markers(path) -> dict` (`{"address_library": bool}`); `peparse.PeError`.

- [ ] **Step 1: Write the PE fixture builder**

`C:\Modding\tools\tests\test_modkit\pebuild.py`:

```python
"""Craft a minimal PE32+ DLL with an export table - just enough to exercise
modkit.peparse. One section (.rdata) at RVA 0x1000 / raw offset 0x400."""
import struct

SEC_RVA, SEC_RAW = 0x1000, 0x400


def skse_version_blob(compatible=(), independent=0, name="TestPlugin"):
    """SKSE PluginVersionData (848 bytes): dataVersion=1 @0, name @8,
    versionIndependence @776, compatibleVersions[16] @780 (0-terminated)."""
    raw = bytearray(848)
    struct.pack_into("<II", raw, 0, 1, 0x01000000)
    raw[8:8 + len(name)] = name.encode("ascii")
    struct.pack_into("<I", raw, 776, independent)
    for i, v in enumerate(list(compatible)[:16]):
        struct.pack_into("<I", raw, 780 + i * 4, v)
    return bytes(raw)


def build_dll(exports=None, extra=b"", machine=0x8664):
    """exports: {name: data_bytes} exported by name. Returns PE file bytes."""
    exports = dict(exports or {})
    blob = bytearray()

    def put(data):
        off = len(blob)
        blob.extend(data)
        return SEC_RVA + off

    edir_rva = None
    if exports:
        edir_rva = put(b"\x00" * 40)
        n = len(exports)
        data_rvas = [put(d) for d in exports.values()]
        name_rvas = [put(k.encode("ascii") + b"\x00") for k in exports]
        eat = put(b"".join(struct.pack("<I", r) for r in data_rvas))
        enpt = put(b"".join(struct.pack("<I", r) for r in name_rvas))
        eot = put(b"".join(struct.pack("<H", i) for i in range(n)))
        base = edir_rva - SEC_RVA
        struct.pack_into("<II", blob, base + 20, n, n)
        struct.pack_into("<III", blob, base + 28, eat, enpt, eot)
    if extra:
        put(extra)
    vsize = max(len(blob), 1)
    raw_size = (vsize + 0x1FF) & ~0x1FF
    dos = (b"MZ" + b"\x00" * 58 + struct.pack("<I", 0x80)).ljust(0x80, b"\x00")
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)          # PE32+ magic
    struct.pack_into("<I", opt, 108, 16)            # NumberOfRvaAndSizes
    if edir_rva is not None:
        struct.pack_into("<II", opt, 112, edir_rva, vsize)  # export data dir
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, len(opt), 0x2022)
    sect = b".rdata\x00\x00" + struct.pack(
        "<IIIIIIHHI", vsize, SEC_RVA, raw_size, SEC_RAW, 0, 0, 0, 0, 0x40000040)
    head = (dos + b"PE\x00\x00" + coff + bytes(opt) + sect).ljust(SEC_RAW, b"\x00")
    return bytes(head) + bytes(blob).ljust(raw_size, b"\x00")
```

- [ ] **Step 2: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_dllvet.py`:

```python
import pytest

from pebuild import build_dll, skse_version_blob

from modkit import peparse


def test_encode_decode_runtime():
    v = peparse.encode_runtime("1.6.1170")
    assert v == (1 << 24) | (6 << 16) | (1170 << 4)
    assert peparse.decode_runtime(v) == "1.6.1170"


def test_pefile_machine_and_exports(tmp_path):
    p = tmp_path / "a.dll"
    p.write_bytes(build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])}))
    pe = peparse.PEFile(p)
    assert pe.machine == "x64"
    assert "SKSEPlugin_Version" in pe.exports()
    vd = peparse.skse_version_data(pe)
    assert vd["compatible"] == [peparse.encode_runtime("1.6.1170")]
    assert vd["address_independent"] is False


def test_pefile_rejects_garbage(tmp_path):
    p = tmp_path / "junk.dll"
    p.write_bytes(b"not a pe at all")
    with pytest.raises(peparse.PeError):
        peparse.PEFile(p)


def test_dllvet_ok_wrong_runtime_and_research(game_env, make_staging, run_cli):
    good = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])})
    bad = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.5.97")])})
    old = build_dll({"SKSEPlugin_Query": b"\x00" * 8})
    sd = make_staging({
        "SKSE/Plugins/good.dll": good,
        "SKSE/Plugins/bad.dll": bad,
        "SKSE/Plugins/old.dll": old,
    }, mod="Dll Mix")
    code, out = run_cli("dllvet", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "WRONG_RUNTIME" in out and "bad.dll" in out
    assert "RESEARCH" in out and "old.dll" in out
    assert "OK" in out and "good.dll" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["dllvet"]
    verdicts = {k.split("\\")[-1].split("/")[-1]: v["verdict"]
                for k, v in st.data["vet_results"]["dllvet"].items()}
    assert verdicts == {"good.dll": "OK", "bad.dll": "WRONG_RUNTIME",
                        "old.dll": "RESEARCH"}


def test_dllvet_address_independent_is_ok(game_env, make_staging, run_cli):
    dll = build_dll({"SKSEPlugin_Version": skse_version_blob(independent=1)},
                    extra=b"versionlib-1-6-1170-0.bin\x00")
    sd = make_staging({"SKSE/Plugins/ng.dll": dll}, mod="NG Mod")
    code, out = run_cli("dllvet", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "Address Library" in out
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_dllvet.py -q`
Expected: collection ERROR — `No module named 'modkit.peparse'`

- [ ] **Step 4: Implement**

`C:\Modding\tools\modkit\peparse.py`:

```python
"""Minimal PE (DLL) parser for dllvet: machine, exports, SKSE PluginVersionData.
Not a general PE library - just what the vet needs.
SKSE encoding: runtime 1.6.1170 -> (1<<24)|(6<<16)|(1170<<4)."""
import struct
from pathlib import Path

ADDRESS_INDEPENDENT = 0x1  # kVersionIndependent_AddressLibraryPostAE


class PeError(Exception):
    """Not a PE file / truncated / bad RVA."""


def encode_runtime(version):
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    major, minor, patch, beta = parts[:4]
    return (major << 24) | (minor << 16) | (patch << 4) | beta


def decode_runtime(value):
    return f"{value >> 24}.{(value >> 16) & 0xFF}.{(value >> 4) & 0xFFF}"


class PEFile:
    def __init__(self, path):
        self.raw = Path(path).read_bytes()
        if len(self.raw) < 0x40 or self.raw[:2] != b"MZ":
            raise PeError("not a PE file (no MZ)")
        pe_off = struct.unpack_from("<I", self.raw, 0x3C)[0]
        if self.raw[pe_off:pe_off + 4] != b"PE\x00\x00":
            raise PeError("not a PE file (no PE signature)")
        machine, nsects = struct.unpack_from("<HH", self.raw, pe_off + 4)
        opt_size = struct.unpack_from("<H", self.raw, pe_off + 20)[0]
        self.machine = {0x8664: "x64", 0x14C: "x86"}.get(machine, hex(machine))
        opt_off = pe_off + 24
        magic = struct.unpack_from("<H", self.raw, opt_off)[0]
        plus = magic == 0x20B
        dd_off = opt_off + (112 if plus else 96)
        self.export_rva, self.export_size = struct.unpack_from("<II", self.raw, dd_off)
        sec_off = opt_off + opt_size
        self.sections = []
        for i in range(nsects):
            base = sec_off + i * 40
            vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", self.raw, base + 8)
            self.sections.append((vaddr, max(vsize, rsize), raddr))

    def _off(self, rva):
        for vaddr, size, raddr in self.sections:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        raise PeError(f"rva {rva:#x} not in any section")

    def read(self, rva, size):
        o = self._off(rva)
        return self.raw[o:o + size]

    def _cstr(self, rva):
        o = self._off(rva)
        end = self.raw.index(b"\x00", o)
        return self.raw[o:end].decode("ascii", "replace")

    def exports(self):
        """{export_name: rva}; {} when the DLL exports nothing by name."""
        if not self.export_rva:
            return {}
        d = self.read(self.export_rva, 40)
        if len(d) < 40:
            raise PeError("export directory truncated")
        _nfuncs, nnames = struct.unpack_from("<II", d, 20)
        addr_funcs, addr_names, addr_ords = struct.unpack_from("<III", d, 28)
        out = {}
        for i in range(nnames):
            name_rva = struct.unpack_from("<I", self.read(addr_names + i * 4, 4))[0]
            ordinal = struct.unpack_from("<H", self.read(addr_ords + i * 2, 2))[0]
            func_rva = struct.unpack_from("<I", self.read(addr_funcs + ordinal * 4, 4))[0]
            out[self._cstr(name_rva)] = func_rva
        return out


def skse_version_data(pe):
    """Decode the exported SKSEPlugin_Version struct; None if not exported.
    Layout (SKSE64 PluginAPI.h PluginVersionData): dataVersion u32 @0,
    pluginVersion u32 @4, name[256] @8, author[256] @264, supportEmail[252] @520,
    versionIndependenceEx u32 @772, versionIndependence u32 @776,
    compatibleVersions[16] u32 @780 (0-terminated), xseMinimum u32 @844."""
    rva = pe.exports().get("SKSEPlugin_Version")
    if rva is None:
        return None
    raw = pe.read(rva, 848)
    if len(raw) < 848:
        raise PeError("SKSEPlugin_Version data truncated")
    name = raw[8:264].split(b"\x00")[0].decode("ascii", "replace")
    indep = struct.unpack_from("<I", raw, 776)[0]
    compat = []
    for i in range(16):
        v = struct.unpack_from("<I", raw, 780 + i * 4)[0]
        if v == 0:
            break
        compat.append(v)
    return {"name": name, "address_independent": bool(indep & ADDRESS_INDEPENDENT),
            "compatible": compat}


def scan_markers(path):
    """Raw byte scan for Address Library dependency markers."""
    raw = Path(path).read_bytes()
    return {"address_library": (b"versionlib-" in raw) or (b"version-1-5-97" in raw)}
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
def cmd_dllvet(args):
    from modkit import peparse, state
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = state.payload_root(staging)
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
```

Append `register_dllvet(sub, common)` to `_register_all`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `41 passed`

- [ ] **Step 6: Commit**

```bash
git -C "C:\Modding\tools" add modkit/peparse.py modkit/cli.py tests/test_modkit
git -C "C:\Modding\tools" commit -m "feat(modkit): PE parser + dllvet runtime-compat verdicts" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: `pluginstxt.py` — Plugins.txt manager + `plugins` command

Kills the anchor-slip (case-sensitive USSEP anchor), batch-append-after-DynDOLOD, and Wrye-Bash-scramble failure classes. Every write is backup-first (snapshot), atomic, BOM/CRLF-preserving, and re-read + validated after.

**Files:**
- Create: `C:\Modding\tools\modkit\pluginstxt.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_plugins`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_pluginstxt.py`

**Interfaces:**
- Consumes: `state.atomic_write_bytes` (Task 2), preset `PLUGINS_TXT`/`BACKUPS_DIR`/`DYNDOLOD_BLOCK` (Task 1).
- Produces (pinned — later tasks depend on these exact names):
  - `modkit.pluginstxt.read(preset) -> list[str]` — plugin lines verbatim (`*` prefix = enabled), comments/blank lines skipped.
  - `modkit.pluginstxt.snapshot(preset, tag: str) -> str` — copies Plugins.txt bytes to `<BACKUPS_DIR>\plugins-<tag>-<ts>.txt`, returns the backup path.
  - `modkit.pluginstxt.diff(path_a: str, path_b: str) -> str` — human report (ADDED / REMOVED / STATE / ORDER lines, or `no differences`).
  - `modkit.pluginstxt.enable(preset, plugin: str, anchor: str|None) -> None` — case-insensitive anchor match (with or without `*`); anchor `None` inserts before the DynDOLOD block (else appends); an anchor landing after the block is clamped before it (DynDOLOD-block-stays-last rule); an already-listed plugin is enabled in place. Snapshot-first, atomic, validated after.
  - `modkit.pluginstxt.disable(preset, plugin: str) -> None` — strips the `*` but keeps the line (order preserved). Snapshot-first, atomic, validated after.
  - Also: `pluginstxt.PluginsTxtError`.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_pluginstxt.py`:

```python
from pathlib import Path

import pytest

from modkit import pluginstxt


def raw(game_env):
    return (game_env / "Plugins.txt").read_bytes()


def lines(game_env):
    return raw(game_env).decode("utf-8-sig").splitlines()


def test_read_returns_verbatim_lines(preset):
    got = pluginstxt.read(preset)
    assert got[0] == "*Unofficial Skyrim Special Edition Patch.esp"
    assert "DisabledMod.esp" in got
    assert len(got) == 6


def test_enable_after_anchor_preserves_bom_crlf_and_snapshots(game_env, preset):
    pluginstxt.enable(preset, "NewMod.esp", "skyui_se.esp")  # case-insensitive anchor
    b = raw(game_env)
    assert b.startswith(b"\xef\xbb\xbf")
    assert b"*SkyUI_SE.esp\r\n*NewMod.esp\r\n" in b
    backups = list((game_env / "backups").glob("plugins-pre-enable-*.txt"))
    assert len(backups) == 1


def test_enable_default_inserts_before_dyndolod_block(game_env, preset):
    pluginstxt.enable(preset, "Tail.esp", None)
    ls = lines(game_env)
    assert ls.index("*Tail.esp") < ls.index("*DynDOLOD.esm")
    assert ls[-3:] == ["*DynDOLOD.esm", "*DynDOLOD.esp", "*Occlusion.esp"]


def test_enable_anchor_inside_block_clamps_before_block(game_env, preset):
    pluginstxt.enable(preset, "Clamped.esp", "Occlusion.esp")
    ls = lines(game_env)
    assert ls.index("*Clamped.esp") < ls.index("*DynDOLOD.esm")


def test_enable_existing_disabled_line_in_place(game_env, preset):
    pluginstxt.enable(preset, "DisabledMod.esp", None)
    ls = lines(game_env)
    assert ls[2] == "*DisabledMod.esp"
    assert len(ls) == 6  # no duplicate line added


def test_enable_unknown_anchor_raises_and_writes_nothing(game_env, preset):
    before = raw(game_env)
    with pytest.raises(pluginstxt.PluginsTxtError):
        pluginstxt.enable(preset, "X.esp", "NoSuchAnchor.esp")
    assert raw(game_env) == before


def test_disable_strips_star_keeps_line(game_env, preset):
    pluginstxt.disable(preset, "SkyUI_SE.esp")
    ls = lines(game_env)
    assert "SkyUI_SE.esp" in ls and "*SkyUI_SE.esp" not in ls
    with pytest.raises(pluginstxt.PluginsTxtError):
        pluginstxt.disable(preset, "NotThere.esp")


def test_snapshot_diff_roundtrip(game_env, preset):
    snap = pluginstxt.snapshot(preset, "test")
    assert Path(snap).is_file()
    assert pluginstxt.diff(snap, str(game_env / "Plugins.txt")) == "no differences"
    pluginstxt.enable(preset, "Added.esp", None)
    pluginstxt.disable(preset, "SkyUI_SE.esp")
    report = pluginstxt.diff(snap, str(game_env / "Plugins.txt"))
    assert "ADDED   *Added.esp" in report
    assert "STATE" in report and "enabled -> disabled" in report


def test_cli_plugins_list_and_diff_usage(game_env, preset, run_cli):
    code, out = run_cli("plugins", "list", "--game", "skyrim")
    assert code == 0
    assert "*Unofficial Skyrim Special Edition Patch.esp" in out
    code, out = run_cli("plugins", "diff", "--game", "skyrim")  # needs 2 paths
    assert code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_pluginstxt.py -q`
Expected: collection ERROR — `No module named 'modkit.pluginstxt'`

- [ ] **Step 3: Implement `pluginstxt.py`**

`C:\Modding\tools\modkit\pluginstxt.py`:

```python
"""Plugins.txt manager: BOM/CRLF-preserving, case-insensitive anchors,
DynDOLOD-block-stays-last, snapshot/diff to bracket external GUI tools
(the Wrye Bash silent-scramble class). Convention: '*' prefix = enabled."""
import datetime
import shutil
from pathlib import Path

from modkit.state import atomic_write_bytes


class PluginsTxtError(Exception):
    """Missing file, unknown anchor, or post-write validation failure."""


def _plugins_path(preset):
    p = getattr(preset, "PLUGINS_TXT", None)
    if not p:
        raise PluginsTxtError(f"game {preset.NAME!r} has no plugins_txt configured")
    if not Path(p).is_file():
        raise PluginsTxtError(f"Plugins.txt not found: {p}")
    return Path(p)


def _read_raw(path):
    raw = Path(path).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return bom, lines


def _write_raw(preset, bom, lines):
    body = "\r\n".join(lines) + "\r\n"
    atomic_write_bytes(_plugins_path(preset),
                       (b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))


def _name(line):
    return line.lstrip("*").strip().lower()


def read(preset):
    """Plugin lines verbatim ('*' = enabled); comments/blank lines skipped."""
    _bom, lines = _read_raw(_plugins_path(preset))
    return [l for l in lines if l.strip() and not l.lstrip().startswith("#")]


def snapshot(preset, tag):
    """Byte-copy Plugins.txt to BACKUPS_DIR\\plugins-<tag>-<ts>.txt; returns path."""
    src = _plugins_path(preset)
    bdir = Path(preset.BACKUPS_DIR)
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = bdir / f"plugins-{tag}-{ts}.txt"
    shutil.copy2(src, dest)
    return str(dest)


def diff(path_a, path_b):
    """Human report: ADDED/REMOVED lines, STATE flips, ORDER changes."""
    def load(p):
        _b, lines = _read_raw(p)
        return [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    a, b = load(path_a), load(path_b)
    amap = {_name(l): l for l in a}
    bmap = {_name(l): l for l in b}
    out = []
    for n, line in bmap.items():
        if n not in amap:
            out.append(f"ADDED   {line}")
    for n, line in amap.items():
        if n not in bmap:
            out.append(f"REMOVED {line}")
    for n in amap:
        if n in bmap and amap[n] != bmap[n]:
            sa = "enabled" if amap[n].startswith("*") else "disabled"
            sb = "enabled" if bmap[n].startswith("*") else "disabled"
            if sa != sb:
                out.append(f"STATE   {bmap[n].lstrip('*')}: {sa} -> {sb}")
    order_a = [n for n in map(_name, a) if n in bmap]
    order_b = [n for n in map(_name, b) if n in amap]
    if order_a != order_b:
        out.append("ORDER   load order changed for pre-existing plugins")
    return "\n".join(out) if out else "no differences"


def enable(preset, plugin, anchor):
    """Enable (insert or star-in-place). Snapshot-first, atomic, validated after."""
    path = _plugins_path(preset)
    target = plugin.lstrip("*").strip()
    tname = target.lower()
    bom, lines = _read_raw(path)
    idx_of = {_name(l): i for i, l in enumerate(lines) if l.strip()}
    if anchor and _name(anchor) not in idx_of:
        raise PluginsTxtError(f"anchor {anchor!r} not found in Plugins.txt "
                              "(anchors are case-insensitive, '*' optional)")
    snapshot(preset, "pre-enable")
    if tname in idx_of:
        i = idx_of[tname]
        lines[i] = "*" + lines[i].lstrip("*")
    else:
        block = tuple(n.lower() for n in getattr(preset, "DYNDOLOD_BLOCK", ()) or ())
        block_start = len(lines)
        for i, l in enumerate(lines):
            if _name(l) in block:
                block_start = i
                break
        index = idx_of[_name(anchor)] + 1 if anchor else block_start
        if tname not in block and index > block_start:
            index = block_start  # DynDOLOD block stays last
        lines.insert(index, "*" + target)
    _write_raw(preset, bom, lines)
    after = read(preset)
    if not any(_name(l) == tname and l.startswith("*") for l in after):
        raise PluginsTxtError(f"post-write validation failed: {target} not enabled")


def disable(preset, plugin):
    """Strip the '*' but KEEP the line (order preserved). Snapshot-first, validated."""
    path = _plugins_path(preset)
    tname = plugin.lstrip("*").strip().lower()
    bom, lines = _read_raw(path)
    if not any(_name(l) == tname for l in lines if l.strip()):
        raise PluginsTxtError(f"{plugin!r} not in Plugins.txt")
    snapshot(preset, "pre-disable")
    lines = [l.lstrip("*") if _name(l) == tname else l for l in lines]
    _write_raw(preset, bom, lines)
    _b, after = _read_raw(path)
    if any(l.startswith("*") and _name(l) == tname for l in after):
        raise PluginsTxtError(f"post-write validation failed: {plugin} still enabled")
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
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
```

Append `register_plugins(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `50 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/pluginstxt.py modkit/cli.py tests/test_modkit/test_pluginstxt.py
git -C "C:\Modding\tools" commit -m "feat(modkit): BOM/CRLF-safe Plugins.txt manager with DynDOLOD tail rule" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: `conflicts.py` — file-overlap sweep + `conflicts` command

**Files:**
- Create: `C:\Modding\tools\modkit\conflicts.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_conflicts`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_conflicts.py`

**Interfaces:**
- Consumes: `state`, `cli._staging_for`, preset `DATA_DIR`/`MANIFESTS_DIR`.
- Produces (used by Tasks 15, 16): `conflicts.sweep(preset, payload_dir) -> list[dict]` (each `{"path": str, "on_disk": True, "owner": str|None}` — owner is the manifest stem that currently claims the path), `conflicts.manifest_owners(manifests_dir) -> dict[str, str]` (read-only; manifests are written by ledger.py only).

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_conflicts.py`:

```python
from modkit import conflicts


def test_sweep_names_losing_mod(game_env, preset, make_staging, run_cli):
    (game_env / "Data" / "textures").mkdir()
    (game_env / "Data" / "textures" / "a.dds").write_bytes(b"OLD")
    (game_env / "manifests" / "Old-Mod.txt").write_bytes(
        b"\xef\xbb\xbftextures\\a.dds\r\n")
    sd = make_staging({"textures/a.dds": b"NEW", "textures/b.dds": b"NEW2"},
                      mod="Overlap Mod")
    hits = conflicts.sweep(preset, sd / "payload")
    assert len(hits) == 1
    assert hits[0]["path"].replace("/", "\\") == "textures\\a.dds"
    assert hits[0]["owner"] == "Old-Mod"
    code, out = run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "OVERLAP" in out and "Old-Mod" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["conflicts"]
    assert st.data["vet_results"]["conflicts"]["overlaps"] == 1


def test_sweep_clean_exit_zero(game_env, preset, make_staging, run_cli):
    sd = make_staging({"meshes/new.nif": b"NIF"}, mod="Clean Mod")
    code, out = run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "no file overlaps" in out


def test_manifest_owner_tolerates_data_prefix_and_comments(game_env):
    (game_env / "manifests" / "Legacy.txt").write_bytes(
        b"\xef\xbb\xbf# comment\r\nData\\meshes\\x.nif\r\n")
    owners = conflicts.manifest_owners(game_env / "manifests")
    assert owners["meshes\\x.nif"] == "Legacy"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_conflicts.py -q`
Expected: collection ERROR — `No module named 'modkit.conflicts'`

- [ ] **Step 3: Implement**

`C:\Modding\tools\modkit\conflicts.py`:

```python
"""File-overlap sweep: payload vs Data\\ + existing manifests. Names the losing
mod per overlap (standing rule: sweep after EVERY install). Read-only."""
from pathlib import Path


def manifest_owners(manifests_dir):
    """{data-relative-lower-backslash-path: manifest-stem}. Tolerates legacy
    Data\\ prefixes and #-comment lines (ledger.py manifest conventions)."""
    owners = {}
    mdir = Path(manifests_dir) if manifests_dir else None
    if not mdir or not mdir.is_dir():
        return owners
    for mf in sorted(mdir.glob("*.txt")):
        try:
            text = mf.read_bytes().decode("utf-8-sig")
        except OSError:
            continue
        for line in text.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rel = line.replace("/", "\\")
            if rel.lower().startswith("data\\"):
                rel = rel[5:]
            owners[rel.lower()] = mf.stem
    return owners


def sweep(preset, payload_dir):
    """Every payload file already present in Data -> overlap hit with owner."""
    if preset.DATA_DIR is None:
        return []
    data_dir = Path(preset.DATA_DIR)
    owners = manifest_owners(getattr(preset, "MANIFESTS_DIR", None))
    payload_dir = Path(payload_dir)
    hits = []
    for f in sorted(payload_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(payload_dir))
        if (data_dir / rel).is_file():
            hits.append({"path": rel, "on_disk": True,
                         "owner": owners.get(rel.replace("/", "\\").lower())})
    return hits
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
def cmd_conflicts(args):
    from modkit import conflicts, state
    preset = _preset(args)
    staging = _staging_for(args, preset)
    st = state.InstallState.load(str(staging))
    pay = state.payload_root(staging)
    hits = conflicts.sweep(preset, pay)
    if not hits:
        safe_print("no file overlaps vs Data")
    for h in hits:
        owner = (f"currently owned by {h['owner']}" if h["owner"]
                 else "owner unknown (no manifest claims it)")
        safe_print(f"OVERLAP {h['path']} - {owner}; deploying makes this mod win")
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
```

Append `register_conflicts(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `53 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/conflicts.py modkit/cli.py tests/test_modkit/test_conflicts.py
git -C "C:\Modding\tools" commit -m "feat(modkit): conflict sweep naming losing mods via manifests" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: `deploy.py` + `deploy` command (robocopy + Plugins.txt + ledger handoff)

The only command besides `remove` allowed to touch game dirs. Order: game-not-running gate (un-forceable) -> vet-stamp gate (warn + refuse, `--force` overrides) -> robocopy (exit <8 = success) -> stamp `deployed` -> Plugins.txt enables (via Task 9, snapshot-first) -> `ledger.py add --files-from` (writes the manifest; ledger.py is the sole ledger/manifest writer) -> stamp `recorded`.

**Files:**
- Create: `C:\Modding\tools\modkit\deploy.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_deploy`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_deploy.py`

**Interfaces:**
- Consumes: `ledger_bridge.run/game_args` (Task 4), `pluginstxt.enable` (Task 9), `state` (Task 2), preset attrs (Task 1).
- Produces (used by Tasks 13, 15): `deploy.run_deploy(preset, staging_dir, anchor: str|None, force: bool, log) -> int` (exit code; `log` is a print callable), `deploy.game_running(preset) -> bool` (tasklist scan), `deploy.robocopy(src, dest) -> int` (raises `DeployError` on exit >= 8), `deploy.payload_files(pay_root) -> list[str]` (Data-relative backslash paths), `deploy.data_root(preset, pay_root) -> Path` (unwraps a single top-level `Data\` dir — the Data-prefix bug class), `deploy.DeployError`.
- Resolution of a spec wording tension ("warns, does not block" vs "treat exit 2 as stop and vet"): without `--force`, missing applicable vet stamps -> print WARN lines, **do not copy anything**, exit 2 (so "stop and vet" is still possible); `--force` suppresses the gate entirely and deploys with exit 0. The game-running check is a hard exit 1 with no force flag — deploying under a live game is never safe.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_deploy.py`:

```python
import json
from pathlib import Path

from test_tes4 import make_tes4

from modkit import ledger_bridge


def vetted_staging(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    return sd


def test_deploy_refuses_pending_vets(game_env, make_staging, run_cli):
    sd = make_staging({"Mod.esp": make_tes4()}, mod="Unvetted Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "REFUSED" in out and "esp" in out
    assert not (game_env / "Data" / "Mod.esp").exists()


def test_deploy_clean_copies_enables_and_records(game_env, make_staging, run_cli):
    sd = vetted_staging(make_staging, run_cli,
                        {"Mod.esp": make_tes4(), "textures/t.dds": b"DDS"},
                        mod="Deploy Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert (game_env / "Data" / "Mod.esp").is_file()
    assert (game_env / "Data" / "textures" / "t.dds").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*Mod.esp" in plines
    assert plines.index("*Mod.esp") < plines.index("*DynDOLOD.esm")
    lcode, lout = ledger_bridge.run(["get", "--name", "Deploy Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
    entry = json.loads(lout)
    assert entry["fileCount"] == 2 and entry["plugin"] == "Mod.esp"
    assert (game_env / "manifests" / "Deploy-Mod.txt").is_file()
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["deployed"] and st["stages"]["recorded"]
    assert "textures\\t.dds" in st["files"]


def test_deploy_force_bypasses_vet_gate(game_env, make_staging, run_cli):
    sd = make_staging({"Forced.esp": make_tes4()}, mod="Forced Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 0
    assert (game_env / "Data" / "Forced.esp").is_file()


def test_deploy_hard_refuses_running_game(game_env, make_staging, run_cli, monkeypatch):
    from modkit import deploy
    monkeypatch.setattr(deploy, "game_running", lambda preset: True)
    sd = make_staging({"X.esp": make_tes4()}, mod="Running Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 1
    assert "game process running" in out
    assert not (game_env / "Data" / "X.esp").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_deploy.py -q`
Expected: FAIL — argparse `invalid choice: 'deploy'`

- [ ] **Step 3: Implement `deploy.py`**

`C:\Modding\tools\modkit\deploy.py`:

```python
"""Deploy engine. Only deploy and remove touch game dirs.
robocopy exit codes < 8 are SUCCESS (>= 8 raises). Ledger writes go through
ledger.py exclusively (its validation + backups apply)."""
import subprocess
from pathlib import Path

from modkit import ledger_bridge, pluginstxt, state


class DeployError(Exception):
    """robocopy >= 8 or other hard deploy failure."""


def game_running(preset):
    """True if any PROCESS_NAMES appears in tasklist output."""
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.lower()
    except OSError:
        return False
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
    if game_running(preset):
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
        pluginstxt.enable(preset, p, anchor)
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
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
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
```

Append `register_deploy(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `57 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/deploy.py modkit/cli.py tests/test_modkit/test_deploy.py
git -C "C:\Modding\tools" commit -m "feat(modkit): deploy - robocopy, Plugins.txt enable, ledger handoff" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: `verify.py` + `verify` command

Payload-vs-Data diff with **no extension filtering** (the MCM Helper burn: filtered .txt/.json hid a half-install), `_SWAP.ini`/`_DISTR.ini` referenced-plugin-exists checks (the ICRFixes class), and a `ledger.py check` tail. Read-only; stamps `verified` only on a clean pass.

**Files:**
- Create: `C:\Modding\tools\modkit\verify.py`
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_verify`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_verify.py`

**Interfaces:**
- Consumes: `deploy.data_root` (Task 11), `ledger_bridge` (Task 4), `state` (Task 2).
- Produces (used by Tasks 14, 16): `verify.run_verify(preset, staging_dir, log) -> int` (0 clean / 1 findings), `verify.diff_payload_vs_data(preset, pay_root) -> list[tuple[str, str]]`, `verify.swap_distr_refs(pay_root) -> list[str]`. Writes `vet_results["verify"]` = `{"ok", "missing_or_mismatched", "missing_swap_refs", "ledger_check_exit", "ts"}` (status reads it in Task 14).
- Resolution: the `ledger.py check` tail is **informational** — its exit code is recorded but does not fail verify (whether findings are *new* is the acceptance-gate judgment, Task 19).

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_verify.py`:

```python
import json

from test_tes4 import make_tes4

from modkit import verify


def deployed_staging(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    return sd


def test_verify_ok_after_clean_deploy(game_env, make_staging, run_cli):
    sd = deployed_staging(make_staging, run_cli,
                          {"Mod.esp": make_tes4(), "interface/mcm.json": b"{}"},
                          mod="Verify Mod")
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "verify OK" in out
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["verified"]
    assert st["vet_results"]["verify"]["ok"] is True


def test_verify_catches_missing_file_no_ext_filter(game_env, make_staging, run_cli):
    sd = deployed_staging(make_staging, run_cli,
                          {"Mod.esp": make_tes4(), "readme.txt": b"docs"},
                          mod="Half Install")
    (game_env / "Data" / "readme.txt").unlink()  # simulate half-install
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 1
    assert "readme.txt" in out and "missing in Data" in out
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["verified"] is None


def test_verify_flags_missing_swap_ref(game_env, make_staging, run_cli):
    ini = b"0x123~NotThere.esp|0x456~AlsoHere.esp\r\n"
    sd = make_staging({"Stuff_SWAP.ini": ini}, mod="Swap Mod")
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 0
    (game_env / "Data" / "AlsoHere.esp").write_bytes(make_tes4())
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 1
    assert "NotThere.esp" in out and "AlsoHere.esp" not in [
        l.split()[-1] for l in out.splitlines() if l.startswith("BAD")]


def test_swap_refs_parser(tmp_path):
    d = tmp_path / "pay"
    d.mkdir()
    (d / "a_DISTR.ini").write_text(
        "Spell = 0x800~Magic Mod.esp|NONE ; comment with Junk.esp\n", encoding="utf-8")
    (d / "normal.ini").write_text("ref=Ignored.esp\n", encoding="utf-8")
    refs = verify.swap_distr_refs(d)
    assert refs == ["Magic Mod.esp"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_verify.py -q`
Expected: collection ERROR — `No module named 'modkit.verify'`

- [ ] **Step 3: Implement**

`C:\Modding\tools\modkit\verify.py`:

```python
"""Post-deploy verification. NO extension filtering on the payload-vs-Data diff
(the MCM Helper burn). _SWAP/_DISTR referenced plugins must exist in Data.
Read-only: verify never writes to game dirs."""
import re
from pathlib import Path

from modkit import deploy, ledger_bridge, state

PLUGIN_REF_RE = re.compile(r"[\w .'()\[\]-]+\.es[pml]\b", re.IGNORECASE)


def diff_payload_vs_data(preset, pay_root):
    """[(rel, problem)] for payload files missing or size-mismatched in Data."""
    data_dir = Path(preset.DATA_DIR)
    pay_root = Path(pay_root)
    problems = []
    for f in sorted(pay_root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(pay_root))
        target = data_dir / rel
        if not target.is_file():
            problems.append((rel, "missing in Data"))
        elif target.stat().st_size != f.stat().st_size:
            problems.append((rel, f"size differs (payload {f.stat().st_size}, "
                                  f"Data {target.stat().st_size})"))
    return problems


def swap_distr_refs(pay_root):
    """Plugin filenames referenced by payload *_SWAP.ini / *_DISTR.ini files.
    ';' starts a comment (BOS/SPID convention)."""
    refs = set()
    for ini in Path(pay_root).rglob("*.ini"):
        low = ini.name.lower()
        if not (low.endswith("_swap.ini") or low.endswith("_distr.ini")):
            continue
        text = ini.read_bytes().decode("utf-8-sig", "replace")
        for line in text.splitlines():
            line = line.split(";", 1)[0]
            for m in PLUGIN_REF_RE.findall(line):
                refs.add(m.strip().lstrip("~|"))
    return sorted(refs)


def run_verify(preset, staging_dir, log):
    st = state.InstallState.load(str(staging_dir))
    if preset.DATA_DIR is None:
        log(f"ERROR: game {preset.NAME!r} has no data_dir - verify unsupported")
        return 1
    pay = deploy.data_root(preset, state.payload_root(staging_dir))
    problems = diff_payload_vs_data(preset, pay)
    for rel, why in problems[:50]:
        log(f"BAD {rel}: {why}")
    if len(problems) > 50:
        log(f"... and {len(problems) - 50} more")
    data_dir = Path(preset.DATA_DIR)
    missing_refs = [r for r in swap_distr_refs(pay) if not (data_dir / r).is_file()]
    for r in missing_refs:
        log(f"BAD _SWAP/_DISTR references missing plugin: {r}")
    code, out = ledger_bridge.run(["check", *ledger_bridge.game_args(preset)])
    tail = "\n".join(out.strip().splitlines()[-8:])
    log(f"ledger check (exit {code}):\n{tail}")
    ok = not problems and not missing_refs
    st.data["vet_results"]["verify"] = {
        "ok": ok, "missing_or_mismatched": len(problems),
        "missing_swap_refs": missing_refs, "ledger_check_exit": code,
        "ts": state.now_iso()}
    if ok:
        st.stamp("verified")
        log("verify OK")
        return 0
    st.save()
    log(f"verify FAILED: {len(problems)} file problems, "
        f"{len(missing_refs)} missing _SWAP/_DISTR refs")
    return 1
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
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
```

Append `register_verify(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `61 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/verify.py modkit/cli.py tests/test_modkit/test_verify.py
git -C "C:\Modding\tools" commit -m "feat(modkit): verify - unfiltered Data diff + SWAP/DISTR ref checks" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: `remove` command (manifest-driven, quarantine, masters check)

Manifest-driven removal: quarantine to `<BACKUPS_DIR>\removed-<modslug>-<ts>\` (**never delete**), count-reconciled, **masters-check-before-disable** (refuse if other enabled plugins master ours — prevented CTDs 3 times), then `ledger.py remove --reason` (sole ledger writer).

**Files:**
- Modify: `C:\Modding\tools\modkit\deploy.py` (add `run_remove`; deploy.py is the game-dir-touching module)
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_remove`, registration)
- Test: `C:\Modding\tools\tests\test_modkit\test_remove.py`

**Interfaces:**
- Consumes: `ledger_bridge` (Task 4), `pluginstxt.read/disable` (Task 9), `tes4.parse_header` (Task 7), `deploy.game_running` (Task 11), `state.slug` (Task 2).
- Produces (used by Tasks 15, 16): `deploy.run_remove(preset, mod_name: str, reason: str, force: bool, log) -> int` — 0 done, 1 hard error, 2 refused on master-dependency (forceable).

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_remove.py`:

```python
import json

from test_tes4 import make_tes4

from modkit import ledger_bridge


def deploy_mod(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    return sd


def test_remove_quarantines_disables_and_records(game_env, make_staging, run_cli):
    deploy_mod(make_staging, run_cli,
               {"Gone.esp": make_tes4(), "textures/g.dds": b"D"}, mod="Gone Mod")
    (game_env / "Data" / "textures" / "g.dds").unlink()  # pre-existing drift: absent file
    code, out = run_cli("remove", "Gone Mod", "--game", "skyrim",
                        "--reason", "testing removal")
    assert code == 0
    assert not (game_env / "Data" / "Gone.esp").exists()
    qdirs = list((game_env / "backups").glob("removed-Gone-Mod-*"))
    assert len(qdirs) == 1 and (qdirs[0] / "Gone.esp").is_file()
    assert "already absent" in out and "textures\\g.dds" in out
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "Gone.esp" in plines and "*Gone.esp" not in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Gone Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    entry = json.loads(lout)
    assert entry["removedReason"] == "testing removal"
    assert "removed-Gone-Mod-" in entry["removedTo"]


def test_remove_refuses_when_other_plugin_masters_ours(game_env, make_staging, run_cli):
    deploy_mod(make_staging, run_cli, {"Master.esm": make_tes4(esm=True)},
               mod="Master Mod")
    (game_env / "Data" / "Dependent.esp").write_bytes(
        make_tes4(masters=("Master.esm",)))
    with open(game_env / "Plugins.txt", "ab") as f:
        f.write(b"*Dependent.esp\r\n")
    code, out = run_cli("remove", "Master Mod", "--game", "skyrim",
                        "--reason", "trying anyway")
    assert code == 2
    assert "Dependent.esp" in out and "REFUSED" in out
    assert (game_env / "Data" / "Master.esm").is_file()  # nothing moved
    code, out = run_cli("remove", "Master Mod", "--game", "skyrim",
                        "--reason", "forced", "--force")
    assert code == 0
    assert not (game_env / "Data" / "Master.esm").exists()


def test_remove_unknown_mod_errors(game_env, run_cli):
    code, out = run_cli("remove", "No Such Mod", "--game", "skyrim",
                        "--reason", "x")
    assert code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_remove.py -q`
Expected: FAIL — argparse `invalid choice: 'remove'`

- [ ] **Step 3: Implement `run_remove`**

In `C:\Modding\tools\modkit\deploy.py`, extend the imports at the top:

```python
import datetime
import json
import shutil
import subprocess
from pathlib import Path

from modkit import ledger_bridge, pluginstxt, state, tes4
```

Then add:

```python
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
```

Add to `C:\Modding\tools\modkit\cli.py`:

```python
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
```

Append `register_remove(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `64 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/deploy.py modkit/cli.py tests/test_modkit/test_remove.py
git -C "C:\Modding\tools" commit -m "feat(modkit): remove - quarantine, masters check, ledger handoff" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 14: `status` command + CLI help polish

`modkit status --game skyrim` lists staging dirs with incomplete stage chains + last verify result. Run at session start and after crashes — kills the half-install-undetected (ICRFixes) and mid-pipeline session-death classes.

**Files:**
- Modify: `C:\Modding\tools\modkit\cli.py` (add `cmd_status`, registration, pipeline epilog)
- Test: `C:\Modding\tools\tests\test_modkit\test_status.py`

**Interfaces:**
- Consumes: `state.InstallState.load/missing_applicable` (Task 2), `vet_results["verify"]` shape (Task 12).
- Produces: `cli.cmd_status` (exit 0 always — informational), `--all` flag to include complete installs.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_status.py`:

```python
from test_tes4 import make_tes4


def test_status_lists_incomplete_with_pending_vets(game_env, make_staging, run_cli):
    make_staging({"Mod.esp": make_tes4()}, mod="Stuck Mod")
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "INCOMPLETE" in out and "Stuck Mod" in out
    assert "pending vets" in out and "esp" in out
    assert "never verified" in out
    assert "1 incomplete" in out


def test_status_complete_only_shown_with_all(game_env, make_staging, run_cli):
    sd = make_staging({"Done.esp": make_tes4()}, mod="Done Mod")
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "0 incomplete" in out and "Done Mod" not in out
    code, out = run_cli("status", "--game", "skyrim", "--all")
    assert "Done Mod" in out and "verify OK" in out


def test_help_lists_all_commands_and_pipeline():
    from modkit import cli
    text = cli.build_parser().format_help()
    for cmd in ("intake", "stage", "fomod", "dllvet", "esp", "conflicts",
                "deploy", "verify", "remove", "plugins", "status"):
        assert cmd in text
    assert "pipeline" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_status.py -q`
Expected: FAIL — argparse `invalid choice: 'status'`

- [ ] **Step 3: Implement**

In `C:\Modding\tools\modkit\cli.py`, add a module-level epilog and pass it to the parser. Replace the `p = argparse.ArgumentParser(...)` line in `build_parser` with:

```python
PIPELINE = """typical install pipeline (skyrim):
  intake -> stage -> fomod (if present) -> dllvet -> esp -> conflicts -> deploy -> verify
judgment gates (dllvet verdicts, FOMOD picks, conflict decisions) are yours between steps.
run `modkit status --game <game>` at session start and after crashes.
exit codes: 0 clean, 1 error/findings, 2 warned or refused-pending-vets (--force)."""
```

```python
    p = argparse.ArgumentParser(prog="modkit.py", description=__doc__,
                                epilog=PIPELINE,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
```

Then add:

```python
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
        except state.StateError as ex:
            safe_print(f"?? {d.name}: {ex}")
            incomplete += 1
            continue
        pending = st.missing_applicable()
        undone = [s for s in ("deployed", "recorded", "verified")
                  if not st.data["stages"].get(s)]
        vres = st.data["vet_results"].get("verify")
        vtxt = (f"verify {'OK' if vres['ok'] else 'FAILED'} at {vres['ts']}"
                if vres else "never verified")
        if pending or undone:
            incomplete += 1
            safe_print(f"INCOMPLETE {d.name} [{st.data['mod']}]")
            if pending:
                safe_print(f"  pending vets: {', '.join(pending)}")
            if undone:
                safe_print(f"  not done: {', '.join(undone)}")
            safe_print(f"  {vtxt}")
        elif args.all:
            safe_print(f"complete   {d.name} [{st.data['mod']}] - {vtxt}")
    safe_print(f"{len(stagings)} staging dir(s), {incomplete} incomplete")
    return 0


def register_status(sub, common):
    sp = sub.add_parser("status", parents=[common],
                        help="staging dirs with incomplete stage chains + last "
                             "verify result (run at session start / after crashes)")
    sp.add_argument("--all", action="store_true", help="also list complete installs")
    sp.set_defaults(func=cmd_status)
```

Append `register_status(sub, common)` to `_register_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `67 passed`

- [ ] **Step 5: Smoke the real help output**

Run: `py -3 C:/Modding/tools/modkit.py --help`
Expected: all 11 commands listed with one-line help, epilog shows the pipeline. Exit 0.

- [ ] **Step 6: Commit**

```bash
git -C "C:\Modding\tools" add modkit/cli.py tests/test_modkit/test_status.py
git -C "C:\Modding\tools" commit -m "feat(modkit): status command + self-documenting help" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 15: CP77 thin preset

`intake` / `stage` / `conflicts` / `deploy` / `verify` / `remove` / `status` only — no fomod/dllvet/esp/plugins (no plugin system). `DATA_DIR` is the game ROOT; deploys target root subdirs (`archive`, `red4ext`, `r6`, `bin`). Conflicts adds `.archive` alphabetical-order reporting for `archive\pc\mod\`.

**Files:**
- Create: `C:\Modding\tools\modkit\games\cp77.py`
- Modify: `C:\Modding\tools\modkit\deploy.py` (stray-top-level gate for DEPLOY_DIRS presets)
- Modify: `C:\Modding\tools\modkit\cli.py` (conflicts: preset order report hook)
- Test: `C:\Modding\tools\tests\test_modkit\test_cp77.py`

**Interfaces:**
- Consumes: everything above; cp77 config entry in `modkit.json` (Task 1).
- Produces: preset module `modkit.games.cp77` with `DEPLOY_DIRS = ("archive", "red4ext", "r6", "bin")`, `PLUGIN_EXTS = ()`, `applicability()` (all False), `archive_order_report(preset, payload_dir) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_cp77.py`:

```python
import json
from pathlib import Path

import pytest

from modkit import config


@pytest.fixture
def cp_env(tmp_path, monkeypatch):
    root = tmp_path
    game_root = root / "CP77"
    (game_root / "archive" / "pc" / "mod").mkdir(parents=True)
    (game_root / "red4ext" / "plugins").mkdir(parents=True)
    (root / "staging").mkdir()
    (root / "backups").mkdir()
    (root / "manifests").mkdir()
    ledger_json = root / "ledger.json"
    ledger_json.write_text(json.dumps({
        "game": "Cyberpunk 2077", "installDir": str(game_root), "mods": []}),
        encoding="utf-8")
    cfg = {"sevenzip": r"C:\Program Files\7-Zip\7z.exe",
           "downloads": [], "staging_root": str(root / "staging"),
           "games": {"cp77": {
               "data_dir": str(game_root), "plugins_txt": None,
               "process_names": ["FakeCyber.exe"], "runtime": None,
               "backups_dir": str(root / "backups"),
               "manifests_dir": str(root / "manifests"),
               "ledger": str(ledger_json)}}}
    (root / "modkit.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("MODKIT_CONFIG", str(root / "modkit.json"))
    return root


def cp_staging(cp_env, files, mod="CP Mod"):
    from modkit import state as mstate
    preset = config.game(config.load(), "cp77")
    sd = Path(preset.STAGING_ROOT) / f"20260711-000000-{mstate.slug(mod)}"
    (sd / "payload").mkdir(parents=True)
    for rel, content in files.items():
        f = sd / "payload" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
    st = mstate.InstallState.create(str(sd), mod=mod, game="cp77",
                                    archive=r"C:\dl\cp-1-1-0.7z",
                                    applicable=preset.applicability(str(sd / "payload")))
    st.stamp("intake")
    st.stamp("staged")
    return sd


def test_cp77_preset_loads(cp_env):
    p = config.game(config.load(), "cp77")
    assert p.NAME == "cp77" and p.PLUGINS_TXT is None
    assert p.DEPLOY_DIRS == ("archive", "red4ext", "r6", "bin")
    assert p.applicability(str(cp_env)) == {"fomod": False, "dllvet": False, "esp": False}


def test_cp77_deploy_verify_roundtrip(cp_env, run_cli):
    sd = cp_staging(cp_env, {"archive/pc/mod/zz_cool.archive": b"ARC"})
    code, out = run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    assert code == 0
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd))
    assert code == 0
    assert (cp_env / "CP77" / "archive" / "pc" / "mod" / "zz_cool.archive").is_file()
    from modkit import ledger_bridge
    lcode, lout = ledger_bridge.run(["get", "--name", "CP Mod",
                                     "--ledger", str(cp_env / "ledger.json")])
    assert lcode == 0 and "plugin" not in json.loads(lout)
    code, out = run_cli("verify", "--game", "cp77", "--staging", str(sd))
    assert code == 0


def test_cp77_deploy_refuses_stray_top_level(cp_env, run_cli):
    sd = cp_staging(cp_env, {"readme.txt": b"docs",
                             "archive/pc/mod/a.archive": b"A"}, mod="Stray Mod")
    run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd))
    assert code == 2
    assert "stray top-level" in out and "readme.txt" in out
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd), "--force")
    assert code == 0


def test_cp77_conflicts_reports_archive_order(cp_env, run_cli):
    (cp_env / "CP77" / "archive" / "pc" / "mod" / "aa_base.archive").write_bytes(b"A")
    sd = cp_staging(cp_env, {"archive/pc/mod/zz_new.archive": b"Z"}, mod="Order Mod")
    code, out = run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    assert "ORDER" in out and "zz_new.archive" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_cp77.py -q`
Expected: FAIL — `test_cp77_preset_loads` gets the generic preset (no `DEPLOY_DIRS` attribute -> AttributeError)

- [ ] **Step 3: Implement**

`C:\Modding\tools\modkit\games\cp77.py`:

```python
"""Cyberpunk 2077 preset (thin): intake/stage/conflicts/deploy/verify/remove/
status only. No plugin system -> no fomod/dllvet/esp/plugins. DATA_DIR is the
game ROOT; deploys land in root subdirs. Paths come from modkit.json."""
from pathlib import Path

DEPLOY_DIRS = ("archive", "red4ext", "r6", "bin")
PLUGIN_EXTS = ()


def applicability(payload_dir):
    return {"fomod": False, "dllvet": False, "esp": False}


def archive_order_report(preset, payload_dir):
    """.archive files in archive\\pc\\mod load in alphabetical order - report
    where each new file sorts among the existing ones. red4ext plugin dir
    collisions surface via the normal file-overlap sweep."""
    mod_rel = Path("archive") / "pc" / "mod"
    existing_dir = Path(preset.DATA_DIR) / mod_rel
    new_dir = Path(payload_dir) / mod_rel
    existing = sorted(p.name.lower() for p in existing_dir.glob("*.archive")) \
        if existing_dir.is_dir() else []
    lines = []
    if new_dir.is_dir():
        for p in sorted(new_dir.glob("*.archive")):
            before = sum(1 for e in existing if e < p.name.lower())
            lines.append(f"{p.name}: alphabetical position {before + 1} of "
                         f"{len(existing) + 1} in archive\\pc\\mod")
    return lines
```

In `C:\Modding\tools\modkit\deploy.py`, inside `run_deploy`, directly after the `if not files:` block (before the `rc = robocopy(...)` line), insert:

```python
    deploy_dirs = tuple(getattr(preset, "DEPLOY_DIRS", ()) or ())
    if deploy_dirs:
        stray = [p.name for p in pay.iterdir()
                 if not (p.is_dir() and p.name.lower() in deploy_dirs)]
        if stray and not force:
            for s in stray:
                log(f"WARN stray top-level entry (expected only "
                    f"{'/'.join(deploy_dirs)}): {s}")
            log("deploy REFUSED - re-stage with only game dirs at payload root, "
                "or re-run with --force")
            return 2
```

In `C:\Modding\tools\modkit\cli.py`, inside `cmd_conflicts`, directly after the `for h in hits:` loop, insert:

```python
    order_fn = getattr(preset, "archive_order_report", None)
    if order_fn:
        for line in order_fn(preset, pay):
            safe_print(f"ORDER {line}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `71 passed`

- [ ] **Step 5: Commit**

```bash
git -C "C:\Modding\tools" add modkit/games/cp77.py modkit/deploy.py modkit/cli.py tests/test_modkit/test_cp77.py
git -C "C:\Modding\tools" commit -m "feat(modkit): CP77 thin preset with archive-order reporting" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 16: `mod-install` skill

Document deliverable — the SKILL.md content below is written out IN FULL and is the exact file content. The live file at `C:\Users\auand\.claude\skills\mod-install\SKILL.md` is the master; a reference copy is committed to the repo for provenance.

**Files:**
- Create: `C:\Users\auand\.claude\skills\mod-install\SKILL.md` (live, master)
- Create: `C:\Modding\tools\adoption\mod-install-SKILL.md` (byte-identical reference copy + one header comment line)

**Interfaces:**
- Consumes: every command shipped in Tasks 4–15 (exact invocations below must match `modkit --help`).
- Produces: the skill that fires at install-request time in game sessions.

- [ ] **Step 1: Write the live skill file**

Create `C:\Users\auand\.claude\skills\mod-install\SKILL.md` with EXACTLY this content:

```markdown
---
name: mod-install
description: Use when the user asks to install, verify, or remove a game mod, or gives a Nexus link or a mod archive path in a game session (Skyrim SE, Cyberpunk 2077, Kenshi). Drives the modkit CLI pipeline - never hand-roll extraction, Data copies, Plugins.txt edits, or ledger writes.
---

# Mod Install (modkit pipeline)

All installs/removals go through **modkit**:
`py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim|cp77 [flags]`
(`--help` is self-documenting). ledger.py stays the sole ledger/manifest writer -
modkit calls it during deploy/remove. **NEVER hand-roll**: 7z extraction,
robocopy into Data\, Plugins.txt edits, or ledger.json writes.

## Standing rules (from sse-mod-workflow)

- **User downloads Nexus files** - downloads are account-bound. Give the exact
  mod link + file name and wait for the archive path. Never fetch mod files yourself.
- **Verify before install**: the compat sweep (runtime, masters, conflicts)
  happens BEFORE deploy, never after.
- **Conflict sweep after EVERY install** - no exceptions.
- **Launch Skyrim ONLY via skse64_loader.exe** (never Steam Play, never MO2).
- Exit codes: 0 clean, 1 error/findings, 2 warned/refused. **Treat exit 2 as
  STOP AND VET.** Never pass --force without telling the user what is being skipped.

## Session start / resume

Run `py -3 C:\Modding\tools\modkit.py status --game <game>` at session start and
after any crash. INCOMPLETE staging dirs = resume them (finish pending vets ->
deploy -> verify) or ask the user. State lives in `<staging>\install.json`;
never redo a stamped stage - resume at the first missing stamp. After a crashed
deploy, run `verify` first to see what actually landed.

## Install pipeline - Skyrim (full preset)

1. **Intake** - `py -3 C:\Modding\tools\modkit.py intake "<archive>" --game skyrim`
   (or bare `intake --game skyrim` to scan Downloads + Vortex).
   Resolve every WARN (0-byte, wrong-game, already-installed) before continuing.
2. **Stage** - `py -3 C:\Modding\tools\modkit.py stage "<archive>" --game skyrim`
   Full-extract + count/size verify. Note the printed staging dir; later commands
   default to the latest staging, or pass `--staging <dir>` explicitly.
   The `pending vets:` line tells you which of steps 3-5 apply.
3. **FOMOD** (if pending) - `py -3 C:\Modding\tools\modkit.py fomod --game skyrim`
   then `--apply picks.json` (judgment gate below).
4. **DLL vet** (if pending) - `py -3 C:\Modding\tools\modkit.py dllvet --game skyrim`
5. **ESP vet** (if pending) - `py -3 C:\Modding\tools\modkit.py esp --game skyrim`
   Missing masters must be installed first (user downloads them; full pipeline each).
6. **Conflicts** (always) - `py -3 C:\Modding\tools\modkit.py conflicts --game skyrim`
7. **Deploy** - `py -3 C:\Modding\tools\modkit.py deploy --game skyrim [--anchor "Plugin.esp"]`
   Game must be closed. Refuses (exit 2) while vets are pending.
8. **Verify** - `py -3 C:\Modding\tools\modkit.py verify --game skyrim`
   Must end `verify OK`. Then report to the user: what was installed, where the
   plugin sits in the load order, and whether a DynDOLOD/TexGen regen is implied
   (see the sse-dyndolod-rerun-rule memory).

## Judgment gates (yours, not modkit's)

- **dllvet verdicts**: `OK` -> proceed. `WRONG_RUNTIME` or `RESEARCH` -> research
  the mod page/posts for a 1.6.1170/AE/NG build (WebSearch; never WebFetch
  nexusmods.com - it 403s; verify any Nexus ID against the live page title before
  giving the user a link). Present findings and wait for the user's call.
  `BAD_ARCH`/`UNPARSEABLE` -> stop and tell the user.
- **FOMOD picks**: run `fomod` without `--apply`, read the JSON tree, and present
  each step/group as a compact list - option names, descriptions, your
  recommendation and why. On the user's choice, Write `picks.json`
  (`{"<step>::<group>": ["Plugin Name"]}`) and run `fomod --apply picks.json`.
- **Conflict decisions**: for each OVERLAP line, name the currently-owning mod
  and state that deploying makes the new mod win. Expected overlaps (patches,
  texture replacers) can proceed; unexpected ones need a user decision. If a
  record-level conflict is likely, search for a compatibility patch (exact
  module match) and give the user the link - they download, then it gets the
  full pipeline too. Record-level conflict resolution itself stays xEdit territory.

## Cyberpunk 2077 (thin preset)

Same flow minus fomod/dllvet/esp/plugins:
intake -> stage -> conflicts -> deploy -> verify, all with `--game cp77`.
Deploy targets the game-root subdirs (archive/red4ext/r6/bin); stray top-level
payload files make deploy refuse - restage properly instead of forcing.

## Kenshi

Preset not built yet: `intake`/`stage`/`status` work with `--game kenshi`;
vets/deploy do not. Stage, then hand the deploy decision to the user and follow
the existing Kenshi manual workflow.

## Remove flow

1. `py -3 C:\Modding\tools\modkit.py remove "<Ledger Name>" --game skyrim --reason "<why>"`
2. Exit 2 = master-dependency refusal: tell the user WHICH enabled plugins
   depend on it; `--force` only after they accept the consequences.
3. Files are quarantined under `C:\Modding\skyrim-manual\backups\removed-<mod>-<ts>\`
   (never deleted) - mention the path in your report.
4. Finish with `status --game skyrim`.

## External GUI tools (Wrye Bash, xEdit, DynDOLOD)

Bracket every GUI run that can touch the load order:
`py -3 C:\Modding\tools\modkit.py plugins snapshot --game skyrim --tag pre-<tool>`
before, and after it exits:
`py -3 C:\Modding\tools\modkit.py plugins diff <snapshot-path> "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt"`
Report any ADDED/REMOVED/STATE/ORDER lines to the user (the Wrye Bash
silent-scramble class).
```

- [ ] **Step 2: Verify the skill file parses**

Run: `py -3 -c "import pathlib; t = pathlib.Path(r'C:\Users\auand\.claude\skills\mod-install\SKILL.md').read_text(encoding='utf-8'); assert t.startswith('---') and 'name: mod-install' in t and 'modkit.py' in t; print('skill ok, %d lines' % len(t.splitlines()))"`
Expected: `skill ok, <n> lines` (n > 100)

- [ ] **Step 3: Commit the reference copy**

Create `C:\Modding\tools\adoption\mod-install-SKILL.md` = the same content with ONE extra first line:

```markdown
<!-- reference copy; live master: C:\Users\auand\.claude\skills\mod-install\SKILL.md -->
```

```bash
git -C "C:\Modding\tools" add adoption/mod-install-SKILL.md
git -C "C:\Modding\tools" commit -m "docs(modkit): mod-install skill (reference copy)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 17: Memory pins (Skyrim, CP77, Kenshi project memories)

One `modkit.md` per game project memory dir, indexed at the TOP of each MEMORY.md (ledger-cli.md precedent: pins at the top are what actually get read at session start).

**Files:**
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\modkit.md`
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\modkit.md`
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\modkit.md`
- Modify: the three sibling `MEMORY.md` index files (one line each, at top of list)
- Create: `C:\Modding\tools\adoption\memory-pins.md` (provenance copy of all three, committed)

**Interfaces:**
- Consumes: the shipped CLI (Tasks 4–15) and skill (Task 16).
- Produces: session-start recall in all three game projects.

- [ ] **Step 1: Write the Skyrim memory file**

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\modkit.md`, EXACT content:

```markdown
---
name: modkit
description: ALL mod installs/removals go through the modkit CLI at C:\Modding\tools\modkit.py - never hand-roll extraction, Data\ copies, Plugins.txt edits, or ledger writes
metadata:
  type: project
---

Installs and removals are driven by **modkit**: `py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim`. Per-install state lives in `C:\Modding\staging\skyrim\<ts>-<mod>\install.json`; `status` shows incomplete pipelines (run it at session start / after crashes). The `mod-install` skill has the full playbook.

Command crib:
- `intake ["<archive>"]` - 0-byte / wrong-game / already-installed gates (Downloads + Vortex scan)
- `stage "<archive>"` - full-extract to fresh staging + count/size verify (NEVER 7z include-patterns)
- `fomod [--apply picks.json]` - option tree as JSON; picks are a judgment gate
- `dllvet` - runtime 1.6.1170 check via SKSE version struct; WRONG_RUNTIME/RESEARCH = research before deploy
- `esp` - TES4 masters + ESL flag; missing masters get installed first
- `conflicts` - overlap sweep vs Data + manifests, names the losing mod (run after EVERY install)
- `deploy [--anchor "X.esp"] [--force]` - robocopy + Plugins.txt enable + ledger add; exit 2 = STOP AND VET
- `verify` - unfiltered payload-vs-Data diff + _SWAP/_DISTR checks + ledger check tail
- `remove "<Name>" --reason "..."` - quarantine (never delete) + masters-check + ledger remove
- `plugins list|enable|disable|snapshot|diff` - BOM/CRLF-safe Plugins.txt; snapshot/diff around Wrye Bash/xEdit/DynDOLOD

**Why:** the hand-rolled install pipeline re-fired its known failure modes every session (reflection-notes #1: FO4 mix-ups x3, include-pattern failures x4, anchor slips x2, wrong-runtime DLLs, half-installs undetected for days).
**How to apply:** NEVER hand-roll 7z x / Expand-Archive / robocopy-to-Data / Plugins.txt writes / ledger.json edits - a PreToolUse guard will warn if you try. ledger.py stays the sole ledger writer (modkit calls it). Config: C:\Modding\tools\modkit.json. Spec/plan: C:\Modding\tools\docs\2026-07-11-modkit-*.md.
```

- [ ] **Step 2: Write the CP77 memory file**

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\modkit.md`, EXACT content:

```markdown
---
name: modkit
description: ALL mod installs/removals go through the modkit CLI at C:\Modding\tools\modkit.py - never hand-roll extraction or game-root copies
metadata:
  type: project
---

Installs and removals are driven by **modkit** (thin CP77 preset): `py -3 C:\Modding\tools\modkit.py <cmd> --game cp77`. Pipeline: `intake -> stage -> conflicts -> deploy -> verify` (no fomod/dllvet/esp/plugins - no plugin system). Per-install state in `C:\Modding\staging\cp77\...\install.json`; run `status --game cp77` at session start. The `mod-install` skill has the full playbook.

- `deploy` targets game-root subdirs (archive\pc\mod, red4ext, r6, bin); stray top-level payload files make it refuse - restage properly instead of forcing.
- `conflicts` reports .archive alphabetical ordering in archive\pc\mod plus file overlaps (red4ext plugin dir collisions included).
- `remove "<Name>" --reason "..."` quarantines to C:\Modding\cyberpunk-manual\backups (never deletes) and records via ledger.py.

**Why:** the Skyrim install discipline was re-improvised from scratch for ~16 CP77 mods on 07-03 (reflection-notes #1).
**How to apply:** NEVER hand-roll 7z x / Expand-Archive / robocopy into the game root / ledger.json edits. ledger.py stays the sole ledger writer. Config: C:\Modding\tools\modkit.json.
```

- [ ] **Step 3: Write the Kenshi memory file**

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\modkit.md`, EXACT content:

```markdown
---
name: modkit
description: modkit CLI (C:\Modding\tools\modkit.py) handles archive intake/staging for Kenshi; full preset not built yet - never hand-roll 7z extraction
metadata:
  type: project
---

**Kenshi preset is NOT built yet** - modkit (the cross-game install toolkit) currently gives Kenshi:
- `py -3 C:\Modding\tools\modkit.py intake "<archive>" --game kenshi` - 0-byte / wrong-game / Nexus-parse gates
- `py -3 C:\Modding\tools\modkit.py stage "<archive>" --game kenshi` - full-extract to C:\Modding\staging\kenshi\ + count/size verify
- `py -3 C:\Modding\tools\modkit.py status --game kenshi` - incomplete-staging report

No vets/deploy/verify/remove for Kenshi yet (mods.cfg + .mod-header masters checks are a future preset build). After staging, deployment follows the existing manual Kenshi workflow with the user.

**How to apply:** even without the full preset, NEVER hand-roll 7z extraction - stage through modkit so counts are verified and the staging dir is tracked. When the Kenshi preset lands, this pin gets updated with the full pipeline.
```

- [ ] **Step 4: Insert the index lines (top of each MEMORY.md list)**

Skyrim — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\MEMORY.md` currently starts with the heading `# Project Memory — Skyrim SE Modding`, a blank line, then the list whose first item is the `[Ledger CLI]` line. Insert this EXACT line as the new FIRST list item (directly above the Ledger CLI line):

```markdown
- [modkit install toolkit](modkit.md) — ALL installs/removals via `py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim` (intake→stage→fomod/dllvet/esp→conflicts→deploy→verify); NEVER hand-roll 7z/robocopy-to-Data/Plugins.txt/ledger writes; run `status` at session start
```

CP77 — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\MEMORY.md` has NO heading (the list starts at line 1, first item is the `[Ledger CLI]` line). Insert this EXACT line as the new line 1:

```markdown
- [modkit install toolkit](modkit.md) — ALL installs/removals via `py -3 C:\Modding\tools\modkit.py <cmd> --game cp77` (intake→stage→conflicts→deploy→verify, thin preset); NEVER hand-roll extraction or game-root copies; run `status` at session start
```

Kenshi — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\MEMORY.md` starts with `# Memory Index`, a blank line, then the list. Insert this EXACT line as the new FIRST list item:

```markdown
- [modkit install toolkit](modkit.md) — preset NOT built yet: only intake/stage/status work with `--game kenshi` (verified full-extract staging); NEVER hand-roll 7z extraction; full Kenshi preset is a future build
```

- [ ] **Step 5: Verify the pins**

Run: `py -3 -c "import pathlib; roots=[r'E--SteamLibrary-steamapps-common-Skyrim-Special-Edition', r'E--SteamLibrary-steamapps-common-Cyberpunk-2077', r'E--SteamLibrary-steamapps-common-Kenshi']; base=pathlib.Path(r'C:\Users\auand\.claude\projects'); [print(s, (base/s/'memory'/'modkit.md').is_file(), 'modkit.md' in (base/s/'memory'/'MEMORY.md').read_text(encoding='utf-8').splitlines()[0] or 'modkit.md' in (base/s/'memory'/'MEMORY.md').read_text(encoding='utf-8')[:600]) for s in roots]"`
Expected: three lines, each `<slug> True True` (modkit.md exists and is indexed near the top).

- [ ] **Step 6: Commit the provenance copy**

Create `C:\Modding\tools\adoption\memory-pins.md` containing a one-line header (`# modkit memory pins - provenance copy; live masters in C:\Users\auand\.claude\projects\<slug>\memory\modkit.md`) followed by the three file contents above, each under an `## <game>` heading, plus the three index lines under `## MEMORY.md index lines`.

```bash
git -C "C:\Modding\tools" add adoption/memory-pins.md
git -C "C:\Modding\tools" commit -m "docs(modkit): per-game memory pins (provenance copy)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 18: `modkit-guard.py` advisory PreToolUse hook + settings.json wiring

The only ACTIVE adoption layer: catches hand-rolling attempts mid-session. It **never blocks** (forensics/repair work must stay possible) — it only injects an `additionalContext` warning naming the correct modkit command. Lives IN THE REPO (`C:\Modding\tools\adoption\modkit-guard.py`, on C: so it works with the H: SSD unplugged); user `settings.json` points directly at it — single copy, no drift.

**Files:**
- Create: `C:\Modding\tools\adoption\modkit-guard.py`
- Modify: `C:\Users\auand\.claude\settings.json` (add a PreToolUse block — see merge rules below)
- Test: `C:\Modding\tools\tests\test_modkit\test_guard.py`

**Interfaces:**
- Consumes: Claude Code PreToolUse hook stdin JSON (`{tool_name, cwd, tool_input: {command}}`).
- Produces: stdout JSON `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}` on a match; NOTHING otherwise; exit code always 0.

- [ ] **Step 1: Write the failing tests**

`C:\Modding\tools\tests\test_modkit\test_guard.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "adoption" / "modkit-guard.py"
GAME_CWD = r"E:\SteamLibrary\steamapps\common\Skyrim Special Edition"


def run_guard(tool_name, cwd, command):
    payload = json.dumps({"tool_name": tool_name, "cwd": cwd,
                          "tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, str(GUARD)], input=payload,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stdout.strip()


def test_hand_roll_extract_warns_with_modkit_command():
    code, out = run_guard("Bash", GAME_CWD, '7z x "C:\\dl\\mod.7z" -oC:\\tmp')
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PreToolUse"
    assert "modkit.py stage" in ctx["additionalContext"]
    assert "ADVISORY" in ctx["additionalContext"]


def test_all_pattern_classes_match():
    cases = [
        ("Expand-Archive -Path mod.zip -Dest x", "stage"),
        (r'robocopy C:\tmp\payload "E:\SteamLibrary\steamapps\common\Skyrim Special Edition\Data" /E', "deploy"),
        (r'Add-Content "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt" "*New.esp"', "plugins"),
        (r'echo *New.esp >> "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt"', "plugins"),
        (r'Set-Content C:\Modding\skyrim-manual\ledger.json $json', "ledger.py"),
    ]
    for command, expected in cases:
        code, out = run_guard("PowerShell", GAME_CWD, command)
        assert code == 0 and out, f"no warning for: {command}"
        assert expected in json.loads(out)["hookSpecificOutput"]["additionalContext"], command


def test_forensics_and_non_game_cwd_stay_silent():
    code, out = run_guard("Bash", GAME_CWD, "rg -n 'MODL' Data/meshes")
    assert code == 0 and out == ""
    code, out = run_guard("Bash", r"H:\DeadMind V.3", "7z x archive.7z")
    assert code == 0 and out == ""
    code, out = run_guard("Read", GAME_CWD, "7z x archive.7z")
    assert code == 0 and out == ""


def test_garbage_stdin_never_blocks():
    proc = subprocess.run([sys.executable, str(GUARD)], input="not json",
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0 and proc.stdout.strip() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit\test_guard.py -q`
Expected: FAIL — guard script does not exist (`FileNotFoundError` on subprocess)

- [ ] **Step 3: Write the hook**

`C:\Modding\tools\adoption\modkit-guard.py`:

```python
#!/usr/bin/env python3
"""modkit-guard - ADVISORY PreToolUse hook for Claude Code.

Warns (NEVER blocks) when a Bash/PowerShell command in a game project or under
C:\\Modding hand-rolls a mod-install step that modkit owns. Output is an
additionalContext note naming the correct modkit command; exit code is always 0
so forensics and repair work stay possible.
Wired from C:\\Users\\auand\\.claude\\settings.json (PreToolUse, Bash|PowerShell).
"""
import json
import re
import sys

MODKIT = r"py -3 C:\Modding\tools\modkit.py"

GAME_HINTS = (
    r"steamlibrary\steamapps\common\skyrim special edition",
    r"steamlibrary\steamapps\common\cyberpunk 2077",
    r"steamlibrary\steamapps\common\kenshi",
    r"steamlibrary\steamapps\common\red dead redemption 2",
    r"c:\modding",
)

PATTERNS = (
    (re.compile(r"\b7z(\.exe|a)?\"?\s+[xe]\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (re.compile(r"\bExpand-Archive\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (re.compile(r"\brobocopy\b[^\r\n]*\\data\b", re.I),
     f"copying into a game Data dir by hand -> use: {MODKIT} deploy --game <game>"),
    (re.compile(r"\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*plugins\.txt", re.I),
     f"editing Plugins.txt by hand -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r">>?\s*\"?[^\r\n\"|<>]*plugins\.txt", re.I),
     f"redirecting into Plugins.txt -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r"(>>?\s*\"?[^\r\n\"|<>]*ledger\.json"
                r"|\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*ledger\.json)", re.I),
     "writing ledger.json directly -> use: py -3 C:\\Modding\\tools\\ledger.py "
     "add/update/remove --game <game> (modkit deploy/remove call it for installs)"),
)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed input must never block anything
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cwd = str(payload.get("cwd") or "").lower().replace("/", "\\")
    if not any(h in cwd for h in GAME_HINTS):
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    hits = [advice for rx, advice in PATTERNS if rx.search(cmd)]
    if not hits:
        return 0
    context = ("modkit-guard (ADVISORY, does not block): this command looks like a "
               "hand-rolled mod-install step. "
               + " | ".join(dict.fromkeys(hits))
               + " | modkit tracks per-install state (intake/vet/verify + ledger); "
                 "hand-rolled steps bypass all of it. If this is forensics or "
                 "repair work, carry on.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `75 passed`

- [ ] **Step 5: Wire settings.json (merge, do NOT clobber)**

`C:\Users\auand\.claude\settings.json` currently has `hooks` entries for SessionStart, PreCompact, SessionEnd, UserPromptSubmit, and PostToolUse — all running dmm-memory-compiler via `dmm-launch.ps1`. There is **no PreToolUse key yet**. Edit the file with the Edit tool (do not rewrite it): add ONLY this key inside the existing `"hooks"` object:

```json
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell",
        "hooks": [
          {
            "type": "command",
            "command": "py -3 \"C:\\Modding\\tools\\adoption\\modkit-guard.py\" # modkit-guard",
            "timeout": 10
          }
        ]
      }
    ]
```

The merged `hooks` object must end up with ALL SIX keys. Abbreviated shape after the merge (existing five entries byte-identical to what is there now):

```json
  "hooks": {
    "SessionStart":     [ { "hooks": [ { "type": "command", "command": "powershell ... dmm-launch.ps1 -HookName \"session-start.py\" # dmm-memory-compiler", "timeout": 30 } ] } ],
    "PreCompact":       [ { "hooks": [ { "type": "command", "command": "powershell ... dmm-launch.ps1 -HookName \"pre-compact.py\" # dmm-memory-compiler", "timeout": 30 } ] } ],
    "SessionEnd":       [ { "hooks": [ { "type": "command", "command": "powershell ... dmm-launch.ps1 -HookName \"session-end.py\" # dmm-memory-compiler", "timeout": 30 } ] } ],
    "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "powershell ... dmm-launch.ps1 -HookName \"wiki-retrieve.py\" # dmm-memory-compiler", "timeout": 15 } ] } ],
    "PostToolUse":      [ { "matcher": "Read|Grep|Glob|Write|Edit", "hooks": [ { "type": "command", "command": "powershell ... dmm-launch.ps1 -HookName \"pulse-emit.py\" # dmm-memory-compiler", "timeout": 5, "async": true } ] } ],
    "PreToolUse":       [ { "matcher": "Bash|PowerShell", "hooks": [ { "type": "command", "command": "py -3 \"C:\\Modding\\tools\\adoption\\modkit-guard.py\" # modkit-guard", "timeout": 10 } ] } ]
  }
```

(The `powershell ...` ellipses above are the EXISTING lines left untouched — only the `PreToolUse` key is new. If a PreToolUse array already exists by the time this runs, APPEND the `{matcher, hooks}` object to that array instead of replacing it.)

Validate the result parses: `py -3 -c "import json; json.load(open(r'C:\Users\auand\.claude\settings.json', encoding='utf-8')); print('settings ok')"`
Expected: `settings ok`

- [ ] **Step 6: Live acceptance probe (manual)**

In a NEW Claude Code session started in the Skyrim project dir, attempt `7z x <some archive>` via Bash — the advisory context should appear (visible in `/hooks` debug or transcript). Then run a forensics command (`rg -n MODL Data/meshes` or similar) — no warning. Note: hooks snapshot at session start, so the CURRENT session will not see the new hook.

- [ ] **Step 7: Commit**

```bash
git -C "C:\Modding\tools" add adoption/modkit-guard.py tests/test_modkit/test_guard.py
git -C "C:\Modding\tools" commit -m "feat(modkit): advisory PreToolUse guard against hand-rolled installs" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 19: Final acceptance — scratch rehearsal, then one real install

Ledger-CLI precedent: an independent reviewer rehearses end-to-end on scratch copies BEFORE anything touches the real game. Only `deploy`/`remove` ever write to game dirs, and in the rehearsal even those hit only the scratch tree.

**Files:**
- Create (temporary): `C:\Modding\tmp\modkit-rehearsal\` (scratch tree + rehearsal config; deleted at the end)
- Modify: `C:\Modding\tools\docs\2026-07-11-modkit-plan.md` (tick checkboxes / acceptance note)

**Interfaces:**
- Consumes: the entire shipped toolkit.
- Produces: acceptance evidence; the toolkit is live.

- [ ] **Step 1: Whole-suite green**

Run: `py -3 -m pytest C:/Modding/tools/tests/test_modkit -q`
Expected: `75 passed`
Also confirm the old suite still passes: `py -3 -m unittest discover -s C:/Modding/tools/tests -t C:/Modding/tools/tests -p "test_ledger.py" -v` — Expected: `OK` with the same test count as before this project (ledger.py untouched; the `-p` filter keeps unittest away from the pytest-style modkit files).

- [ ] **Step 2: Build the scratch rehearsal environment**

```bash
mkdir -p "C:/Modding/tmp/modkit-rehearsal/Data" "C:/Modding/tmp/modkit-rehearsal/backups" "C:/Modding/tmp/modkit-rehearsal/staging"
cp "C:/Users/auand/AppData/Local/Skyrim Special Edition/Plugins.txt" "C:/Modding/tmp/modkit-rehearsal/Plugins.txt"
cp "C:/Modding/skyrim-manual/ledger.json" "C:/Modding/tmp/modkit-rehearsal/ledger.json"
cp -r "C:/Modding/skyrim-manual/manifests" "C:/Modding/tmp/modkit-rehearsal/manifests"
```

Write `C:\Modding\tmp\modkit-rehearsal\modkit-rehearsal.json` (real 7z + Downloads, everything game-side scratch; the `ledger` key routes ledger.py at the scratch copy):

```json
{
    "sevenzip": "C:\\Program Files\\7-Zip\\7z.exe",
    "downloads": ["C:\\Users\\auand\\Downloads"],
    "staging_root": "C:\\Modding\\tmp\\modkit-rehearsal\\staging",
    "games": {
        "skyrim": {
            "data_dir": "C:\\Modding\\tmp\\modkit-rehearsal\\Data",
            "plugins_txt": "C:\\Modding\\tmp\\modkit-rehearsal\\Plugins.txt",
            "process_names": ["SkyrimSE.exe", "skse64_loader.exe"],
            "runtime": "1.6.1170",
            "backups_dir": "C:\\Modding\\tmp\\modkit-rehearsal\\backups",
            "manifests_dir": "C:\\Modding\\tmp\\modkit-rehearsal\\manifests",
            "ledger": "C:\\Modding\\tmp\\modkit-rehearsal\\ledger.json",
            "vortex_downloads": null
        }
    }
}
```

Note: scratch `Data\` starts empty (a full Data copy is 100+ GB — infeasible), so the conflicts sweep will report clean; that command's conflict logic is already covered by unit tests. The rehearsal proves the PIPELINE end-to-end: real archive, real Plugins.txt bytes (BOM/CRLF + real DynDOLOD tail), real ledger content.

- [ ] **Step 3: Rehearse the full pipeline (dispatch a fresh reviewer subagent for this)**

Pick a REAL mod archive already in `C:\Users\auand\Downloads` (any recent Skyrim `.7z`/`.zip`; if none, ask the user for one — user downloads, account-bound). Then, in Git Bash, with the rehearsal config:

```bash
export MODKIT_CONFIG="C:/Modding/tmp/modkit-rehearsal/modkit-rehearsal.json"
py -3 C:\\Modding\\tools\\modkit.py intake "<archive>" --game skyrim
py -3 C:\\Modding\\tools\\modkit.py stage "<archive>" --game skyrim
py -3 C:\\Modding\\tools\\modkit.py dllvet --game skyrim     # if pending
py -3 C:\\Modding\\tools\\modkit.py esp --game skyrim        # if pending
py -3 C:\\Modding\\tools\\modkit.py fomod --game skyrim      # if pending (+ --apply)
py -3 C:\\Modding\\tools\\modkit.py conflicts --game skyrim
py -3 C:\\Modding\\tools\\modkit.py deploy --game skyrim
py -3 C:\\Modding\\tools\\modkit.py verify --game skyrim
py -3 C:\\Modding\\tools\\modkit.py status --game skyrim
```

Reviewer checklist (all must hold):
- `stage` printed a staging dir under the scratch staging root; `install.json` matches the design shape.
- `deploy` exit 0 (after vets), files landed in scratch `Data\`, plugin line inserted BEFORE the DynDOLOD tail in the scratch Plugins.txt with BOM + CRLF intact (check bytes: `head -c 3` shows the BOM).
- Scratch `ledger.json` gained the entry (via ledger.py — check its `backups\` got a new .bak) and scratch `manifests\` gained the manifest.
- `verify` printed `verify OK`; `status` shows the install complete, `0 incomplete`.
- `remove "<Mod>" --game skyrim --reason "rehearsal"` quarantines to scratch `backups\removed-...`, un-stars the plugin, records removal in the scratch ledger.
- The REAL `E:\...\Data`, real Plugins.txt, and real ledger are untouched (spot-check mtimes).

Then delete the scratch: `rm -rf "C:/Modding/tmp/modkit-rehearsal"` and `unset MODKIT_CONFIG`.

- [ ] **Step 4: Real acceptance — ONE live Skyrim install, modkit-only**

Baseline first:

```bash
py -3 C:\\Modding\\tools\\ledger.py check --game skyrim > C:\\Modding\\tmp\\check-baseline.txt
```

Ask the user to pick + download one real mod (standing rule: user downloads, Nexus files are account-bound). Game closed. Then run ONLY modkit commands (no MODKIT_CONFIG set — real `modkit.json`): `intake` -> `stage` -> pending vets -> `conflicts` -> `deploy` -> `verify`, presenting every judgment gate to the user as the skill prescribes.

Acceptance holds when:
- `py -3 C:\Modding\tools\modkit.py status --game skyrim` reports the new install complete and `0 incomplete`.
- `py -3 C:\Modding\tools\ledger.py check --game skyrim > C:\Modding\tmp\check-post.txt` then `diff C:\Modding\tmp\check-baseline.txt C:\Modding\tmp\check-post.txt` shows **no new ERROR/WARN lines** (the known pre-existing residuals from the ledger-cli memory may re-appear identically on both sides).
- Hook acceptance (from Task 18 Step 6) has been observed in a fresh session: a hand-roll attempt warns, a forensics command does not.
- User launches via `skse64_loader.exe` when they choose to; remind them of any DynDOLOD-regen implication.

- [ ] **Step 5: Close out**

Tick the plan's checkboxes for completed tasks, then:

```bash
git -C "C:\Modding\tools" add docs/2026-07-11-modkit-plan.md
git -C "C:\Modding\tools" commit -m "docs(modkit): acceptance complete - rehearsal + live install verified" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Execution Handoff

**Plan complete and saved to `C:\Modding\tools\docs\2026-07-11-modkit-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development
- Fresh subagent per task + two-stage review

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans
- Batch execution with checkpoints for review

**Which approach?**
