"""modkit snapshot - per-game session-state snapshot/diff + open-items tracker.

Extends the modkit core CLI (docs/2026-07-11-modkit-design.md) with the
`snapshot take|diff` and `openitems add|done|list` subcommands.
Plan: docs/2026-07-11-snapshot-plan.md. Evidence: reflection-notes.md #9.

Safety: this module NEVER writes into game dirs, Plugins.txt, or the ledger.
Its only writes are C:\\Modding\\<game>-manual\\snapshots\\*.json and
C:\\Modding\\<game>-manual\\open-items.md (both atomic).
"""
import datetime
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from . import config, ledger_bridge, pluginstxt

SCHEMA_VERSION = 1


def safe_print(s):
    """print() that survives cp1252 Windows consoles (ledger.py pattern)."""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def read_text(path):
    """Read a text file BOM- and CRLF-tolerantly. Returns None if missing."""
    p = Path(path)
    if not p.is_file():
        return None
    return p.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")


def read_ini_key(path, section, key):
    """Value of `key` under `[section]` in a game-style INI, or None.

    A line scanner, deliberately NOT configparser: game INIs carry
    duplicate keys (last one wins, matching engine behavior), '%' chars,
    stray BOMs, and case drift ('[Display]' vs '[display]') that trip
    configparser. Section and key match case-insensitively. The value is
    everything after the first '=', stripped, verbatim (no inline-comment
    stripping - watched values are bare tokens like '1' or 'true').
    """
    text = read_text(path)
    if text is None:
        return None
    want_section = section.strip().lower()
    want_key = key.strip().lower()
    in_section = False
    value = None
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip().lower() == want_section
            continue
        if in_section and "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == want_key:
                value = v.strip()  # keep scanning: last occurrence wins
    return value


