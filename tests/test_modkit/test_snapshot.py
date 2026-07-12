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


def test_capture_steam_missing_autoupdatebehavior_key_warns(tmp_path):
    # Valid, parseable AppState block, appid matches configured steamAppId,
    # but the AutoUpdateBehavior key itself is absent (not just falsy).
    # Fail-safe contract: absent means "unknown, warn" - not "assume safe".
    acf_no_autoupdate = (
        '"AppState"\n{\n\t"appid"\t\t"489830"\n\t"name"\t\t"Skyrim SE"\n'
        '\t"UserConfig"\n\t{\n\t\t"language"\t\t"english"\n\t}\n}\n')
    p = tmp_path / "appmanifest_489830.acf"
    p.write_text(acf_no_autoupdate, encoding="utf-8")
    sec, warns = snapshot.capture_steam({"appmanifest": str(p), "steamAppId": 489830})
    assert sec["appId"] == "489830"
    assert sec["autoUpdateBehavior"] is None
    assert len(warns) == 1
    assert "AutoUpdateBehavior=None" in warns[0]
    assert "unknown value" in warns[0]
    assert "loader chain" in warns[0]
    assert "not found" not in warns[0]


def test_capture_steam_malformed_acf_warns_not_raises(tmp_path):
    # Unbalanced braces: parses far enough to reach the '{' handling and
    # then raises ValueError (unclosed block) rather than failing at
    # tokenization. capture_steam must catch it and warn, not propagate.
    malformed = '"AppState"\n{\n\t"appid"\t\t"489830"\n\t"AutoUpdateBehavior"\t\t"1"\n'
    p = tmp_path / "appmanifest_489830.acf"
    p.write_text(malformed, encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot.parse_acf(malformed)  # confirms this fixture is actually malformed
    sec, warns = snapshot.capture_steam({"appmanifest": str(p), "steamAppId": 489830})
    assert sec == {"appmanifest": str(p), "appId": None, "autoUpdateBehavior": None}
    assert len(warns) == 1
    assert "unparseable" in warns[0]
    assert str(p) in warns[0]


# ---------------------------------------------------------------- Task 3

LEDGER_OK = (0, "13 total, 11 active, 2 removed (13 matching filters)")


def _stub_preset(tmp_path):
    """Fixture preset carrying the contract attrs; never a real path."""
    return types.SimpleNamespace(
        DATA_DIR=str(tmp_path / "Data"),
        PLUGINS_TXT=str(tmp_path / "Plugins.txt"),
        PROCESS_NAMES=["SkyrimSE.exe"],
        RUNTIME="1.6.1170",
        STAGING_ROOT=str(tmp_path / "staging"),
        BACKUPS_DIR=str(tmp_path / "manual" / "backups"),
    )


def _patch_core(monkeypatch, plugins=("*USSEP.esp", "Precision.esp"), ledger=LEDGER_OK):
    monkeypatch.setattr(snapshot.pluginstxt, "read", lambda preset: list(plugins))
    monkeypatch.setattr(snapshot.ledger_bridge, "run", lambda args: ledger)


def test_capture_plugins_list_hash_counts(tmp_path, monkeypatch):
    _patch_core(monkeypatch)
    sec, warns = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["lines"] == ["*USSEP.esp", "Precision.esp"]
    assert sec["enabled"] == 1 and sec["total"] == 2
    assert sec["sha256"] == snapshot.hashlib.sha256(
        b"*USSEP.esp\nPrecision.esp\n").hexdigest()
    assert warns == []


def test_capture_plugins_hash_stable_and_blankline_free(tmp_path, monkeypatch):
    _patch_core(monkeypatch, plugins=("*A.esp", "", "  ", "*B.esp"))
    sec, _ = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["lines"] == ["*A.esp", "*B.esp"]
    _patch_core(monkeypatch, plugins=("*A.esp", "*B.esp"))
    sec2, _ = snapshot.capture_plugins(_stub_preset(tmp_path))
    assert sec["sha256"] == sec2["sha256"]


def test_capture_plugins_skipped_when_no_plugins_txt(tmp_path):
    preset = _stub_preset(tmp_path)
    preset.PLUGINS_TXT = None  # CP77: no Plugins.txt
    assert snapshot.capture_plugins(preset) == (None, [])


def test_capture_dlls_sorted_toplevel(tmp_path):
    d = tmp_path / "SKSE" / "Plugins"
    (d / "sub").mkdir(parents=True)
    (d / "b.dll").write_bytes(b"x")
    (d / "A.dll").write_bytes(b"x")
    (d / "note.txt").write_bytes(b"x")
    (d / "sub" / "nested.dll").write_bytes(b"x")  # top-level only
    sec, warns = snapshot.capture_dlls({"dllDir": str(d)})
    assert sec["dlls"] == ["A.dll", "b.dll"]
    assert warns == []


def test_capture_dlls_missing_dir_warns_and_unconfigured_skips(tmp_path):
    sec, warns = snapshot.capture_dlls({"dllDir": str(tmp_path / "gone")})
    assert sec["dlls"] is None and len(warns) == 1
    assert snapshot.capture_dlls({}) == (None, [])


def test_capture_ini_values_and_missing_file_warns(tmp_path):
    ini = tmp_path / "Skyrim.ini"
    ini.write_text("[Display]\niTexMipMapSkip=1\n")
    cfg = {"ini": [
        {"file": str(ini), "section": "Display", "key": "iTexMipMapSkip"},
        {"file": str(tmp_path / "gone.ini"), "section": "X", "key": "y"},
    ]}
    sec, warns = snapshot.capture_ini(cfg)
    assert sec["Skyrim.ini::Display::iTexMipMapSkip"] == "1"
    assert sec["gone.ini::X::y"] is None
    assert len(warns) == 1 and "gone.ini" in warns[0]
    assert snapshot.capture_ini({}) == (None, [])


def test_capture_enb_keys(tmp_path):
    enb = tmp_path / "enbseries.ini"
    enb.write_text("[COMPLEXPARTICLELIGHTS]\nEnableShadow=true\n")
    cfg = {"enb": {"file": str(enb), "keys": [
        {"section": "COMPLEXPARTICLELIGHTS", "key": "EnableShadow"},
        {"section": "EFFECT", "key": "EnableComplexParticleLights"},
    ]}}
    sec, warns = snapshot.capture_enb(cfg)
    assert sec["keys"]["COMPLEXPARTICLELIGHTS::EnableShadow"] == "true"
    assert sec["keys"]["EFFECT::EnableComplexParticleLights"] is None
    assert warns == []
    assert snapshot.capture_enb({}) == (None, [])


def test_capture_enb_missing_file_degrades_gracefully(tmp_path):
    cfg = {"enb": {"file": str(tmp_path / "gone-enbseries.ini"), "keys": [
        {"section": "EFFECT", "key": "EnableComplexParticleLights"},
    ]}}
    sec, warns = snapshot.capture_enb(cfg)
    assert sec["keys"]["EFFECT::EnableComplexParticleLights"] is None
    assert len(warns) == 1 and "not found" in warns[0]


def test_capture_ledger_parses_counts(monkeypatch):
    calls = []
    monkeypatch.setattr(snapshot.ledger_bridge, "run",
                        lambda args: calls.append(args) or LEDGER_OK)
    sec, warns = snapshot.capture_ledger("skyrim")
    assert sec == {"total": 13, "active": 11, "removed": 2}
    assert warns == []
    assert calls == [["list", "--game", "skyrim", "--count"]]


def test_capture_ledger_failure_warns(monkeypatch):
    monkeypatch.setattr(snapshot.ledger_bridge, "run",
                        lambda args: (1, "ERROR: ledger not found"))
    sec, warns = snapshot.capture_ledger("skyrim")
    assert sec is None and len(warns) == 1 and "rc=1" in warns[0]


def test_capture_assembles_sections_and_thin_config(tmp_path, monkeypatch):
    _patch_core(monkeypatch)
    preset = _stub_preset(tmp_path)
    snap = snapshot.capture("skyrim", preset, {})
    assert snap["schemaVersion"] == 1 and snap["game"] == "skyrim"
    assert snap["sections"]["plugins"]["total"] == 2
    assert snap["sections"]["ledger"] == {"total": 13, "active": 11, "removed": 2}
    # thin config: unconfigured sections are None, no phantom warnings
    for name in ("dlls", "ini", "enb", "steam"):
        assert snap["sections"][name] is None
    assert snap["warnings"] == []
    assert snapshot.manual_dir(preset) == Path(preset.BACKUPS_DIR).parent
    assert snapshot.snapshot_cfg({"snapshot": {"skyrim": {"dllDir": "d"}}},
                                 "skyrim") == {"dllDir": "d"}
    assert snapshot.snapshot_cfg({}, "cp77") == {}


# ---------------------------------------------------------------- Task 4

def test_take_writes_snapshot_json(tmp_path, monkeypatch):
    _patch_core(monkeypatch, plugins=("*A.esp",))
    preset = _stub_preset(tmp_path)
    path, snap = snapshot.take("skyrim", preset, {}, stamp="20260711-120000")
    assert path == (Path(preset.BACKUPS_DIR).parent / "snapshots"
                    / "snapshot-20260711-120000.json")
    on_disk = snapshot.load_snapshot(path)
    assert on_disk["game"] == "skyrim"
    assert on_disk["sections"]["plugins"]["enabled"] == 1
    assert on_disk == json.loads(json.dumps(snap))  # round-trip identical


def test_snapshots_dir_derived_from_backups_dir(tmp_path):
    preset = _stub_preset(tmp_path)
    assert snapshot.snapshots_dir(preset) == tmp_path / "manual" / "snapshots"


def test_latest_snapshot_picks_newest_and_none(tmp_path):
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "snapshot-20260701-090000.json").write_text("{}")
    (d / "snapshot-20260711-090000.json").write_text("{}")
    (d / "unrelated.txt").write_text("x")
    assert snapshot.latest_snapshot(d).name == "snapshot-20260711-090000.json"
    assert snapshot.latest_snapshot(tmp_path / "empty") is None


