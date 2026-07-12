import json
from pathlib import Path

import pytest

from modkit import state


def make_state(tmp_path, applicable=None):
    sd = tmp_path / "20260711-120000-test-mod"
    sd.mkdir()
    return state.InstallState.create(
        str(sd), mod="Test Mod", game="skyrim", archive=r"C:\dl\Test Mod-1-1-0.7z",
        nexus_id=1, version="1.0", applicable=applicable)


def test_create_writes_design_shape_and_load_roundtrips(tmp_path):
    st = make_state(tmp_path, {"fomod": False, "dllvet": True, "esp": True})
    raw = json.loads((st.staging_dir / "install.json").read_text(encoding="utf-8"))
    assert raw["mod"] == "Test Mod" and raw["game"] == "skyrim"
    assert set(raw["stages"]) == set(state.STAGES)
    assert all(v is None for v in raw["stages"].values())
    assert raw["applicable"] == {"fomod": False, "dllvet": True, "esp": True}
    assert raw["vet_results"] == {} and raw["files"] == []
    st2 = state.InstallState.load(str(st.staging_dir))
    assert st2.data == st.data


def test_stamp_sets_iso_timestamp_and_persists(tmp_path):
    st = make_state(tmp_path)
    st.stamp("staged")
    reloaded = state.InstallState.load(str(st.staging_dir))
    ts = reloaded.data["stages"]["staged"]
    assert ts and ts[:4].isdigit() and "T" in ts
    with pytest.raises(state.StateError):
        st.stamp("nonsense")


def test_missing_applicable_conflicts_always(tmp_path):
    st = make_state(tmp_path, {"fomod": False, "dllvet": True, "esp": True})
    assert st.missing_applicable() == ["dllvet", "esp", "conflicts"]
    st.stamp("dllvet")
    st.stamp("conflicts")
    assert st.missing_applicable() == ["esp"]
    st.stamp("esp")
    assert st.missing_applicable() == []


def test_atomic_write_leaves_no_temp(tmp_path):
    st = make_state(tmp_path)
    st.stamp("intake")
    leftovers = [p.name for p in st.staging_dir.iterdir() if ".tmp-" in p.name]
    assert leftovers == []


def test_load_missing_raises(tmp_path):
    with pytest.raises(state.StateError):
        state.InstallState.load(str(tmp_path))


def test_payload_root_prefers_payload_final(tmp_path):
    (tmp_path / "payload").mkdir()
    assert state.payload_root(tmp_path).name == "payload"
    (tmp_path / "payload_final").mkdir()
    assert state.payload_root(tmp_path).name == "payload_final"


def test_latest_staging_and_slug(tmp_path, preset):
    root = Path(preset.STAGING_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("20260701-010101-old-mod", "20260711-090909-new-mod"):
        d = root / name
        d.mkdir()
        (d / "install.json").write_text("{}", encoding="utf-8")
    (root / "not-a-staging").mkdir()
    assert state.latest_staging(preset).name == "20260711-090909-new-mod"
    assert state.slug("Simple Dual Sheath (v1.5) [SE]") == "Simple-Dual-Sheath-v1.5-SE"
