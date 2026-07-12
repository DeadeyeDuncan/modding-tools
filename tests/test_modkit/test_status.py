import json
from pathlib import Path

from test_tes4 import make_tes4


def test_status_missing_staging_root_no_crash_no_create(game_env, preset, run_cli):
    """STAGING_ROOT may not exist on disk (ground-truth constraint) - status must
    report cleanly and stay read-only, never creating the dir it's reporting on."""
    root = Path(preset.STAGING_ROOT)
    assert not root.exists(), "test setup assumption: staging root not pre-created"
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "no staging dirs" in out
    assert not root.exists(), "status must never create the staging root"


def test_status_skips_malformed_install_json(game_env, make_staging, preset, run_cli):
    """One well-formed install.json + one valid-JSON-but-missing-'stages' install.json:
    status must report the good one and skip the bad one with a warning, not crash."""
    make_staging({"Mod.esp": make_tes4()}, mod="Good Mod")
    bad_dir = Path(preset.STAGING_ROOT) / "20260711-010000-bad-mod"
    bad_dir.mkdir()
    (bad_dir / "install.json").write_text(json.dumps({
        "mod": "Bad Mod",
        "game": "skyrim",
        "archive": r"C:\dl\bad.7z",
        "nexusId": None,
        "version": None,
        "applicable": {"fomod": False, "dllvet": False, "esp": False},
        # deliberately missing "stages" (and "vet_results")
    }), encoding="utf-8")
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "Good Mod" in out
    assert "bad-mod" in out and "unreadable install.json (skipped)" in out
    assert "2 staging dir(s)" in out


def test_status_lists_incomplete_with_pending_vets(game_env, make_staging, run_cli):
    make_staging({"Mod.esp": make_tes4()}, mod="Stuck Mod")
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "INCOMPLETE" in out and "Stuck Mod" in out
    assert "pending vets" in out and "esp" in out
    assert "never verified" in out
    assert "1 incomplete" in out


def test_status_complete_only_shown_with_all(game_env, make_staging, run_cli):
    sd = make_staging({"Done.esp": make_tes4()}, mod="Done Mod")
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    code, out = run_cli("status", "--game", "skyrim")
    assert code == 0
    assert "0 incomplete" in out and "Done Mod" not in out
    code, out = run_cli("status", "--game", "skyrim", "--all")
    assert "Done Mod" in out and "verify OK" in out


def test_help_lists_all_commands_and_pipeline():
    from modkit import cli
    text = cli.build_parser().format_help()
    for cmd in ("intake", "stage", "fomod", "dllvet", "esp", "conflicts",
                "deploy", "verify", "remove", "plugins", "status"):
        assert cmd in text
    assert "pipeline" in text