# ---------------------------------------------------------------- Task 5

def _snap(plugins=None, dlls=None, ini=None, enb=None, ledger=None, steam=None,
          warnings=()):
    """Hand-build a snapshot dict in the exact capture() shape."""
    return {"schemaVersion": 1, "game": "skyrim", "takenAt": "2026-07-11T12:00:00",
            "sections": {"plugins": plugins, "dlls": dlls, "ini": ini,
                         "enb": enb, "ledger": ledger, "steam": steam},
            "warnings": list(warnings)}


def _plug(*lines):
    joined = "\n".join(lines) + "\n"
    import hashlib as h
    return {"lines": list(lines),
            "sha256": h.sha256(joined.encode("utf-8")).hexdigest(),
            "enabled": sum(1 for x in lines if x.startswith("*")),
            "total": len(lines)}


def test_diff_identical_no_drift():
    a = _snap(plugins=_plug("*A.esp"))
    text, deltas, warns = snapshot.diff_report(a, a)
    assert deltas == 0 and warns == 0
    assert "no drift" in text
    assert "ASK THE USER" not in text


def test_diff_plugin_added_removed():
    base = _snap(plugins=_plug("*A.esp", "*B.esp"))
    live = _snap(plugins=_plug("*A.esp", "*C.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 2
    assert "ADDED:   *C.esp" in text
    assert "REMOVED: *B.esp" in text


def test_diff_plugin_enable_flip():
    base = _snap(plugins=_plug("*Precision.esp"))
    live = _snap(plugins=_plug("Precision.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "CHANGED: Precision.esp: enabled -> DISABLED" in text


def test_diff_hash_only_change():
    base = _snap(plugins=_plug("*A.esp", "*B.esp"))
    live = _snap(plugins=_plug("*B.esp", "*A.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "same plugin set, different order/content" in text


def test_diff_dll_added():
    base = _snap(dlls={"dir": "d", "dlls": ["a.dll"]})
    live = _snap(dlls={"dir": "d", "dlls": ["a.dll", "OutfitDistributor.dll"]})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "ADDED:   OutfitDistributor.dll" in text


def test_diff_kv_ini_enb_changed():
    base = _snap(ini={"Skyrim.ini::Display::iTexMipMapSkip": "1"},
                 enb={"file": "e", "keys": {"EFFECT::X": "true"}})
    live = _snap(ini={"Skyrim.ini::Display::iTexMipMapSkip": None},
                 enb={"file": "e", "keys": {"EFFECT::X": "false"}})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 2
    assert "CHANGED: Skyrim.ini::Display::iTexMipMapSkip: '1' -> None" in text
    assert "CHANGED: EFFECT::X: 'true' -> 'false'" in text


def test_diff_ledger_and_steam_changed_and_warnings_surface():
    base = _snap(ledger={"total": 10, "active": 9, "removed": 1},
                 steam={"appmanifest": "p", "appId": "489830",
                        "autoUpdateBehavior": "1"})
    live = _snap(ledger={"total": 11, "active": 10, "removed": 1},
                 steam={"appmanifest": "p", "appId": "489830",
                        "autoUpdateBehavior": "0"},
                 warnings=["Steam AutoUpdateBehavior='0' ..."])
    text, deltas, warns = snapshot.diff_report(base, live)
    assert deltas == 2 and warns == 1
    assert "total 10 -> 11" in text
    assert "AutoUpdateBehavior '1' -> '0'" in text
    assert "WARNINGS (live state)" in text


def test_diff_ask_user_note_only_when_deltas():
    base = _snap(plugins=_plug("*A.esp"))
    live = _snap(plugins=_plug("A.esp"))
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1
    assert "ASK THE USER" in text and "Precision.esp" in text
    # warnings alone do not trigger the deltas note
    warntext, d2, w2 = snapshot.diff_report(base, _snap(plugins=_plug("*A.esp"),
                                                        warnings=["w"]))
    assert d2 == 0 and w2 == 1 and "ASK THE USER" not in warntext


def test_diff_section_presence_change_reported():
    base = _snap()
    live = _snap(dlls={"dir": "d", "dlls": ["a.dll"]})
    text, deltas, _ = snapshot.diff_report(base, live)
    assert deltas == 1 and "appeared (newly configured)" in text
