import json

from test_tes4 import make_tes4

from modkit import verify


def deployed_staging(make_staging, run_cli, files, mod):
    sd = make_staging(files, mod=mod)
    run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    return sd


def test_verify_ok_after_clean_deploy(game_env, make_staging, run_cli):
    sd = deployed_staging(make_staging, run_cli,
                          {"Mod.esp": make_tes4(), "interface/mcm.json": b"{}"},
                          mod="Verify Mod")
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "verify OK" in out
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["verified"]
    assert st["vet_results"]["verify"]["ok"] is True


def test_verify_catches_missing_file_no_ext_filter(game_env, make_staging, run_cli):
    sd = deployed_staging(make_staging, run_cli,
                          {"Mod.esp": make_tes4(), "readme.txt": b"docs"},
                          mod="Half Install")
    (game_env / "Data" / "readme.txt").unlink()  # simulate half-install
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 1
    assert "readme.txt" in out and "missing in Data" in out
    st = json.loads((sd / "install.json").read_text(encoding="utf-8"))
    assert st["stages"]["verified"] is None


def test_verify_flags_missing_swap_ref(game_env, make_staging, run_cli):
    ini = b"0x123~NotThere.esp|0x456~AlsoHere.esp\r\n"
    sd = make_staging({"Stuff_SWAP.ini": ini}, mod="Swap Mod")
    run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    code, _ = run_cli("deploy", "--game", "skyrim", "--staging", str(sd), "--force")
    assert code == 0
    (game_env / "Data" / "AlsoHere.esp").write_bytes(make_tes4())
    code, out = run_cli("verify", "--game", "skyrim", "--staging", str(sd))
    assert code == 1
    assert "NotThere.esp" in out and "AlsoHere.esp" not in [
        l.split()[-1] for l in out.splitlines() if l.startswith("BAD")]


def test_swap_refs_parser(tmp_path):
    d = tmp_path / "pay"
    d.mkdir()
    (d / "a_DISTR.ini").write_text(
        "Spell = 0x800~Magic Mod.esp|NONE ; comment with Junk.esp\n", encoding="utf-8")
    (d / "normal.ini").write_text("ref=Ignored.esp\n", encoding="utf-8")
    refs = verify.swap_distr_refs(d)
    assert refs == ["Magic Mod.esp"]
