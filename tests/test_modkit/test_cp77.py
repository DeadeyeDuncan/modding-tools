import json
from pathlib import Path

import pytest

from modkit import config


@pytest.fixture
def cp_env(tmp_path, monkeypatch):
    root = tmp_path
    game_root = root / "CP77"
    (game_root / "archive" / "pc" / "mod").mkdir(parents=True)
    (game_root / "red4ext" / "plugins").mkdir(parents=True)
    (root / "staging").mkdir()
    (root / "backups").mkdir()
    (root / "manifests").mkdir()
    ledger_json = root / "ledger.json"
    ledger_json.write_text(json.dumps({
        "game": "Cyberpunk 2077", "installDir": str(game_root), "mods": []}),
        encoding="utf-8")
    cfg = {"sevenzip": r"C:\Program Files\7-Zip\7z.exe",
           "downloads": [], "staging_root": str(root / "staging"),
           "games": {"cp77": {
               "data_dir": str(game_root), "plugins_txt": None,
               "process_names": ["FakeCyber.exe"], "runtime": None,
               "backups_dir": str(root / "backups"),
               "manifests_dir": str(root / "manifests"),
               "ledger": str(ledger_json)}}}
    (root / "modkit.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("MODKIT_CONFIG", str(root / "modkit.json"))
    return root


def cp_staging(cp_env, files, mod="CP Mod"):
    from modkit import state as mstate
    preset = config.game(config.load(), "cp77")
    sd = Path(preset.STAGING_ROOT) / f"20260711-000000-{mstate.slug(mod)}"
    (sd / "payload").mkdir(parents=True)
    for rel, content in files.items():
        f = sd / "payload" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
    st = mstate.InstallState.create(str(sd), mod=mod, game="cp77",
                                    archive=r"C:\dl\cp-1-1-0.7z",
                                    applicable=preset.applicability(str(sd / "payload")))
    st.stamp("intake")
    st.stamp("staged")
    return sd


def test_cp77_preset_loads(cp_env):
    p = config.game(config.load(), "cp77")
    assert p.NAME == "cp77" and p.PLUGINS_TXT is None
    assert p.DEPLOY_DIRS == ("archive", "red4ext", "r6", "bin")
    assert p.applicability(str(cp_env)) == {"fomod": False, "dllvet": False, "esp": False}


def test_cp77_deploy_verify_roundtrip(cp_env, run_cli):
    sd = cp_staging(cp_env, {"archive/pc/mod/zz_cool.archive": b"ARC"})
    code, out = run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    assert code == 0
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd))
    assert code == 0
    assert (cp_env / "CP77" / "archive" / "pc" / "mod" / "zz_cool.archive").is_file()
    from modkit import ledger_bridge
    lcode, lout = ledger_bridge.run(["get", "--name", "CP Mod",
                                     "--ledger", str(cp_env / "ledger.json")])
    assert lcode == 0 and "plugin" not in json.loads(lout)
    code, out = run_cli("verify", "--game", "cp77", "--staging", str(sd))
    assert code == 0


def test_cp77_deploy_refuses_stray_top_level(cp_env, run_cli):
    sd = cp_staging(cp_env, {"readme.txt": b"docs",
                             "archive/pc/mod/a.archive": b"A"}, mod="Stray Mod")
    run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd))
    assert code == 2
    assert "stray top-level" in out and "readme.txt" in out
    code, out = run_cli("deploy", "--game", "cp77", "--staging", str(sd), "--force")
    assert code == 0


def test_cp77_conflicts_reports_archive_order(cp_env, run_cli):
    (cp_env / "CP77" / "archive" / "pc" / "mod" / "aa_base.archive").write_bytes(b"A")
    sd = cp_staging(cp_env, {"archive/pc/mod/zz_new.archive": b"Z"}, mod="Order Mod")
    code, out = run_cli("conflicts", "--game", "cp77", "--staging", str(sd))
    assert "ORDER" in out and "zz_new.archive" in out
