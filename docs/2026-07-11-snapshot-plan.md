# modkit snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `snapshot` subcommand (take/diff of per-game session state) and an `openitems` subcommand (per-game pending-fixes tracker) to the existing modkit CLI, so every modding session starts from a machine-verified baseline instead of a ~30-tool-call manual audit, and root-caused fixes stop sitting unexecuted for weeks.

**Architecture:** One new module `modkit\snapshot.py` (capture -> JSON snapshot file, snapshot-vs-live diff report, tolerant markdown open-items tracker) wired into the core modkit argparse CLI via a `register(sub)` hook. All game-dir access is read-only; the only writes go to `C:\Modding\<game>-manual\snapshots\` and `C:\Modding\<game>-manual\open-items.md` (both derived from the preset's `BACKUPS_DIR` parent). Steam auto-update state is read from the game's `appmanifest_<appid>.acf` via a minimal Valve KeyValues parser written in this plan.

**Tech Stack:** Python 3.13 via `py -3` (never the Store `python` alias), stdlib only at runtime (`json`, `hashlib`, `re`, `pathlib`, `datetime`, `os`, `uuid`); `pytest` as dev-only test runner (design-doc precedent). Git repo at `C:\Modding\tools`.

**Spec / evidence:**
- Core design this extends: `C:\Modding\tools\docs\2026-07-11-modkit-design.md` (snapshot is an explicitly deferred subcommand: "LOD regen and snapshot — separate plans").
- Evidence base: `H:\DeadMind V.3\reflection-notes.md` §9 (session-start state drift) and §15 (stale config debris).
- Manual artifacts this automates: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\sse-baseline.md` (the hand-maintained baseline that drifted stale) and `memory\sse-audit-20260701-open-items.md` (the improvised open-items memo).

**DEPENDENCY CONTRACT — must be complete before executing this plan:**
modkit core plan `docs\2026-07-11-modkit-plan.md` **Tasks 1-2 and 9** (package scaffold + config loader + CLI dispatch, and pluginstxt/ledger_bridge). This plan consumes EXACTLY these core interfaces and nothing else:

| Interface | Signature |
|---|---|
| `modkit.config.load()` | `-> dict` (parsed `C:\Modding\tools\modkit.json`) |
| `modkit.config.game(cfg, name)` | `-> preset` object with attrs `DATA_DIR`, `PLUGINS_TXT`, `PROCESS_NAMES`, `RUNTIME`, `STAGING_ROOT`, `BACKUPS_DIR` |
| `modkit.pluginstxt.read(preset)` | `-> list[str]` (Plugins.txt lines, BOM/CRLF-safe per core design) |
| `modkit.ledger_bridge.run(args)` | `-> (rc, stdout)` (subprocess wrapper around ledger.py, the sole ledger writer) |

Do NOT invent or consume any other modkit interface. Everything snapshot-specific lives in `modkit\snapshot.py`. (Of the preset attrs, snapshot uses `PLUGINS_TXT` and `BACKUPS_DIR`; the rest are contract-guaranteed but unused here — the watched-DLL dir comes from the snapshot config section, not `DATA_DIR`, so the watch list is explicit config, not convention.)

**Section-9 evidence -> feature map (self-review anchor):**

| §9 evidence | Captured field / behavior |
|---|---|
| ~30-call manual audit from stale baseline (125 vs 152 plugins, `92da9748`) | `plugins` section: full line list + normalized SHA256 + enabled/total counts; diff ADDED/REMOVED/CHANGED |
| Precision.esp disabled *by choice*, flagged as urgent bug (`bcb5a461`) | diff report ends with the ASK-THE-USER note: unexplained deltas are questions for the user, never auto-bugs |
| Root-caused fixes (XPMSE disable, Bashed Patch) unexecuted for weeks (`dba84d3e`) | `openitems add/done/list` + session-start convention in the memory pins; acceptance task seeds the two real open items |
| Steam auto-update near-miss — RDR2 10 hours from loader-chain break (07-01) | `steam` section: `AutoUpdateBehavior` parsed from `appmanifest_<appid>.acf`; WARNING at both `take` and `diff` whenever value != "1" |
| Baseline memory drifted stale mid-marathon (`2a754ac5`) | `take` at session end / post-install writes a fresh timestamped snapshot; `diff` always compares against latest |
| "pending verify" TrueHUD flag matched a new symptom instantly (07-01) | open-items format keeps dated, human-editable checkbox lines reviewed at session start |
| §15 stale config debris / silent INI drift (`iTexMipMapSkip=1` hand-added, audit item 3) | `ini` section: watched keys from modkit.json (incl. `iTexMipMapSkip`); `enb` section: watched enbseries.ini flags |
| Ledger vs reality drift (Beards for HPH, 07-03) | `ledger` section: total/active/removed counts via `ledger_bridge` |

## Global Constraints

- **Python 3.13, stdlib only at runtime.** Run via `py -3`. `pytest` is dev-only (tests). No third-party runtime imports in `modkit\snapshot.py`.
- **Read-only against game dirs.** `snapshot take`/`diff` NEVER write into game dirs, `Plugins.txt`, `ledger.json`, or modkit staging — pure reads. All writes go to `C:\Modding\<game>-manual\snapshots\` and `C:\Modding\<game>-manual\open-items.md` only.
- **Tests never touch real paths.** All tests use `tmp_path` fixture dirs, stub presets (`types.SimpleNamespace`), fixture snapshot-config dicts, and monkeypatched `pluginstxt.read` / `ledger_bridge.run` / `_ctx`. No test reads `E:\SteamLibrary\...`, `C:\Modding\skyrim-manual\...`, or the real `modkit.json`.
- **Atomic writes** for snapshot files and open-items.md: temp file in the same directory + `os.replace` (ledger.py pattern; same-volume atomic).
- **Normalized-before-hash:** the Plugins.txt SHA256 is computed over BOM-stripped, CRLF-normalized, blank-line-free lines (`pluginstxt.read` guarantees BOM/CRLF safety per core design; snapshot additionally drops blank lines) so hashes are stable across editors and re-saves.
- **Ledger access only via `modkit.ledger_bridge.run`** — never import or reimplement ledger.py, never read ledger.json directly.
- **Exit-code convention (modkit core):** 0 = clean, 1 = error, 2 = warned/drift ("stop and ask").
- **TDD, one commit per task**, commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Config paths live in `modkit.json`, NOT in code (SSD/multi-machine portability).
- All commands below run from `C:\Modding\tools` (the `py -3 -m pytest` form puts the repo root on `sys.path`, which is how `import modkit` resolves).

## File Structure

- Create: `C:\Modding\tools\modkit\snapshot.py` — all snapshot/openitems logic (helpers, .acf parser, capture, diff, open-items, CLI handlers, `register`).
- Create: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` — pytest suite (grows task by task; final count 51 tests).
- Modify: `C:\Modding\tools\modkit\cli.py` — two lines: import + `snapshot.register(sub)` (Task 6).
- Modify: `C:\Modding\tools\modkit.json` — add the `"snapshot"` top-level section with real machine values (Task 9).
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\snapshot.md` + index line in that dir's `MEMORY.md` (Task 9).
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\snapshot.md` + index line in that dir's `MEMORY.md` (Task 9).

## The `snapshot` config section of modkit.json (exact schema)

Every key is **optional**; a missing key means that section is skipped at capture time and in diffs (this is how the CP77 thin preset works — it configures only the Steam keys):

```json
"snapshot": {
    "<game>": {
        "ini": [
            {"file": "<abs path to an INI>", "section": "<section name>", "key": "<key name>"}
        ],
        "enb": {
            "file": "<abs path to enbseries.ini>",
            "keys": [
                {"section": "<section name>", "key": "<key name>"}
            ]
        },
        "dllDir": "<abs path to the watched DLL dir - Data\\SKSE\\Plugins for skyrim>",
        "steamAppId": 489830,
        "appmanifest": "<abs path to steamapps\\appmanifest_<appid>.acf>"
    }
}
```

- `ini`: list of watched INI keys. The code reads **whatever is configured** — key lists are config, not code. Watched files must have distinct basenames (composite report key is `basename::section::key`, kept machine-portable by not embedding the drive letter).
- `enb`: one config file + a list of watched `[SECTION] key` flags (e.g. `EnableShadow` under `[COMPLEXPARTICLELIGHTS]`).
- `dllDir`: top-level `*.dll` filenames are listed (non-recursive — matches the sse-baseline counting convention).
- `steamAppId` + `appmanifest`: the `.acf` is parsed for `AppState.AutoUpdateBehavior`; a value other than `"1"` ("only update this game when I launch it") is a **WARNING** — auto-update breaks loader chains. `steamAppId` is cross-checked against the manifest's own `appid` to catch a mis-pointed path.

## Snapshot file format (schemaVersion 1)

Written to `C:\Modding\<game>-manual\snapshots\snapshot-<YYYYMMDD-HHMMSS>.json`:

```json
{
    "schemaVersion": 1,
    "game": "skyrim",
    "takenAt": "2026-07-11T14:33:05",
    "sections": {
        "plugins": {"lines": ["*USSEP.esp"], "sha256": "<hex>", "enabled": 1, "total": 1},
        "dlls": {"dir": "<path>", "dlls": ["EngineFixes.dll"]},
        "ini": {"Skyrim.ini::Display::iTexMipMapSkip": "1"},
        "enb": {"file": "<path>", "keys": {"EFFECT::EnableComplexParticleLights": "true"}},
        "ledger": {"total": 234, "active": 220, "removed": 14},
        "steam": {"appmanifest": "<path>", "appId": "489830", "autoUpdateBehavior": "1"}
    },
    "warnings": []
}
```

Unconfigured sections are `null`. A `null` plugins section also happens when `preset.PLUGINS_TXT` is `None` (CP77 has no Plugins.txt).

---

### Task 1: Module skeleton + text/INI helpers + atomic writes

