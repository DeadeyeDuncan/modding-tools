from test_tes4 import make_tes4


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
