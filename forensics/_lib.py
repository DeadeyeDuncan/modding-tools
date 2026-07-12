"""forensics/_lib.py — shared helpers for the Skyrim forensics kit.

Every tool in this package is standalone:
    py -3 C:\\Modding\\tools\\forensics\\<tool>.py
Each tool file begins with the sys.path bootstrap:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from forensics import _lib

All tools are READ-ONLY against game directories: they report, never modify.
Config comes from C:\\Modding\\tools\\modkit.json (forensics section) via
modkit.config — the two adapter functions at the bottom (load_config,
tes4_header) are the ONLY places this kit touches modkit.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent  # C:\Modding\tools
DEFAULT_CONFIG = TOOLS_ROOT / "modkit.json"


class ForensicsError(SystemExit):
    def __init__(self, msg):
        super().__init__("ERROR: " + str(msg))


def say(s):
    """ASCII-safe print (cp1252 console; ledger.py precedent)."""
    print(str(s).encode("ascii", "replace").decode("ascii"))


# ---------- config ----------

def load_config(path=None):
    """Load modkit.json.

    Explicit path (tests, --config flags): plain JSON read.
    Default path: delegate to modkit.config so forensics and modkit never
    drift on config semantics (modkit plan Task 1). modkit.config.load()
    raises ConfigError (not ImportError) on bad/missing config, so that is
    allowed to propagate; only an unmerged modkit core (ImportError) falls
    back to a plain-JSON read.
    """
    if path is not None:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    try:
        from modkit import config as _mk
    except ImportError:
        with open(DEFAULT_CONFIG, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return _mk.load(str(DEFAULT_CONFIG))


def _dig(cfg, dotted):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def game_path(cfg, key, game="skyrim"):
    for dotted in ("games.%s.%s" % (game, key),
                   "forensics.games.%s.%s" % (game, key)):
        val = _dig(cfg, dotted)
        if val is not None and not isinstance(val, (dict, list)):
            return str(val)
    raise ForensicsError(
        "modkit.json missing '%s' for game '%s' (looked under games.* and "
        "forensics.games.*) — see forensics/README.md" % (key, game))


def game_list(cfg, key, game="skyrim"):
    for dotted in ("games.%s.%s" % (game, key),
                   "forensics.games.%s.%s" % (game, key)):
        val = _dig(cfg, dotted)
        if isinstance(val, list):
            return list(val)
    raise ForensicsError(
        "modkit.json missing list '%s' for game '%s'" % (key, game))


def tool_path(cfg, name):
    val = _dig(cfg, "forensics.tools.%s" % name)
    if not val:
        raise ForensicsError("modkit.json missing forensics.tools.%s" % name)
    if not os.path.isfile(val):
        raise ForensicsError("configured %s not found on disk: %s" % (name, val))
    return str(val)


def cache_dir(cfg):
    val = _dig(cfg, "forensics.cacheDir")
    if not val:
        raise ForensicsError("modkit.json missing forensics.cacheDir")
    p = Path(val)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- path normalization ----------

def norm_rel(p):
    return str(p).strip().strip('"').replace("/", "\\").lower()


def strip_data_prefix(p):
    q = norm_rel(p)
    if q.startswith("data\\"):
        return q[5:]
    return q


# ---------- plugins.txt / load order ----------

def read_plugins_txt(path):
    """[(plugin_name, enabled)] in file order. BOM-safe; '*' prefix = enabled;
    '#'/';' comments and blanks skipped (ledger.py conventions)."""
    out = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            enabled = line.startswith("*")
            out.append((line.lstrip("*").strip(), enabled))
    return out


def load_order(cfg, game="skyrim"):
    """Implicit base masters + enabled Plugins.txt entries, case-insensitively
    deduped, order preserved. NOTE: the implicit set on an AE install (cc*
    content) is verify-on-machine — see Task 5 Step 10."""
    implicit = game_list(cfg, "implicitMasters", game)
    order, seen = [], set()
    for name in implicit + [n for n, en in read_plugins_txt(game_path(cfg, "pluginsTxt", game)) if en]:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            order.append(name)
    return order


# ---------- manifests ----------

def manifest_baseline(manifests_dir):
    """norm rel path -> owning manifest filename, from every *.txt under the
    manifests dir (recursive — the real dir has subfolders like jk-interiors\\).
    Skips '#' comment lines (the manifest-comment bug class, cleaned 2026-07-04)
    and tolerates legacy 'Data\\' prefixes (the Data-prefix bug, commit 581b8ca)."""
    base = {}
    for txt in sorted(Path(manifests_dir).rglob("*.txt")):
        with open(txt, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rel = strip_data_prefix(line)
                if rel and rel not in base:
                    base[rel] = txt.name
    return base


# ---------- filesystem ----------

def iter_files(root, exts=None):
    """Yield (abs Path, rel norm str) for files under root. exts = lowercase
    tuple filter like ('.nif',)."""
    root = Path(root)
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if exts and not fn.lower().endswith(exts):
                continue
            ap = Path(dirpath) / fn
            yield ap, norm_rel(ap.relative_to(root))


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True))


# ---------- subprocess ----------

def run(cmd):
    """Run a command list; return (returncode, merged decoded output)."""
    p = subprocess.run(cmd, capture_output=True)
    text = ((p.stdout or b"").decode("utf-8", "replace")
            + (p.stderr or b"").decode("utf-8", "replace"))
    return p.returncode, text


# ---------- modkit adapters ----------

def tes4_header(path):
    """Masters + ESL flag via modkit.tes4.parse_header (modkit plan Task 7).

    Returns {"masters": [str, ...], "esl": bool}. Every forensics tool goes
    through THIS function — nothing else imports modkit.tes4.
    """
    try:
        from modkit import tes4 as _tes4
    except ImportError:
        raise ForensicsError("modkit.tes4 not importable — merge modkit core "
                             "Tasks 1 and 7 before using the forensics kit")
    info = _tes4.parse_header(str(path))
    return {"masters": list(info["masters"]), "esl": bool(info["esl"])}