**Files:**
- Create: `C:\Modding\tools\modkit\snapshot.py`
- Create: `C:\Modding\tools\tests\test_modkit\test_snapshot.py`

**Interfaces:**
- Consumes: nothing from core yet (imports `config`, `ledger_bridge`, `pluginstxt` at module level for later tasks — core Tasks 1-2/9 provide them).
- Produces: `read_text(path) -> str|None`, `read_ini_key(path, section, key) -> str|None`, `atomic_write(path, text) -> None`, `safe_print(s)` — used by every later task.

- [ ] **Step 1: Write the failing tests**

Create `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (if `tests\test_modkit\` does not exist yet, create the directory; no `__init__.py` needed):

```python
"""Tests for modkit.snapshot.

Run from C:\\Modding\\tools:
    py -3 -m pytest tests/test_modkit/test_snapshot.py -v
(the -m form puts the repo root on sys.path so `import modkit` resolves;
if pytest is missing: py -3 -m pip install pytest)
"""
import argparse
import json
import types
from pathlib import Path

import pytest

from modkit import snapshot


# ---------------------------------------------------------------- Task 1

def test_read_text_strips_bom_and_normalizes_crlf(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"\xef\xbb\xbfline1\r\nline2\r\n")
    assert snapshot.read_text(p) == "line1\nline2\n"


def test_read_text_missing_file_returns_none(tmp_path):
    assert snapshot.read_text(tmp_path / "nope.txt") is None


def test_read_ini_key_finds_value_case_insensitive(tmp_path):
    ini = tmp_path / "Skyrim.ini"
    ini.write_bytes(
        b"\xef\xbb\xbf[Display]\r\niTexMipMapSkip=1\r\n[General]\r\nuGridsToLoad=5\r\n")
    assert snapshot.read_ini_key(ini, "display", "itexmipmapskip") == "1"
    assert snapshot.read_ini_key(ini, "General", "uGridsToLoad") == "5"


def test_read_ini_key_last_duplicate_wins(tmp_path):
    ini = tmp_path / "enbseries.ini"
    ini.write_text("[EFFECT]\nEnableShadow=false\nEnableShadow=true\n")
    assert snapshot.read_ini_key(ini, "EFFECT", "EnableShadow") == "true"


def test_read_ini_key_absent_returns_none(tmp_path):
    ini = tmp_path / "a.ini"
    ini.write_text("[Display]\nfGamma=1.0\n; comment=ignored\n")
    assert snapshot.read_ini_key(ini, "Display", "iTexMipMapSkip") is None
    assert snapshot.read_ini_key(ini, "NoSection", "fGamma") is None
    assert snapshot.read_ini_key(tmp_path / "missing.ini", "Display", "x") is None


def test_atomic_write_creates_parents_and_replaces(tmp_path):
    target = tmp_path / "sub" / "out.md"
    snapshot.atomic_write(target, "one\n")
    snapshot.atomic_write(target, "two\n")
    assert target.read_bytes() == b"two\r\n"
    assert list(target.parent.glob("*.tmp-*")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `C:\Modding\tools`): `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'modkit.snapshot'`

- [ ] **Step 3: Write the implementation**

Create `C:\Modding\tools\modkit\snapshot.py`:

```python
"""modkit snapshot - per-game session-state snapshot/diff + open-items tracker.

Extends the modkit core CLI (docs/2026-07-11-modkit-design.md) with the
`snapshot take|diff` and `openitems add|done|list` subcommands.
Plan: docs/2026-07-11-snapshot-plan.md. Evidence: reflection-notes.md #9.

Safety: this module NEVER writes into game dirs, Plugins.txt, or the ledger.
Its only writes are C:\\Modding\\<game>-manual\\snapshots\\*.json and
C:\\Modding\\<game>-manual\\open-items.md (both atomic).
"""
import datetime
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from . import config, ledger_bridge, pluginstxt

SCHEMA_VERSION = 1


def safe_print(s):
    """print() that survives cp1252 Windows consoles (ledger.py pattern)."""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def read_text(path):
    """Read a text file BOM- and CRLF-tolerantly. Returns None if missing."""
    p = Path(path)
    if not p.is_file():
        return None
    return p.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")


def read_ini_key(path, section, key):
    """Value of `key` under `[section]` in a game-style INI, or None.

    A line scanner, deliberately NOT configparser: game INIs carry
    duplicate keys (last one wins, matching engine behavior), '%' chars,
    stray BOMs, and case drift ('[Display]' vs '[display]') that trip
    configparser. Section and key match case-insensitively. The value is
    everything after the first '=', stripped, verbatim (no inline-comment
    stripping - watched values are bare tokens like '1' or 'true').
    """
    text = read_text(path)
    if text is None:
        return None
    want_section = section.strip().lower()
    want_key = key.strip().lower()
    in_section = False
    value = None
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip().lower() == want_section
            continue
        if in_section and "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == want_key:
                value = v.strip()  # keep scanning: last occurrence wins
    return value


def atomic_write(path, text):
    """Write text as UTF-8/CRLF via temp file + os.replace (same-volume atomic)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **6 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): module skeleton, INI key scanner, atomic writes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Valve KeyValues (.acf) parser + Steam auto-update capture

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: `read_text` (Task 1).
- Produces: `parse_acf(text) -> dict` (raises `ValueError` on malformed input), `acf_get(d, *path) -> str|dict|None` (case-insensitive nested lookup), `capture_steam(snap_cfg) -> (dict|None, list[str])` — Task 3's `capture()` calls `capture_steam`.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 2

ACF = ('"AppState"\n{\n\t"appid"\t\t"489830"\n\t"name"\t\t"Skyrim SE"\n'
       '\t"AutoUpdateBehavior"\t\t"0"\n\t"UserConfig"\n\t{\n'
       '\t\t"language"\t\t"english"\n\t}\n}\n')


def _write_acf(tmp_path, behavior="1", appid="489830"):
    p = tmp_path / f"appmanifest_{appid}.acf"
    p.write_text(ACF.replace('"0"', f'"{behavior}"').replace('"489830"', f'"{appid}"'),
                 encoding="utf-8")
    return p


def test_parse_acf_nested_appmanifest():
    d = snapshot.parse_acf(ACF)
    assert d["AppState"]["appid"] == "489830"
    assert d["AppState"]["AutoUpdateBehavior"] == "0"
    assert d["AppState"]["UserConfig"]["language"] == "english"


def test_parse_acf_bare_tokens_escapes_comments():
    text = '// header comment\n"Root"\n{\n\tkey value\n\t"quoted"\t"a \\"b\\" c"\n}\n'
    d = snapshot.parse_acf(text)
    assert d["Root"]["key"] == "value"
    assert d["Root"]["quoted"] == 'a "b" c'


def test_parse_acf_unbalanced_raises():
    with pytest.raises(ValueError):
        snapshot.parse_acf('"a"\n{\n')
    with pytest.raises(ValueError):
        snapshot.parse_acf("}")


def test_acf_get_case_insensitive_missing_none():
    d = snapshot.parse_acf(ACF)
    assert snapshot.acf_get(d, "appstate", "AUTOUPDATEBEHAVIOR") == "0"
    assert snapshot.acf_get(d, "AppState", "UserConfig", "language") == "english"
    assert snapshot.acf_get(d, "AppState", "nope") is None
    assert snapshot.acf_get(d, "AppState", "appid", "deeper") is None


def test_capture_steam_behavior_1_no_warning(tmp_path):
    p = _write_acf(tmp_path, behavior="1")
    sec, warns = snapshot.capture_steam({"appmanifest": str(p), "steamAppId": 489830})
    assert sec["autoUpdateBehavior"] == "1"
    assert sec["appId"] == "489830"
    assert warns == []


def test_capture_steam_behavior_0_warns(tmp_path):
    p = _write_acf(tmp_path, behavior="0")
    sec, warns = snapshot.capture_steam({"appmanifest": str(p), "steamAppId": 489830})
    assert sec["autoUpdateBehavior"] == "0"
    assert len(warns) == 1 and "AutoUpdateBehavior" in warns[0] and "loader chain" in warns[0]


def test_capture_steam_missing_file_warns(tmp_path):
    sec, warns = snapshot.capture_steam(
        {"appmanifest": str(tmp_path / "gone.acf"), "steamAppId": 489830})
    assert sec["autoUpdateBehavior"] is None
    assert len(warns) == 1 and "not found" in warns[0]


def test_capture_steam_appid_mismatch_warns(tmp_path):
    p = _write_acf(tmp_path, behavior="1", appid="1091500")
    sec, warns = snapshot.capture_steam({"appmanifest": str(p), "steamAppId": 489830})
    assert len(warns) == 1 and "489830" in warns[0] and "1091500" in warns[0]


def test_capture_steam_unconfigured_skipped():
    assert snapshot.capture_steam({}) == (None, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 6 passed, **9 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'parse_acf'` (and `capture_steam`)

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# Valve KeyValues (.acf) - minimal text parser for Steam appmanifests
# --------------------------------------------------------------------------

def _acf_tokens(text):
    """Yield (token, is_string) - is_string False only for '{' / '}'.

    Handles quoted strings with \\" \\\\ \\n \\t escapes, bare tokens,
    and // line comments.
    """
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if c in "{}":
            yield c, False
            i += 1
            continue
        if c == '"':
            out = []
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    esc = text[i + 1]
                    out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1  # closing quote
            yield "".join(out), True
            continue
        j = i
        while j < n and text[j] not in ' \t\r\n"{}':
            j += 1
        yield text[i:j], True
        i = j


