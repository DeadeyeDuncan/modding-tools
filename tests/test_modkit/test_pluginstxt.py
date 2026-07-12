from pathlib import Path

import pytest

from modkit import pluginstxt


def raw(game_env):
    return (game_env / "Plugins.txt").read_bytes()


def lines(game_env):
    return raw(game_env).decode("utf-8-sig").splitlines()


def test_read_returns_verbatim_lines(preset):
    got = pluginstxt.read(preset)
    assert got[0] == "*Unofficial Skyrim Special Edition Patch.esp"
    assert "DisabledMod.esp" in got
    assert len(got) == 6


def test_enable_after_anchor_preserves_bom_crlf_and_snapshots(game_env, preset):
    pluginstxt.enable(preset, "NewMod.esp", "skyui_se.esp")  # case-insensitive anchor
    b = raw(game_env)
    assert b.startswith(b"\xef\xbb\xbf")
    assert b"*SkyUI_SE.esp\r\n*NewMod.esp\r\n" in b
    backups = list((game_env / "backups").glob("plugins-pre-enable-*.txt"))
    assert len(backups) == 1


def test_enable_default_inserts_before_dyndolod_block(game_env, preset):
    pluginstxt.enable(preset, "Tail.esp", None)
    ls = lines(game_env)
    assert ls.index("*Tail.esp") < ls.index("*DynDOLOD.esm")
    assert ls[-3:] == ["*DynDOLOD.esm", "*DynDOLOD.esp", "*Occlusion.esp"]


def test_enable_anchor_inside_block_clamps_before_block(game_env, preset):
    pluginstxt.enable(preset, "Clamped.esp", "Occlusion.esp")
    ls = lines(game_env)
    assert ls.index("*Clamped.esp") < ls.index("*DynDOLOD.esm")


def test_enable_existing_disabled_line_in_place(game_env, preset):
    pluginstxt.enable(preset, "DisabledMod.esp", None)
    ls = lines(game_env)
    assert ls[2] == "*DisabledMod.esp"
    assert len(ls) == 6  # no duplicate line added


def test_enable_unknown_anchor_raises_and_writes_nothing(game_env, preset):
    before = raw(game_env)
    with pytest.raises(pluginstxt.PluginsTxtError):
        pluginstxt.enable(preset, "X.esp", "NoSuchAnchor.esp")
    assert raw(game_env) == before


def test_disable_strips_star_keeps_line(game_env, preset):
    pluginstxt.disable(preset, "SkyUI_SE.esp")
    ls = lines(game_env)
    assert "SkyUI_SE.esp" in ls and "*SkyUI_SE.esp" not in ls
    with pytest.raises(pluginstxt.PluginsTxtError):
        pluginstxt.disable(preset, "NotThere.esp")


def test_snapshot_diff_roundtrip(game_env, preset):
    snap = pluginstxt.snapshot(preset, "test")
    assert Path(snap).is_file()
    assert pluginstxt.diff(snap, str(game_env / "Plugins.txt")) == "no differences"
    pluginstxt.enable(preset, "Added.esp", None)
    pluginstxt.disable(preset, "SkyUI_SE.esp")
    report = pluginstxt.diff(snap, str(game_env / "Plugins.txt"))
    assert "ADDED   *Added.esp" in report
    assert "STATE" in report and "enabled -> disabled" in report


def test_cli_plugins_list_and_diff_usage(game_env, preset, run_cli):
    code, out = run_cli("plugins", "list", "--game", "skyrim")
    assert code == 0
    assert "*Unofficial Skyrim Special Edition Patch.esp" in out
    code, out = run_cli("plugins", "diff", "--game", "skyrim")  # needs 2 paths
    assert code == 1


# --- extra coverage required by the task-9 assignment (BOM/CRLF + external-scramble) ---

