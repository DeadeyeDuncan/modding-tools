import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ledger.main(["--ledger", str(self.ledger_path), *argv])
        return code, buf.getvalue()


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

    def test_masters_esl_requires_role_types(self):
        v = ledger.validate_data({"mods": [self.ok_entry(masters="not-a-list")]})
        self.assertTrue(any("masters" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(esl="yes")]})
        self.assertTrue(any("esl" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(requires=5)]})
        self.assertTrue(any("requires" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(role=5)]})
        self.assertTrue(any("role" in x for x in v))
        v = ledger.validate_data({"mods": [self.ok_entry(
            masters=["Skyrim.esm"], esl=True, requires=["SKSE"], role="body mod")]})
        self.assertEqual(v, [])


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

    def test_failed_replace_leaves_original_and_no_tmp_litter(self):
        self.write_ledger([self.entry()])
        data = ledger.load_ledger(self.ledger_path)
        before = self.ledger_path.read_bytes()
        from unittest import mock
        with mock.patch.object(ledger.os, "replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                ledger.save_ledger(self.ledger_path, data)
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("ledger.json.tmp-*")), [])
        baks = list((self.root / "backups").glob("ledger.json.bak-*"))
        self.assertTrue(len(baks) >= 1)


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

    def test_flag_after_subcommand_and_repeated_last_wins(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ledger.main(["list", "--ledger", str(self.ledger_path), "--count"])
        self.assertEqual(code, 0)
        self.assertIn("2 total", buf.getvalue())
        other = self.root / "other.json"
        other.write_bytes(json.dumps({"game": "x", "mods": []}).encode("utf-8"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ledger.main(["--ledger", str(other), "list",
                                "--ledger", str(self.ledger_path), "--count"])
        self.assertEqual(code, 0)
        self.assertIn("2 total", buf.getvalue())


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

    def test_note_empty_string_clears(self):
        code, _ = self.run_cli("update", "--name", "Mod A", "--note", "")
        self.assertEqual(code, 0)
        self.assertEqual(self.reload_a()["note"], "")

    def test_note_replace_then_append_combined(self):
        code, _ = self.run_cli("update", "--name", "Mod A",
                               "--note", "replaced", "--append-note", "checked")
        self.assertEqual(code, 0)
        note = self.reload_a()["note"]
        self.assertTrue(note.startswith("replaced\n["))
        self.assertIn("] checked", note)


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
        self.assertEqual(code, 1)
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

    def test_files_plus_manifest_co_presence_skipped(self):
        mods = [
            {"name": "Both List", "installed": "2026-06-20",
             "manifest": "manifests\\Hand-Named.txt", "files": ["meshes\\a.nif"]},
            {"name": "Both String", "installed": "2026-06-20",
             "manifest": "manifests\\Other.txt", "files": "Data\\SKSE\\Plugins\\thing.dll"},
            {"name": "Both Empty", "installed": "2026-06-20",
             "manifest": "manifests\\Third.txt", "files": []},
        ]
        self.write_ledger(mods)
        before = self.ledger_path.read_bytes()
        code, out = self.run_cli("migrate", "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(out.count("SKIP"), 3)
        for name in ("Both List", "Both String", "Both Empty"):
            self.assertIn(name, out)
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertFalse((self.manifests / "Both-List.txt").exists())

    def test_files_prose_string_without_manifest_flagged(self):
        self.write_ledger([{"name": "Prose Files", "installed": "2026-06-20",
                            "files": "Data\\SKSE\\Plugins\\thing.dll"}])
        code, out = self.run_cli("migrate")
        self.assertEqual(code, 1)
        self.assertIn("MANUAL Prose Files", out)
        self.assertIn("prose text", out)

    def test_empty_files_without_manifest_dropped_with_report(self):
        self.write_ledger([{"name": "Empty Files", "installed": "2026-06-20",
                            "files": [], "fileCount": 4754}])
        code, out = self.run_cli("migrate", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("empty 'files' dropped", out)
        mods = json.loads(self.ledger_path.read_bytes().decode("utf-8-sig"))["mods"]
        self.assertNotIn("files", mods[0])
        self.assertEqual(mods[0]["fileCount"], 4754)


if __name__ == "__main__":
    unittest.main()