def parse_acf(text):
    """Minimal Valve KeyValues (.acf/.vdf text) parser -> nested dict.

    Grammar: `key value` pairs and `key { ... }` blocks, keys/values quoted
    or bare. Duplicate keys: last one wins. Raises ValueError on unbalanced
    braces or a dangling key.
    """
    root = {}
    stack = [root]
    key = None
    for tok, is_str in _acf_tokens(text):
        if not is_str and tok == "{":
            if key is None:
                raise ValueError("acf: '{' with no preceding key")
            child = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif not is_str and tok == "}":
            if key is not None:
                raise ValueError(f"acf: dangling key {key!r} before '}}'")
            if len(stack) == 1:
                raise ValueError("acf: unbalanced '}'")
            stack.pop()
        elif key is None:
            key = tok
        else:
            stack[-1][key] = tok
            key = None
    if len(stack) != 1:
        raise ValueError("acf: unclosed '{'")
    if key is not None:
        raise ValueError(f"acf: dangling key {key!r} at end of input")
    return root


def acf_get(d, *path):
    """Case-insensitive nested lookup; None when any hop is missing."""
    cur = d
    for name in path:
        if not isinstance(cur, dict):
            return None
        found = None
        for k, v in cur.items():
            if k.lower() == name.lower():
                found = v
        if found is None:
            return None
        cur = found
    return cur


AUTOUPDATE_MEANING = {
    "0": "always keep this game updated - DANGEROUS for modded games",
    "1": "only update this game when I launch it",
    "2": "high priority auto-update - DANGEROUS for modded games",
}


def capture_steam(snap_cfg):
    """Read AutoUpdateBehavior from the configured appmanifest.

    Returns (section_dict_or_None, warnings). None section = not configured.
    Any behavior other than "1" is a WARNING: an unattended Steam update
    breaks loader chains (RDR2 was 10 hours from exactly this, 2026-07-01).
    """
    path = snap_cfg.get("appmanifest")
    if not path:
        return None, []
    want_id = snap_cfg.get("steamAppId")
    section = {"appmanifest": str(path), "appId": None, "autoUpdateBehavior": None}
    text = read_text(path)
    if text is None:
        return section, [f"appmanifest not found: {path}"]
    try:
        acf = parse_acf(text)
    except ValueError as ex:
        return section, [f"appmanifest unparseable: {path}: {ex}"]
    section["appId"] = acf_get(acf, "AppState", "appid")
    behavior = acf_get(acf, "AppState", "AutoUpdateBehavior")
    section["autoUpdateBehavior"] = behavior
    warnings = []
    if want_id is not None and section["appId"] is not None \
            and str(want_id) != str(section["appId"]):
        warnings.append(f"appmanifest appid {section['appId']} != configured "
                        f"steamAppId {want_id} - wrong manifest path in modkit.json?")
    if behavior != "1":
        meaning = AUTOUPDATE_MEANING.get(behavior or "", "unknown value")
        warnings.append(
            f"Steam AutoUpdateBehavior={behavior!r} ({meaning}) - must be 1 "
            f"('only update when I launch'): an unattended auto-update can break "
            f"the loader chain (RDR2 near-miss 2026-07-01). "
            f"Fix in Steam > Properties > Updates.")
    return section, warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **15 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): Valve KeyValues .acf parser + Steam auto-update warning

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: Section captures + capture()

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: `modkit.pluginstxt.read(preset) -> list[str]`, `modkit.ledger_bridge.run(args) -> (rc, stdout)` (dependency contract); `read_ini_key`, `read_text`, `capture_steam` (Tasks 1-2).
- Produces: `capture(game, preset, snap_cfg, now=None) -> dict` (the full snapshot dict), plus per-section helpers `capture_plugins(preset)`, `capture_dlls(snap_cfg)`, `capture_ini(snap_cfg)`, `capture_enb(snap_cfg)`, `capture_ledger(game)`, and `snapshot_cfg(cfg, game)` / `manual_dir(preset)`. Tasks 4-6 rely on all of these names exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 3

LEDGER_OK = (0, "13 total, 11 active, 2 removed (13 matching filters)")


def _stub_preset(tmp_path):
    """Fixture preset carrying the contract attrs; never a real path."""
    return types.SimpleNamespace(
        DATA_DIR=str(tmp_path / "Data"),
        PLUGINS_TXT=str(tmp_path / "Plugins.txt"),
        PROCESS_NAMES=["SkyrimSE.exe"],
        RUNTIME="1.6.1170",
        STAGING_ROOT=str(tmp_path / "staging"),
        BACKUPS_DIR=str(tmp_path / "manual" / "backups"),
    )


def _patch_core(monkeypatch, plugins=("*USSEP.esp", "Precision.esp"), ledger=LEDGER_OK):
    monkeypatch.setattr(snapshot.pluginstxt, "read", lambda preset: list(plugins))
    monkeypatch.setattr(snapshot.ledger_bridge, "run", lambda args: ledger)


def test_capture_plugins_list_hash_counts(tmp_path, monkeypatch):
    _patch_core(monkeypatch)
    sec, warns = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["lines"] == ["*USSEP.esp", "Precision.esp"]
    assert sec["enabled"] == 1 and sec["total"] == 2
    assert sec["sha256"] == snapshot.hashlib.sha256(
        b"*USSEP.esp\nPrecision.esp\n").hexdigest()
    assert warns == []


def test_capture_plugins_hash_stable_and_blankline_free(tmp_path, monkeypatch):
    _patch_core(monkeypatch, plugins=("*A.esp", "", "  ", "*B.esp"))
    sec, _ = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["lines"] == ["*A.esp", "*B.esp"]
    _patch_core(monkeypatch, plugins=("*A.esp", "*B.esp"))
    sec2, _ = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["sha256"] == sec2["sha256"]


def test_capture_plugins_skipped_when_no_plugins_txt(tmp_path):
    preset = _stub_preset(tmp_path)
    preset.PLUGINS_TXT = None  # CP77: no Plugins.txt
    assert snapshot.capture_plugins(preset) == (None, [])


def test_capture_dlls_sorted_toplevel(tmp_path):
    d = tmp_path / "SKSE" / "Plugins"
    (d / "sub").mkdir(parents=True)
    (d / "b.dll").write_bytes(b"x")
    (d / "A.dll").write_bytes(b"x")
    (d / "note.txt").write_bytes(b"x")
    (d / "sub" / "nested.dll").write_bytes(b"x")  # top-level only
    sec, warns = snapshot.capture_dlls({"dllDir": str(d)})
    assert sec["dlls"] == ["A.dll", "b.dll"]
    assert warns == []


def test_capture_dlls_missing_dir_warns_and_unconfigured_skips(tmp_path):
    sec, warns = snapshot.capture_dlls({"dllDir": str(tmp_path / "gone")})
    assert sec["dlls"] is None and len(warns) == 1
    assert snapshot.capture_dlls({}) == (None, [])


def test_capture_ini_values_and_missing_file_warns(tmp_path):
    ini = tmp_path / "Skyrim.ini"
    ini.write_text("[Display]\niTexMipMapSkip=1\n")
    cfg = {"ini": [
        {"file": str(ini), "section": "Display", "key": "iTexMipMapSkip"},
        {"file": str(tmp_path / "gone.ini"), "section": "X", "key": "y"},
    ]}
    sec, warns = snapshot.capture_ini(cfg)
    assert sec["Skyrim.ini::Display::iTexMipMapSkip"] == "1"
    assert sec["gone.ini::X::y"] is None
    assert len(warns) == 1 and "gone.ini" in warns[0]
    assert snapshot.capture_ini({}) == (None, [])


def test_capture_enb_keys(tmp_path):
    enb = tmp_path / "enbseries.ini"
    enb.write_text("[COMPLEXPARTICLELIGHTS]\nEnableShadow=true\n")
    cfg = {"enb": {"file": str(enb), "keys": [
        {"section": "COMPLEXPARTICLELIGHTS", "key": "EnableShadow"},
        {"section": "EFFECT", "key": "EnableComplexParticleLights"},
    ]}}
    sec, warns = snapshot.capture_enb(cfg)
    assert sec["keys"]["COMPLEXPARTICLELIGHTS::EnableShadow"] == "true"
    assert sec["keys"]["EFFECT::EnableComplexParticleLights"] is None
    assert warns == []
    assert snapshot.capture_enb({}) == (None, [])


def test_capture_ledger_parses_counts(monkeypatch):
    calls = []
    monkeypatch.setattr(snapshot.ledger_bridge, "run",
                        lambda args: calls.append(args) or LEDGER_OK)
    sec, warns = snapshot.capture_ledger("skyrim")
    assert sec == {"total": 13, "active": 11, "removed": 2}
    assert warns == []
    assert calls == [["list", "--game", "skyrim", "--count"]]


def test_capture_ledger_failure_warns(monkeypatch):
    monkeypatch.setattr(snapshot.ledger_bridge, "run",
                        lambda args: (1, "ERROR: ledger not found"))
    sec, warns = snapshot.capture_ledger("skyrim")
    assert sec is None and len(warns) == 1 and "rc=1" in warns[0]


