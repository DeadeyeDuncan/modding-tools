import json

from test_tes4 import make_tes4

from modkit import ledger_bridge


def deploy_mod(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    return sd


def test_remove_quarantines_disables_and_records(game_env, make_staging, run_cli):
    deploy_mod(make_staging, run_cli,
               {"Gone.esp": make_tes4(), "textures/g.dds": b"D"}, mod="Gone Mod")
    (game_env / "Data" / "textures" / "g.dds").unlink()  # pre-existing drift: absent file
    code, out = run_cli("remove", "Gone Mod", "--game", "skyrim",
                        "--reason", "testing removal")
    assert code == 0
    assert not (game_env / "Data" / "Gone.esp").exists()
    qdirs = list((game_env / "backups").glob("removed-Gone-Mod-*"))
    assert len(qdirs) == 1 and (qdirs[0] / "Gone.esp").is_file()
    assert "already absent" in out and "textures\\g.dds" in out
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "Gone.esp" in plines and "*Gone.esp" not in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Gone Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    entry = json.loads(lout)
    assert entry["removedReason"] == "testing removal"
    assert "removed-Gone-Mod-" in entry["removedTo"]


def test_remove_refuses_when_other_plugin_masters_ours(game_env, make_staging, run_cli):
    deploy_mod(make_staging, run_cli, {"Master.esm": make_tes4(esm=True)},
               mod="Master Mod")
    (game_env / "Data" / "Dependent.esp").write_bytes(
        make_tes4(masters=("Master.esm",)))
    with open(game_env / "Plugins.txt", "ab") as f:
        f.write(b"*Dependent.esp\r\n")
    code, out = run_cli("remove", "Master Mod", "--game", "skyrim",
                        "--reason", "trying anyway")
    assert code == 2
    assert "Dependent.esp" in out and "REFUSED" in out
    assert (game_env / "Data" / "Master.esm").is_file()  # nothing moved
    code, out = run_cli("remove", "Master Mod", "--game", "skyrim",
                        "--reason", "forced", "--force")
    assert code == 0
    assert not (game_env / "Data" / "Master.esm").exists()


def test_remove_unknown_mod_errors(game_env, run_cli):
    code, out = run_cli("remove", "No Such Mod", "--game", "skyrim",
                        "--reason", "x")
    assert code == 1


def test_remove_refuses_running_game(game_env, make_staging, run_cli, monkeypatch):
    from modkit import deploy
    deploy_mod(make_staging, run_cli, {"Running.esp": make_tes4()}, mod="Running Mod")
    monkeypatch.setattr(deploy, "game_running", lambda preset: True)
    code, out = run_cli("remove", "Running Mod", "--game", "skyrim",
                        "--reason", "x")
    assert code == 1
    assert "game process running" in out
    # nothing moved, nothing disabled, ledger untouched
    assert (game_env / "Data" / "Running.esp").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*Running.esp" in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Running Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
    assert "removed" not in json.loads(lout)
    # confirmed-running has NO --force override, unlike the GameStateUnknown gate
    code, out = run_cli("remove", "Running Mod", "--game", "skyrim",
                        "--reason", "x", "--force")
    assert code == 1
    assert "game process running" in out
    assert (game_env / "Data" / "Running.esp").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*Running.esp" in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Running Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
    assert "removed" not in json.loads(lout)


def test_remove_refuses_on_unknown_game_state(game_env, make_staging, run_cli,
                                               monkeypatch):
    from modkit import deploy
    deploy_mod(make_staging, run_cli, {"Unknown.esp": make_tes4()},
               mod="Unknown State Mod")

    def _raise(preset):
        raise deploy.GameStateUnknown("tasklist exited 1: access denied")
    monkeypatch.setattr(deploy, "game_running", _raise)

    code, out = run_cli("remove", "Unknown State Mod", "--game", "skyrim",
                        "--reason", "x")
    assert code == 2
    assert "could not verify the game is closed" in out
    # nothing moved, nothing disabled, ledger untouched
    assert (game_env / "Data" / "Unknown.esp").is_file()
    assert not list((game_env / "backups").glob("removed-Unknown-State-Mod-*"))
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*Unknown.esp" in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Unknown State Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
    assert "removed" not in json.loads(lout)

    code, out = run_cli("remove", "Unknown State Mod", "--game", "skyrim",
                        "--reason", "forced through", "--force")
    assert code == 0
    assert not (game_env / "Data" / "Unknown.esp").exists()
    qdirs = list((game_env / "backups").glob("removed-Unknown-State-Mod-*"))
    assert len(qdirs) == 1 and (qdirs[0] / "Unknown.esp").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "Unknown.esp" in plines and "*Unknown.esp" not in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Unknown State Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    entry = json.loads(lout)
    assert entry.get("removedReason") == "forced through"


def test_remove_refuses_on_unparseable_dependent_header(game_env, make_staging, run_cli):
    deploy_mod(make_staging, run_cli, {"Master.esm": make_tes4(esm=True)},
               mod="Master Mod Two")
    # deliberately-corrupt other-enabled plugin: fails tes4.parse_header (bad magic)
    (game_env / "Data" / "Corrupt.esp").write_bytes(b"JUNKJUNKJUNKTRUNCATED")
    with open(game_env / "Plugins.txt", "ab") as f:
        f.write(b"*Corrupt.esp\r\n")
    code, out = run_cli("remove", "Master Mod Two", "--game", "skyrim",
                        "--reason", "trying anyway")
    assert code == 2
    assert "Corrupt.esp" in out and "could not verify" in out
    assert (game_env / "Data" / "Master.esm").is_file()  # nothing moved
    assert not list((game_env / "backups").glob("removed-Master-Mod-Two-*"))
    code, out = run_cli("remove", "Master Mod Two", "--game", "skyrim",
                        "--reason", "forced", "--force")
    assert code == 0
    assert not (game_env / "Data" / "Master.esm").exists()
    qdirs = list((game_env / "backups").glob("removed-Master-Mod-Two-*"))
    assert len(qdirs) == 1 and (qdirs[0] / "Master.esm").is_file()
