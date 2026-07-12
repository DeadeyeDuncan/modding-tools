from pathlib import Path

import pytest

from modkit import config


def test_load_reads_env_config(game_env):
    cfg = config.load()
    assert cfg["games"]["skyrim"]["runtime"] == "1.6.1170"


def test_load_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("MODKIT_CONFIG", str(tmp_path / "nope.json"))
    with pytest.raises(config.ConfigError):
        config.load()


def test_game_preset_attributes_from_config(game_env):
    p = config.game(config.load(), "skyrim")
    assert Path(p.DATA_DIR) == game_env / "Data"
    assert Path(p.PLUGINS_TXT) == game_env / "Plugins.txt"
    assert p.PROCESS_NAMES == ["FakeGame.exe"]
    assert p.RUNTIME == "1.6.1170"
    assert Path(p.STAGING_ROOT) == game_env / "staging" / "skyrim"
    assert Path(p.BACKUPS_DIR) == game_env / "backups"
    assert p.NAME == "skyrim"
    assert Path(p.SEVENZIP).name == "7z.exe"


def test_game_unconfigured_raises(game_env):
    with pytest.raises(config.ConfigError):
        config.game(config.load(), "rdr2")


def test_generic_preset_for_moduleless_game(game_env, tmp_path):
    cfg = config.load()
    cfg["games"]["kenshi"] = {"data_dir": None, "plugins_txt": None,
                              "process_names": ["kenshi_x64.exe"], "runtime": None,
                              "backups_dir": str(tmp_path / "kb")}
    p = config.game(cfg, "kenshi")
    assert p.NAME == "kenshi"
    assert p.DATA_DIR is None
    assert p.applicability(str(tmp_path)) == {"fomod": False, "dllvet": False, "esp": False}


def test_skyrim_applicability(preset, tmp_path):
    pay = tmp_path / "payload"
    (pay / "fomod").mkdir(parents=True)
    (pay / "fomod" / "ModuleConfig.xml").write_text("<config/>")
    (pay / "SKSE" / "Plugins").mkdir(parents=True)
    (pay / "SKSE" / "Plugins" / "thing.dll").write_bytes(b"MZ")
    (pay / "Mod.esp").write_bytes(b"TES4")
    assert preset.applicability(str(pay)) == {"fomod": True, "dllvet": True, "esp": True}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert preset.applicability(str(empty)) == {"fomod": False, "dllvet": False, "esp": False}


def test_guess_game_fallout_outranks_skyrim():
    from modkit import games
    assert games.guess_game(["Data/F4SE/Plugins/x.dll", "Data/Mod.esp"]) == "fallout4"
    assert games.guess_game(["textures/a.ba2"]) == "fallout4"
    assert games.guess_game(["SKSE/Plugins/x.dll", "Mod.esp"]) == "skyrim"
    assert games.guess_game(["archive/pc/mod/cool.archive"]) == "cp77"
    assert games.guess_game(["readme.txt"]) is None
