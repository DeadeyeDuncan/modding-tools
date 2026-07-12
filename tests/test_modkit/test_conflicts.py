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