def test_enable_no_bom_source_stays_no_bom_and_crlf(game_env, preset):
    """Round-trip a Plugins.txt WITHOUT a BOM: must stay BOM-less, CRLF-only."""
    p = game_env / "Plugins.txt"
    p.write_bytes(
        b"*Unofficial Skyrim Special Edition Patch.esp\r\n"
        b"*SkyUI_SE.esp\r\n"
        b"DisabledMod.esp\r\n"
        b"*DynDOLOD.esm\r\n"
        b"*DynDOLOD.esp\r\n"
        b"*Occlusion.esp\r\n")
    pluginstxt.enable(preset, "NoBomMod.esp", None)
    b = raw(game_env)
    assert not b.startswith(b"\xef\xbb\xbf")
    assert b.count(b"\n") == b.count(b"\r\n")  # every line CRLF-terminated, no bare LF
    assert b"*NoBomMod.esp\r\n*DynDOLOD.esm\r\n" in b


def test_diff_detects_external_scramble_reorder_and_disable(game_env, preset):
    """Bracket an external GUI tool (Wrye Bash class of bug): snapshot before,
    let something else rewrite Plugins.txt directly (reorder two lines AND
    silently disable one), then diff must clearly flag both the reorder and
    the state flip."""
    snap = pluginstxt.snapshot(preset, "pre-wryebash")
    scrambled = (
        b"\xef\xbb\xbf"
        b"*SkyUI_SE.esp\r\n"
        b"Unofficial Skyrim Special Edition Patch.esp\r\n"  # reordered + disabled
        b"DisabledMod.esp\r\n"
        b"*DynDOLOD.esm\r\n"
        b"*DynDOLOD.esp\r\n"
        b"*Occlusion.esp\r\n")
    (game_env / "Plugins.txt").write_bytes(scrambled)
    report = pluginstxt.diff(snap, str(game_env / "Plugins.txt"))
    assert "ORDER" in report
    assert "STATE" in report and "enabled -> disabled" in report


# --- task-9 regression tests: LF-normalize, backup ordering, read() filtering ---

def test_enable_bare_lf_source_normalizes_to_crlf(game_env, preset):
    """Round-trip a Plugins.txt whose bytes use ONLY bare LF line endings
    (no CR anywhere, no BOM). _write_raw always joins with '\\r\\n', so the
    output must be fully CRLF: no bare LF survives and no line gets doubled
    to '\\r\\r\\n'. This is the one input shape (LF-only, no CRLF at all)
    the rest of the suite doesn't exercise."""
    p = game_env / "Plugins.txt"
    p.write_bytes(
        b"*Unofficial Skyrim Special Edition Patch.esp\n"
        b"*SkyUI_SE.esp\n"
        b"DisabledMod.esp\n"
        b"*DynDOLOD.esm\n"
        b"*DynDOLOD.esp\n"
        b"*Occlusion.esp\n")
    pluginstxt.enable(preset, "LfMod.esp", None)
    b = raw(game_env)
    assert b"\r\n" in b
    assert b.count(b"\n") == b.count(b"\r\n")  # every \n is part of a \r\n pair
    assert b"\r\r\n" not in b  # no doubled CR


def test_enable_backup_captures_bytes_before_mutation(game_env, preset):
    """snapshot() must copy Plugins.txt BEFORE any in-memory lines are
    written back out. Capture the exact pre-call bytes, then assert the
    backup file enable() creates matches them byte-for-byte (not just that
    a backup exists) -- this pins the backup-before-mutation ordering."""
    p = game_env / "Plugins.txt"
    before = p.read_bytes()
    pluginstxt.enable(preset, "BackupOrderCheck.esp", None)
    backups = list((game_env / "backups").glob("plugins-pre-enable-*.txt"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before


def test_read_skips_comments_and_blank_lines(game_env, preset):
    """read()'s filter (`l.strip() and not l.lstrip().startswith('#')`) must
    actually drop comment lines and blank/whitespace-only lines, not just
    pass every line through."""
    p = game_env / "Plugins.txt"
    p.write_bytes(
        b"\xef\xbb\xbf"
        b"# comment header\r\n"
        b"*Unofficial Skyrim Special Edition Patch.esp\r\n"
        b"\r\n"
        b"*SkyUI_SE.esp\r\n"
        b"   \r\n"
        b"DisabledMod.esp\r\n")
    got = pluginstxt.read(preset)
    assert got == [
        "*Unofficial Skyrim Special Edition Patch.esp",
        "*SkyUI_SE.esp",
        "DisabledMod.esp",
    ]
