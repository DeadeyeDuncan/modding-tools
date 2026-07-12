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
