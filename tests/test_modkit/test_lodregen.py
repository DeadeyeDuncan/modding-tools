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


def make_tes4(masters, esl=False):
    """Minimal valid SSE plugin: a TES4 record with HEDR + MAST/DATA pairs.
    Header: sig(4) dataSize(4) flags(4) formid(4) vc(4) version(2) unk(2).
    Defined here (not in Task 5) so Task 4's tests are self-contained --
    it is pure struct-packing, no game data."""
    subs = b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 0, 0x800)
    for m in masters:
        name = m.encode("cp1252") + b"\x00"
        subs += b"MAST" + struct.pack("<H", len(name)) + name
        subs += b"DATA" + struct.pack("<H", 8) + b"\x00" * 8
    flags = 0x200 if esl else 0
    return (b"TES4" + struct.pack("<IIII", len(subs), flags, 0, 0)
            + struct.pack("<HH", 44, 0) + subs)


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


# ---------------------------------------------------------------- Task 3

PROTECTED = [
    "textures\\dyndolod\\lod\\dyndolodtreelod*",
    "textures\\dyndolod\\lod\\dyndolodbackgroundtreelod*",
    "textures\\dyndolod\\lod\\version.ini",
    "textures\\dyndolod\\lod\\defaultdiffuse*",
    "textures\\dyndolod\\lod\\texgen_sse.ini",
    "meshes\\dyndolod\\lod\\*holycow*",
    "meshes\\dyndolod\\lod\\*mxtundra*_dyndolod_lod.nif",
    "*statics_e.dds",
    "*landscape\\statics\\rocks01*",
]


def test_protected_matches_every_known_input():
    # the exact victims/inputs from the wiki clean-trap table
    hits = [
        "textures\\DynDOLOD\\lod\\DynDOLODTreeLOD.dds",
        "Textures\\dyndolod\\lod\\dyndolodbackgroundtreelod.dds",
        "textures/dyndolod/lod/version.ini",          # forward slashes tolerated
        "textures\\dyndolod\\lod\\defaultdiffuse.dds",
        "textures\\dyndolod\\lod\\TexGen_SSE.ini",
        "meshes\\dyndolod\\lod\\holycow_dyndolod_load.nif",
        # the 7 mxtundra meshes live in SUBFOLDERS -- pattern must span dirs
        "meshes\\dyndolod\\lod\\effects\\mxtundrastreamtransition01_0100A123_dyndolod_lod.nif",
        "textures\\cubemaps\\statics_e.dds",
        "textures\\landscape\\statics\\rocks01.dds",
        "textures\\landscape\\statics\\rocks01_n.dds",
    ]
    for rel in hits:
        assert lodregen.is_protected(rel, PROTECTED), rel


def test_protected_does_not_match_regenerable_output():
    misses = [
        "meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto",
        "textures\\dyndolod\\lod\\dyndolod_tamriel.dds",   # generated atlas
        "meshes\\dyndolod\\lod\\somecity_aaa_dyndolod_lod.nif",
        "DynDOLOD.esm",
    ]
    for rel in misses:
        assert not lodregen.is_protected(rel, PROTECTED), rel


def _mk(data, rel):
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_guarded_clean_moves_skips_reports(tmp_path):
    data = tmp_path / "Data"
    quarantine = tmp_path / "q"
    out_file = _mk(data, "meshes/terrain/tamriel/objects/tamriel.4.0.-1.bto")
    prot_file = _mk(data, "textures/dyndolod/lod/dyndolodtreelod.dds")
    manifest = [
        "meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto",
        "textures\\dyndolod\\lod\\dyndolodtreelod.dds",   # polluted manifest!
        "textures\\dyndolod\\lod\\long_gone.dds",         # already missing
    ]
    rep = lodregen.guarded_clean(str(data), manifest, PROTECTED, str(quarantine))
    assert rep["moved"] == ["meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto"]
    assert rep["protected"] == ["textures\\dyndolod\\lod\\dyndolodtreelod.dds"]
    assert rep["missing"] == ["textures\\dyndolod\\lod\\long_gone.dds"]
    assert not out_file.exists()
    assert (quarantine / "meshes/terrain/tamriel/objects/tamriel.4.0.-1.bto").is_file()
    assert prot_file.is_file()   # the input SURVIVED the polluted manifest


