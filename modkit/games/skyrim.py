"""Skyrim SE preset (full). Paths (DATA_DIR etc.) are populated by
modkit.games.load() from modkit.json - never hardcode them here."""
from pathlib import Path

PLUGIN_EXTS = (".esp", ".esm", ".esl")
# Plugins.txt lines that must stay last (batch-append-after-DynDOLOD bug):
DYNDOLOD_BLOCK = ("dyndolod.esm", "dyndolod.esp", "occlusion.esp")


def applicability(payload_dir):
    """Computed at stage time from payload contents (design: state machine).
    dllvet fires on ANY .dll (superset of the spec's SKSE-path wording -
    wrong-layout archives drop DLLs at payload root; gate is warn-only)."""
    root = Path(payload_dir)
    rel = [str(p.relative_to(root)).lower().replace("\\", "/")
           for p in root.rglob("*") if p.is_file()]
    return {
        "fomod": any(r.endswith("fomod/moduleconfig.xml") for r in rel),
        "dllvet": any(r.endswith(".dll") for r in rel),
        "esp": any(r.endswith(PLUGIN_EXTS) for r in rel),
    }
