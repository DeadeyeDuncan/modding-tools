import json
from pathlib import Path

from test_tes4 import make_tes4

from modkit import ledger_bridge


def vetted_staging(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    return sd


def test_deploy_refuses_pending_vets(game_env, make_staging, run_cli):
    sd = make_staging({"Mod.esp": make_tes4()}, mod="Unvetted Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "REFUSED" in out and "esp" in out
    assert not (game_env / "Data" / "Mod.esp").exists()


def test_deploy_clean_copies_enables_and_records(game_env, make_staging, run_cli):
    sd = vetted_staging(make_staging, run_cli,
                        {"Mod.esp": make_tes4(), "textures/t.dds": b"DDS"},
                        mod="Deploy Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert (game_env / "Data" / "Mod.esp").is_file()
    assert (game_env / "Data" / "textures" / "t.dds").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*Mod.esp" in plines
    assert plines.index("*Mod.esp") < plines.index("*DynDOLOD.esm")
    lcode, lout = ledger_bridge.run(["get", "--name", "Deploy Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
    entry = json.loads(lout)
    assert entry["fileCount"] == 2 and entry["plugin"] == "Mod.esp"
    assert (game_env / "manifests" / "Deploy-Mod.txt").is_file()
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["deployed"] and st["stages"]["recorded"]
    assert "textures\\t.dds" in st["files"]


def test_deploy_force_bypasses_vet_gate(game_env, make_staging, run_cli):
    sd = make_staging({"Forced.esp": make_tes4()}, mod="Forced Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 0
    assert (game_env / "Data" / "Forced.esp").is_file()


def test_deploy_hard_refuses_running_game(game_env, make_staging, run_cli, monkeypatch):
    from modkit import deploy
    monkeypatch.setattr(deploy, "game_running", lambda preset: True)
    sd = make_staging({"X.esp": make_tes4()}, mod="Running Mod")
    # --force is passed and MUST NOT override: confirmed-running is the one
    # un-forceable gate. If a future regression makes this forceable, this
    # assertion (exit 1, not 0/2) is what catches it.
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 1
    assert "game process running" in out
    assert not (game_env / "Data" / "X.esp").exists()


def test_deploy_refuses_when_game_state_unknown(game_env, make_staging, run_cli, monkeypatch):
    """tasklist itself fails to launch -> game state is unverifiable, which is
    DISTINCT from confirmed-not-running. Must warn + refuse (exit 2) and must
    NOT proceed, unlike a plain OSError-swallowed-as-False bug would."""
    from modkit import deploy

    def boom(*a, **k):
        raise OSError("tasklist.exe not found")

    monkeypatch.setattr(deploy.subprocess, "run", boom)
    sd = make_staging({"Unverified.esp": make_tes4()}, mod="Unverified Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "could not verify the game is closed" in out
    assert "--force" in out
    # nothing written: no robocopy, no Plugins.txt change, no ledger add
    assert not (game_env / "Data" / "Unverified.esp").exists()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig")
    assert "Unverified.esp" not in plines
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert not st["stages"].get("deployed")


def test_deploy_force_bypasses_unknown_game_state(game_env, make_staging, run_cli, monkeypatch):
    """--force DOES override the unverifiable-state gate (unlike the
    confirmed-running gate above) - deploy proceeds fully."""
    from modkit import deploy
    real_run = deploy.subprocess.run

    def flaky_tasklist(cmd, *a, **k):
        if cmd and cmd[0] == "tasklist":
            raise OSError("tasklist.exe not found")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(deploy.subprocess, "run", flaky_tasklist)
    sd = make_staging({"ForcedUnknown.esp": make_tes4()}, mod="Forced Unknown Mod")
    code, out = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 0
    assert (game_env / "Data" / "ForcedUnknown.esp").is_file()
    plines = (game_env / "Plugins.txt").read_bytes().decode("utf-8-sig").splitlines()
    assert "*ForcedUnknown.esp" in plines
    lcode, lout = ledger_bridge.run(["get", "--name", "Forced Unknown Mod",
                                     "--ledger", str(game_env / "ledger.json")])
    assert lcode == 0
