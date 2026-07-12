"""Fallback preset for games without a dedicated module (e.g. kenshi).
intake/stage/status work; anything that would touch game dirs is refused
by the commands themselves (DATA_DIR is None / no deploy support)."""
PLUGIN_EXTS = ()


def applicability(payload_dir):
    return {"fomod": False, "dllvet": False, "esp": False}
