import json
from pathlib import Path

import pytest

from modkit import fomod

MODULE_XML = """<config xmlns="http://qconsulting.ca/fo3/ModConfig5.0.xsd">
  <moduleName>Cool Mod</moduleName>
  <requiredInstallFiles>
    <folder source="core" destination="" />
  </requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Main">
      <optionalFileGroups order="Explicit">
        <group name="Variant" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Red">
              <description>red one</description>
              <files><folder source="opt-red" destination="textures" /></files>
              <conditionFlags><flag name="red">On</flag></conditionFlags>
            </plugin>
            <plugin name="Blue">
              <description>blue one</description>
              <files><folder source="opt-blue" destination="textures" /></files>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
  <conditionalFileInstalls>
    <patterns>
      <pattern>
        <dependencies operator="And">
          <flagDependency flag="red" value="On" />
        </dependencies>
        <files><file source="extras/red-extra.ini" destination="red-extra.ini" /></files>
      </pattern>
    </patterns>
  </conditionalFileInstalls>
</config>"""


@pytest.fixture
def fomod_staging(tmp_path):
    staging = tmp_path / "20260711-000000-cool-mod"
    pay = staging / "payload"
    (pay / "fomod").mkdir(parents=True)
    (pay / "fomod" / "ModuleConfig.xml").write_text(MODULE_XML, encoding="utf-8")
    (pay / "core").mkdir()
    (pay / "core" / "Cool.esp").write_text("TES4")
    (pay / "opt-red").mkdir()
    (pay / "opt-red" / "red.dds").write_text("RED")
    (pay / "opt-blue").mkdir()
    (pay / "opt-blue" / "blue.dds").write_text("BLUE")
    (pay / "extras").mkdir()
    (pay / "extras" / "red-extra.ini").write_text("[x]")
    return staging, pay


def test_parse_tree_shape(fomod_staging):
    _, pay = fomod_staging
    tree = fomod.parse(pay)
    assert tree["moduleName"] == "Cool Mod"
    assert tree["required"][0] == {"kind": "folder", "source": "core", "destination": ""}
    grp = tree["steps"][0]["groups"][0]
    assert grp["type"] == "SelectExactlyOne"
    assert [p["name"] for p in grp["plugins"]] == ["Red", "Blue"]
    assert grp["plugins"][0]["flags"] == {"red": "On"}
    assert tree["conditional"][0]["flags"] == {"red": "On"}


def test_apply_red_materializes_required_pick_and_conditional(fomod_staging):
    staging, pay = fomod_staging
    count = fomod.apply(pay, staging, {"Main::Variant": ["Red"]})
    final = staging / "payload_final"
    assert (final / "Cool.esp").is_file()
    assert (final / "textures" / "red.dds").is_file()
    assert (final / "red-extra.ini").is_file()
    assert not (final / "textures" / "blue.dds").exists()
    assert count == 3


def test_apply_blue_skips_conditional(fomod_staging):
    staging, pay = fomod_staging
    fomod.apply(pay, staging, {"Main::Variant": ["Blue"]})
    final = staging / "payload_final"
    assert (final / "textures" / "blue.dds").is_file()
    assert not (final / "red-extra.ini").exists()


def test_apply_validates_picks(fomod_staging):
    staging, pay = fomod_staging
    with pytest.raises(fomod.FomodError):
        fomod.apply(pay, staging, {"Main::Variant": ["Green"]})
    with pytest.raises(fomod.FomodError):
        fomod.apply(pay, staging, {"Main::Variant": []})  # SelectExactlyOne needs 1


def test_parse_missing_config_raises(tmp_path):
    with pytest.raises(fomod.FomodError):
        fomod.parse(tmp_path)


def test_cli_fomod_print_and_apply(game_env, preset, run_cli, fomod_staging, tmp_path):
    import shutil
    from modkit import state as mstate
    src_staging, src_pay = fomod_staging
    root = Path(preset.STAGING_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / "20260711-000000-cool-mod"
    shutil.copytree(src_staging, staging)
    mstate.InstallState.create(str(staging), mod="Cool Mod", game="skyrim",
                               archive=r"C:\dl\Cool Mod-1-1-0.7z",
                               applicable={"fomod": True, "dllvet": False, "esp": True})
    code, out = run_cli("fomod", "--game", "skyrim", "--staging", str(staging))
    assert code == 0
    assert json.loads(out)["moduleName"] == "Cool Mod"
    picks = tmp_path / "picks.json"
    picks.write_text(json.dumps({"Main::Variant": ["Red"]}), encoding="utf-8")
    code, out = run_cli("fomod", "--game", "skyrim", "--staging", str(staging),
                        "--apply", str(picks))
    assert code == 0
    st = mstate.InstallState.load(str(staging))
    assert st.data["stages"]["fomod"]
    assert st.data["vet_results"]["fomod"]["files"] == 3
