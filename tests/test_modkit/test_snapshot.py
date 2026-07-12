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