def test_capture_assembles_sections_and_thin_config(tmp_path, monkeypatch):
    _patch_core(monkeypatch)
    preset = _stub_preset(tmp_path)
    snap = snapshot.capture("skyrim", preset, {})
    assert snap["schemaVersion"] == 1 and snap["game"] == "skyrim"
    assert snap["sections"]["plugins"]["total"] == 2
    assert snap["sections"]["ledger"] == {"total": 13, "active": 11, "removed": 2}
    # thin config: unconfigured sections are None, no phantom warnings
    for name in ("dlls", "ini", "enb", "steam"):
        assert snap["sections"][name] is None
    assert snap["warnings"] == []
    assert snapshot.manual_dir(preset) == Path(preset.BACKUPS_DIR).parent
    assert snapshot.snapshot_cfg({"snapshot": {"skyrim": {"dllDir": "d"}}},
                                 "skyrim") == {"dllDir": "d"}
    assert snapshot.snapshot_cfg({}, "cp77") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 15 passed, **10 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'capture_plugins'` (and siblings)

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# Section captures (all pure reads)
# --------------------------------------------------------------------------

def snapshot_cfg(cfg, game):
    """The per-game 'snapshot' section of modkit.json ({} when absent)."""
    return (cfg.get("snapshot") or {}).get(game) or {}


def manual_dir(preset):
    """C:\\Modding\\<game>-manual, derived from the preset's BACKUPS_DIR
    (skyrim-manual\\backups -> skyrim-manual). Keeps this plan inside the
    dependency contract instead of inventing a new preset attribute."""
    return Path(preset.BACKUPS_DIR).parent


def capture_plugins(preset):
    """Plugins.txt state: verbatim non-blank lines + normalized SHA256 + counts.

    pluginstxt.read() is BOM/CRLF-safe (core contract); dropping blank lines
    and hashing '\\n'.join(lines)+'\\n' makes the hash stable across editors,
    trailing newlines, and CRLF re-saves (normalized-before-hash constraint).
    Returns (None, []) when the preset has no Plugins.txt (CP77).
    """
    if getattr(preset, "PLUGINS_TXT", None) is None:
        return None, []
    lines = [ln for ln in pluginstxt.read(preset) if ln.strip()]
    joined = "\n".join(lines) + "\n"
    return {
        "lines": lines,
        "sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "enabled": sum(1 for ln in lines if ln.startswith("*")),
        "total": len(lines),
    }, []


def capture_dlls(snap_cfg):
    """Top-level *.dll filenames in the configured dllDir (SKSE plugins for
    skyrim). Non-recursive, matching the sse-baseline counting convention."""
    d = snap_cfg.get("dllDir")
    if not d:
        return None, []
    p = Path(d)
    if not p.is_dir():
        return {"dir": str(d), "dlls": None}, [f"dllDir not found: {d}"]
    return {"dir": str(d), "dlls": sorted(f.name for f in p.glob("*.dll"))}, []


def capture_ini(snap_cfg):
    """Watched INI keys -> {'basename::section::key': value-or-None}.

    Key list comes from modkit.json - the code reads whatever is configured.
    Basenames (not full paths) keep snapshot keys drive-letter-portable;
    watched files must therefore have distinct basenames.
    """
    entries = snap_cfg.get("ini")
    if not entries:
        return None, []
    out, warnings = {}, []
    for e in entries:
        label = f"{Path(e['file']).name}::{e['section']}::{e['key']}"
        if not Path(e["file"]).is_file():
            out[label] = None
            warnings.append(f"ini file not found: {e['file']}")
            continue
        out[label] = read_ini_key(e["file"], e["section"], e["key"])
    return out, warnings


def capture_enb(snap_cfg):
    """Watched ENB flags from the configured enbseries.ini."""
    enb = snap_cfg.get("enb")
    if not enb:
        return None, []
    path = enb["file"]
    warnings = [] if Path(path).is_file() else [f"ENB config not found: {path}"]
    keys = {}
    for e in enb.get("keys", []):
        keys[f"{e['section']}::{e['key']}"] = read_ini_key(path, e["section"], e["key"])
    return {"file": str(path), "keys": keys}, warnings


_LEDGER_COUNT_RE = re.compile(r"(\d+) total, (\d+) active, (\d+) removed")


def capture_ledger(game):
    """Entry counts via `ledger.py list --game <g> --count` through the
    core ledger_bridge (never reads ledger.json directly)."""
    rc, stdout = ledger_bridge.run(["list", "--game", game, "--count"])
    m = _LEDGER_COUNT_RE.search(stdout or "")
    if rc != 0 or not m:
        return None, [f"ledger count unavailable (rc={rc}): "
                      f"{(stdout or '').strip()[:200]}"]
    return {"total": int(m.group(1)), "active": int(m.group(2)),
            "removed": int(m.group(3))}, []


def capture(game, preset, snap_cfg, now=None):
    """Capture the full live session-state snapshot dict (pure reads)."""
    now = now or datetime.datetime.now()
    sections, warnings = {}, []
    for name, (sec, w) in {
        "plugins": capture_plugins(preset),
        "dlls": capture_dlls(snap_cfg),
        "ini": capture_ini(snap_cfg),
        "enb": capture_enb(snap_cfg),
        "ledger": capture_ledger(game),
        "steam": capture_steam(snap_cfg),
    }.items():
        sections[name] = sec
        warnings.extend(w)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "game": game,
        "takenAt": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "sections": sections,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **25 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): live-state capture (plugins/dlls/ini/enb/ledger/steam)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: `snapshot take` core (file writing + latest lookup)

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: `capture`, `manual_dir`, `atomic_write` (Tasks 1, 3).
- Produces: `snapshots_dir(preset) -> Path`, `take(game, preset, snap_cfg, stamp=None) -> (Path, dict)`, `latest_snapshot(snapdir) -> Path|None`, `load_snapshot(path) -> dict`. Tasks 5-6 rely on these names exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 4

def test_take_writes_snapshot_json(tmp_path, monkeypatch):
    _patch_core(monkeypatch, plugins=("*A.esp",))
    preset = _stub_preset(tmp_path)
    path, snap = snapshot.take("skyrim", preset, {}, stamp="20260711-120000")
    assert path == (Path(preset.BACKUPS_DIR).parent / "snapshots"
                    / "snapshot-20260711-120000.json")
    on_disk = snapshot.load_snapshot(path)
    assert on_disk["game"] == "skyrim"
    assert on_disk["sections"]["plugins"]["enabled"] == 1
    assert on_disk == json.loads(json.dumps(snap))  # round-trip identical


def test_snapshots_dir_derived_from_backups_dir(tmp_path):
    preset = _stub_preset(tmp_path)
    assert snapshot.snapshots_dir(preset) == tmp_path / "manual" / "snapshots"


def test_latest_snapshot_picks_newest_and_none(tmp_path):
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "snapshot-20260701-090000.json").write_text("{}")
    (d / "snapshot-20260711-090000.json").write_text("{}")
    (d / "unrelated.txt").write_text("x")
    assert snapshot.latest_snapshot(d).name == "snapshot-20260711-090000.json"
    assert snapshot.latest_snapshot(tmp_path / "empty") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 25 passed, **3 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'take'`

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# snapshot take
# --------------------------------------------------------------------------

def snapshots_dir(preset):
    return manual_dir(preset) / "snapshots"


