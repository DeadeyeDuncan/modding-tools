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
