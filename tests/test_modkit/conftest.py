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