def take(game, preset, snap_cfg, stamp=None):
    """Capture live state and write snapshot-<ts>.json atomically.

    Returns (path, snapshot_dict). Writes ONLY under
    C:\\Modding\\<game>-manual\\snapshots\\ - game dirs are read, never written.
    """
    snap = capture(game, preset, snap_cfg)
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = snapshots_dir(preset) / f"snapshot-{stamp}.json"
    atomic_write(out, json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    return out, snap


def latest_snapshot(snapdir):
    """Newest snapshot file by name (stamp format sorts lexicographically)."""
    files = sorted(Path(snapdir).glob("snapshot-*.json"))
    return files[-1] if files else None


def load_snapshot(path):
    """Parse a snapshot file (BOM-tolerant). Raises on missing/corrupt."""
    return json.loads(Path(path).read_bytes().decode("utf-8-sig"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **28 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): take - atomic timestamped snapshot files + latest lookup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 5: diff engine + human report + the ask-the-user rule

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: snapshot dict shape from `capture` (Task 3).
- Produces: `diff_report(base, live) -> (text, delta_count, warning_count)`, module constant `ASK_THE_USER`. Task 6's `cmd_diff` relies on this signature exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 5

def _snap(plugins=None, dlls=None, ini=None, enb=None, ledger=None, steam=None,
          warnings=()):
    """Hand-build a snapshot dict in the exact capture() shape."""
    return {"schemaVersion": 1, "game": "skyrim", "takenAt": "2026-07-11T12:00:00",
            "sections": {"plugins": plugins, "dlls": dlls, "ini": ini,
                         "enb": enb, "ledger": ledger, "steam": steam},
            "warnings": list(warnings)}


def _plug(*lines):
    joined = "\n".join(lines) + "\n"
    import hashlib as h
    return {"lines": list(lines),
            "sha256": h.sha256(joined.encode("utf-8")).hexdigest(),
            "enabled": sum(1 for x in lines if x.startswith("*")),
            "total": len(lines)}


def test_diff_identical_no_drift():
    a = _snap(plugins=_plug("*A.esp"))
    text, deltas, warns = snapshot.diff_report(a, a)
    assert deltas == 0 and warns == 0
    assert "no drift" in text
    assert "ASK THE USER" not in text


def test_diff_plugin_added_removed():
    base = _snap(plugins=_plug("*A.esp", "*B.esp"))
    live = _snap(plugins=_plug("*A.esp", "*C.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 2
    assert "ADDED:   *C.esp" in text
    assert "REMOVED: *B.esp" in text


def test_diff_plugin_enable_flip():
    base = _snap(plugins=_plug("*Precision.esp"))
    live = _snap(plugins=_plug("Precision.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "CHANGED: Precision.esp: enabled -> DISABLED" in text


def test_diff_hash_only_change():
    base = _snap(plugins=_plug("*A.esp", "*B.esp"))
    live = _snap(plugins=_plug("*B.esp", "*A.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "same plugin set, different order/content" in text


def test_diff_dll_added():
    base = _snap(dlls={"dir": "d", "dlls": ["a.dll"]})
    live = _snap(dlls={"dir": "d", "dlls": ["a.dll", "OutfitDistributor.dll"]})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "ADDED:   OutfitDistributor.dll" in text


def test_diff_kv_ini_enb_changed():
    base = _snap(ini={"Skyrim.ini::Display::iTexMipMapSkip": "1"},
                 enb={"file": "e", "keys": {"EFFECT::X": "true"}})
    live = _snap(ini={"Skyrim.ini::Display::iTexMipMapSkip": None},
                 enb={"file": "e", "keys": {"EFFECT::X": "false"}})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 2
    assert "CHANGED: Skyrim.ini::Display::iTexMipMapSkip: '1' -> None" in text
    assert "CHANGED: EFFECT::X: 'true' -> 'false'" in text


def test_diff_ledger_and_steam_changed_and_warnings_surface():
    base = _snap(ledger={"total": 10, "active": 9, "removed": 1},
                 steam={"appmanifest": "p", "appId": "489830",
                        "autoUpdateBehavior": "1"})
    live = _snap(ledger={"total": 11, "active": 10, "removed": 1},
                 steam={"appmanifest": "p", "appId": "489830",
                        "autoUpdateBehavior": "0"},
                 warnings=["Steam AutoUpdateBehavior='0' ..."])
    text, deltas, warns = snapshot.diff_report(base, live)
    assert deltas == 2 and warns == 1
    assert "total 10 -> 11" in text
    assert "AutoUpdateBehavior '1' -> '0'" in text
    assert "WARNINGS (live state)" in text


def test_diff_ask_user_note_only_when_deltas():
    base = _snap(plugins=_plug("*A.esp"))
    live = _snap(plugins=_plug("A.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "ASK THE USER" in text and "Precision.esp" in text
    # warnings alone do not trigger the deltas note
    warntext, d2, w2 = snapshot.diff_report(base, _snap(plugins=_plug("*A.esp"),
                                                        warnings=["w"]))
    assert d2 == 0 and w2 == 1 and "ASK THE USER" not in warntext


def test_diff_section_presence_change_reported():
    base = _snap()
    live = _snap(dlls={"dir": "d", "dlls": ["a.dll"]})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1 and "appeared (newly configured)" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 28 passed, **9 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'diff_report'`

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# snapshot diff
# --------------------------------------------------------------------------

ASK_THE_USER = """\
------------------------------------------------------------
NOTE FOR CLAUDE - read before acting on this report:
Unexplained deltas are NOT automatically bugs. The user changes things
between sessions deliberately (2026-07-01: Precision.esp was disabled by
choice, and a session-start audit wrongly flagged it as an urgent bug).
Before treating any delta above as a defect - and before "fixing" anything -
ASK THE USER: "What did you change manually since the last snapshot?"
Only act on a delta after the user confirms it was not deliberate."""


def _plugin_map(sec):
    """plugins section -> {lowercased name: (enabled, display_name)}."""
    out = {}
    for ln in sec.get("lines") or []:
        display = ln.lstrip("*").strip()
        out[display.lower()] = (ln.startswith("*"), display)
    return out


def _diff_kv(bd, ld):
    """Diff two flat {key: value} dicts -> report lines (sorted by key)."""
    lines = []
    for k in sorted(set(bd) | set(ld)):
        if k not in bd:
            lines.append(f"  ADDED:   {k} = {ld[k]!r}")
        elif k not in ld:
            lines.append(f"  REMOVED: {k} (was {bd[k]!r})")
        elif bd[k] != ld[k]:
            lines.append(f"  CHANGED: {k}: {bd[k]!r} -> {ld[k]!r}")
    return lines


def diff_report(base, live):
    """Stored snapshot vs live capture -> (text, delta_count, warning_count).

    Deltas are grouped ADDED / REMOVED / CHANGED per section. Whenever any
    delta exists the report ends with the ASK_THE_USER note - deliberate
    user changes must never be treated as bugs (reflection-notes.md #9).
    """
    out = []
    deltas = 0
    bsec = base.get("sections") or {}
    lsec = live.get("sections") or {}

    def presence_changed(heading, b, l):
        nonlocal deltas
        if (b is None) != (l is None):
            out.append(heading)
            out.append("  CHANGED: section "
                       + ("appeared (newly configured)" if b is None
                          else "disappeared (config removed?)"))
            deltas += 1
            return True
        return False

    # --- Plugins.txt
    b, l = bsec.get("plugins"), lsec.get("plugins")
    if not presence_changed("PLUGINS (Plugins.txt)", b, l) and b is not None:
        bm, lm = _plugin_map(b), _plugin_map(l)
        added = sorted(set(lm) - set(bm))
        removed = sorted(set(bm) - set(lm))
        flipped = sorted(n for n in set(bm) & set(lm) if bm[n][0] != lm[n][0])
        hash_only = (b["sha256"] != l["sha256"]) and not (added or removed or flipped)
        if added or removed or flipped or hash_only:
            out.append("PLUGINS (Plugins.txt)")
            for n in added:
                out.append(f"  ADDED:   {'*' if lm[n][0] else ''}{lm[n][1]}")
            for n in removed:
                out.append(f"  REMOVED: {'*' if bm[n][0] else ''}{bm[n][1]}")
            for n in flipped:
                state = "disabled -> ENABLED" if lm[n][0] else "enabled -> DISABLED"
                out.append(f"  CHANGED: {lm[n][1]}: {state}")
            if hash_only:
                out.append("  CHANGED: same plugin set, different order/content "
                           "(sha256 differs)")
            out.append(f"  enabled {b['enabled']} -> {l['enabled']}, "
                       f"total {b['total']} -> {l['total']}")
            deltas += len(added) + len(removed) + len(flipped) + (1 if hash_only else 0)

    # --- watched DLLs
    b, l = bsec.get("dlls"), lsec.get("dlls")
    if not presence_changed("DLLS", b, l) and b is not None:
        bd, ld = set(b.get("dlls") or []), set(l.get("dlls") or [])
        if bd != ld:
            out.append(f"DLLS ({l.get('dir')})")
            for n in sorted(ld - bd):
                out.append(f"  ADDED:   {n}")
            for n in sorted(bd - ld):
                out.append(f"  REMOVED: {n}")
            deltas += len(bd ^ ld)

    # --- watched INI keys
    b, l = bsec.get("ini"), lsec.get("ini")
    if not presence_changed("WATCHED INI KEYS", b, l) and b is not None:
        kv = _diff_kv(b, l)
        if kv:
            out.append("WATCHED INI KEYS")
            out.extend(kv)
            deltas += len(kv)

    # --- watched ENB flags
    b, l = bsec.get("enb"), lsec.get("enb")
    if not presence_changed("WATCHED ENB FLAGS", b, l) and b is not None:
        kv = _diff_kv(b.get("keys") or {}, l.get("keys") or {})
        if kv:
            out.append(f"WATCHED ENB FLAGS ({l.get('file')})")
            out.extend(kv)
            deltas += len(kv)

    # --- ledger counts
    b, l = bsec.get("ledger"), lsec.get("ledger")
    if not presence_changed("LEDGER", b, l) and b is not None and b != l:
        out.append("LEDGER")
        out.append(f"  CHANGED: total {b['total']} -> {l['total']}, "
                   f"active {b['active']} -> {l['active']}, "
                   f"removed {b['removed']} -> {l['removed']}")
        deltas += 1

    # --- steam auto-update
    b, l = bsec.get("steam"), lsec.get("steam")
    if not presence_changed("STEAM", b, l) and b is not None:
        if b.get("autoUpdateBehavior") != l.get("autoUpdateBehavior"):
            out.append("STEAM")
            out.append(f"  CHANGED: AutoUpdateBehavior "
                       f"{b.get('autoUpdateBehavior')!r} -> "
                       f"{l.get('autoUpdateBehavior')!r}")
            deltas += 1

    warnings = list(live.get("warnings") or [])
    if warnings:
        out.append("WARNINGS (live state)")
        out.extend(f"  {w}" for w in warnings)

    if deltas == 0 and not warnings:
        out.append("no drift - live state matches the snapshot.")
    else:
        out.append("")
        out.append(f"{deltas} delta(s), {len(warnings)} warning(s).")
        if deltas:
            out.append(ASK_THE_USER)
    return "\n".join(out), deltas, len(warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **37 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): diff engine with grouped report + ask-the-user rule

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 6: CLI handlers + wiring into the modkit CLI

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\modkit\cli.py` (two lines)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: `modkit.config.load() -> dict`, `modkit.config.game(cfg, name) -> preset` (dependency contract); `take`, `latest_snapshot`, `load_snapshot`, `diff_report`, `snapshot_cfg` (Tasks 3-5).
- Produces: `_ctx(args) -> (preset, snap_cfg)` (the single seam tests monkeypatch), `cmd_take(args) -> int`, `cmd_diff(args) -> int`, `register(sub)`. Task 8 extends `register`.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 6

def _cli(argv):
    p = argparse.ArgumentParser(prog="modkit")
    sub = p.add_subparsers(dest="command", required=True)
    snapshot.register(sub)
    return p.parse_args(argv)


def _patch_ctx(monkeypatch, preset, snap_cfg=None):
    monkeypatch.setattr(snapshot, "_ctx", lambda args: (preset, snap_cfg or {}))


def test_register_parses_snapshot_cmds():
    a = _cli(["snapshot", "take", "--game", "skyrim"])
    assert a.func is snapshot.cmd_take and a.game == "skyrim"
    a = _cli(["snapshot", "diff", "--game", "cp77", "--against", "x.json"])
    assert a.func is snapshot.cmd_diff and a.against == "x.json"


def test_cmd_take_rc0_clean_rc2_on_warning(tmp_path, monkeypatch, capsys):
    _patch_core(monkeypatch)
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    rc = snapshot.cmd_take(_cli(["snapshot", "take", "--game", "skyrim"]))
    assert rc == 0
    assert "snapshot written:" in capsys.readouterr().out
    # a missing dllDir produces a warning -> rc 2
    _patch_ctx(monkeypatch, preset, {"dllDir": str(tmp_path / "gone")})
    rc = snapshot.cmd_take(_cli(["snapshot", "take", "--game", "skyrim"]))
    assert rc == 2
    assert "WARNING:" in capsys.readouterr().out


def test_cmd_diff_no_snapshots_rc1(tmp_path, monkeypatch, capsys):
    _patch_core(monkeypatch)
    _patch_ctx(monkeypatch, _stub_preset(tmp_path))
    rc = snapshot.cmd_diff(_cli(["snapshot", "diff", "--game", "skyrim"]))
    assert rc == 1
    assert "no snapshots" in capsys.readouterr().out


def test_cmd_take_then_diff_clean_then_drift(tmp_path, monkeypatch, capsys):
    plugins = ["*A.esp", "*B.esp"]
    monkeypatch.setattr(snapshot.pluginstxt, "read", lambda p: list(plugins))
    monkeypatch.setattr(snapshot.ledger_bridge, "run", lambda a: LEDGER_OK)
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    assert snapshot.cmd_take(_cli(["snapshot", "take", "--game", "skyrim"])) == 0
    assert snapshot.cmd_diff(_cli(["snapshot", "diff", "--game", "skyrim"])) == 0
    assert "no drift" in capsys.readouterr().out
    plugins[1] = "B.esp"  # user disables a plugin between sessions
    rc = snapshot.cmd_diff(_cli(["snapshot", "diff", "--game", "skyrim"]))
    out = capsys.readouterr().out
    assert rc == 2
    assert "B.esp: enabled -> DISABLED" in out and "ASK THE USER" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 37 passed, **4 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'register'`

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# CLI handlers + registration
# --------------------------------------------------------------------------

def _ctx(args):
    """Resolve (preset, snapshot-config) via the core interfaces.

    The single seam tests monkeypatch; everything below it is pure logic
    over fixture paths.
    """
    cfg = config.load()
    preset = config.game(cfg, args.game)
    return preset, snapshot_cfg(cfg, args.game)


def cmd_take(args):
    preset, snap_cfg = _ctx(args)
    path, snap = take(args.game, preset, snap_cfg)
    safe_print(f"snapshot written: {path}")
    for w in snap["warnings"]:
        safe_print(f"WARNING: {w}")
    return 2 if snap["warnings"] else 0


def cmd_diff(args):
    preset, snap_cfg = _ctx(args)
    if args.against:
        base_path = Path(args.against)
        if not base_path.is_file():
            safe_print(f"ERROR: snapshot not found: {base_path}")
            return 1
    else:
        base_path = latest_snapshot(snapshots_dir(preset))
        if base_path is None:
            safe_print(f"no snapshots in {snapshots_dir(preset)} - "
                       f"run: modkit snapshot take --game {args.game}")
            return 1
    try:
        base = load_snapshot(base_path)
    except (OSError, ValueError) as ex:
        safe_print(f"ERROR: cannot read snapshot {base_path}: {ex}")
        return 1
    live = capture(args.game, preset, snap_cfg)
    text, deltas, warnings = diff_report(base, live)
    safe_print(f"snapshot diff - {args.game}")
    safe_print(f"baseline: {base_path} (taken {base.get('takenAt', '?')})")
    safe_print("live:     captured now")
    safe_print("")
    safe_print(text)
    return 2 if (deltas or warnings) else 0


def register(sub):
    """Wire the snapshot subcommand into the modkit CLI.

    `sub` is the top-level argparse subparsers object in modkit\\cli.py.
    Handlers are plain `func(args) -> int` set via set_defaults, matching
    the core dispatch (`args.func(args)`, ledger.py pattern). --game is
    declared on each leaf parser so this module is self-contained.
    """
    sp = sub.add_parser(
        "snapshot", help="per-game session-state snapshot: take / diff")
    ssub = sp.add_subparsers(dest="snapshot_cmd", required=True)

    t = ssub.add_parser(
        "take", help="capture live state to <game>-manual\\snapshots\\")
    t.add_argument("--game", required=True, help="skyrim | cp77")
    t.set_defaults(func=cmd_take)

    d = ssub.add_parser(
        "diff", help="latest (or --against) snapshot vs live state; exit 2 = drift")
    d.add_argument("--game", required=True, help="skyrim | cp77")
    d.add_argument("--against", help="explicit snapshot .json (default: latest)")
    d.set_defaults(func=cmd_diff)
```

Then modify `C:\Modding\tools\modkit\cli.py` — exactly two additions:

1. With the module's other intra-package imports, add:

```python
from . import snapshot
```

2. Immediately after the core subcommands are registered on the top-level subparsers object (created by `add_subparsers(...)` — use whatever local name core cli.py gave it; shown here as `sub`), add:

```python
snapshot.register(sub)
```

If the merged core cli.py dispatches other than via `args.func(args)`, adapt only these two wiring lines — the snapshot handlers are plain `f(args) -> int` and need no other change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **41 passed**

Also verify the wiring end-to-end (help text only — touches no real state):

Run: `py -3 C:\Modding\tools\modkit.py snapshot --help`
Expected: usage text listing `take` and `diff`.

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py modkit/cli.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): take/diff CLI handlers wired into modkit

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 7: open-items parser + renderer

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_open_items(text) -> {"open": [...], "done": [...], "notes": [...]}`, `render_open_items(doc, game) -> str`. Task 8's handlers rely on these exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 7

HAND_EDITED = """# Open Items - skyrim

## Open

- [ ] 2026-07-01 - iTexMipMapSkip=1 decision pending
- [x] 2026-07-01 - BTPS config restored (done, wrong section by hand)
some prose note the user typed
* [ ] star-bullet item added by hand

## Completed

- [X] 2026-06-30 - Bashed Patch rebuilt (done 2026-07-01)
"""


def test_parse_tolerant_checkbox_authority():
    doc = snapshot.parse_open_items(HAND_EDITED)
    # the checkbox mark decides, not the heading the line sits under
    assert doc["open"] == ["2026-07-01 - iTexMipMapSkip=1 decision pending",
                           "star-bullet item added by hand"]
    assert doc["done"] == [
        "2026-07-01 - BTPS config restored (done, wrong section by hand)",
        "2026-06-30 - Bashed Patch rebuilt (done 2026-07-01)"]
    assert doc["notes"] == ["some prose note the user typed"]


def test_parse_empty_or_missing_text():
    assert snapshot.parse_open_items("") == {"open": [], "done": [], "notes": []}
    assert snapshot.parse_open_items(None) == {"open": [], "done": [], "notes": []}


def test_render_canonical():
    doc = {"open": ["a"], "done": ["b (done 2026-07-11)"], "notes": ["n"]}
    text = snapshot.render_open_items(doc, "skyrim")
    assert text.startswith("# Open Items - skyrim\n")
    assert "## Open\n\n- [ ] a" in text
    assert "## Completed\n\n- [x] b (done 2026-07-11)" in text
    assert "## Notes\n\nn" in text


def test_render_empty_sections_use_placeholder():
    text = snapshot.render_open_items({"open": [], "done": [], "notes": []}, "cp77")
    assert text.count("(none)") == 2


def test_roundtrip_stable():
    doc = snapshot.parse_open_items(HAND_EDITED)
    text1 = snapshot.render_open_items(doc, "skyrim")
    doc2 = snapshot.parse_open_items(text1)
    assert doc2 == doc                       # nothing lost, nothing duplicated
    assert snapshot.render_open_items(doc2, "skyrim") == text1  # fixpoint
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 41 passed, **5 failed** — `AttributeError: module 'modkit.snapshot' has no attribute 'parse_open_items'`

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
# --------------------------------------------------------------------------
# open-items tracker (C:\Modding\<game>-manual\open-items.md)
# --------------------------------------------------------------------------

_ITEM_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<body>.*\S)\s*$")


def parse_open_items(text):
    """Tolerant parse of open-items.md -> {"open", "done", "notes"} lists.

    Authority is the checkbox mark, not the heading: any '- [ ]' line
    anywhere counts as open and any '- [x]' as completed, so hand-added
    items in the wrong section still round-trip correctly. Blank lines,
    headings ('#...'), and '(none)' placeholders are layout and dropped;
    every other non-blank line is preserved verbatim under notes.
    """
    doc = {"open": [], "done": [], "notes": []}
    for line in (text or "").split("\n"):
        m = _ITEM_RE.match(line)
        if m:
            bucket = "done" if m.group("mark") in "xX" else "open"
            doc[bucket].append(m.group("body"))
            continue
        s = line.strip()
        if not s or s.startswith("#") or s == "(none)":
            continue
        doc["notes"].append(s)
    return doc


def render_open_items(doc, game):
    """Canonical open-items.md text. Human-editable; reparsed tolerantly."""
    out = [f"# Open Items - {game}", "", "## Open", ""]
    if doc["open"]:
        out += [f"- [ ] {b}" for b in doc["open"]]
    else:
        out.append("(none)")
    out += ["", "## Completed", ""]
    if doc["done"]:
        out += [f"- [x] {b}" for b in doc["done"]]
    else:
        out.append("(none)")
    if doc["notes"]:
        out += ["", "## Notes", ""]
        out += doc["notes"]
    out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **46 passed**

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): tolerant open-items markdown parser + canonical renderer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 8: `openitems add|done|list` handlers + wiring

**Files:**
- Modify: `C:\Modding\tools\modkit\snapshot.py` (append handlers; replace `register`)
- Modify: `C:\Modding\tools\tests\test_modkit\test_snapshot.py` (append)

**Interfaces:**
- Consumes: `parse_open_items`, `render_open_items` (Task 7), `_ctx`, `manual_dir`, `atomic_write`, `read_text`, `safe_print` (Tasks 1, 3, 6).
- Produces: `open_items_path(preset) -> Path`, `cmd_openitems_add/done/list(args) -> int`; `register(sub)` grows the `openitems` subcommand.

- [ ] **Step 1: Write the failing tests**

Append to `tests\test_modkit\test_snapshot.py`:

```python
# ---------------------------------------------------------------- Task 8

def test_register_parses_openitems_cmds():
    a = _cli(["openitems", "add", "--game", "skyrim", "fix the thing"])
    assert a.func is snapshot.cmd_openitems_add and a.text == "fix the thing"
    a = _cli(["openitems", "done", "--game", "skyrim", "thing"])
    assert a.func is snapshot.cmd_openitems_done
    a = _cli(["openitems", "list", "--game", "cp77"])
    assert a.func is snapshot.cmd_openitems_list


def test_openitems_add_creates_file(tmp_path, monkeypatch, capsys):
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    rc = snapshot.cmd_openitems_add(
        _cli(["openitems", "add", "--game", "skyrim", "decide iTexMipMapSkip"]))
    assert rc == 0
    path = tmp_path / "manual" / "open-items.md"
    doc = snapshot.parse_open_items(snapshot.read_text(path))
    assert len(doc["open"]) == 1 and doc["open"][0].endswith("- decide iTexMipMapSkip")


def test_openitems_done_moves_item(tmp_path, monkeypatch, capsys):
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    snapshot.cmd_openitems_add(_cli(["openitems", "add", "--game", "skyrim", "alpha task"]))
    snapshot.cmd_openitems_add(_cli(["openitems", "add", "--game", "skyrim", "beta task"]))
    rc = snapshot.cmd_openitems_done(_cli(["openitems", "done", "--game", "skyrim", "alpha"]))
    assert rc == 0
    doc = snapshot.parse_open_items(
        snapshot.read_text(tmp_path / "manual" / "open-items.md"))
    assert len(doc["open"]) == 1 and "beta task" in doc["open"][0]
    assert len(doc["done"]) == 1 and "alpha task" in doc["done"][0]
    assert "(done " in doc["done"][0]


def test_openitems_done_ambiguous_or_none_rc1(tmp_path, monkeypatch, capsys):
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    snapshot.cmd_openitems_add(_cli(["openitems", "add", "--game", "skyrim", "task one"]))
    snapshot.cmd_openitems_add(_cli(["openitems", "add", "--game", "skyrim", "task two"]))
    capsys.readouterr()
    rc = snapshot.cmd_openitems_done(_cli(["openitems", "done", "--game", "skyrim", "task"]))
    assert rc == 1 and "2 open item(s) match" in capsys.readouterr().out
    rc = snapshot.cmd_openitems_done(_cli(["openitems", "done", "--game", "skyrim", "zzz"]))
    assert rc == 1 and "0 open item(s) match" in capsys.readouterr().out
    # nothing was moved on error
    doc = snapshot.parse_open_items(
        snapshot.read_text(tmp_path / "manual" / "open-items.md"))
    assert len(doc["open"]) == 2 and doc["done"] == []


def test_openitems_list_output(tmp_path, monkeypatch, capsys):
    preset = _stub_preset(tmp_path)
    _patch_ctx(monkeypatch, preset)
    rc = snapshot.cmd_openitems_list(_cli(["openitems", "list", "--game", "skyrim"]))
    assert rc == 0 and "no open items" in capsys.readouterr().out
    snapshot.cmd_openitems_add(_cli(["openitems", "add", "--game", "skyrim", "gamma"]))
    capsys.readouterr()
    rc = snapshot.cmd_openitems_list(_cli(["openitems", "list", "--game", "skyrim"]))
    out = capsys.readouterr().out
    assert rc == 0 and "gamma" in out and "1 open, 0 completed" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: 46 passed, **5 failed** — first failure `argparse` error: `invalid choice: 'openitems'`

- [ ] **Step 3: Write the implementation**

Append to `modkit\snapshot.py`:

```python
def open_items_path(preset):
    return manual_dir(preset) / "open-items.md"


def cmd_openitems_add(args):
    preset, _ = _ctx(args)
    path = open_items_path(preset)
    doc = parse_open_items(read_text(path) or "")
    body = f"{datetime.date.today().isoformat()} - {args.text}"
    doc["open"].append(body)
    atomic_write(path, render_open_items(doc, args.game))
    safe_print(f"added open item: {body}")
    return 0


def cmd_openitems_done(args):
    preset, _ = _ctx(args)
    path = open_items_path(preset)
    doc = parse_open_items(read_text(path) or "")
    needle = args.text.lower()
    hits = [b for b in doc["open"] if needle in b.lower()]
    if len(hits) != 1:
        safe_print(f"ERROR: {len(hits)} open item(s) match {args.text!r} - "
                   f"need exactly 1:")
        for b in (hits or doc["open"]):
            safe_print(f"  - [ ] {b}")
        return 1
    doc["open"].remove(hits[0])
    doc["done"].append(f"{hits[0]} (done {datetime.date.today().isoformat()})")
    atomic_write(path, render_open_items(doc, args.game))
    safe_print(f"completed: {hits[0]}")
    return 0


def cmd_openitems_list(args):
    preset, _ = _ctx(args)
    path = open_items_path(preset)
    doc = parse_open_items(read_text(path) or "")
    if not doc["open"]:
        safe_print(f"no open items for {args.game} "
                   f"({len(doc['done'])} completed) - {path}")
        return 0
    safe_print(f"open items - {args.game}:")
    for b in doc["open"]:
        safe_print(f"  - [ ] {b}")
    safe_print(f"{len(doc['open'])} open, {len(doc['done'])} completed - {path}")
    return 0
```

Then REPLACE the existing `register` function (from Task 6) with this full version:

```python
def register(sub):
    """Wire the snapshot + openitems subcommands into the modkit CLI.

    `sub` is the top-level argparse subparsers object in modkit\\cli.py.
    Handlers are plain `func(args) -> int` set via set_defaults, matching
    the core dispatch (`args.func(args)`, ledger.py pattern). --game is
    declared on each leaf parser so this module is self-contained.
    """
    sp = sub.add_parser(
        "snapshot", help="per-game session-state snapshot: take / diff")
    ssub = sp.add_subparsers(dest="snapshot_cmd", required=True)

    t = ssub.add_parser(
        "take", help="capture live state to <game>-manual\\snapshots\\")
    t.add_argument("--game", required=True, help="skyrim | cp77")
    t.set_defaults(func=cmd_take)

    d = ssub.add_parser(
        "diff", help="latest (or --against) snapshot vs live state; exit 2 = drift")
    d.add_argument("--game", required=True, help="skyrim | cp77")
    d.add_argument("--against", help="explicit snapshot .json (default: latest)")
    d.set_defaults(func=cmd_diff)

    op = sub.add_parser(
        "openitems", help="per-game pending-fixes tracker (open-items.md)")
    osub = op.add_subparsers(dest="openitems_cmd", required=True)

    a = osub.add_parser("add", help="add an open item (dated)")
    a.add_argument("--game", required=True, help="skyrim | cp77")
    a.add_argument("text", help="item text")
    a.set_defaults(func=cmd_openitems_add)

    dn = osub.add_parser("done", help="complete the single item matching a substring")
    dn.add_argument("--game", required=True, help="skyrim | cp77")
    dn.add_argument("text", help="substring uniquely matching one open item")
    dn.set_defaults(func=cmd_openitems_done)

    ls = osub.add_parser("list", help="list open items (run at session start)")
    ls.add_argument("--game", required=True, help="skyrim | cp77")
    ls.set_defaults(func=cmd_openitems_list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_modkit/test_snapshot.py -v`
Expected: **51 passed**

Run: `py -3 C:\Modding\tools\modkit.py openitems --help`
Expected: usage text listing `add`, `done`, `list`.

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add modkit/snapshot.py tests/test_modkit/test_snapshot.py
git -C C:\Modding\tools commit -m @'
feat(snapshot): openitems add/done/list subcommand

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 9: Real modkit.json snapshot section + memory pins

**Files:**
- Modify: `C:\Modding\tools\modkit.json` (add one top-level key)
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\snapshot.md`
- Modify: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\MEMORY.md` (one index line)
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\snapshot.md`
- Modify: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\MEMORY.md` (one index line)

**Interfaces:**
- Consumes: the config schema defined at the top of this plan.
- Produces: live configuration + the adoption layer (memory pins carry the session-start/session-end convention).

- [ ] **Step 1: Add the snapshot section to modkit.json**

Edit `C:\Modding\tools\modkit.json` and add this top-level key alongside the existing core keys (keep everything already there; paths below were verified on disk 2026-07-11):

```json
"snapshot": {
    "skyrim": {
        "ini": [
            {"file": "C:\\Users\\auand\\Documents\\My Games\\Skyrim Special Edition\\Skyrim.ini",
             "section": "Display", "key": "iTexMipMapSkip"}
        ],
        "enb": {
            "file": "E:\\SteamLibrary\\steamapps\\common\\Skyrim Special Edition\\enbseries.ini",
            "keys": [
                {"section": "EFFECT", "key": "EnableComplexParticleLights"},
                {"section": "COMPLEXPARALLAXMATERIALS", "key": "Enable"},
                {"section": "COMPLEXPARTICLELIGHTS", "key": "EnableShadow"}
            ]
        },
        "dllDir": "E:\\SteamLibrary\\steamapps\\common\\Skyrim Special Edition\\Data\\SKSE\\Plugins",
        "steamAppId": 489830,
        "appmanifest": "E:\\SteamLibrary\\steamapps\\appmanifest_489830.acf"
    },
    "cp77": {
        "steamAppId": 1091500,
        "appmanifest": "E:\\SteamLibrary\\steamapps\\appmanifest_1091500.acf"
    }
}
```

Why these watch keys: `iTexMipMapSkip` is the audit's open item 3 (hand-added, halves texture res silently); `EnableComplexParticleLights` [EFFECT] is load-bearing for ENB Light; `[COMPLEXPARALLAXMATERIALS] Enable` is load-bearing for the Route B parallax bake (off = shimmer/purple); `EnableShadow` [COMPLEXPARTICLELIGHTS] is the TP-shop FPS fix that already silently persisted/reverted once. Add more keys later by editing config only — no code change.

- [ ] **Step 2: Verify the config parses and take works against it**

Run: `py -3 -c "import json; c=json.load(open(r'C:\Modding\tools\modkit.json', encoding='utf-8-sig')); print(c['snapshot']['skyrim']['steamAppId'], c['snapshot']['cp77']['steamAppId'])"`
Expected: `489830 1091500`

- [ ] **Step 3: Write the Skyrim memory pin**

Create `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\snapshot.md`:

```markdown
---
name: snapshot
description: session-state snapshots + open-items via modkit — diff & openitems list at session START, take at session END / after installs; unexplained deltas = ASK THE USER, not bugs
metadata:
  type: project
---

Session-state drift and pending fixes are managed by modkit
(`py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim`):

- **Session START (every modding session):**
  `py -3 C:\Modding\tools\modkit.py snapshot diff --game skyrim`
  `py -3 C:\Modding\tools\modkit.py openitems list --game skyrim`
  Exit 2 from diff = drift or warnings — read the report. **Unexplained deltas
  are questions for the user ("what did you change manually?"), NOT bugs to
  fix** (Precision.esp was disabled by choice 2026-07-01 and a session-start
  audit wrongly flagged it as an urgent bug).
- **Session END and after every install batch:**
  `py -3 C:\Modding\tools\modkit.py snapshot take --game skyrim`
- Any root-caused-but-not-executed fix gets
  `py -3 C:\Modding\tools\modkit.py openitems add --game skyrim "<item>"`
  BEFORE the session ends (XPMSE/Bashed-Patch fixes sat unexecuted for weeks
  when they lived only in prose notes).
- Snapshots: `C:\Modding\skyrim-manual\snapshots\snapshot-<ts>.json` (plugin
  list + normalized SHA256 + counts, SKSE DLL list, watched INI keys, watched
  ENB flags, ledger counts, Steam AutoUpdateBehavior). Open items:
  `C:\Modding\skyrim-manual\open-items.md` (checkbox markdown; hand-edits are
  fine — the parser is tolerant).
- Steam AutoUpdateBehavior must stay **1** ("only update when I launch") —
  anything else risks an unattended update breaking the SKSE loader chain
  (RDR2 was 10 hours from exactly that, 2026-07-01). take/diff WARN when it
  is not 1.
- Watched INI/ENB key lists live in `C:\Modding\tools\modkit.json` under
  `snapshot.skyrim` — extend by editing config, not code.

**Why:** stale baselines cost ~30 tool calls per session-start re-audit
(reflection-notes.md #9). **How:** never hand-write snapshot files; snapshot
never writes into game dirs (reads only).
```

- [ ] **Step 4: Index it in the Skyrim MEMORY.md**

Edit `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\MEMORY.md` — insert this line directly after the `# Project Memory — Skyrim SE Modding` heading (i.e. as the FIRST index entry, above the Ledger CLI line):

```markdown
- [Snapshot + open items](snapshot.md) — session START: `modkit snapshot diff` + `openitems list`; session END/installs: `snapshot take`; unexplained deltas = ASK THE USER, not bugs; Steam AutoUpdateBehavior must stay 1
```

- [ ] **Step 5: Write the CP77 memory pin**

Create `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\snapshot.md`:

```markdown
---
name: snapshot
description: session-state snapshots + open-items via modkit — diff & openitems list at session START, take at session END / after installs; unexplained deltas = ASK THE USER, not bugs
metadata:
  type: project
---

Session-state drift and pending fixes are managed by modkit
(`py -3 C:\Modding\tools\modkit.py <cmd> --game cp77`):

- **Session START (every modding session):**
  `py -3 C:\Modding\tools\modkit.py snapshot diff --game cp77`
  `py -3 C:\Modding\tools\modkit.py openitems list --game cp77`
  Exit 2 from diff = drift or warnings — read the report. **Unexplained deltas
  are questions for the user ("what did you change manually?"), NOT bugs to
  fix** (Skyrim lesson 2026-07-01: Precision.esp was disabled by choice and
  got flagged as an urgent bug).
- **Session END and after every install batch:**
  `py -3 C:\Modding\tools\modkit.py snapshot take --game cp77`
- Any root-caused-but-not-executed fix gets
  `py -3 C:\Modding\tools\modkit.py openitems add --game cp77 "<item>"`
  BEFORE the session ends.
- Snapshots: `C:\Modding\cyberpunk-manual\snapshots\snapshot-<ts>.json`;
  open items: `C:\Modding\cyberpunk-manual\open-items.md` (checkbox markdown;
  hand-edits are fine — the parser is tolerant).
- CP77 is the THIN preset: the snapshot currently captures ledger counts +
  Steam AutoUpdateBehavior only (no Plugins.txt/SKSE/ENB/INI equivalents
  configured). Plugin/DLL/INI/ENB watch sections appear automatically if
  configured later under `snapshot.cp77` in `C:\Modding\tools\modkit.json`
  (e.g. `dllDir` pointed at `red4ext\plugins`).
- Steam AutoUpdateBehavior must stay **1** ("only update when I launch") —
  anything else risks an unattended update breaking the RED4ext loader chain
  (RDR2 was 10 hours from exactly that, 2026-07-01). take/diff WARN when it
  is not 1.

**Why:** stale baselines cost ~30 tool calls per session-start re-audit
(reflection-notes.md #9). **How:** never hand-write snapshot files; snapshot
never writes into game dirs (reads only).
```

- [ ] **Step 6: Index it in the CP77 MEMORY.md**

Edit `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\MEMORY.md` — insert this as the FIRST line (this file has no heading; the Ledger CLI line is currently first):

```markdown
- [Snapshot + open items](snapshot.md) — session START: `modkit snapshot diff` + `openitems list`; session END/installs: `snapshot take`; unexplained deltas = ASK THE USER, not bugs; Steam AutoUpdateBehavior must stay 1
```

- [ ] **Step 7: Commit**

```powershell
git -C C:\Modding\tools add modkit.json
git -C C:\Modding\tools commit -m @'
feat(snapshot): configure skyrim + cp77 snapshot watch lists

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

(If core gitignored `modkit.json` as machine config, `git add` will refuse — that is fine, skip the commit; the memory-dir files are outside the repo and are never committed.)

---

### Task 10: Acceptance — real take/diff + seed the real open items

This task touches real machine state (allowed: reads of game dirs, writes only under `C:\Modding\<game>-manual\`). Run the full suite first.

- [ ] **Step 1: Full test suite green**

Run: `py -3 -m pytest tests/test_modkit/ -v`
Expected: all tests pass (51 from this plan + the core suite), 0 failures.

- [ ] **Step 2: First real Skyrim snapshot**

Run: `py -3 C:\Modding\tools\modkit.py snapshot take --game skyrim`
Expected: `snapshot written: C:\Modding\skyrim-manual\snapshots\snapshot-<ts>.json`, exit 0 — or exit 2 with a WARNING line. A WARNING here is a REAL finding (e.g. AutoUpdateBehavior != 1): report it to the user verbatim, do not "fix" Steam settings yourself.

Then: `py -3 C:\Modding\tools\modkit.py snapshot diff --game skyrim`
Expected: `no drift - live state matches the snapshot.` and exit 0 (barring live warnings, which re-print with exit 2).

- [ ] **Step 3: First real CP77 snapshot**

Run: `py -3 C:\Modding\tools\modkit.py snapshot take --game cp77`
Then: `py -3 C:\Modding\tools\modkit.py snapshot diff --game cp77`
Expected: same shape as Step 2; the snapshot's `plugins/dlls/ini/enb` sections are `null` (thin preset).

- [ ] **Step 4: Seed the two real open items from the 2026-07-01 audit**

```powershell
py -3 C:\Modding\tools\modkit.py openitems add --game skyrim "iTexMipMapSkip=1 in Skyrim.ini [Display] - user decision pending: removing raises VRAM use (sse-audit-20260701 item 3)"
py -3 C:\Modding\tools\modkit.py openitems add --game skyrim "XPMSE clean-save disable - root-caused, PENDING user exec (sse-combat-fps-script-lag)"
py -3 C:\Modding\tools\modkit.py openitems list --game skyrim
```

Expected: list prints both items and `2 open, 0 completed - C:\Modding\skyrim-manual\open-items.md`.

- [ ] **Step 5: Commit any remaining tracked changes and verify clean tree**

```powershell
git -C C:\Modding\tools status
```

Expected: clean tree (snapshots/open-items live under `C:\Modding\<game>-manual\`, outside the repo). If anything tracked is dirty, commit it:

```powershell
git -C C:\Modding\tools add -A
git -C C:\Modding\tools commit -m @'
chore(snapshot): acceptance run artifacts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

## Self-Review (run after writing/executing, per writing-plans)

1. **Spec coverage:** take (plugins+hash+count, DLLs, INI keys, ENB flags, ledger count, AutoUpdateBehavior warning) = Tasks 2-4; diff grouped ADDED/REMOVED/CHANGED + ask-the-user closing = Task 5; openitems add/done/list with tolerant human-editable markdown = Tasks 7-8; memory pins with session-start/end convention = Task 9; CP77 thin coverage = config-driven section skipping (Task 3 test) + Task 9 config + Task 10 Step 3; every §9 evidence item maps per the header table.
2. **Placeholder scan:** no TBD/TODO/"handle edge cases"/"similar to Task N" anywhere; every code step shows complete code; every run step has an exact command and expected output.
3. **Type consistency:** the only core names used are `config.load()`, `config.game(cfg, name)`, `pluginstxt.read(preset)`, `ledger_bridge.run(args)` and preset attrs `PLUGINS_TXT`/`BACKUPS_DIR` (both in the contract attr list); internal names (`capture`, `take`, `diff_report`, `parse_open_items`, `render_open_items`, `_ctx`, `register`) are defined before first use and match across tasks.

## Execution Handoff

**Plan complete and saved to `C:\Modding\tools\docs\2026-07-11-snapshot-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session with `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**

(Precondition either way: modkit core plan `docs\2026-07-11-modkit-plan.md` Tasks 1-2 and 9 merged — this plan imports `modkit.config`, `modkit.pluginstxt`, and `modkit.ledger_bridge` at module load.)
