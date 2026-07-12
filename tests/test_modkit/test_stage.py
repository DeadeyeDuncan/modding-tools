import json
import zipfile
from pathlib import Path

from conftest import needs_7z


def make_archive(game_env, fname, members):
    p = game_env / "downloads" / fname
    with zipfile.ZipFile(p, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return p


@needs_7z
def test_stage_creates_staging_with_state(game_env, run_cli):
    arc = make_archive(game_env, "Cool Mod-42-1-2.zip", {
        "Cool.esp": "TES4xxxx",
        "SKSE/Plugins/cool.dll": "MZxxxx",
        "fomod/ModuleConfig.xml": "<config/>",
        "meshes/c.nif": "NIF",
    })
    code, out = run_cli("stage", str(arc), "--game", "skyrim")
    assert code == 0
    staged_line = [l for l in out.splitlines() if l.startswith("staged: ")][0]
    staging = Path(staged_line.split("staged: ", 1)[1])
    assert staging.parent == game_env / "staging" / "skyrim"
    assert staging.name.endswith("-Cool-Mod")
    st = json.loads((staging / "install.json").read_text(encoding="utf-8"))
    assert st["mod"] == "Cool Mod" and st["nexusId"] == 42 and st["version"] == "1.2"
    assert st["applicable"] == {"fomod": True, "dllvet": True, "esp": True}
    assert st["stages"]["intake"] and st["stages"]["staged"]
    assert st["stages"]["deployed"] is None
    assert (staging / "payload" / "meshes" / "c.nif").is_file()


@needs_7z
def test_stage_name_override_and_plain_archive(game_env, run_cli):
    arc = make_archive(game_env, "weird-name.zip", {"textures/t.dds": "DDS"})
    code, out = run_cli("stage", str(arc), "--game", "skyrim", "--name", "Weird Mod")
    assert code == 0
    staging = Path(out.split("staged: ", 1)[1].splitlines()[0])
    st = json.loads((staging / "install.json").read_text(encoding="utf-8"))
    assert st["mod"] == "Weird Mod" and st["nexusId"] is None
    assert st["applicable"] == {"fomod": False, "dllvet": False, "esp": False}


def test_stage_missing_archive_errors(game_env, run_cli):
    code, out = run_cli("stage", str(game_env / "nope.7z"), "--game", "skyrim")
    assert code == 1
    assert "no such archive" in out
