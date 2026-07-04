# Ledger CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-file Python CLI (`C:\Modding\tools\ledger.py`) that owns all reads/writes of the Skyrim and Cyberpunk 2077 mod-install ledgers: add/update/remove/get/list/validate/check/migrate, with atomic validated writes and backups.

**Architecture:** One stdlib-only Python file with three layers: IO (load/save with backup+atomic replace), data (validate/migrate/manifest helpers), CLI (argparse subcommands returning exit codes 0/1/2). Tests are stdlib `unittest` against synthetic ledgers in temp dirs.

**Tech Stack:** Python 3.13 via `py -3` (never the `python` Store alias), `unittest`, `argparse`, `json`, `pathlib`. No third-party deps. Git repo at `C:\Modding\tools`.

**Spec:** `C:\Modding\tools\docs\2026-07-04-ledger-cli-design.md` (approved 2026-07-04).

**Ground-truth notes for the implementer:**
- Real Skyrim ledger: `C:\Modding\skyrim-manual\ledger.json` — 234 entries, CRLF, UTF-8 no BOM, PowerShell-style 4-space indent with `":  "` separators (normalize on first write).
- Drift to migrate: `nexus`→`nexusId` (~40), `notes`→`note` (~6), `esp`/`esm`→`plugin` (~13), inline `files` arrays (~41). Entries #153–160 have **no `installed` date** (migrate reports them; acceptance backfills).
- Extra keys like `tool`, `mods`, `facegenSkipped`, `aka`, `author` are legitimate — preserve silently.
- Manifests convention: `manifests\` dir sibling of ledger.json; files are UTF-8 **with BOM**, CRLF, one Data-relative backslash path per line.
- CP77 ledger: `C:\Modding\cyberpunk-manual\ledger.json` — 11 entries, already canonical, no `plugin` field (no plugin system).

---

### Task 0: Repo + scaffold

**Files:**
- Create: `C:\Modding\tools\.gitignore`
- Create: `C:\Modding\tools\ledger.py` (skeleton)
- Create: `C:\Modding\tools\tests\test_ledger.py` (skeleton)

- [ ] **Step 1: Init repo and commit existing docs**

```powershell
git -C C:\Modding\tools init
```

Create `C:\Modding\tools\.gitignore`:

```
__pycache__/
*.pyc
```

```powershell
git -C C:\Modding\tools add .gitignore docs
git -C C:\Modding\tools commit -m "docs: ledger CLI design spec and plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write skeleton files**

`C:\Modding\tools\ledger.py`:

```python
#!/usr/bin/env python3
"""Ledger CLI - validated reads/writes for Claude-managed manual mod-install ledgers.

Games: Skyrim SE (C:\\Modding\\skyrim-manual\\ledger.json),
Cyberpunk 2077 (C:\\Modding\\cyberpunk-manual\\ledger.json).
Run via:  py -3 C:\\Modding\\tools\\ledger.py <command> --game skyrim|cp77
Spec: docs/2026-07-04-ledger-cli-design.md
"""
import argparse
import copy
import datetime
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path

GAMES = {
    "skyrim": Path(r"C:\Modding\skyrim-manual\ledger.json"),
    "cp77": Path(r"C:\Modding\cyberpunk-manual\ledger.json"),
}
BACKUP_KEEP = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VANILLA_PLUGINS = {"skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm"}


class LedgerError(Exception):
    """Raised for any condition that must abort without writing."""


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def main(argv=None):
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`C:\Modding\tools\tests\test_ledger.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ledger


