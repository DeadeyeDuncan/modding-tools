import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = Path(__file__).resolve().parent
for _p in (str(TOOLS_ROOT), str(TEST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forensics import _lib


def make_cfg(tmp):
    """Fixture config dict shaped like modkit.json's forensics section."""
    data_dir = Path(tmp) / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifests = Path(tmp) / "manifests"
    manifests.mkdir(exist_ok=True)
    plugins = Path(tmp) / "Plugins.txt"
    plugins.write_text("﻿*ModA.esp\nDisabled.esp\n# comment\n*ModB.esp\n", encoding="utf-8")
    return {
        "forensics": {
            "cacheDir": str(Path(tmp) / "cache"),
            "tools": {"bsarch": str(Path(tmp) / "BSArch64.exe"),
                      "texconv": str(Path(tmp) / "Texconv.exe")},
            "games": {"skyrim": {
                "dataDir": str(data_dir),
                "pluginsTxt": str(plugins),
                "manifestsDir": str(manifests),
                "ledgerEpoch": "2026-06-19",
                "implicitMasters": ["Skyrim.esm", "Update.esm"],
            }},
        }
    }


class TestConfig(unittest.TestCase):
    def test_load_config_explicit_path_plain_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "modkit.json"
            p.write_text('{"forensics": {"cacheDir": "x"}}', encoding="utf-8")
            cfg = _lib.load_config(str(p))
            self.assertEqual(cfg["forensics"]["cacheDir"], "x")

    def test_game_path_prefers_games_over_forensics_fallback(self):
        cfg = {"games": {"skyrim": {"dataDir": "PRIMARY"}},
               "forensics": {"games": {"skyrim": {"dataDir": "FALLBACK"}}}}
        self.assertEqual(_lib.game_path(cfg, "dataDir"), "PRIMARY")

    def test_game_path_falls_back_and_errors_clearly(self):
        cfg = {"forensics": {"games": {"skyrim": {"dataDir": "FALLBACK"}}}}
        self.assertEqual(_lib.game_path(cfg, "dataDir"), "FALLBACK")
        with self.assertRaises(SystemExit):
            _lib.game_path(cfg, "nosuchkey")

    def test_tool_path_checks_existence(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "BSArch64.exe"
            exe.write_bytes(b"MZ")
            cfg = {"forensics": {"tools": {"bsarch": str(exe)}}}
            self.assertEqual(_lib.tool_path(cfg, "bsarch"), str(exe))
            cfg2 = {"forensics": {"tools": {"bsarch": str(Path(tmp) / "gone.exe")}}}
            with self.assertRaises(SystemExit):
                _lib.tool_path(cfg2, "bsarch")


class TestPaths(unittest.TestCase):
    def test_norm_rel(self):
        self.assertEqual(_lib.norm_rel("Meshes/Foo\\Bar.NIF "), "meshes\\foo\\bar.nif")

    def test_strip_data_prefix(self):
        self.assertEqual(_lib.strip_data_prefix("Data\\textures\\a.dds"), "textures\\a.dds")
        self.assertEqual(_lib.strip_data_prefix("textures\\a.dds"), "textures\\a.dds")


class TestPluginsTxt(unittest.TestCase):
    def test_read_plugins_txt_bom_star_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            path = _lib.game_path(cfg, "pluginsTxt")
            entries = _lib.read_plugins_txt(path)
            self.assertEqual(entries, [("ModA.esp", True), ("Disabled.esp", False), ("ModB.esp", True)])

    def test_load_order_implicit_masters_first_enabled_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            order = _lib.load_order(cfg)
            self.assertEqual(order, ["Skyrim.esm", "Update.esm", "ModA.esp", "ModB.esp"])

    def test_load_order_dedupes_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            plugins = Path(_lib.game_path(cfg, "pluginsTxt"))
            plugins.write_text("*skyrim.esm\n*ModA.esp\n", encoding="utf-8")
            order = _lib.load_order(cfg)
            self.assertEqual(order, ["Skyrim.esm", "Update.esm", "ModA.esp"])


class TestManifests(unittest.TestCase):
    def test_manifest_baseline_comments_prefix_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / "manifests"
            (man / "sub").mkdir(parents=True)
            (man / "moda.txt").write_text(
                "﻿# install note comment\r\ntextures\\a\\one.dds\r\nData\\meshes\\b\\two.nif\r\n\r\n",
                encoding="utf-8")
            (man / "sub" / "modb.txt").write_text("Textures\\A\\THREE.dds\n", encoding="utf-8")
            base = _lib.manifest_baseline(str(man))
            self.assertEqual(base["textures\\a\\one.dds"], "moda.txt")
            self.assertEqual(base["meshes\\b\\two.nif"], "moda.txt")
            self.assertEqual(base["textures\\a\\three.dds"], "modb.txt")
            self.assertNotIn("# install note comment", base)


class TestMisc(unittest.TestCase):
    def test_atomic_write_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "out" / "x.json"
            _lib.atomic_write_json(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 1})

    def test_iter_files_filters_ext_and_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Meshes" / "Sub").mkdir(parents=True)
            (root / "Meshes" / "Sub" / "A.NIF").write_bytes(b"x")
            (root / "Meshes" / "skip.txt").write_bytes(b"x")
            got = list(_lib.iter_files(root, exts=(".nif",)))
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0][1], "meshes\\sub\\a.nif")

    def test_tes4_header_via_modkit_on_fixture(self):
        import fixtures
        with tempfile.TemporaryDirectory() as tmp:
            esp = Path(tmp) / "t.esp"
            esp.write_bytes(fixtures.build_esp(masters=["Skyrim.esm"], stats=[], esl=True))
            info = _lib.tes4_header(str(esp))
            self.assertEqual([m.lower() for m in info["masters"]], ["skyrim.esm"])
            self.assertTrue(info["esl"])


if __name__ == "__main__":
    unittest.main()