def test_guarded_clean_refuses_wildcards_and_dirs(tmp_path):
    data = tmp_path / "Data"
    (data / "meshes").mkdir(parents=True)
    with pytest.raises(lodregen.LodregenError, match="wildcard"):
        lodregen.guarded_clean(str(data), ["meshes\\*.nif"], PROTECTED,
                               str(tmp_path / "q"))
    with pytest.raises(lodregen.LodregenError, match="directory"):
        lodregen.guarded_clean(str(data), ["meshes"], PROTECTED,
                               str(tmp_path / "q"))


def test_guarded_clean_aborts_before_moving_anything_when_valid_line_precedes_wildcard(tmp_path):
    """Reviewer-reported ordering bug: a valid, movable line that PRECEDES a
    wildcard (or directory) poison-pill line must NOT be moved before the
    abort is raised. guarded_clean now validates every manifest line before
    executing any shutil.move, so the whole-clean abort really is
    all-or-nothing -- nothing is touched, not even lines that would have
    been valid on their own."""
    data = tmp_path / "Data"
    quarantine = tmp_path / "q"
    out_file = _mk(data, "meshes/terrain/tamriel/objects/tamriel.4.0.-1.bto")
    manifest = [
        "meshes\\terrain\\tamriel\\objects\\tamriel.4.0.-1.bto",  # valid; moves first under the old code
        "meshes\\*.nif",                                          # wildcard -> aborts
    ]
    with pytest.raises(lodregen.LodregenError, match="wildcard"):
        lodregen.guarded_clean(str(data), manifest, PROTECTED, str(quarantine))
    assert out_file.is_file()                # still at its original location
    assert not quarantine.exists()           # nothing was ever quarantined


def test_read_lines_bomsafe(tmp_path):
    f = tmp_path / "m.txt"
    f.write_bytes(b"\xef\xbb\xbf" + b"a.dds\r\nb.dds\r\n\r\n")
    assert lodregen.read_lines_bomsafe(f) == ["a.dds", "b.dds"]


# ---------------------------------------------------------------- Task 4

TASKLIST_IDLE = ('"svchost.exe","1234","Services","0","10,000 K"\n'
                 '"explorer.exe","5678","Console","1","90,000 K"\n')
TASKLIST_GAME = TASKLIST_IDLE + '"SkyrimSE.exe","9999","Console","1","2,000,000 K"\n'


def test_running_processes_parses_tasklist_csv():
    names = ["SkyrimSE.exe", "TexGenx64.exe"]
    assert lodregen.running_processes(names, csv_text=TASKLIST_IDLE) == []
    assert lodregen.running_processes(names, csv_text=TASKLIST_GAME) == ["SkyrimSE.exe"]


