"""modkit.json loader. Machine paths live in config, never in code
(SSD/multi-machine portability)."""
import json
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "modkit.json"


class ConfigError(Exception):
    """Bad or missing configuration / unknown game."""


def load(path=None):
    """Load modkit.json -> dict. Order: explicit path, MODKIT_CONFIG env, repo default."""
    p = Path(path or os.environ.get("MODKIT_CONFIG") or DEFAULT_PATH)
    if not p.is_file():
        raise ConfigError(f"config not found: {p}")
    try:
        cfg = json.loads(p.read_bytes().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise ConfigError(f"config unparseable: {p}: {ex}")
    for key in ("sevenzip", "staging_root", "games"):
        if key not in cfg:
            raise ConfigError(f"config missing required key {key!r}: {p}")
    return cfg


def game(cfg, name):
    """Return the populated preset module for `name`."""
    from modkit import games
    return games.load(cfg, name)
