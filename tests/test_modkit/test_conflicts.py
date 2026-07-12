import json

from modkit import conflicts


def test_sweep_names_losing_mod(game_env, preset, make_staging, run_cli):
    (game_env / "Data" / "textures").mkdir()
    (game_env / "Data" / "textures" / "a.dds").write_bytes(b"OLD")
    (game_env / "manifests" / "Old-Mod.txt").write_bytes(
        b"\xef\xbb\xbftextures\\a.dds\r\n")
    sd = make_staging({"textures/a.dds": b"NEW", "textures/b.dds": b"NEW2"},
                      mod="Overlap Mod")
    hits = conflicts.sweep(preset, sd / "payload")
    assert len(hits) == 1
    assert hits[0]["path"].replace("/", "\\") == "textures\\a.dds"
    assert hits[0]["owner"] == "Old-Mod"
    code, out = run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "OVERLAP" in out and "Old-Mod" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["conflicts"]
    assert st.data["vet_results"]["conflicts"]["overlaps"] == 1


def test_sweep_clean_exit_zero(game_env, preset, make_staging, run_cli):
    sd = make_staging({"meshes/new.nif": b"NIF"}, mod="Clean Mod")
    code, out = run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "no file overlaps" in out


def test_manifest_owner_tolerates_data_prefix_and_comments(game_env):
    (game_env / "manifests" / "Legacy.txt").write_bytes(
        b"\xef\xbb\xbf# comment\r\nData\\meshes\\x.nif\r\n")
    owners = conflicts.manifest_owners(game_env / "manifests")
    assert owners["meshes\\x.nif"] == "Legacy"


def test_conflicts_unwraps_data_payload_wrapper(game_env, preset, make_staging, run_cli):
    """Archives packaged with a single top-level Data\\ folder (common Nexus
    layout) must be unwrapped the same way deploy/verify do - otherwise the
    sweep builds paths like Data\\textures\\... that never exist under the
    payload root and reports a false-clean while deploy really overwrites
    the file."""
    (game_env / "Data" / "textures").mkdir()
    (game_env / "Data" / "textures" / "shared.dds").write_bytes(b"OLD")
    sd = make_staging({"Data/textures/shared.dds": b"NEW"}, mod="Wrapped Mod")
    code, out = run_cli("conflicts", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "OVERLAP" in out
    assert "shared.dds" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["vet_results"]["conflicts"]["overlaps"] == 1
    assert st.data["vet_results"]["conflicts"]["paths"][0].replace("/", "\\") == \
        "textures\\shared.dds"


def test_conflicts_hard_errors_on_null_data_dir(game_env, run_cli):
    """conflicts must refuse (exit 1) for a preset with no data_dir configured
    (e.g. kenshi), not silently report a false "no overlaps" all-clear."""
    cfg_path = game_env / "modkit.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["games"]["kenshi"] = {
        "data_dir": None, "plugins_txt": None,
        "process_names": ["kenshi_x64.exe"], "runtime": None,
        "backups_dir": str(game_env / "kenshi-backups"),
    }
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    code, out = run_cli("conflicts", "--game", "kenshi")
    assert code == 1
    assert "no data_dir" in out and "unsupported" in out
    assert "no file overlaps" not in out
    assert "OVERLAP" not in out