class LedgerTestCase(unittest.TestCase):
    """Base: builds a synthetic game dir with ledger.json, manifests/, Data/, Plugins.txt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = self.root / "Data"
        self.data_dir.mkdir()
        self.manifests = self.root / "manifests"
        self.manifests.mkdir()
        self.plugins_txt = self.root / "Plugins.txt"
        self.ledger_path = self.root / "ledger.json"

    def write_ledger(self, mods, header=None):
        data = {
            "game": "Skyrim Special Edition",
            "dataDir": str(self.data_dir),
            "pluginsTxt": str(self.plugins_txt),
            "mods": mods,
        }
        if header:
            data.update(header)
        text = json.dumps(data, indent=4).replace("\n", "\r\n")
        self.ledger_path.write_bytes(text.encode("utf-8"))
        return data


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify the test scaffold runs**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: `Ran 0 tests` and imports succeed. On Python 3.12+ zero collected tests prints `NO TESTS RAN` with exit code 5 (older Pythons printed `OK`/exit 0) — this is expected and transient until Task 1 adds real tests.

- [ ] **Step 4: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: ledger CLI skeleton

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 1: `validate_data`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class ValidateTests(LedgerTestCase):
    def ok_entry(self, **over):
        e = {"name": "Mod A", "installed": "2026-07-01", "nexusId": 123,
             "plugin": "ModA.esp", "note": "fine"}
        e.update(over)
        return e

    def test_clean_ledger_passes(self):
        data = {"game": "x", "mods": [self.ok_entry()]}
        self.assertEqual(ledger.validate_data(data), [])

    def test_root_must_have_mods_list(self):
        self.assertTrue(ledger.validate_data({"game": "x"}))
        self.assertTrue(ledger.validate_data([]))

    def test_missing_name_and_installed(self):
        v = ledger.validate_data({"mods": [{"note": "no name"}]})
        self.assertTrue(any("name" in x for x in v))
        self.assertTrue(any("installed" in x for x in v))

    def test_duplicate_name_case_insensitive(self):
        v = ledger.validate_data({"mods": [self.ok_entry(), self.ok_entry(name="mod a")]})
        self.assertTrue(any("duplicate" in x for x in v))

    def test_removed_requires_reason(self):
        v = ledger.validate_data({"mods": [self.ok_entry(removed="2026-07-02")]})
        self.assertTrue(any("removedReason" in x for x in v))
        v2 = ledger.validate_data({"mods": [self.ok_entry(
            removed="2026-07-02", removedReason="broke saves")]})
        self.assertEqual(v2, [])

    def test_bad_date_format(self):
        v = ledger.validate_data({"mods": [self.ok_entry(installed="July 1")]})
        self.assertTrue(any("YYYY-MM-DD" in x for x in v))

    def test_known_field_types(self):
        v = ledger.validate_data({"mods": [self.ok_entry(fileCount="12")]})
        self.assertTrue(any("fileCount" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(fileCount=True)]})
        self.assertTrue(any("fileCount" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(plugin=["A.esp", "B.esl"])]})
        self.assertEqual(v, [])
        v = ledger.validate_data({"mods": [self.ok_entry(plugin=7)]})
        self.assertTrue(any("plugin" in x for x in v))

    def test_unknown_fields_ignored(self):
        v = ledger.validate_data({"mods": [self.ok_entry(
            facegenSkipped=True, tool=True, mods=["sub1"], aka="alias")]})
        self.assertEqual(v, [])
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: FAIL / ERROR — `ledger` has no attribute `validate_data`

- [ ] **Step 3: Implement `validate_data`**

Add to `ledger.py` (after `LedgerError`):

```python
_STR_FIELDS = ("version", "source", "role", "type", "note", "manifest",
               "removedTo", "removedReason")


def validate_data(data):
    """Return list of violation strings. Empty list = valid.

    Structure strict, vocabulary open: unknown extra keys are never flagged.
    """
    if not isinstance(data, dict) or not isinstance(data.get("mods"), list):
        return ["ledger root must be an object containing a 'mods' array"]
    v = []
    seen = {}
    for i, e in enumerate(data["mods"]):
        if not isinstance(e, dict):
            v.append(f"entry #{i}: not an object")
            continue
        name = e.get("name")
        label = name if isinstance(name, str) and name.strip() else f"entry #{i}"
        if not isinstance(name, str) or not name.strip():
            v.append(f"entry #{i}: missing or empty 'name'")
        else:
            key = name.strip().lower()
            if key in seen:
                v.append(f"{label}: duplicate name (also entry #{seen[key]})")
            else:
                seen[key] = i
        inst = e.get("installed")
        if not (isinstance(inst, str) and DATE_RE.match(inst)):
            v.append(f"{label}: 'installed' missing or not YYYY-MM-DD")
        if "removed" in e:
            if not (isinstance(e["removed"], str) and DATE_RE.match(e["removed"])):
                v.append(f"{label}: 'removed' not YYYY-MM-DD")
            reason = e.get("removedReason")
            if not (isinstance(reason, str) and reason.strip()):
                v.append(f"{label}: 'removed' requires non-empty 'removedReason'")
        for f in _STR_FIELDS:
            if f in e and e[f] is not None and not isinstance(e[f], str):
                v.append(f"{label}: '{f}' should be a string")
        for f in ("nexusId", "fileCount"):
            val = e.get(f)
            if f in e and val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                v.append(f"{label}: '{f}' should be an integer")
        if "esl" in e and not isinstance(e["esl"], bool):
            v.append(f"{label}: 'esl' should be a boolean")
        if "masters" in e and not isinstance(e["masters"], list):
            v.append(f"{label}: 'masters' should be a list")
        plugin = e.get("plugin")
        if "plugin" in e and plugin is not None and not isinstance(plugin, (str, list)):
            v.append(f"{label}: 'plugin' should be a string, list, or null")
        if "requires" in e and not isinstance(e["requires"], (list, str)):
            v.append(f"{label}: 'requires' should be a list or string")
    return v
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: validate_data schema checks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `load_ledger` / `save_ledger` (atomic, backup, prune)

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class IoTests(LedgerTestCase):
    def entry(self):
        return {"name": "Mod A", "installed": "2026-07-01"}

    def test_load_roundtrip_and_bom(self):
        self.write_ledger([self.entry()])
        # also tolerate a BOM on read
        self.ledger_path.write_bytes(b"\xef\xbb\xbf" + self.ledger_path.read_bytes())
        data = ledger.load_ledger(self.ledger_path)
        self.assertEqual(data["mods"][0]["name"], "Mod A")

    def test_save_writes_crlf_no_bom_indent4(self):
        self.write_ledger([self.entry()])
        data = ledger.load_ledger(self.ledger_path)
        ledger.save_ledger(self.ledger_path, data)
        raw = self.ledger_path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b'\r\n    "game"', raw)

    def test_save_creates_backup_and_prunes(self):
        self.write_ledger([self.entry()])
        data = ledger.load_ledger(self.ledger_path)
        for _ in range(25):
            ledger.save_ledger(self.ledger_path, data)
        baks = list((self.root / "backups").glob("ledger.json.bak-*"))
        self.assertTrue(0 < len(baks) <= ledger.BACKUP_KEEP)

    def test_save_rejects_invalid_and_leaves_original(self):
        self.write_ledger([self.entry()])
        before = self.ledger_path.read_bytes()
        bad = ledger.load_ledger(self.ledger_path)
        bad["mods"].append({"note": "nameless"})
        with self.assertRaises(ledger.LedgerError):
            ledger.save_ledger(self.ledger_path, bad)
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_load_missing_file_raises(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.load_ledger(self.root / "nope.json")
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — no attribute `load_ledger`

- [ ] **Step 3: Implement**

Add to `ledger.py`:

```python
def load_ledger(path):
    path = Path(path)
    if not path.is_file():
        raise LedgerError(f"ledger not found: {path}")
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise LedgerError(f"ledger unparseable: {path}: {ex}")


def save_ledger(path, data):
    """Validate -> backup -> write temp -> atomic replace. Never partial."""
    path = Path(path)
    violations = validate_data(data)
    if violations:
        raise LedgerError("refusing to write invalid ledger:\n  " + "\n  ".join(violations))
    backups = path.parent / "backups"
    backups.mkdir(exist_ok=True)
    if path.is_file():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, backups / f"{path.name}.bak-{stamp}")
        old = sorted(backups.glob(f"{path.name}.bak-*"))
        for stale in old[:-BACKUP_KEEP]:
            stale.unlink()
    text = json.dumps(data, indent=4, ensure_ascii=False).replace("\n", "\r\n") + "\r\n"
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}"
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: atomic validated ledger IO with backups

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: CLI skeleton + `get` / `list` / `validate`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class CliReadTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.write_ledger([
            {"name": "Mod A", "installed": "2026-06-20", "version": "1.0", "plugin": "A.esp"},
            {"name": "Mod B", "installed": "2026-07-01", "removed": "2026-07-02",
             "removedReason": "broke saves"},
        ])

    def test_get_prints_entry_json(self):
        code, out = self.run_cli("get", "--name", "mod a")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["name"], "Mod A")

    def test_get_unknown_exits_2(self):
        code, out = self.run_cli("get", "--name", "Nope")
        self.assertEqual(code, 2)

    def test_list_filters(self):
        code, out = self.run_cli("list", "--active")
        self.assertEqual(code, 0)
        self.assertIn("Mod A", out)
        self.assertNotIn("Mod B", out)
        code, out = self.run_cli("list", "--removed")
        self.assertIn("Mod B", out)
        code, out = self.run_cli("list", "--since", "2026-07-01")
        self.assertNotIn("Mod A", out)
        code, out = self.run_cli("list", "--count")
        self.assertIn("2 total", out)

    def test_validate_clean_and_dirty(self):
        code, _ = self.run_cli("validate")
        self.assertEqual(code, 0)
        raw = json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))
        raw["mods"].append({"name": "Mod A", "installed": "2026-07-03"})
        self.ledger_path.write_bytes(json.dumps(raw).encode("utf-8"))
        code, out = self.run_cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("duplicate", out)

    def test_game_preset_resolution(self):
        # --game must map to the baked-in path; unknown game exits 2
        code = ledger.main(["get", "--game", "nogame", "--name", "x"])
        self.assertEqual(code, 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: FAIL — `main` returns 0 and prints nothing

- [ ] **Step 3: Implement CLI**

Replace the `main` stub in `ledger.py`:

```python
def find_entry(data, name):
    key = name.strip().lower()
    for e in data["mods"]:
        if isinstance(e.get("name"), str) and e["name"].strip().lower() == key:
            return e
    return None


def today():
    return datetime.date.today().isoformat()


def _resolve_ledger(args):
    if getattr(args, "ledger", None):
        return Path(args.ledger)
    game = getattr(args, "game", None)
    if game in GAMES:
        return GAMES[game]
    raise LedgerError(f"unknown --game {game!r}; pass --game skyrim|cp77 or --ledger <path>")


def _entry_line(e):
    bits = [e.get("name", "?")]
    if e.get("version"):
        bits.append(f"v{e['version']}")
    bits.append(f"installed {e.get('installed', '?')}")
    plugin = e.get("plugin")
    if plugin:
        bits.append(", ".join(plugin) if isinstance(plugin, list) else plugin)
    if "removed" in e:
        bits.append(f"[REMOVED {e['removed']}]")
    return "  ".join(bits)


def cmd_get(args):
    data = load_ledger(_resolve_ledger(args))
    e = find_entry(data, args.name)
    if e is None:
        close = difflib.get_close_matches(
            args.name, [x.get("name", "") for x in data["mods"]], n=3)
        raise LedgerError(f"no entry named {args.name!r}" +
                          (f"; close: {', '.join(close)}" if close else ""))
    safe_print(json.dumps(e, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args):
    data = load_ledger(_resolve_ledger(args))
    mods = data["mods"]
    if args.active:
        mods = [e for e in mods if "removed" not in e]
    if args.removed:
        mods = [e for e in mods if "removed" in e]
    if args.since:
        mods = [e for e in mods if e.get("installed", "") >= args.since]
    if args.count:
        total = len(data["mods"])
        removed = sum(1 for e in data["mods"] if "removed" in e)
        safe_print(f"{total} total, {total - removed} active, {removed} removed"
                   f" ({len(mods)} matching filters)")
        return 0
    for e in mods:
        safe_print(_entry_line(e))
    return 0


def cmd_validate(args):
    data = load_ledger(_resolve_ledger(args))
    violations = validate_data(data)
    for x in violations:
        safe_print(f"VIOLATION: {x}")
    safe_print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


def build_parser():
    p = argparse.ArgumentParser(prog="ledger.py", description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--game", choices=None, help="skyrim | cp77")
    common.add_argument("--ledger", help="explicit ledger.json path (overrides --game)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("get", parents=[common])
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("list", parents=[common])
    sp.add_argument("--active", action="store_true")
    sp.add_argument("--removed", action="store_true")
    sp.add_argument("--since")
    sp.add_argument("--count", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("validate", parents=[common])
    sp.set_defaults(func=cmd_validate)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # global flags may appear before the subcommand; hoist them behind it
    lead, rest = [], list(argv)
    while rest and (rest[0] in ("--game", "--ledger")
                    or rest[0].startswith(("--game=", "--ledger="))):
        if "=" in rest[0] or len(rest) < 2:
            lead.append(rest.pop(0))
        else:
            lead += rest[:2]
            rest = rest[2:]
    parser = build_parser()
    args = parser.parse_args(rest + lead)
    try:
        return args.func(args)
    except LedgerError as ex:
        safe_print(f"ERROR: {ex}")
        return 2
```

(`--game` uses free text + `_resolve_ledger` raising `LedgerError`, so unknown games exit 2 instead of argparse's own error path — matches the test. main() hoists leading --game/--ledger flags behind the subcommand so both `ledger.py --ledger X get` and `ledger.py get --ledger X` parse; flags are registered on subparsers only.)

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: CLI with get/list/validate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `add` (+ manifest writer)

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class AddTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20"}])

    def reload(self):
        return json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))

    def test_add_basic_auto_date(self):
        code, _ = self.run_cli("add", "--name", "Mod B", "--nexus-id", "42",
                               "--version", "2.1", "--plugin", "B.esp",
                               "--note", "combat overhaul")
        self.assertEqual(code, 0)
        e = [x for x in self.reload()["mods"] if x["name"] == "Mod B"][0]
        self.assertEqual(e["nexusId"], 42)
        self.assertEqual(e["plugin"], "B.esp")
        self.assertRegex(e["installed"], r"^\d{4}-\d{2}-\d{2}$")

    def test_add_multi_plugin_becomes_list(self):
        self.run_cli("add", "--name", "Mod C", "--plugin", "C1.esp", "--plugin", "C2.esl")
        e = [x for x in self.reload()["mods"] if x["name"] == "Mod C"][0]
        self.assertEqual(e["plugin"], ["C1.esp", "C2.esl"])

    def test_add_duplicate_refused(self):
        code, out = self.run_cli("add", "--name", "mod a")
        self.assertEqual(code, 2)
        self.assertIn("update", out)

    def test_add_files_from_writes_manifest_bom_crlf(self):
        staged = self.root / "staged.txt"
        staged.write_text("meshes\\a.nif\ntextures\\b.dds\n", encoding="utf-8")
        code, _ = self.run_cli("add", "--name", "Mod D", "--files-from", str(staged))
        self.assertEqual(code, 0)
        e = [x for x in self.reload()["mods"] if x["name"] == "Mod D"][0]
        self.assertEqual(e["fileCount"], 2)
        self.assertEqual(e["manifest"], "manifests\\Mod-D.txt")
        raw = (self.manifests / "Mod-D.txt").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"meshes\\a.nif\r\n", raw)

    def test_add_manifest_collision_refused(self):
        (self.manifests / "Mod-E.txt").write_bytes(b"\xef\xbb\xbfother\r\n")
        staged = self.root / "staged.txt"
        staged.write_text("meshes\\e.nif\n", encoding="utf-8")
        code, out = self.run_cli("add", "--name", "Mod E", "--files-from", str(staged))
        self.assertEqual(code, 2)
        self.assertIn("exists", out)
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — argparse: invalid choice 'add'

- [ ] **Step 3: Implement**

Add to `ledger.py`:

```python
def sanitize_name(name):
    out = re.sub(r"[^A-Za-z0-9.+-]+", "-", name.strip()).strip("-")
    return out or "unnamed"


def write_manifest(ledger_path, name, paths, expect_absent=True):
    """Write manifests\\<sanitized>.txt (UTF-8 BOM, CRLF). Returns (pointer, count)."""
    mdir = Path(ledger_path).parent / "manifests"
    mdir.mkdir(exist_ok=True)
    fname = sanitize_name(name) + ".txt"
    target = mdir / fname
    body = "\r\n".join(paths) + "\r\n"
    if target.exists():
        existing = target.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").strip()
        if existing != "\n".join(paths).strip():
            if expect_absent:
                raise LedgerError(f"manifest already exists with different content: {target}")
    target.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    return f"manifests\\{fname}", len(paths)


def read_staged_list(path):
    p = Path(path)
    if not p.is_file():
        raise LedgerError(f"staged file list not found: {p}")
    lines = p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    return [x.strip() for x in lines if x.strip()]


def _plugin_value(plugins):
    if not plugins:
        return None
    return plugins[0] if len(plugins) == 1 else plugins


def cmd_add(args):
    path = _resolve_ledger(args)
    data = load_ledger(path)
    if find_entry(data, args.name):
        raise LedgerError(f"entry {args.name!r} already exists - use `update`")
    e = {"name": args.name}
    if args.nexus_id is not None:
        e["nexusId"] = args.nexus_id
    for field, val in (("version", args.version), ("source", args.source),
                       ("role", args.role), ("note", args.note)):
        if val:
            e[field] = val
    plugin = _plugin_value(args.plugin)
    if plugin is not None:
        e["plugin"] = plugin
    if args.esl:
        e["esl"] = True
    if args.files_from:
        paths = read_staged_list(args.files_from)
        e["manifest"], e["fileCount"] = write_manifest(path, args.name, paths)
    e["installed"] = args.installed or today()
    data["mods"].append(e)
    save_ledger(path, data)
    safe_print(f"added: {_entry_line(e)}")
    return 0
```

In `build_parser()` add before `return p`:

```python
    sp = sub.add_parser("add", parents=[common])
    sp.add_argument("--name", required=True)
    sp.add_argument("--nexus-id", type=int, dest="nexus_id")
    sp.add_argument("--version")
    sp.add_argument("--source")
    sp.add_argument("--plugin", action="append", default=[])
    sp.add_argument("--esl", action="store_true")
    sp.add_argument("--role")
    sp.add_argument("--note")
    sp.add_argument("--installed", help="override auto date (YYYY-MM-DD)")
    sp.add_argument("--files-from", help="staged file list -> writes manifests\\<name>.txt")
    sp.set_defaults(func=cmd_add)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: add command with manifest writer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `update`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class UpdateTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20",
                            "version": "1.0", "note": "first"}])

    def reload_a(self):
        data = json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))
        return data["mods"][0]

    def test_update_fields(self):
        code, _ = self.run_cli("update", "--name", "Mod A", "--version", "1.1",
                               "--plugin", "A.esp", "--installed", "2026-06-21")
        self.assertEqual(code, 0)
        e = self.reload_a()
        self.assertEqual((e["version"], e["plugin"], e["installed"]),
                         ("1.1", "A.esp", "2026-06-21"))

    def test_append_note_dated(self):
        self.run_cli("update", "--name", "Mod A", "--append-note", "re-tested fine")
        note = self.reload_a()["note"]
        self.assertTrue(note.startswith("first\n["))
        self.assertIn("] re-tested fine", note)

    def test_unknown_name_suggests_close(self):
        code, out = self.run_cli("update", "--name", "Mod Aa", "--version", "2")
        self.assertEqual(code, 2)
        self.assertIn("Mod A", out)
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — invalid choice 'update'

- [ ] **Step 3: Implement**

Add to `ledger.py`:

```python
def cmd_update(args):
    path = _resolve_ledger(args)
    data = load_ledger(path)
    e = find_entry(data, args.name)
    if e is None:
        close = difflib.get_close_matches(
            args.name, [x.get("name", "") for x in data["mods"]], n=3)
        raise LedgerError(f"no entry named {args.name!r}" +
                          (f"; close: {', '.join(close)}" if close else ""))
    for field, val in (("version", args.version), ("source", args.source),
                       ("role", args.role), ("note", args.note),
                       ("installed", args.installed)):
        if val is not None:
            e[field] = val
    if args.nexus_id is not None:
        e["nexusId"] = args.nexus_id
    plugin = _plugin_value(args.plugin)
    if plugin is not None:
        e["plugin"] = plugin
    if args.append_note:
        stamp = f"[{today()}] {args.append_note}"
        e["note"] = (e["note"] + "\n" + stamp) if e.get("note") else stamp
    save_ledger(path, data)
    safe_print(f"updated: {_entry_line(e)}")
    return 0
```

In `build_parser()` add:

```python
    sp = sub.add_parser("update", parents=[common])
    sp.add_argument("--name", required=True)
    sp.add_argument("--nexus-id", type=int, dest="nexus_id")
    sp.add_argument("--version")
    sp.add_argument("--source")
    sp.add_argument("--plugin", action="append", default=[])
    sp.add_argument("--role")
    sp.add_argument("--note", help="replace note")
    sp.add_argument("--append-note", dest="append_note", help="append dated line to note")
    sp.add_argument("--installed", help="set/backfill install date (YYYY-MM-DD)")
    sp.set_defaults(func=cmd_update)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: update command with dated note append

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `remove`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class RemoveTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20"}])

    def test_remove_sets_fields_keeps_entry(self):
        code, _ = self.run_cli("remove", "--name", "Mod A",
                               "--reason", "caused CTD",
                               "--to", "backups\\moda-20260704")
        self.assertEqual(code, 0)
        data = json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))
        e = data["mods"][0]
        self.assertEqual(len(data["mods"]), 1)
        self.assertRegex(e["removed"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(e["removedReason"], "caused CTD")
        self.assertEqual(e["removedTo"], "backups\\moda-20260704")

    def test_remove_requires_reason(self):
        code, _ = self.run_cli("remove", "--name", "Mod A", "--reason", "  ")
        self.assertEqual(code, 2)

    def test_remove_twice_errors(self):
        self.run_cli("remove", "--name", "Mod A", "--reason", "x")
        code, out = self.run_cli("remove", "--name", "Mod A", "--reason", "y")
        self.assertEqual(code, 2)
        self.assertIn("already removed", out)
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — invalid choice 'remove'

- [ ] **Step 3: Implement**

Add to `ledger.py`:

```python
def cmd_remove(args):
    path = _resolve_ledger(args)
    data = load_ledger(path)
    e = find_entry(data, args.name)
    if e is None:
        raise LedgerError(f"no entry named {args.name!r}")
    if "removed" in e:
        raise LedgerError(f"{e['name']!r} already removed on {e['removed']}")
    if not args.reason.strip():
        raise LedgerError("--reason must be non-empty")
    e["removed"] = today()
    e["removedReason"] = args.reason
    if args.to:
        e["removedTo"] = args.to
    save_ledger(path, data)
    safe_print(f"removed: {_entry_line(e)}")
    return 0
```

In `build_parser()` add:

```python
    sp = sub.add_parser("remove", parents=[common])
    sp.add_argument("--name", required=True)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--to", help="backup path the files were moved to")
    sp.set_defaults(func=cmd_remove)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: remove command (history-preserving)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `migrate`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class MigrateTests(LedgerTestCase):
    def drift_mods(self):
        return [
            {"name": "Old Nexus", "installed": "2026-06-20", "nexus": 111},
            {"name": "Old Notes", "installed": "2026-06-20", "notes": "legacy text"},
            {"name": "Old Esp", "installed": "2026-06-20", "esp": "old.esp"},
            {"name": "Inline Files", "installed": "2026-06-20",
             "files": ["meshes\\x.nif", "textures\\y.dds"], "fileCount": 2},
            {"name": "No Date", "nexus": 222, "note": "missing installed"},
            {"name": "Clean", "installed": "2026-06-21", "nexusId": 333},
        ]

    def reload(self):
        return json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))

    def test_dry_run_reports_but_does_not_write(self):
        self.write_ledger(self.drift_mods())
        before = self.ledger_path.read_bytes()
        code, out = self.run_cli("migrate")
        self.assertEqual(code, 0)
        self.assertIn("nexus -> nexusId", out)
        self.assertIn("MANUAL", out)  # the No Date entry
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertFalse((self.manifests / "Inline-Files.txt").exists())

    def test_apply_normalizes(self):
        self.write_ledger(self.drift_mods())
        code, out = self.run_cli("migrate", "--apply")
        # exit 1: the No Date entry still needs manual backfill
        self.assertEqual(code, 1)
        mods = {e["name"]: e for e in self.reload()["mods"]}
        self.assertEqual(mods["Old Nexus"]["nexusId"], 111)
        self.assertNotIn("nexus", mods["Old Nexus"])
        self.assertEqual(mods["Old Notes"]["note"], "legacy text")
        self.assertNotIn("notes", mods["Old Notes"])
        self.assertEqual(mods["Old Esp"]["plugin"], "old.esp")
        self.assertNotIn("esp", mods["Old Esp"])
        self.assertEqual(mods["Inline Files"]["manifest"], "manifests\\Inline-Files.txt")
        self.assertNotIn("files", mods["Inline Files"])
        raw = (self.manifests / "Inline-Files.txt").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"meshes\\x.nif\r\n", raw)
        # No Date: aliases normalized but installed still absent
        self.assertEqual(mods["No Date"]["nexusId"], 222)
        self.assertNotIn("installed", mods["No Date"])

    def test_apply_idempotent(self):
        self.write_ledger(self.drift_mods())
        self.run_cli("migrate", "--apply")
        code, out = self.run_cli("migrate")
        self.assertNotIn("->", out)

    def test_manifest_collision_skips_entry(self):
        (self.manifests / "Inline-Files.txt").write_bytes(b"\xef\xbb\xbfdifferent\r\n")
        self.write_ledger(self.drift_mods())
        code, out = self.run_cli("migrate", "--apply")
        self.assertIn("SKIP", out)
        mods = {e["name"]: e for e in self.reload()["mods"]}
        self.assertIn("files", mods["Inline Files"])  # untouched
```

Note: `test_apply_*` write through `save_ledger`, which requires a valid result — but the "No Date" entry stays invalid (`installed` missing). Migration must therefore write via a **relaxed save** that tolerates exactly the violations it reported as MANUAL. Implementation handles this by snapshotting the ledger's pre-existing violations before migration and passing them as `allow_violations` — migration may not introduce NEW violations, but violations that predate it pass through.

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — invalid choice 'migrate'

- [ ] **Step 3: Implement**

Modify `save_ledger` signature (Task 2 code) to:

```python
def save_ledger(path, data, allow_violations=()):
    """Validate -> backup -> write temp -> atomic replace. Never partial.

    allow_violations: exact violation strings tolerated (used by migrate for
    pre-existing MANUAL items it just reported).
    """
    path = Path(path)
    violations = [v for v in validate_data(data) if v not in set(allow_violations)]
    if violations:
        raise LedgerError("refusing to write invalid ledger:\n  " + "\n  ".join(violations))
    ...  # rest unchanged
```

Add to `ledger.py`:

```python
def migrate_data(data, ledger_path, apply):
    """Normalize drift-era fields. Returns (report_lines, manual_lines).

    report_lines: changes made (or would be made); manual_lines: things a human
    must fix (e.g. missing installed dates).
    """
    report, manual = [], []
    for e in data["mods"]:
        if not isinstance(e, dict):
            continue
        label = e.get("name", "?")
        if "nexus" in e:
            if "nexusId" in e and e["nexusId"] != e["nexus"]:
                manual.append(f"SKIP {label}: nexus={e['nexus']} conflicts nexusId={e['nexusId']}")
            else:
                e.setdefault("nexusId", e["nexus"])
                del e["nexus"]
                report.append(f"{label}: nexus -> nexusId")
        if "notes" in e:
            if e.get("note"):
                e["note"] = e["note"] + "\n" + str(e["notes"])
            else:
                e["note"] = str(e["notes"])
            del e["notes"]
            report.append(f"{label}: notes -> note")
        for alias in ("esp", "esm"):
            if alias in e:
                if e.get("plugin") and e["plugin"] != e[alias]:
                    manual.append(f"SKIP {label}: {alias}={e[alias]!r} conflicts plugin={e['plugin']!r}")
                else:
                    e["plugin"] = e[alias]
                    del e[alias]
                    report.append(f"{label}: {alias} -> plugin")
        if isinstance(e.get("files"), list) and e["files"]:
            try:
                if apply:
                    pointer, count = write_manifest(ledger_path, label, e["files"])
                else:
                    pointer, count = f"manifests\\{sanitize_name(label)}.txt", len(e["files"])
                    mdir = Path(ledger_path).parent / "manifests"
                    target = mdir / (sanitize_name(label) + ".txt")
                    if target.exists():
                        existing = target.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").strip()
                        if existing != "\n".join(e["files"]).strip():
                            raise LedgerError(f"manifest already exists with different content: {target}")
                e["manifest"] = pointer
                e["fileCount"] = count
                del e["files"]
                report.append(f"{label}: {count} inline files -> {pointer}")
            except LedgerError as ex:
                manual.append(f"SKIP {label}: {ex}")
        if "installed" not in e:
            manual.append(f"MANUAL {label}: no 'installed' date - backfill with "
                          f"`update --name \"{label}\" --installed YYYY-MM-DD`")
    return report, manual


def cmd_migrate(args):
    path = _resolve_ledger(args)
    data = load_ledger(path)
    pre_existing = validate_data(data)  # violations that predate migration (e.g. missing installed dates)
    work = data if args.apply else copy.deepcopy(data)
    report, manual = migrate_data(work, path, apply=args.apply)
    for line in report:
        safe_print(("" if args.apply else "would: ") + line)
    for line in manual:
        safe_print(line)
    safe_print(f"{len(report)} change(s), {len(manual)} manual item(s)"
               + ("" if args.apply else " [dry-run - use --apply]"))
    if args.apply and report:
        save_ledger(path, work, allow_violations=pre_existing)
    return 1 if manual else 0
```

In `build_parser()` add:

```python
    sp = sub.add_parser("migrate", parents=[common])
    sp.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    sp.set_defaults(func=cmd_migrate)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS (including earlier suites — `save_ledger` default behavior unchanged)

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: migrate command normalizing drift-era fields

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `check`

**Files:**
- Modify: `C:\Modding\tools\ledger.py`
- Test: `C:\Modding\tools\tests\test_ledger.py`

- [ ] **Step 1: Write failing tests**

Append to `test_ledger.py`:

```python
class CheckTests(LedgerTestCase):
    def make_manifest(self, name, paths, create_files=True):
        body = "\r\n".join(paths) + "\r\n"
        (self.manifests / name).write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        if create_files:
            for p in paths:
                f = self.data_dir / p.replace("\\", "/")
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x")

    def test_clean_setup_passes(self):
        self.make_manifest("Mod-A.txt", ["meshes\\a.nif"])
        self.plugins_txt.write_text("*A.esp\n", encoding="utf-8")
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20",
                            "plugin": "A.esp", "manifest": "manifests\\Mod-A.txt"}])
        code, out = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("0 error(s)", out)

    def test_plugin_missing_from_plugins_txt_is_error(self):
        self.plugins_txt.write_text("", encoding="utf-8")
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20", "plugin": "A.esp"}])
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("A.esp", out)

    def test_unowned_plugin_is_warn_vanilla_ignored(self):
        self.plugins_txt.write_text("*Skyrim.esm\n*Mystery.esp\n*ccBGSSSE001-Fish.esm\n",
                                    encoding="utf-8")
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20"}])
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("WARN", out)
        self.assertIn("Mystery.esp", out)
        self.assertNotIn("Skyrim.esm", out)
        self.assertNotIn("ccBGSSSE001", out)

    def test_removed_plugin_not_required(self):
        self.plugins_txt.write_text("", encoding="utf-8")
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20", "plugin": "A.esp",
                            "removed": "2026-07-01", "removedReason": "gone"}])
        code, out = self.run_cli("check")
        self.assertEqual(code, 0)

    def test_missing_manifest_pointer_is_error(self):
        self.plugins_txt.write_text("", encoding="utf-8")
        self.write_ledger([{"name": "Mod A", "installed": "2026-06-20",
                            "manifest": "manifests\\Nope.txt"}])
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("Nope.txt", out)

    def test_active_missing_files_warn_removed_present_info(self):
        self.make_manifest("Mod-A.txt", ["meshes\\gone.nif"], create_files=False)
        self.make_manifest("Mod-B.txt", ["meshes\\still.nif"], create_files=True)
        self.plugins_txt.write_text("", encoding="utf-8")
        self.write_ledger([
            {"name": "Mod A", "installed": "2026-06-20", "manifest": "manifests\\Mod-A.txt"},
            {"name": "Mod B", "installed": "2026-06-20", "manifest": "manifests\\Mod-B.txt",
             "removed": "2026-07-01", "removedReason": "swapped out"},
        ])
        code, out = self.run_cli("check")
        self.assertIn("WARN", out)
        self.assertIn("gone.nif", out)
        self.assertIn("INFO", out)
        self.assertIn("Mod B", out)
        self.assertEqual(code, 1)  # WARN fails; INFO alone would not

    def test_duplicate_plugin_claim_is_error(self):
        self.plugins_txt.write_text("*A.esp\n", encoding="utf-8")
        self.write_ledger([
            {"name": "Mod A", "installed": "2026-06-20", "plugin": "A.esp"},
            {"name": "Mod B", "installed": "2026-06-21", "plugin": ["A.esp", "B.esp"]},
        ])
        code, out = self.run_cli("check")
        self.assertIn("ERROR", out)
        self.assertIn("claimed by", out)

    def test_cp77_style_no_plugins_txt(self):
        # header without pluginsTxt: plugin checks skipped, manifest checks run
        self.make_manifest("Mod-A.txt", ["archive\\pc\\mod\\a.archive"])
        data = {"game": "Cyberpunk 2077", "installDir": str(self.data_dir),
                "mods": [{"name": "Mod A", "installed": "2026-07-02",
                          "manifest": "manifests\\Mod-A.txt"}]}
        text = json.dumps(data, indent=4).replace("\n", "\r\n")
        self.ledger_path.write_bytes(text.encode("utf-8"))
        code, out = self.run_cli("check")
        self.assertEqual(code, 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: ERROR — invalid choice 'check'

- [ ] **Step 3: Implement**

Add to `ledger.py`:

```python
def parse_plugins_txt(path):
    """Return set of enabled plugin filenames (lowercase). '*' prefix = enabled."""
    p = Path(path)
    if not p.is_file():
        raise LedgerError(f"Plugins.txt not found: {p}")
    out = set()
    for line in p.read_bytes().decode("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            out.add(line[1:].strip().lower())
    return out


def _entry_plugins(e):
    plugin = e.get("plugin")
    if isinstance(plugin, str):
        return [plugin]
    if isinstance(plugin, list):
        return [x for x in plugin if isinstance(x, str)]
    return []


def cmd_check(args):
    path = _resolve_ledger(args)
    data = load_ledger(path)
    findings = []  # (severity, message)
    for v in validate_data(data):
        findings.append(("ERROR", v))
    active = [e for e in data["mods"] if isinstance(e, dict) and "removed" not in e]
    removed = [e for e in data["mods"] if isinstance(e, dict) and "removed" in e]

    plugins_txt = data.get("pluginsTxt")
    if plugins_txt:
        enabled = parse_plugins_txt(plugins_txt)
        claims = {}
        for e in active:
            for pl in _entry_plugins(e):
                key = pl.lower()
                if key in claims:
                    findings.append(("ERROR", f"{pl} claimed by both "
                                     f"{claims[key]!r} and {e.get('name')!r}"))
                else:
                    claims[key] = e.get("name")
                if key not in enabled:
                    findings.append(("ERROR", f"{e.get('name')}: plugin {pl} "
                                     f"not enabled in Plugins.txt"))
        for pl in sorted(enabled):
            if pl in VANILLA_PLUGINS or pl.startswith("cc"):
                continue
            if pl not in claims:
                findings.append(("WARN", f"Plugins.txt: {pl} not owned by any "
                                 f"active ledger entry"))

    root = data.get("dataDir") or data.get("installDir")
    ledger_dir = Path(path).parent
    for e in active + removed:
        pointer = e.get("manifest")
        if not pointer:
            continue
        mpath = ledger_dir / pointer
        if not mpath.is_file():
            findings.append(("ERROR", f"{e.get('name')}: manifest missing: {pointer}"))
            continue
        if not root:
            continue
        paths = [x for x in mpath.read_bytes().decode("utf-8-sig").splitlines() if x.strip()]
        hits = [p for p in paths if (Path(root) / p.replace("\\", "/")).exists()]
        if "removed" not in e:
            missing = [p for p in paths if p not in set(hits)]
            if missing:
                shown = "; ".join(missing[:5])
                findings.append(("WARN", f"{e.get('name')}: {len(missing)}/{len(paths)} "
                                 f"manifest file(s) missing on disk: {shown}"))
        elif hits:
            findings.append(("INFO", f"{e.get('name')} (removed): {len(hits)}/{len(paths)} "
                             f"file(s) still on disk (later mod may own them)"))

    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for sev, msg in findings:
        counts[sev] += 1
        safe_print(f"{sev}: {msg}")
    safe_print(f"{counts['ERROR']} error(s), {counts['WARN']} warning(s), "
               f"{counts['INFO']} info")
    return 1 if counts["ERROR"] or counts["WARN"] else 0
```

In `build_parser()` add:

```python
    sp = sub.add_parser("check", parents=[common])
    sp.set_defaults(func=cmd_check)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git -C C:\Modding\tools add ledger.py tests
git -C C:\Modding\tools commit -m "feat: check command - ledger/Plugins.txt/manifest/disk consistency

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Acceptance against real data (user-gated)

**Files:** none created — live runs.

- [ ] **Step 1: Full suite green**

Run: `py -3 -m unittest discover -s C:\Modding\tools\tests -v`
Expected: all PASS

- [ ] **Step 2: Validate both live ledgers (read-only)**

```powershell
py -3 C:\Modding\tools\ledger.py validate --game skyrim
py -3 C:\Modding\tools\ledger.py validate --game cp77
```

Expected: Skyrim reports violations on drift-era entries (8 missing `installed`, alias fields are NOT violations — aliases are unknown keys until migrated); CP77 clean (exit 0).

- [ ] **Step 3: Migrate dry-run on the real Skyrim ledger (read-only)**

```powershell
py -3 C:\Modding\tools\ledger.py migrate --game skyrim
```

Expected: ~40 `nexus -> nexusId`, ~6 `notes -> note`, ~13 `esp/esm -> plugin`, ~41 inline-files extractions, 8 MANUAL missing-date lines (entries #153–160: CBPC, HIMBO, TNG, TNG TRX, Floppy Schlongs, SkySight, Lucid, TNG Racial Variances). **Present the full report to the user. STOP for approval before Step 4.**

- [ ] **Step 4: Apply (after user approval)**

```powershell
py -3 C:\Modding\tools\ledger.py migrate --game skyrim --apply
py -3 C:\Modding\tools\ledger.py validate --game skyrim
```

Expected: apply exits 1 (8 manual items outstanding); backup exists in `C:\Modding\skyrim-manual\backups\`.

- [ ] **Step 5: Backfill the 8 missing dates from wiki evidence**

Wiki-attested install dates ([[concepts/skyrim-cbpc-body-physics]] 06-21, [[concepts/skyrim-male-body-himbo-tng]]: HIMBO 06-21 → TNG swap 06-24, [[concepts/skyrim-body-skins-skysight-lucid]] 06-21):

```powershell
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "CBPC - Physics with Collisions" --installed 2026-06-21
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "HIMBO (male body) + refits" --installed 2026-06-21
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "The New Gentleman (TNG)" --installed 2026-06-24
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "TNG Male Penis Addon (TRX)" --installed 2026-06-24
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "Floppy Schlongs SE (CBPC/SMP)" --installed 2026-06-24
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "SkySight Skins (male)" --installed 2026-06-21
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "Lucid Skin (female)" --installed 2026-06-21
py -3 C:\Modding\tools\ledger.py update --game skyrim --name "TNG Racial Penis Variances (LDD BnP/TRX)" --installed 2026-06-24
```

(Confirm each date against the wiki articles before running; adjust if an article says otherwise. These entries pre-date manifests — several were removed/swapped later per wiki; their alias-era `esp` fields become `plugin` in migration.)

Then: `py -3 C:\Modding\tools\ledger.py validate --game skyrim` → Expected: exit 0, `0 violation(s)`.

- [ ] **Step 6: Live consistency check**

```powershell
py -3 C:\Modding\tools\ledger.py check --game skyrim
py -3 C:\Modding\tools\ledger.py check --game cp77
```

Expected: findings ARE likely (that's the tool's job — e.g. unowned generated plugins like Bashed Patch/DynDOLOD trio, swap-pattern INFO lines). Review with the user; real drift becomes follow-up work, not a blocker for this build. Note: known-generated plugins that keep WARNing may justify a header `generatedPlugins` allowlist — record as future work if it fires.

- [ ] **Step 7: Final commit + record the tool**

```powershell
git -C C:\Modding\tools add -A
git -C C:\Modding\tools commit -m "chore: acceptance run artifacts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Add a pointer in the Skyrim game project memory (`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\`) so sessions use `py -3 C:\Modding\tools\ledger.py ...` instead of hand-editing ledger.json. Same for the CP77 project memory.

---

## Self-review notes

- Spec coverage: layout/invocation (T0, T3), schema (T1), migration (T7 + T9), commands (T3–T8), check severities incl. swap-pattern INFO (T8), safety/atomicity/backups/prune (T2), encoding/CRLF/indent-4 normalize (T2), ASCII-safe output (T0 `safe_print`), exit codes (T3 `main`), acceptance incl. dry-run gate (T9). Non-goals respected (no file installs).
- Type consistency: `find_entry`, `_resolve_ledger`, `_entry_line`, `_plugin_value`, `write_manifest(ledger_path, name, paths)`, `save_ledger(path, data, allow_violations=())` used consistently across tasks.
- Known deliberate deviation: `save_ledger` gains `allow_violations` (not in spec) so migrate can persist normalization while the 8 undated entries await manual backfill — without it, migrate could not write at all. Scoped to the exact violation strings that pre-existed migration.
