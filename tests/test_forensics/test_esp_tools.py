import struct
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
from forensics import esp_tools


class TestRecordWalk(unittest.TestCase):
    def test_iter_records_walks_grups(self):
        data = fixtures.build_esp(
            masters=["Skyrim.esm"],
            stats=[(0x000123, "FixtureRock01", "meshes\\fixture\\rock01.nif"),
                   (0x000124, "FixtureRock02", None)])
        types = [r[0] for r in esp_tools.iter_records(data)]
        self.assertEqual(types, ["TES4", "STAT", "STAT"])

    def test_compressed_record_payload_roundtrip(self):
        data = fixtures.build_esp(
            masters=[], stats=[(0x000200, "CompStat", "meshes\\c\\z.nif")],
            compressed_formids={0x000200})
        recs = [r for r in esp_tools.iter_records(data) if r[0] == "STAT"]
        self.assertEqual(len(recs), 1)
        rtype, flags, formid, raw = recs[0]
        self.assertTrue(flags & fixtures.FLAG_COMPRESSED)
        payload = esp_tools.record_payload(flags, raw)
        subs = dict(esp_tools.iter_subrecords(payload))
        self.assertEqual(subs["MODL"], b"meshes\\c\\z.nif\x00")


class TestModl(unittest.TestCase):
    def test_modl_records_extracts_paths_and_types(self):
        data = fixtures.build_esp(
            masters=["Skyrim.esm"],
            stats=[(0x000123, "A", "meshes\\_pgpatcher_dups\\1\\x.nif"),
                   (0x000124, "B", None),
                   (0x000125, "C", "meshes\\smim\\y-smimice.nif")])
        with tempfile.TemporaryDirectory() as tmp:
            esp = Path(tmp) / "t.esp"
            esp.write_bytes(data)
            modls, errors = esp_tools.modl_records(str(esp))
        self.assertEqual(errors, [])
        self.assertEqual(modls, [
            (0x000123, "STAT", "meshes\\_pgpatcher_dups\\1\\x.nif"),
            (0x000125, "STAT", "meshes\\smim\\y-smimice.nif")])

    def test_truncated_record_reports_error_not_crash(self):
        good = fixtures.build_esp(masters=[], stats=[(0x1, "A", "meshes\\a.nif")])
        with tempfile.TemporaryDirectory() as tmp:
            esp = Path(tmp) / "t.esp"
            esp.write_bytes(good[:-10])  # cut mid-record
            modls, errors = esp_tools.modl_records(str(esp))
        self.assertTrue(errors)


class TestGut(unittest.TestCase):
    def test_gut_stub_is_first_24_plus_datasize_bytes(self):
        data = fixtures.build_esp(
            masters=["Skyrim.esm", "Update.esm"],
            stats=[(0x000123, "A", "meshes\\a.nif")])
        stub = esp_tools.gut_stub_bytes(data)
        tes4_size = struct.unpack_from("<I", data, 4)[0]
        self.assertEqual(len(stub), 24 + tes4_size)
        self.assertEqual(stub, data[:24 + tes4_size])
        # the stub still carries its MAST entries (why dependents don't CTD)
        self.assertIn(b"MAST", stub)
        self.assertIn(b"Update.esm", stub)
        # and no records survive
        self.assertNotIn(b"STAT", stub)

    def test_gut_rejects_non_tes4(self):
        with self.assertRaises(SystemExit):
            esp_tools.gut_stub_bytes(b"JUNKxxxxxxxxxxxxxxxxxxxxxxxx")

    def test_gut_cli_refuses_output_under_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "Data"
            data_dir.mkdir()
            src = Path(tmp) / "t.esp"
            src.write_bytes(fixtures.build_esp(masters=[], stats=[]))
            cfg_path = Path(tmp) / "modkit.json"
            cfg_path.write_text(
                '{"forensics": {"games": {"skyrim": {"dataDir": "%s"}}}}'
                % str(data_dir).replace("\\", "\\\\"), encoding="utf-8")
            rc = None
            try:
                rc = esp_tools.main(["gut", str(src),
                                     "-o", str(data_dir / "t.esp"),
                                     "--config", str(cfg_path)])
            except SystemExit as e:
                rc = e.code
            self.assertNotEqual(rc, 0)
            self.assertFalse((data_dir / "t.esp").exists())


if __name__ == "__main__":
    unittest.main()