def make_env(tmp_path, monkeypatch, trio_in_data=True, ledger_list_out=None,
            trio_in_plugins=True):
    """Fixture game env: fake Data + real Plugins.txt handled by the REAL
    modkit.pluginstxt, fake ledger_bridge, idle tasklist.

    trio_in_plugins=False builds a Plugins.txt with the trio LINES ABSENT
    entirely (not merely disabled) -- the genuine first-ever-DynDOLOD-setup
    condition, where the trio plugins are tool-generated and have no
    Plugins.txt entry at all yet."""
    data = tmp_path / "Data"
    data.mkdir(exist_ok=True)
    plugins = tmp_path / "Plugins.txt"
    lines = ["*Unofficial Skyrim Special Edition Patch.esp", "*SomeMod.esp"]
    if trio_in_plugins:
        lines += ["*DynDOLOD.esm", "*DynDOLOD.esp", "*Occlusion.esp"]
    plugins.write_bytes(b"\xef\xbb\xbf"
                        + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    (tmp_path / "backups").mkdir(exist_ok=True)
    preset = SimpleNamespace(
        DATA_DIR=str(data), PLUGINS_TXT=str(plugins),
        PROCESS_NAMES=["SkyrimSE.exe"], RUNTIME="1.6.1170",
        STAGING_ROOT=str(tmp_path / "staging"),
        BACKUPS_DIR=str(tmp_path / "backups"))
    sec = fixture_section(tmp_path)
    cfg = {"lodregen": {"skyrim": sec}}
    # tool exes + ini exist
    for key, p in sec["tools"].items():
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("Wizard=0\nExpert=0\n" if key == "dyndolod_ini" else "MZ")
    # NG markers exist
    for m in sec["ng_markers"]:
        _mk(data, m.replace("\\", "/"))
    if trio_in_data:
        for name in sec["trio"]:
            (data / name).write_bytes(make_tes4(["Skyrim.esm"]))
    # ledger fake
    calls = []
    list_out = ledger_list_out if ledger_list_out is not None else (
        "DynDOLOD Output  installed 2026-06-28  DynDOLOD.esm\n"
        "TexGen Output  installed 2026-06-28\n")

    def fake_run(argv):
        calls.append(list(argv))
        if argv[0] == "list":
            return 0, list_out
        if argv[0] == "get":
            name = argv[argv.index("--name") + 1]
            safe = name.replace(" ", "-").replace("(", "").replace(")", "")
            return 0, json.dumps({"name": name,
                                  "manifest": f"manifests\\{safe}.txt"})
        return 0, "ok"

    monkeypatch.setattr(lodregen.ledger_bridge, "run", fake_run)
    monkeypatch.setattr(lodregen, "running_processes", lambda names: [])
    return SimpleNamespace(cfg=cfg, sec=sec, preset=preset, data=data,
                           plugins=plugins, ledger_calls=calls)


def write_manifest_fixture(env, name, rels):
    mdir = Path(env.sec["ledger_dir"]) / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    safe = name.replace(" ", "-").replace("(", "").replace(")", "")
    (mdir / f"{safe}.txt").write_bytes(
        b"\xef\xbb\xbf" + ("\r\n".join(rels) + "\r\n").encode("utf-8"))


def _pre_args(**kw):
    d = dict(game="skyrim", no_pgpatcher=False, clean_texgen=False, force=False)
    d.update(kw)
    return SimpleNamespace(**d)


def test_pre_pulls_trio_disables_lines_writes_state(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output",
                           ["meshes\\terrain\\tamriel\\objects\\old.bto"])
    _mk(env.data, "meshes/terrain/tamriel/objects/old.bto")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc in (0, 2)
    runs = lodregen.pending_runs(env.sec["holding_root"])
    assert len(runs) == 1
    run_dir, state = runs[0]
    # trio FILES left Data (from-scratch requirement), held in run_dir\trio
    for name in env.sec["trio"]:
        assert not (env.data / name).exists()
        assert (run_dir / "trio" / name).is_file()
    assert state["pre"]["trio_moved"] == env.sec["trio"]
    # trio lines disabled -- via the real pluginstxt
    from modkit import pluginstxt
    enabled = lodregen.enabled_plugins(pluginstxt.read(env.preset))
    for name in env.sec["trio"]:
        assert name.lower() not in enabled
    # old output quarantined
    assert (run_dir / "quarantine" / "meshes/terrain/tamriel/objects/old.bto").is_file()
    # snapshot recorded and exists
    assert Path(state["pre"]["plugins_snapshot"]).is_file()
    # GUI ritual printed, never-drive stated, TexGen Ignore noted
    assert "NEVER launch" in out
    assert "TexGenx64.exe" in out and "IGNORE" in out
    assert "post --game skyrim --stage texgen" in out


def test_pre_protected_input_survives_polluted_manifest(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output", [
        "meshes\\terrain\\tamriel\\objects\\old.bto",
        "textures\\dyndolod\\lod\\dyndolodtreelod.dds",   # pollution
    ])
    _mk(env.data, "meshes/terrain/tamriel/objects/old.bto")
    tree = _mk(env.data, "textures/dyndolod/lod/dyndolodtreelod.dds")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert tree.is_file()               # THE guard: input never left Data
    assert "PROTECTED" in out
    assert rc in (0, 2)


