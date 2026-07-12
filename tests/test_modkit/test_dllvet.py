import pytest

from pebuild import build_dll, skse_version_blob

from modkit import peparse


def test_encode_decode_runtime():
    v = peparse.encode_runtime("1.6.1170")
    assert v == (1 << 24) | (6 << 16) | (1170 << 4)
    assert peparse.decode_runtime(v) == "1.6.1170"


def test_pefile_machine_and_exports(tmp_path):
    p = tmp_path / "a.dll"
    p.write_bytes(build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])}))
    pe = peparse.PEFile(p)
    assert pe.machine == "x64"
    assert "SKSEPlugin_Version" in pe.exports()
    vd = peparse.skse_version_data(pe)
    assert vd["compatible"] == [peparse.encode_runtime("1.6.1170")]
    assert vd["address_independent"] is False


def test_pefile_rejects_garbage(tmp_path):
    p = tmp_path / "junk.dll"
    p.write_bytes(b"not a pe at all")
    with pytest.raises(peparse.PeError):
        peparse.PEFile(p)


def test_dllvet_ok_wrong_runtime_and_research(game_env, make_staging, run_cli):
    good = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])})
    bad = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.5.97")])})
    old = build_dll({"SKSEPlugin_Query": b"\x00" * 8})
    sd = make_staging({
        "SKSE/Plugins/good.dll": good,
        "SKSE/Plugins/bad.dll": bad,
        "SKSE/Plugins/old.dll": old,
    }, mod="Dll Mix")
    code, out = run_cli("dllvet", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "WRONG_RUNTIME" in out and "bad.dll" in out
    assert "RESEARCH" in out and "old.dll" in out
    assert "OK" in out and "good.dll" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["dllvet"]
    verdicts = {k.split("\\")[-1].split("/")[-1]: v["verdict"]
                for k, v in st.data["vet_results"]["dllvet"].items()}
    assert verdicts == {"good.dll": "OK", "bad.dll": "WRONG_RUNTIME",
                        "old.dll": "RESEARCH"}


def test_dllvet_address_independent_is_ok(game_env, make_staging, run_cli):
    dll = build_dll({"SKSEPlugin_Version": skse_version_blob(independent=1)},
                    extra=b"versionlib-1-6-1170-0.bin\x00")
    sd = make_staging({"SKSE/Plugins/ng.dll": dll}, mod="NG Mod")
    code, out = run_cli("dllvet", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "Address Library" in out


def test_dllvet_truncated_dll_is_unparseable_not_a_crash(game_env, make_staging, run_cli):
    """A payload with one healthy DLL and one DLL truncated mid-COFF-header must
    not crash the whole dllvet batch - the truncated file gets a per-file
    UNPARSEABLE verdict and the healthy one still gets vetted normally."""
    good = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])})
    victim = build_dll({"SKSEPlugin_Version": skse_version_blob(
        compatible=[peparse.encode_runtime("1.6.1170")])})
    # PE signature lives at offset 0x80 (dos header's e_lfanew), COFF header
    # starts right after it at 0x84. Cut 2 bytes into the COFF header so the
    # signature check passes but struct.unpack_from("<HH", ..., pe_off + 4)
    # would previously blow up with a raw struct.error.
    truncated = victim[:0x86]
    assert len(truncated) < len(victim)
    sd = make_staging({
        "SKSE/Plugins/good.dll": good,
        "SKSE/Plugins/truncated.dll": truncated,
    }, mod="Truncated Mix")
    code, out = run_cli("dllvet", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "OK" in out and "good.dll" in out
    assert "UNPARSEABLE" in out and "truncated.dll" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    verdicts = {k.split("\\")[-1].split("/")[-1]: v["verdict"]
                for k, v in st.data["vet_results"]["dllvet"].items()}
    assert verdicts == {"good.dll": "OK", "truncated.dll": "UNPARSEABLE"}
