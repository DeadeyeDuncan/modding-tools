import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # C:\Modding\tools


@pytest.fixture
def game_env(tmp_path, monkeypatch):
    """Synthetic machine: fake Data\\, Plugins.txt (BOM+CRLF), staging, backups,
    manifests, downloads — and a modkit.json pointing at all of it.
    No test ever touches real game dirs."""
    root = tmp_path
    (root / "Data").mkdir()
    (root / "staging").mkdir()
    (root / "backups").mkdir()
    (root / "manifests").mkdir()
    (root / "downloads").mkdir()
    plugins = root / "Plugins.txt"
    plugins.write_bytes(
        b"\xef\xbb\xbf"
        b"*Unofficial Skyrim Special Edition Patch.esp\r\n"
        b"*SkyUI_SE.esp\r\n"
        b"DisabledMod.esp\r\n"
        b"*DynDOLOD.esm\r\n"
        b"*DynDOLOD.esp\r\n"
        b"*Occlusion.esp\r\n")
    ledger_json = root / "ledger.json"
    ledger_json.write_text(json.dumps({
        "game": "Skyrim Special Edition",
        "dataDir": str(root / "Data"),
        "pluginsTxt": str(plugins),
        "mods": [{"name": "Already Installed Mod", "installed": "2026-07-01"}],
    }), encoding="utf-8")
    cfg = {
        "sevenzip": r"C:\Program Files\7-Zip\7z.exe",
        "downloads": [str(root / "downloads")],
        "staging_root": str(root / "staging"),
        "games": {
            "skyrim": {
                "data_dir": str(root / "Data"),
                "plugins_txt": str(plugins),
                "process_names": ["FakeGame.exe"],
                "runtime": "1.6.1170",
                "backups_dir": str(root / "backups"),
                "manifests_dir": str(root / "manifests"),
                "vortex_downloads": None,
                "ledger": str(ledger_json),
            }
        },
    }
    cfg_path = root / "modkit.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("MODKIT_CONFIG", str(cfg_path))
    return root


@pytest.fixture
def preset(game_env):
    from modkit import config
    return config.game(config.load(), "skyrim")


SEVENZIP = Path(r"C:\Program Files\7-Zip\7z.exe")
needs_7z = pytest.mark.skipif(not SEVENZIP.is_file(), reason="7z.exe not installed")


@pytest.fixture
def run_cli(capsys):
    from modkit import cli

    def _run(*argv):
        code = cli.main(list(argv))
        return code, capsys.readouterr().out
    return _run


@pytest.fixture
def make_staging(preset):
    from modkit import state as mstate

    def _make(files, mod="Test Mod", applicable=None, nexus_id=77, version="1.0"):
        root = Path(preset.STAGING_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        sd = root / f"20260711-000000-{mstate.slug(mod)}"
        sd.mkdir()
        pay = sd / "payload"
        pay.mkdir()
        for rel, content in files.items():
            f = pay / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content if isinstance(content, bytes) else content.encode())
        st = mstate.InstallState.create(
            str(sd), mod=mod, game="skyrim", archive=r"C:\dl\x-77-1-0.7z",
            nexus_id=nexus_id, version=version,
            applicable=applicable if applicable is not None
            else preset.applicability(str(pay)))
        st.stamp("intake")
        st.stamp("staged")
        return sd
    return _make
