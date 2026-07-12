"""Preset registry. config.game() populates a preset module's path attributes
from modkit.json at load time - presets hardcode behavior, never paths."""
import importlib
from pathlib import Path

from modkit.config import ConfigError

# archive-listing markers -> game guess (intake wrong-game gate).
# fallout4 markers outrank skyrim: .ba2/F4SE never appear in SSE mods,
# while .esp/.esm appear in both (the FO4-mixup trap, 3 incidents).
_MARKERS = (
    ("f4se/", "fallout4"), (".ba2", "fallout4"),
    ("skse/", "skyrim"), (".bsa", "skyrim"),
    (".esp", "skyrim"), (".esm", "skyrim"), (".esl", "skyrim"),
    ("archive/pc/mod/", "cp77"), (".archive", "cp77"),
    ("red4ext/", "cp77"), ("r6/scripts", "cp77"),
)


def guess_game(paths):
    """Best-guess game from archive-relative paths; None = unknown."""
    votes = {}
    for p in paths:
        low = p.replace("\\", "/").lower()
        for marker, g in _MARKERS:
            hit = low.endswith(marker) if marker.startswith(".") else marker in low
            if hit:
                votes[g] = votes.get(g, 0) + 1
    if not votes:
        return None
    if votes.get("fallout4"):
        return "fallout4"
    return max(votes, key=lambda k: votes[k])


def load(cfg, name):
    if name not in cfg.get("games", {}):
        known = ", ".join(sorted(cfg.get("games", {})))
        raise ConfigError(f"game {name!r} not in modkit.json (configured: {known})")
    try:
        mod = importlib.import_module(f"modkit.games.{name}")
    except ModuleNotFoundError:
        mod = importlib.import_module("modkit.games.generic")
    g = cfg["games"][name]
    if "process_names" not in g or "backups_dir" not in g:
        raise ConfigError(f"game {name!r} config needs process_names + backups_dir")
    mod.NAME = name
    mod.DATA_DIR = g.get("data_dir")
    mod.PLUGINS_TXT = g.get("plugins_txt")
    mod.PROCESS_NAMES = list(g["process_names"])
    mod.RUNTIME = g.get("runtime")
    mod.STAGING_ROOT = str(Path(cfg["staging_root"]) / name)
    mod.BACKUPS_DIR = g["backups_dir"]
    mod.MANIFESTS_DIR = g.get("manifests_dir")
    mod.VORTEX_DOWNLOADS = g.get("vortex_downloads")
    mod.DOWNLOADS = list(cfg.get("downloads", []))
    mod.SEVENZIP = cfg["sevenzip"]
    return mod
