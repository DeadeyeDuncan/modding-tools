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
from forensics import bsa_index

BSARCH = r"C:\Modding\BSArch\BSArch64.exe"


class TestListingParse(unittest.TestCase):
    def test_parse_bsarch_listing_keeps_paths_drops_noise(self):
        text = (
            "BSArch v0.9c by ElminsterAU\n"
            "Archive: fixture.bsa\n"
            "meshes\\fixture\\a.nif\n"
            "MESHES\\Fixture\\Sub\\B.NIF\n"
            "textures/fixture/c.dds\n"
            "Done in 0.01s, 3 files\n")
        got = bsa_index.parse_bsarch_listing(text)
        self.assertEqual(sorted(got), [
            "meshes\\fixture\\a.nif",
            "meshes\\fixture\\sub\\b.nif",
            "textures\\fixture\\c.dds"])

    def test_parse_ignores_lines_without_asset_extension(self):
        self.assertEqual(bsa_index.parse_bsarch_listing("no paths here\n123\n"), [])


class TestIndexQueries(unittest.TestCase):
    def setUp(self):
        self.index = {"dataDir": "x", "bsas": {
            "Skyrim - Meshes0.bsa": ["meshes\\clutter\\sack01.nif"],
            "SMIM.bsa": ["meshes\\smim\\a.nif", "meshes\\smim\\deep\\b.nif"]}}

    def test_contains_exact_rel(self):
        self.assertEqual(bsa_index.contains(self.index, "MESHES/clutter/Sack01.NIF"),
                         ["Skyrim - Meshes0.bsa"])
        self.assertEqual(bsa_index.contains(self.index, "meshes\\nope.nif"), [])

    def test_all_paths_and_dir_prefixes(self):
        self.assertIn("meshes\\smim\\deep\\b.nif", bsa_index.all_paths(self.index))
        prefixes = bsa_index.dir_prefixes(self.index)
        self.assertIn("meshes\\smim", prefixes)
        self.assertIn("meshes\\smim\\deep", prefixes)
        self.assertIn("meshes\\clutter", prefixes)
        self.assertNotIn("meshes\\_pgpatcher_dups", prefixes)


class TestRawConfirm(unittest.TestCase):
    def test_raw_confirm_finds_name_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            bsa = Path(tmp) / "fake.bsa"
            bsa.write_bytes(b"\x00BSA\x00junk\x00Sack01.NIF\x00more")
            self.assertTrue(bsa_index.raw_confirm(str(bsa), "sack01.nif"))
            self.assertFalse(bsa_index.raw_confirm(str(bsa), "coinbaglarge.nif"))

    def test_raw_confirm_straddles_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            bsa = Path(tmp) / "fake.bsa"
            needle = b"needle.nif"  # 10 bytes
            # With chunk=64, a 60-byte prefix puts the boundary at byte 64,
            # which falls INSIDE the needle (bytes 60-69) - 4 bytes ("need")
            # land in the first chunk and the remaining 6 ("le.nif") land in
            # the second, so this only passes if the carry-over logic really
            # stitches chunk boundaries back together (the old fixture placed
            # the needle at offset 100, entirely inside the second chunk, so
            # it never exercised the carry-over at all).
            bsa.write_bytes(b"A" * 60 + needle + b"B" * 100)
            self.assertTrue(bsa_index.raw_confirm(str(bsa), "needle.nif", chunk=64))
            self.assertFalse(bsa_index.raw_confirm(str(bsa), "nomatch.nif", chunk=64))


@unittest.skipUnless(os.path.isfile(BSARCH), "BSArch not installed on this machine")
class TestRealBsaRoundTrip(unittest.TestCase):
    """THE correctness fixture. An inline BSA parser once had an offset bug that
    caused hours of false-positive triage (reflection-notes s6, 3a7247b5); this
    test packs known loose files with BSArch and asserts the listing pipeline
    returns exactly that set."""

    def test_pack_then_list_matches_loose_set(self):
        # Deliberately mixes extensions OUTSIDE the old ASSET_EXTS allowlist
        # (.strings, .btt) with ones that WERE on it (.nif, .dds). This is
        # the fixture that would have caught the Task 2 review bug: an
        # extension allowlist gating BSArch's own authoritative -list output
        # silently dropped 889 real entries (.strings/.dlstrings/.ilstrings,
        # .btt/.lst, ...) across 12 real Data\ BSAs.
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            expected = ["meshes\\fixture\\a.nif",
                        "meshes\\fixture\\sub\\b.nif",
                        "meshes\\terrain\\fixture.btt",
                        "strings\\fixture_english.strings",
                        "textures\\fixture\\c.dds"]
            for rel in expected:
                p = loose / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"fixture-bytes-" + rel.encode("ascii"))
            out_bsa = Path(tmp) / "fixture.bsa"
            rc, text = _lib.run(bsa_index.bsarch_pack_cmd(BSARCH, str(loose), str(out_bsa)))
            self.assertEqual(rc, 0, "BSArch pack failed:\n" + text)
            self.assertTrue(out_bsa.is_file(), "pack produced no archive:\n" + text)

            paths = bsa_index.list_bsa(BSARCH, str(out_bsa), tmp_root=tmp)
            self.assertEqual(len(paths), len(expected),
                             "listing count does not match packed loose set")
            self.assertEqual(sorted(paths), expected,
                             "listing does not match packed loose set (extensions "
                             "outside the old ASSET_EXTS allowlist must round-trip too)")

    def test_raw_confirm_on_real_bsa(self):
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            p = loose / "meshes" / "fixture" / "a.nif"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"x")
            out_bsa = Path(tmp) / "fixture.bsa"
            rc, text = _lib.run(bsa_index.bsarch_pack_cmd(BSARCH, str(loose), str(out_bsa)))
            self.assertEqual(rc, 0, text)
            self.assertTrue(bsa_index.raw_confirm(str(out_bsa), "a.nif"))


if __name__ == "__main__":
    unittest.main()
