import zipfile
from pathlib import Path

from conftest import needs_7z

from modkit.cli import parse_nexus_filename


def dl_zip(game_env, fname, members):
    p = game_env / "downloads" / fname
    with zipfile.ZipFile(p, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return p


def test_parse_nexus_filename():
    m = parse_nexus_filename("Simple Dual Sheath-50049-1-5-2-1170.7z")
    assert m == {"name": "Simple Dual Sheath", "modid": 50049, "version": "1.5.2.1170"}
    m = parse_nexus_filename("Some Mod-123-2-0-1712345678.zip")
    assert m["modid"] == 123 and m["version"] == "2.0"
    assert parse_nexus_filename("random-archive.zip") is None


def test_intake_flags_zero_byte(game_env, run_cli):
    (game_env / "downloads" / "Broken Mod-99-1-0.7z").write_bytes(b"")
    code, out = run_cli("intake", "--game", "skyrim")
    assert code == 2
    assert "0-byte" in out


@needs_7z
def test_intake_wrong_game_gate(game_env, run_cli):
    dl_zip(game_env, "Totally Skyrim-777-1-0.zip",
           {"Data/F4SE/Plugins/thing.dll": "MZ", "Data/Mod.esp": "TES4"})
    code, out = run_cli("intake", "--game", "skyrim")
    assert code == 2
    assert "fallout4" in out and "wrong-game" in out


@needs_7z
def test_intake_already_installed_flags_warn(game_env, run_cli):
    arc = dl_zip(game_env, "Already Installed Mod-123-1-0.zip", {"Mod.esp": "TES4"})
    code, out = run_cli("intake", str(arc), "--game", "skyrim")
    assert code == 2
    assert "already in ledger" in out


@needs_7z
def test_intake_clean_single_path_exits_zero(game_env, run_cli):
    fresh = dl_zip(game_env, "Fresh Mod-456-2-0.zip", {"Fresh.esp": "TES4"})
    code, out = run_cli("intake", str(fresh), "--game", "skyrim")
    assert code == 0
    assert "Fresh Mod" in out and "skyrim" in out
