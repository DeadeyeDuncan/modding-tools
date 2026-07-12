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

    def test_raw_confirm_backstop_flips_would_be_missing_to_bsa_raw(self):
        """The false-triage scenario: a ref that's neither loose nor in the
        (stubbed) bsa_index all_paths() set — but the BSArch -list output is
        documented to genuinely omit some real entries (sack01.nif quirk,
        bsa_index.py). raw_confirm() is the backstop for exactly that gap;
        when it reports a hit, check_refs must NOT classify the ref MISSING."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "Data"
            data_dir.mkdir()
            refs = ["textures\\a\\index_missed_me.dds"]
            calls = []

            def fake_raw_confirm(bsa_path, name):
                calls.append((bsa_path, name))
                return True  # simulates the byte-scan finding it in the BSA

            got = nif_texrefs.check_refs(
                refs, data_dir, set(),  # empty bsa_paths_set: not in the index
                bsa_files=["fake.bsa"], raw_confirm=fake_raw_confirm)
            self.assertEqual(got, {"textures\\a\\index_missed_me.dds": "BSA-RAW"})
            self.assertEqual(calls, [("fake.bsa", "textures\\a\\index_missed_me.dds")])

    def test_genuine_missing_survives_raw_confirm_backstop(self):
        """Loose empty + index empty + raw_confirm empty (all three back-
        stops exhausted) -> still MISSING. Proves the backstop only clears
        refs raw_confirm actually finds, not everything."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "Data"
            data_dir.mkdir()
            refs = ["textures\\a\\really_gone.dds"]
            got = nif_texrefs.check_refs(
                refs, data_dir, set(),
                bsa_files=["fake.bsa"], raw_confirm=lambda b, n: False)
            self.assertEqual(got, {"textures\\a\\really_gone.dds": "MISSING"})

    def test_no_bsa_files_skips_backstop_and_keeps_old_behavior(self):
        """bsa_files defaults to () — callers that don't opt in (e.g. the
        original synthetic test above) get plain LOOSE/BSA/MISSING with no
        raw_confirm import or call at all."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "Data"
            data_dir.mkdir()
            got = nif_texrefs.check_refs(["textures\\a\\gone.dds"], data_dir, set())
            self.assertEqual(got, {"textures\\a\\gone.dds": "MISSING"})


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

    def test_check_cli_backstops_would_be_missing_via_raw_confirm_by_default(self):
        """End-to-end: --check must not need a --raw-confirm flag. A ref
        that's absent from loose Data\\ and absent from the (on-disk, empty)
        bsa_index would previously be reported MISSING; with a BSA file
        present under dataDir and bsa_index.raw_confirm monkeypatched to hit,
        the CLI must report BSA-RAW and rc=0 (no false quarantine)."""
        from forensics import bsa_index
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            data_dir = tmp / "Data"
            mesh_dir = tmp / "meshes"
            data_dir.mkdir()
            mesh_dir.mkdir()
            (data_dir / "Fake.bsa").write_bytes(b"")
            (mesh_dir / "one.nif").write_bytes(
                fixtures.build_nif(["textures\\a\\index_missed_me.dds"]))
            idx_path = tmp / "idx.json"
            idx_path.write_text(
                json.dumps({"dataDir": str(data_dir), "bsas": {}}), encoding="utf-8")
            cfg_path = tmp / "modkit.json"
            cfg_path.write_text(
                json.dumps({"games": {"skyrim": {"dataDir": str(data_dir)}}}),
                encoding="utf-8")

            orig_raw_confirm = bsa_index.raw_confirm
            bsa_index.raw_confirm = lambda bsa_path, name: True
            try:
                rc = nif_texrefs.main([
                    str(mesh_dir), "--check",
                    "--config", str(cfg_path), "--index", str(idx_path)])
            finally:
                bsa_index.raw_confirm = orig_raw_confirm

            self.assertEqual(rc, 0)  # BSA-RAW, not MISSING -> no quarantine signal


if __name__ == "__main__":
    unittest.main()