def atomic_write(path, text):
    """Write text as UTF-8/CRLF via temp file + os.replace (same-volume atomic)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Valve KeyValues (.acf) - minimal text parser for Steam appmanifests
# --------------------------------------------------------------------------

def _acf_tokens(text):
    """Yield (token, is_string) - is_string False only for '{' / '}'.

    Handles quoted strings with \\" \\\\ \\n \\t escapes, bare tokens,
    and // line comments.
    """
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if c in "{}":
            yield c, False
            i += 1
            continue
        if c == '"':
            out = []
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    esc = text[i + 1]
                    out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1  # closing quote
            yield "".join(out), True
            continue
        j = i
        while j < n and text[j] not in ' \t\r\n"{}':
            j += 1
        yield text[i:j], True
        i = j


def parse_acf(text):
    """Minimal Valve KeyValues (.acf/.vdf text) parser -> nested dict.

    Grammar: `key value` pairs and `key { ... }` blocks, keys/values quoted
    or bare. Duplicate keys: last one wins. Raises ValueError on unbalanced
    braces or a dangling key.
    """
    root = {}
    stack = [root]
    key = None
    for tok, is_str in _acf_tokens(text):
        if not is_str and tok == "{":
            if key is None:
                raise ValueError("acf: '{' with no preceding key")
            child = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif not is_str and tok == "}":
            if key is not None:
                raise ValueError(f"acf: dangling key {key!r} before '}}'")
            if len(stack) == 1:
                raise ValueError("acf: unbalanced '}'")
            stack.pop()
        elif key is None:
            key = tok
        else:
            stack[-1][key] = tok
            key = None
    if len(stack) != 1:
        raise ValueError("acf: unclosed '{'")
    if key is not None:
        raise ValueError(f"acf: dangling key {key!r} at end of input")
    return root


def acf_get(d, *path):
    """Case-insensitive nested lookup; None when any hop is missing."""
    cur = d
    for name in path:
        if not isinstance(cur, dict):
            return None
        found = None
        for k, v in cur.items():
            if k.lower() == name.lower():
                found = v
        if found is None:
            return None
        cur = found
    return cur


AUTOUPDATE_MEANING = {
    "0": "always keep this game updated - DANGEROUS for modded games",
    "1": "only update this game when I launch it",
    "2": "high priority auto-update - DANGEROUS for modded games",
}


def capture_steam(snap_cfg):
    """Read AutoUpdateBehavior from the configured appmanifest.

    Returns (section_dict_or_None, warnings). None section = not configured.
    Any behavior other than "1" is a WARNING: an unattended Steam update
    breaks loader chains (RDR2 was 10 hours from exactly this, 2026-07-01).
    """
    path = snap_cfg.get("appmanifest")
    if not path:
        return None, []
    want_id = snap_cfg.get("steamAppId")
    section = {"appmanifest": str(path), "appId": None, "autoUpdateBehavior": None}
    text = read_text(path)
    if text is None:
        return section, [f"appmanifest not found: {path}"]
    try:
        acf = parse_acf(text)
    except ValueError as ex:
        return section, [f"appmanifest unparseable: {path}: {ex}"]
    section["appId"] = acf_get(acf, "AppState", "appid")
    behavior = acf_get(acf, "AppState", "AutoUpdateBehavior")
    section["autoUpdateBehavior"] = behavior
    warnings = []
    if want_id is not None and section["appId"] is not None \
            and str(want_id) != str(section["appId"]):
        warnings.append(f"appmanifest appid {section['appId']} != configured "
                        f"steamAppId {want_id} - wrong manifest path in modkit.json?")
    if behavior != "1":
        meaning = AUTOUPDATE_MEANING.get(behavior or "", "unknown value")
        warnings.append(
            f"Steam AutoUpdateBehavior={behavior!r} ({meaning}) - must be 1 "
            f"('only update when I launch'): an unattended auto-update can break "
            f"the loader chain (RDR2 near-miss 2026-07-01). "
            f"Fix in Steam > Properties > Updates.")
    return section, warnings


# --------------------------------------------------------------------------
# Section captures (all pure reads)
# --------------------------------------------------------------------------

def snapshot_cfg(cfg, game):
    """The per-game 'snapshot' section of modkit.json ({} when absent)."""
    return (cfg.get("snapshot") or {}).get(game) or {}


def manual_dir(preset):
    """C:\\Modding\\<game>-manual, derived from the preset's BACKUPS_DIR
    (skyrim-manual\\backups -> skyrim-manual). Keeps this plan inside the
    dependency contract instead of inventing a new preset attribute."""
    return Path(preset.BACKUPS_DIR).parent


def capture_plugins(preset):
    """Plugins.txt state: verbatim non-blank lines + normalized SHA256 + counts.

    pluginstxt.read() is BOM/CRLF-safe (core contract); dropping blank lines
    and hashing '\\n'.join(lines)+'\\n' makes the hash stable across editors,
    trailing newlines, and CRLF re-saves (normalized-before-hash constraint).
    Returns (None, []) when the preset has no Plugins.txt (CP77).
    """
    if getattr(preset, "PLUGINS_TXT", None) is None:
        return None, []
    lines = [ln for ln in pluginstxt.read(preset) if ln.strip()]
    joined = "\n".join(lines) + "\n"
    return {
        "lines": lines,
        "sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "enabled": sum(1 for ln in lines if ln.startswith("*")),
        "total": len(lines),
    }, []


def capture_dlls(snap_cfg):
    """Top-level *.dll filenames in the configured dllDir (SKSE plugins for
    skyrim). Non-recursive, matching the sse-baseline counting convention."""
    d = snap_cfg.get("dllDir")
    if not d:
        return None, []
    p = Path(d)
    if not p.is_dir():
        return {"dir": str(d), "dlls": None}, [f"dllDir not found: {d}"]
    return {"dir": str(d), "dlls": sorted(f.name for f in p.glob("*.dll"))}, []


def capture_ini(snap_cfg):
    """Watched INI keys -> {'basename::section::key': value-or-None}.

    Key list comes from modkit.json - the code reads whatever is configured.
    Basenames (not full paths) keep snapshot keys drive-letter-portable;
    watched files must therefore have distinct basenames.
    """
    entries = snap_cfg.get("ini")
    if not entries:
        return None, []
    out, warnings = {}, []
    for e in entries:
        label = f"{Path(e['file']).name}::{e['section']}::{e['key']}"
        if not Path(e["file"]).is_file():
            out[label] = None
            warnings.append(f"ini file not found: {e['file']}")
            continue
        out[label] = read_ini_key(e["file"], e["section"], e["key"])
    return out, warnings


def capture_enb(snap_cfg):
    """Watched ENB flags from the configured enbseries.ini."""
    enb = snap_cfg.get("enb")
    if not enb:
        return None, []
    path = enb["file"]
    warnings = [] if Path(path).is_file() else [f"ENB config not found: {path}"]
    keys = {}
    for e in enb.get("keys", []):
        keys[f"{e['section']}::{e['key']}"] = read_ini_key(path, e["section"], e["key"])
    return {"file": str(path), "keys": keys}, warnings


_LEDGER_COUNT_RE = re.compile(r"(\d+) total, (\d+) active, (\d+) removed")


def capture_ledger(game):
    """Entry counts via `ledger.py list --game <g> --count` through the
    core ledger_bridge (never reads ledger.json directly)."""
    rc, stdout = ledger_bridge.run(["list", "--game", game, "--count"])
    m = _LEDGER_COUNT_RE.search(stdout or "")
    if rc != 0 or not m:
        return None, [f"ledger count unavailable (rc={rc}): "
                      f"{(stdout or '').strip()[:200]}"]
    return {"total": int(m.group(1)), "active": int(m.group(2)),
            "removed": int(m.group(3))}, []


def capture(game, preset, snap_cfg, now=None):
    """Capture the full live session-state snapshot dict (pure reads)."""
    now = now or datetime.datetime.now()
    sections, warnings = {}, []
    for name, (sec, w) in {
        "plugins": capture_plugins(preset),
        "dlls": capture_dlls(snap_cfg),
        "ini": capture_ini(snap_cfg),
        "enb": capture_enb(snap_cfg),
        "ledger": capture_ledger(game),
        "steam": capture_steam(snap_cfg),
    }.items():
        sections[name] = sec
        warnings.extend(w)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "game": game,
        "takenAt": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "sections": sections,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# snapshot take
# --------------------------------------------------------------------------

def snapshots_dir(preset):
    return manual_dir(preset) / "snapshots"


def take(game, preset, snap_cfg, stamp=None):
    """Capture live state and write snapshot-<ts>.json atomically.

    Returns (path, snapshot_dict). Writes ONLY under
    C:\\Modding\\<game>-manual\\snapshots\\ - game dirs are read, never written.
    """
    snap = capture(game, preset, snap_cfg)
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = snapshots_dir(preset) / f"snapshot-{stamp}.json"
    atomic_write(out, json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    return out, snap


def latest_snapshot(snapdir):
    """Newest snapshot file by name (stamp format sorts lexicographically)."""
    files = sorted(Path(snapdir).glob("snapshot-*.json"))
    return files[-1] if files else None


def load_snapshot(path):
    """Parse a snapshot file (BOM-tolerant). Raises on missing/corrupt."""
    return json.loads(Path(path).read_bytes().decode("utf-8-sig"))


# --------------------------------------------------------------------------
# snapshot diff
# --------------------------------------------------------------------------

ASK_THE_USER = """\
------------------------------------------------------------
NOTE FOR CLAUDE - read before acting on this report:
Unexplained deltas are NOT automatically bugs. The user changes things
between sessions deliberately (2026-07-01: Precision.esp was disabled by
choice, and a session-start audit wrongly flagged it as an urgent bug).
Before treating any delta above as a defect - and before "fixing" anything -
ASK THE USER: "What did you change manually since the last snapshot?"
Only act on a delta after the user confirms it was not deliberate."""


def _plugin_map(sec):
    """plugins section -> {lowercased name: (enabled, display_name)}."""
    out = {}
    for ln in sec.get("lines") or []:
        display = ln.lstrip("*").strip()
        out[display.lower()] = (ln.startswith("*"), display)
    return out


def _diff_kv(bd, ld):
    """Diff two flat {key: value} dicts -> report lines (sorted by key)."""
    lines = []
    for k in sorted(set(bd) | set(ld)):
        if k not in bd:
            lines.append(f"  ADDED:   {k} = {ld[k]!r}")
        elif k not in ld:
            lines.append(f"  REMOVED: {k} (was {bd[k]!r})")
        elif bd[k] != ld[k]:
            lines.append(f"  CHANGED: {k}: {bd[k]!r} -> {ld[k]!r}")
    return lines


def diff_report(base, live):
    """Stored snapshot vs live capture -> (text, delta_count, warning_count).

    Deltas are grouped ADDED / REMOVED / CHANGED per section. Whenever any
    delta exists the report ends with the ASK_THE_USER note - deliberate
    user changes must never be treated as bugs (reflection-notes.md #9).
    """
    out = []
    deltas = 0
    bsec = base.get("sections") or {}
    lsec = live.get("sections") or {}

    def presence_changed(heading, b, l):
        nonlocal deltas
        if (b is None) != (l is None):
            out.append(heading)
            out.append("  CHANGED: section "
                       + ("appeared (newly configured)" if b is None
                          else "disappeared (config removed?)"))
            deltas += 1
            return True
        return False

    # --- Plugins.txt
    b, l = bsec.get("plugins"), lsec.get("plugins")
    if not presence_changed("PLUGINS (Plugins.txt)", b, l) and b is not None:
        bm, lm = _plugin_map(b), _plugin_map(l)
        added = sorted(set(lm) - set(bm))
        removed = sorted(set(bm) - set(lm))
        flipped = sorted(n for n in set(bm) & set(lm) if bm[n][0] != lm[n][0])
        hash_only = (b["sha256"] != l["sha256"]) and not (added or removed or flipped)
        if added or removed or flipped or hash_only:
            out.append("PLUGINS (Plugins.txt)")
            for n in added:
                out.append(f"  ADDED:   {'*' if lm[n][0] else ''}{lm[n][1]}")
            for n in removed:
                out.append(f"  REMOVED: {'*' if bm[n][0] else ''}{bm[n][1]}")
            for n in flipped:
                state = "disabled -> ENABLED" if lm[n][0] else "enabled -> DISABLED"
                out.append(f"  CHANGED: {lm[n][1]}: {state}")
            if hash_only:
                out.append("  CHANGED: same plugin set, different order/content "
                           "(sha256 differs)")
            out.append(f"  enabled {b['enabled']} -> {l['enabled']}, "
                       f"total {b['total']} -> {l['total']}")
            deltas += len(added) + len(removed) + len(flipped) + (1 if hash_only else 0)

    # --- watched DLLs
    b, l = bsec.get("dlls"), lsec.get("dlls")
    if not presence_changed("DLLS", b, l) and b is not None:
        bd, ld = set(b.get("dlls") or []), set(l.get("dlls") or [])
        if bd != ld:
            out.append(f"DLLS ({l.get('dir')})")
            for n in sorted(ld - bd):
                out.append(f"  ADDED:   {n}")
            for n in sorted(bd - ld):
                out.append(f"  REMOVED: {n}")
            deltas += len(bd ^ ld)

    # --- watched INI keys
    b, l = bsec.get("ini"), lsec.get("ini")
    if not presence_changed("WATCHED INI KEYS", b, l) and b is not None:
        kv = _diff_kv(b, l)
        if kv:
            out.append("WATCHED INI KEYS")
            out.extend(kv)
            deltas += len(kv)

    # --- watched ENB flags
    b, l = bsec.get("enb"), lsec.get("enb")
    if not presence_changed("WATCHED ENB FLAGS", b, l) and b is not None:
        kv = _diff_kv(b.get("keys") or {}, l.get("keys") or {})
        if kv:
            out.append(f"WATCHED ENB FLAGS ({l.get('file')})")
            out.extend(kv)
            deltas += len(kv)

    # --- ledger counts
    b, l = bsec.get("ledger"), lsec.get("ledger")
    if not presence_changed("LEDGER", b, l) and b is not None and b != l:
        out.append("LEDGER")
        out.append(f"  CHANGED: total {b['total']} -> {l['total']}, "
                   f"active {b['active']} -> {l['active']}, "
                   f"removed {b['removed']} -> {l['removed']}")
        deltas += 1

    # --- steam auto-update
    b, l = bsec.get("steam"), lsec.get("steam")
    if not presence_changed("STEAM", b, l) and b is not None:
        if b.get("autoUpdateBehavior") != l.get("autoUpdateBehavior"):
            out.append("STEAM")
            out.append(f"  CHANGED: AutoUpdateBehavior "
                       f"{b.get('autoUpdateBehavior')!r} -> "
                       f"{l.get('autoUpdateBehavior')!r}")
            deltas += 1

    warnings = list(live.get("warnings") or [])
    if warnings:
        out.append("WARNINGS (live state)")
        out.extend(f"  {w}" for w in warnings)

    if deltas == 0 and not warnings:
        out.append("no drift - live state matches the snapshot.")
    else:
        out.append("")
        out.append(f"{deltas} delta(s), {len(warnings)} warning(s).")
        if deltas:
            out.append(ASK_THE_USER)
    return "\n".join(out), deltas, len(warnings)
