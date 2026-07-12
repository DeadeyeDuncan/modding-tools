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


@needs_7z
def test_stage_verify_failure_keeps_staging_without_state(game_env, run_cli, monkeypatch):
    """A real archive that extracts fine, but whose listing is poisoned with a
    phantom entry the real extraction can never produce, must fail
    verify_extraction genuinely: exit 1, staging dir kept with its payload,
    but no install.json written anywhere under it."""
    from modkit import archive as arch

    arc = make_archive(game_env, "Broken Mod-99-1-0.zip", {
        "Broken.esp": "TES4xxxx",
        "textures/b.dds": "DDS",
    })

    real_listing = arch.listing

    def fake_listing(sevenzip, archive_path):
        entries = real_listing(sevenzip, archive_path)
        entries.append({"path": "phantom/not-really-extracted.dll",
                        "size": 123, "is_dir": False})
        return entries

    monkeypatch.setattr(arch, "listing", fake_listing)

    code, out = run_cli("stage", str(arc), "--game", "skyrim")

    assert code == 1
    assert "BAD missing after extract: phantom/not-really-extracted.dll" in out
    assert "ERROR: extraction verify failed (1 problems)" in out
    assert "staging kept for inspection" in out

    staging_root = game_env / "staging" / "skyrim"
    staging_dirs = list(staging_root.iterdir())
    assert len(staging_dirs) == 1
    staging = staging_dirs[0]
    assert staging.name.endswith("-Broken-Mod")
    assert (staging / "payload" / "Broken.esp").is_file()
    assert (staging / "payload" / "textures" / "b.dds").is_file()
    assert not (staging / "install.json").exists()
    assert not list(staging_root.rglob("install.json"))