def test_pre_refuses_when_game_running(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(lodregen, "running_processes",
                        lambda names: ["SkyrimSE.exe"])
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().out
    assert lodregen.pending_runs(env.sec["holding_root"]) == []


def test_pre_refuses_when_game_running_even_with_force(tmp_path, monkeypatch, capsys):
    """The confirmed-running refusal (the `if procs:` block) has no --force
    bypass by design -- unlike the pending-run, missing-tool, and
    GameStateUnknown gates, which all honor --force. This locks that in: a
    future edit that adds `and not args.force` to the confirmed-running
    check would still pass test_pre_refuses_when_game_running (force
    defaults to False there) but must fail here."""
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(lodregen, "running_processes",
                        lambda names: ["SkyrimSE.exe"])
    plugins_before = env.plugins.read_bytes()
    rc = lodregen.cmd_pre(_pre_args(force=True), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSED" in out
    # nothing mutated: no run-state written, trio untouched, Plugins.txt
    # byte-identical
    assert lodregen.pending_runs(env.sec["holding_root"]) == []
    assert lodregen.all_runs(env.sec["holding_root"]) == []
    for name in env.sec["trio"]:
        assert (env.data / name).is_file()
    assert env.plugins.read_bytes() == plugins_before


def test_pre_refuses_when_pending_run_exists(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    lodregen.new_run(env.sec, "skyrim")   # simulate an interrupted run
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert rc == 1
    assert "pending" in capsys.readouterr().out.lower()


def test_pre_texgen_not_cleaned_by_default(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output", [])
    write_manifest_fixture(env, "TexGen Output",
                           ["textures\\lod\\some_old_texgen.dds"])
    old_tex = _mk(env.data, "textures/lod/some_old_texgen.dds")
    lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    assert old_tex.is_file()   # wiki 2026-06-25: never pre-clean TexGen


def test_pre_first_run_tolerates_missing_trio_and_entries(tmp_path, monkeypatch, capsys):
    """Genuine first-ever DynDOLOD setup: the trio plugins have NO Plugins.txt
    line at all (not merely disabled) AND no file in Data yet.
    pluginstxt.disable() raises PluginsTxtError for a plugin with no line --
    cmd_pre must swallow that per-name, not crash mid-bracket, and still
    complete the bracket (snapshot + run-state + GUI sequence) with a WARN."""
    env = make_env(tmp_path, monkeypatch, trio_in_data=False,
                   trio_in_plugins=False, ledger_list_out="")
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 2          # warnings, not failure -- and, critically, no traceback
    assert "Traceback" not in out
    assert "trio file(s) not in Data" in out
    for name in env.sec["trio"]:
        assert name in out

    # bracket still fully opened despite the absent trio
    runs = lodregen.pending_runs(env.sec["holding_root"])
    assert len(runs) == 1
    run_dir, state = runs[0]
    assert state["pre"] is not None
    assert state["pre"]["trio_moved"] == []
    assert sorted(state["pre"]["trio_absent"]) == sorted(env.sec["trio"])
    # Plugins.txt snapshot still taken
    assert Path(state["pre"]["plugins_snapshot"]).is_file()
    # trio lines genuinely absent -- pluginstxt.read() has no trace of them
    from modkit import pluginstxt
    all_names = [ln.lstrip("*").strip().lower() for ln in pluginstxt.read(env.preset)]
    for name in env.sec["trio"]:
        assert name.lower() not in all_names
    # GUI ritual still printed
    assert "NEVER launch" in out
    assert "TexGenx64.exe" in out


# ---- extra: game-state 3-state handling (deploy.py's GameStateUnknown
# contract) -- required by the task brief's "Critical safety semantics"
# but not covered by the plan doc's own Step-1 test list.

def test_pre_warns_and_refuses_when_game_state_unknown(tmp_path, monkeypatch, capsys):
    from modkit import deploy
    env = make_env(tmp_path, monkeypatch)

    def raise_unknown(names):
        raise deploy.GameStateUnknown("tasklist exited 1: access denied")
    monkeypatch.setattr(lodregen, "running_processes", raise_unknown)
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 2
    assert "WARN" in out and "could not verify" in out.lower()
    assert "--force" in out
    # nothing committed -- no bracket opened while state is unverifiable
    assert lodregen.pending_runs(env.sec["holding_root"]) == []


def test_pre_force_proceeds_past_game_state_unknown(tmp_path, monkeypatch, capsys):
    from modkit import deploy
    env = make_env(tmp_path, monkeypatch)
    write_manifest_fixture(env, "DynDOLOD Output", [])

    def raise_unknown(names):
        raise deploy.GameStateUnknown("tasklist exited 1: access denied")
    monkeypatch.setattr(lodregen, "running_processes", raise_unknown)
    rc = lodregen.cmd_pre(_pre_args(force=True), cfg=env.cfg, preset=env.preset)
    capsys.readouterr()
    assert rc in (0, 2)
    # --force pushed past the unverifiable game state and the bracket opened
    assert len(lodregen.pending_runs(env.sec["holding_root"])) == 1


# ---- extra: new_run() FileExistsError on a same-second collision must be
# caught with a friendly message, never a raw traceback (per brief).

def test_pre_new_run_collision_surfaces_friendly_message(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, monkeypatch)
    fixed = lodregen._now()
    monkeypatch.setattr(lodregen, "_now", lambda: fixed)
    # a COMPLETED run already occupies the run_id cmd_pre is about to use --
    # pending_runs() won't flag it (post is set), so cmd_pre reaches
    # new_run() and collides on the same-second directory name.
    run_dir, state = lodregen.new_run(env.sec, "skyrim")
    state["pre"] = {"stamp": "x", "epoch": 1.0}
    state["post"] = {"stamp": "y"}
    lodregen.save_state(run_dir, state)
    rc = lodregen.cmd_pre(_pre_args(), cfg=env.cfg, preset=env.preset)
    out = capsys.readouterr().out
    assert rc == 1
    assert "try again" in out.lower()
    assert "Traceback" not in out


# ---------------------------------------------------------------- Task 5

def test_read_masters_roundtrip(tmp_path):
    p = tmp_path / "DynDOLOD.esp"
    p.write_bytes(make_tes4(["Skyrim.esm", "Update.esm", "JKs Skyrim.esp",
                             "DynDOLOD.esm"]))
    assert lodregen.read_masters(p) == ["Skyrim.esm", "Update.esm",
                                        "JKs Skyrim.esp", "DynDOLOD.esm"]


def test_read_masters_rejects_non_plugin(tmp_path):
    p = tmp_path / "not_a_plugin.esp"
    p.write_bytes(b"MZ\x90\x00 definitely not TES4")
    with pytest.raises(ValueError, match="TES4"):
        lodregen.read_masters(p)


def test_read_masters_handles_xxxx_oversize(tmp_path):
    # An XXXX subrecord promotes the NEXT subrecord's size to 32 bits
    # (DynDOLOD.esm headers carry huge ONAM arrays). MAST after it must
    # still parse.
    onam = b"\x00" * 70000
    subs = (b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 0, 0)
            + b"XXXX" + struct.pack("<H", 4) + struct.pack("<I", len(onam))
            + b"ONAM" + struct.pack("<H", 0) + onam
            + b"MAST" + struct.pack("<H", 11) + b"Skyrim.esm\x00"
            + b"DATA" + struct.pack("<H", 8) + b"\x00" * 8)
    p = tmp_path / "big.esm"
    p.write_bytes(b"TES4" + struct.pack("<IIII", len(subs), 1, 0, 0)
                  + struct.pack("<HH", 44, 0) + subs)
    assert lodregen.read_masters(p) == ["Skyrim.esm"]


def test_master_problems_classifies(tmp_path):
    data = tmp_path / "Data"
    data.mkdir()
    # masters on disk
    (data / "JKs Skyrim.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    (data / "LateMod.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    plugin = data / "Occlusion.esp"
    plugin.write_bytes(make_tes4([
        "Skyrim.esm",          # implicit -> never reported
        "ccBGSSSE037-Curios.esl",   # cc* -> never reported
        "_ResourcePack.esl",   # implicit -> never reported
        "JKs Skyrim.esp",      # on disk + enabled earlier -> fine
        "GoneMod.esp",         # not on disk -> MISSING
        "DisabledMod.esp",     # on disk but not enabled -> NOT ENABLED
        "LateMod.esp",         # enabled AFTER the plugin -> loads AFTER
    ]))
    (data / "DisabledMod.esp").write_bytes(make_tes4(["Skyrim.esm"]))
    enabled = ["jks skyrim.esp", "occlusion.esp", "latemod.esp"]
    probs = lodregen.master_problems(plugin, data, enabled)
    text = "\n".join(probs)
    assert "GoneMod.esp" in text and "MISSING" in text
    assert "DisabledMod.esp" in text and "NOT ENABLED" in text
    assert "LateMod.esp" in text and "AFTER" in text
    assert "Skyrim.esm" not in text
    assert "ccBGSSSE037" not in text
    assert "_ResourcePack" not in text
    assert len(probs) == 3


def test_master_problems_also_present_covers_undeployed_trio(tmp_path):
    # DynDOLOD.esp masters DynDOLOD.esm; during post's verify the esm is
    # still in the OUTPUT dir, not Data -- also_present covers it.
    data = tmp_path / "Data"
    data.mkdir()
    out = tmp_path / "DynDOLOD_Output"
    out.mkdir()
    esp = out / "DynDOLOD.esp"
    esp.write_bytes(make_tes4(["Skyrim.esm", "DynDOLOD.esm"]))
    future = ["dyndolod.esm", "dyndolod.esp", "occlusion.esp"]
    assert lodregen.master_problems(esp, data, future,
                                    also_present=["DynDOLOD.esm"]) == []
    # without also_present it is MISSING
    probs = lodregen.master_problems(esp, data, future)
    assert len(probs) == 1 and "MISSING" in probs[0]


def test_enabled_plugins_strips_stars_and_comments():
    lines = ["# comment", "*Foo.esp", "Disabled.esp", "*Bar.esm", ""]
    assert lodregen.enabled_plugins(lines) == ["foo.esp", "bar.esm"]
