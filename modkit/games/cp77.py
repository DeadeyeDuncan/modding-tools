"""Cyberpunk 2077 preset (thin): intake/stage/conflicts/deploy/verify/remove/
status only. No plugin system -> no fomod/dllvet/esp/plugins. DATA_DIR is the
game ROOT; deploys land in root subdirs. Paths come from modkit.json."""
from pathlib import Path

DEPLOY_DIRS = ("archive", "red4ext", "r6", "bin")
PLUGIN_EXTS = ()


def applicability(payload_dir):
    return {"fomod": False, "dllvet": False, "esp": False}


def archive_order_report(preset, payload_dir):
    """.archive files in archive\\pc\\mod load in alphabetical order - report
    where each new file sorts among the existing ones. red4ext plugin dir
    collisions surface via the normal file-overlap sweep."""
    mod_rel = Path("archive") / "pc" / "mod"
    existing_dir = Path(preset.DATA_DIR) / mod_rel
    new_dir = Path(payload_dir) / mod_rel
    existing = sorted(p.name.lower() for p in existing_dir.glob("*.archive")) \
        if existing_dir.is_dir() else []
    lines = []
    if new_dir.is_dir():
        for p in sorted(new_dir.glob("*.archive")):
            before = sum(1 for e in existing if e < p.name.lower())
            lines.append(f"{p.name}: alphabetical position {before + 1} of "
                         f"{len(existing) + 1} in archive\\pc\\mod")
    return lines
