import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = Path(__file__).resolve().parent
for _p in (str(TOOLS_ROOT), str(TEST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures
from forensics import nif_texrefs


class TestExtract(unittest.TestCase):
    def test_extracts_normalizes_and_dedupes(self):
        data = fixtures.build_nif([
            "textures\\clutter\\pot01.dds",
            "TEXTURES\\Clutter\\POT01.DDS",              # dupe, different case
            "textures/cubemaps/ore_ebony_e.dds",          # forward slashes
        ])
        refs = nif_texrefs.extract_texrefs(data)
        self.assertEqual(refs, ["textures\\clutter\\pot01.dds",
                                "textures\\cubemaps\\ore_ebony_e.dds"])

    def test_ignores_non_dds_and_non_texture_strings(self):
        data = fixtures.build_nif([], extra=b"scripts\\foo.pex\x00textures\\bad.nif\x00")
        self.assertEqual(nif_texrefs.extract_texrefs(data), [])

    def test_finds_the_cm_bake_fingerprint_path(self):
        data = fixtures.build_nif(["textures\\cubemaps\\dynamic1pxcubemap_black.dds"])
        self.assertIn("textures\\cubemaps\\dynamic1pxcubemap_black.dds",
                      nif_texrefs.extract_texrefs(data))


class TestCheck(unittest.TestCase):
    def test_classifies_loose_bsa_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "Data"
            loose = data_dir / "textures" / "a" / "loose.dds"
            loose.parent.mkdir(parents=True)
            loose.write_bytes(b"DDS ")
            refs = ["textures\\a\\loose.dds", "textures\\a\\inbsa.dds",
                    "textures\\a\\gone.dds"]
            got = nif_texrefs.check_refs(refs, data_dir, {"textures\\a\\inbsa.dds"})
            self.assertEqual(got, {"textures\\a\\loose.dds": "LOOSE",
                                   "textures\\a\\inbsa.dds": "BSA",
                                   "textures\\a\\gone.dds": "MISSING"})


class TestCli(unittest.TestCase):
    def test_scan_dir_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            mesh_dir = Path(tmp) / "meshes"
            mesh_dir.mkdir()
            (mesh_dir / "one.nif").write_bytes(
                fixtures.build_nif(["textures\\x\\one.dds"]))
            (mesh_dir / "skip.txt").write_bytes(b"textures\\x\\no.dds")
            out_json = Path(tmp) / "out.json"
            rc = nif_texrefs.main([str(mesh_dir), "--json", str(out_json)])
            self.assertEqual(rc, 0)
            report = json.loads(out_json.read_text(encoding="utf-8"))
            (only,) = report["meshes"].values()
            self.assertEqual(only, ["textures\\x\\one.dds"])


if __name__ == "__main__":
    unittest.main()
