import struct

import pytest

from modkit import tes4


def make_tes4(masters=(), esl=False, esm=False):
    """Minimal TES4 record: 24-byte record header + HEDR/MAST/DATA subrecords."""
    body = b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.71, 1, 0x800)
    for m in masters:
        mb = m.encode("cp1252") + b"\x00"
        body += b"MAST" + struct.pack("<H", len(mb)) + mb
        body += b"DATA" + struct.pack("<H", 8) + b"\x00" * 8
    flags = (0x200 if esl else 0) | (0x1 if esm else 0)
    return (b"TES4" + struct.pack("<I", len(body)) + struct.pack("<I", flags)
            + b"\x00" * 12 + body)


def test_parse_masters_and_flags(tmp_path):
    p = tmp_path / "Mod.esp"
    p.write_bytes(make_tes4(masters=("Skyrim.esm", "Update.esm"), esl=True))
    hdr = tes4.parse_header(p)
    assert hdr["masters"] == ["Skyrim.esm", "Update.esm"]
    assert hdr["esl"] is True and hdr["esm"] is False
    assert hdr["version"] == 1.71


def test_parse_rejects_non_plugin(tmp_path):
    p = tmp_path / "notaplugin.esp"
    p.write_bytes(b"JUNKJUNKJUNK")
    with pytest.raises(tes4.Tes4Error):
        tes4.parse_header(p)


def test_esp_cmd_clean_when_masters_present(game_env, preset, make_staging, run_cli):
    (game_env / "Data" / "Skyrim.esm").write_bytes(b"x")
    sd = make_staging({"Mod.esp": make_tes4(masters=("Skyrim.esm",))}, mod="Clean Esp")
    code, out = run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    assert code == 0
    assert "Skyrim.esm" in out
    from modkit import state as mstate
    st = mstate.InstallState.load(str(sd))
    assert st.data["stages"]["esp"]
    assert st.data["vet_results"]["esp"]["Mod.esp"]["missing"] == []


def test_esp_cmd_warns_on_missing_master(game_env, preset, make_staging, run_cli):
    sd = make_staging({"Mod.esp": make_tes4(masters=("NotInstalled.esm",))},
                      mod="Broken Esp")
    code, out = run_cli("esp", "--game", "skyrim", "--staging", str(sd))
    assert code == 2
    assert "missing master" in out and "NotInstalled.esm" in out
