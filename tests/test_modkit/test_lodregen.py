"""Tests for modkit lodregen. No test touches a real game dir: every path is
built under tmp_path and injected via a fixture config dict + SimpleNamespace
preset carrying the modkit core preset attrs."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from modkit import lodregen


# ---------------------------------------------------------------- fixtures

def fixture_section(tmp_path):
    """A complete lodregen.skyrim config section rooted under tmp_path."""
    return {
        "holding_root": str(tmp_path / "holding"),
        "ledger_dir": str(tmp_path / "ledgerdir"),
        "trio": ["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"],
        "tool_processes": ["PGPatcher.exe", "TexGenx64.exe", "DynDOLODx64.exe"],
        "tools": {
            "pgpatcher_exe": str(tmp_path / "tools" / "PGPatcher.exe"),
            "texgen_exe": str(tmp_path / "tools" / "TexGenx64.exe"),
            "dyndolod_exe": str(tmp_path / "tools" / "DynDOLODx64.exe"),
            "dyndolod_ini": str(tmp_path / "tools" / "DynDOLOD_SSE.ini"),
        },
        "outputs": {
            "pgpatcher": str(tmp_path / "PGPatcher-Output"),
            "texgen": str(tmp_path / "TexGen_Output"),
            "dyndolod": str(tmp_path / "DynDOLOD_Output"),
        },
        "min_output_files": {"texgen": 3, "dyndolod": 5},
        "ledger_prefixes": {"texgen": "TexGen Output", "dyndolod": "DynDOLOD Output"},
        "ng_markers": ["SKSE\\Plugins\\DynDOLOD.DLL",
                       "textures\\DynDOLOD\\lod\\version.ini"],
        "protected_inputs": [
            "textures\\dyndolod\\lod\\dyndolodtreelod*",
            "textures\\dyndolod\\lod\\dyndolodbackgroundtreelod*",
            "textures\\dyndolod\\lod\\version.ini",
            "textures\\dyndolod\\lod\\defaultdiffuse*",
            "textures\\dyndolod\\lod\\texgen_sse.ini",
            "meshes\\dyndolod\\lod\\*holycow*",
            "meshes\\dyndolod\\lod\\*mxtundra*_dyndolod_lod.nif",
            "*statics_e.dds",
            "*landscape\\statics\\rocks01*",
        ],
        "resources_staging": str(tmp_path / "dyndolod-resources"),
    }


def fixture_cfg(tmp_path):
    return {"lodregen": {"skyrim": fixture_section(tmp_path)}}


# ---------------------------------------------------------------- Task 1

def test_section_returns_game_config(tmp_path):
    cfg = fixture_cfg(tmp_path)
    sec = lodregen.section(cfg, "skyrim")
    assert sec["trio"] == ["DynDOLOD.esm", "DynDOLOD.esp", "Occlusion.esp"]
    assert sec["ledger_prefixes"]["dyndolod"] == "DynDOLOD Output"


def test_section_missing_game_raises(tmp_path):
    with pytest.raises(lodregen.LodregenError, match="no lodregen section"):
        lodregen.section({"lodregen": {}}, "skyrim")
    with pytest.raises(lodregen.LodregenError, match="no lodregen section"):
        lodregen.section({}, "skyrim")


def test_section_missing_keys_raises(tmp_path):
    cfg = fixture_cfg(tmp_path)
    del cfg["lodregen"]["skyrim"]["protected_inputs"]
    with pytest.raises(lodregen.LodregenError, match="protected_inputs"):
        lodregen.section(cfg, "skyrim")


def test_section_rejects_wrong_trio_shape(tmp_path):
    cfg = fixture_cfg(tmp_path)
    cfg["lodregen"]["skyrim"]["trio"] = ["DynDOLOD.esm", "Occlusion.esp"]
    with pytest.raises(lodregen.LodregenError, match="exactly 3"):
        lodregen.section(cfg, "skyrim")


# ---------------------------------------------------------------- Task 2

def test_new_run_creates_state_file(tmp_path):
    sec = fixture_section(tmp_path)
    run_dir, state = lodregen.new_run(sec, "skyrim")
    assert run_dir.is_dir()
    assert run_dir.parent == Path(sec["holding_root"])
    on_disk = lodregen.load_state(run_dir)
    assert on_disk == state
    assert on_disk["game"] == "skyrim"
    assert on_disk["pre"] is None and on_disk["post"] is None
    assert on_disk["run_id"] == run_dir.name


def test_pending_runs_and_save_state(tmp_path):
    sec = fixture_section(tmp_path)
    run_dir, state = lodregen.new_run(sec, "skyrim")
    assert len(lodregen.pending_runs(sec["holding_root"])) == 1
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    state["post"] = {"stamp": "2026-07-11T12:00:00"}
    lodregen.save_state(run_dir, state)
    assert lodregen.pending_runs(sec["holding_root"]) == []
    assert len(lodregen.all_runs(sec["holding_root"])) == 1


def test_pending_runs_empty_when_no_holding_root(tmp_path):
    assert lodregen.pending_runs(str(tmp_path / "nope")) == []


def test_status_lists_pending_and_exits_2(tmp_path, capsys):
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    run_dir, state = lodregen.new_run(sec, "skyrim")
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    lodregen.save_state(run_dir, state)
    args = SimpleNamespace(game="skyrim")
    rc = lodregen.cmd_status(args, cfg=cfg)
    out = capsys.readouterr().out
    assert rc == 2
    assert "PENDING" in out
    assert "texgen NOT deployed" in out
    assert "modkit lodregen post" in out


def test_status_clean_when_complete(tmp_path, capsys):
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    run_dir, state = lodregen.new_run(sec, "skyrim")
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    state["post"] = {"stamp": "2026-07-11T12:00:00"}
    lodregen.save_state(run_dir, state)
    rc = lodregen.cmd_status(SimpleNamespace(game="skyrim"), cfg=cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "COMPLETE" in out


def test_new_run_collision_raises(tmp_path, monkeypatch):
    """new_run() uses mkdir(parents=True, exist_ok=False) on purpose: a
    same-second run_id collision must raise instead of silently stepping
    into (and potentially corrupting) another in-flight run's state file.
    Lock that behavior in by pinning _now() so two calls collide."""
    sec = fixture_section(tmp_path)
    fixed = lodregen._now()
    monkeypatch.setattr(lodregen, "_now", lambda: fixed)
    lodregen.new_run(sec, "skyrim")
    with pytest.raises(FileExistsError):
        lodregen.new_run(sec, "skyrim")


def test_status_skips_corrupt_run_json(tmp_path, capsys):
    """all_runs() used to call load_state() with no guard, so one corrupt
    or foreign lodregen-run.json raised and aborted cmd_status for every
    run and game -- ironic for a status reporter. Now it's skipped (BROKEN
    unreadable) and the well-formed run still reports; status still exits
    0. (The well-formed run here is COMPLETE rather than merely PENDING:
    a genuinely PENDING lodregen run legitimately returns exit 2 by
    existing, deliberate design -- see test_status_lists_pending_and_exits_2
    -- a pending regen blocks the game launch, and that contract is
    unrelated to and unchanged by this corrupt-json resilience fix.)"""
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    run_dir, state = lodregen.new_run(sec, "skyrim")
    state["pre"] = {"stamp": "2026-07-11T10:00:00", "epoch": 1.0}
    state["post"] = {"stamp": "2026-07-11T12:00:00"}
    lodregen.save_state(run_dir, state)

    broken_dir = Path(sec["holding_root"]) / "20260711-999999"
    broken_dir.mkdir(parents=True)
    (broken_dir / lodregen.RUN_STATE).write_text("{not valid json", encoding="utf-8")

    rc = lodregen.cmd_status(SimpleNamespace(game="skyrim"), cfg=cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "COMPLETE" in out
    assert state["run_id"] in out
    assert "BROKEN" in out and "unreadable" in out


def test_cli_reports_lodregen_error_cleanly(game_env, run_cli):
    """main() in cli.py caught config.ConfigError but not
    lodregen.LodregenError, so `lodregen status --game <no-section>` dumped
    a raw traceback instead of the codebase's ERROR: ... + exit-1 pattern.
    game_env's modkit.json has a "skyrim" game preset but no "lodregen"
    section at all, which is exactly what section() rejects."""
    code, out = run_cli("lodregen", "status", "--game", "skyrim")
    assert code == 1
    assert "ERROR" in out
    assert "no lodregen section" in out


def test_register_wires_three_subcommands():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    lodregen.register(sub)
    args = p.parse_args(["lodregen", "status", "--game", "skyrim"])
    assert args.func is lodregen.cmd_status
    args = p.parse_args(["lodregen", "pre", "--game", "skyrim", "--no-pgpatcher"])
    assert args.func is lodregen.cmd_pre and args.no_pgpatcher
    args = p.parse_args(["lodregen", "post", "--game", "skyrim", "--stage", "texgen"])
    assert args.func is lodregen.cmd_post and args.stage == "texgen"
