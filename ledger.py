#!/usr/bin/env python3
"""Ledger CLI - validated reads/writes for Claude-managed manual mod-install ledgers.

Games: Skyrim SE (C:\\Modding\\skyrim-manual\\ledger.json),
Cyberpunk 2077 (C:\\Modding\\cyberpunk-manual\\ledger.json).
Run via:  py -3 C:\\Modding\\tools\\ledger.py <command> --game skyrim|cp77
Spec: docs/2026-07-04-ledger-cli-design.md
"""
import argparse
import copy
import datetime
import difflib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

GAMES = {
    "skyrim": Path(r"C:\Modding\skyrim-manual\ledger.json"),
    "cp77": Path(r"C:\Modding\cyberpunk-manual\ledger.json"),
}
BACKUP_KEEP = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VANILLA_PLUGINS = {"skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm"}


class LedgerError(Exception):
    """Raised for any condition that must abort without writing."""


_STR_FIELDS = ("version", "source", "role", "type", "note", "manifest",
               "removedTo", "removedReason")


def validate_data(data):
    """Return list of violation strings. Empty list = valid.

    Structure strict, vocabulary open: unknown extra keys are never flagged.
    """
    if not isinstance(data, dict) or not isinstance(data.get("mods"), list):
        return ["ledger root must be an object containing a 'mods' array"]
    v = []
    seen = {}
    for i, e in enumerate(data["mods"]):
        if not isinstance(e, dict):
            v.append(f"entry #{i}: not an object")
            continue
        name = e.get("name")
        label = name if isinstance(name, str) and name.strip() else f"entry #{i}"
        if not isinstance(name, str) or not name.strip():
            v.append(f"entry #{i}: missing or empty 'name'")
        else:
            key = name.strip().lower()
            if key in seen:
                v.append(f"{label}: duplicate name (also entry #{seen[key]})")
            else:
                seen[key] = i
        inst = e.get("installed")
        if not (isinstance(inst, str) and DATE_RE.match(inst)):
            v.append(f"{label}: 'installed' missing or not YYYY-MM-DD")
        if "removed" in e:
            if not (isinstance(e["removed"], str) and DATE_RE.match(e["removed"])):
                v.append(f"{label}: 'removed' not YYYY-MM-DD")
            reason = e.get("removedReason")
            if not (isinstance(reason, str) and reason.strip()):
                v.append(f"{label}: 'removed' requires non-empty 'removedReason'")
        # nexusId/plugin/str-fields treat None as absent; masters/esl/requires deliberately reject null
        for f in _STR_FIELDS:
            if f in e and e[f] is not None and not isinstance(e[f], str):
                v.append(f"{label}: '{f}' should be a string")
        for f in ("nexusId", "fileCount"):
            val = e.get(f)
            if f in e and val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                v.append(f"{label}: '{f}' should be an integer")
        if "esl" in e and not isinstance(e["esl"], bool):
            v.append(f"{label}: 'esl' should be a boolean")
        if "masters" in e and not isinstance(e["masters"], list):
            v.append(f"{label}: 'masters' should be a list")
        plugin = e.get("plugin")
        if "plugin" in e and plugin is not None and not isinstance(plugin, (str, list)):
            v.append(f"{label}: 'plugin' should be a string, list, or null")
        if "requires" in e and not isinstance(e["requires"], (list, str)):
            v.append(f"{label}: 'requires' should be a list or string")
    return v


def load_ledger(path):
    path = Path(path)
    if not path.is_file():
        raise LedgerError(f"ledger not found: {path}")
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise LedgerError(f"ledger unparseable: {path}: {ex}")


def save_ledger(path, data, allow_violations=()):
    """Validate -> backup -> write temp -> atomic replace. Never partial.

    allow_violations: exact violation strings tolerated (used by migrate for
    pre-existing MANUAL items it just reported).
    """
    path = Path(path)
    violations = [v for v in validate_data(data) if v not in set(allow_violations)]
    if violations:
        raise LedgerError("refusing to write invalid ledger:\n  " + "\n  ".join(violations))
    backups = path.parent / "backups"
    backups.mkdir(exist_ok=True)
    if path.is_file():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, backups / f"{path.name}.bak-{stamp}")
        old = sorted(backups.glob(f"{path.name}.bak-*"))
        for stale in old[:-BACKUP_KEEP]:
            stale.unlink()
    text = json.dumps(data, indent=4, ensure_ascii=False).replace("\n", "\r\n") + "\r\n"
    # tmp must stay in path.parent: os.replace is only atomic same-volume
    for stale_tmp in path.parent.glob(f"{path.name}.tmp-*"):
        stale_tmp.unlink(missing_ok=True)
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def find_entry(data, name):
    key = name.strip().lower()
    for e in data["mods"]:
        if isinstance(e.get("name"), str) and e["name"].strip().lower() == key:
            return e
    return None


def today():
    return datetime.date.today().isoformat()


def _resolve_ledger(args):
    if getattr(args, "ledger", None):
        return Path(args.ledger)
    game = getattr(args, "game", None)
    if game in GAMES:
        return GAMES[game]
    raise LedgerError(f"unknown --game {game!r}; pass --game skyrim|cp77 or --ledger <path>")


def _entry_line(e):
    bits = [e.get("name", "?")]
    if e.get("version"):
        bits.append(f"v{e['version']}")
    bits.append(f"installed {e.get('installed', '?')}")
    plugin = e.get("plugin")
    if plugin:
        bits.append(", ".join(plugin) if isinstance(plugin, list) else plugin)
    if "removed" in e:
        bits.append(f"[REMOVED {e['removed']}]")
    return "  ".join(bits)


def cmd_get(args):
    data = load_ledger(_resolve_ledger(args))
    e = find_entry(data, args.name)
    if e is None:
        close = difflib.get_close_matches(
            args.name, [x.get("name", "") for x in data["mods"]], n=3)
        raise LedgerError(f"no entry named {args.name!r}" +
                          (f"; close: {', '.join(close)}" if close else ""))
    safe_print(json.dumps(e, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args):
    data = load_ledger(_resolve_ledger(args))
    mods = data["mods"]
    if args.active:
        mods = [e for e in mods if "removed" not in e]
    if args.removed:
        mods = [e for e in mods if "removed" in e]
    if args.since:
        mods = [e for e in mods if e.get("installed", "") >= args.since]
    if args.count:
        total = len(data["mods"])
        removed = sum(1 for e in data["mods"] if "removed" in e)
        safe_print(f"{total} total, {total - removed} active, {removed} removed"
                   f" ({len(mods)} matching filters)")
        return 0
    for e in mods:
        safe_print(_entry_line(e))
    return 0


def cmd_validate(args):
    data = load_ledger(_resolve_ledger(args))
    violations = validate_data(data)
    for x in violations:
        safe_print(f"VIOLATION: {x}")
    safe_print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


def build_parser():
    p = argparse.ArgumentParser(prog="ledger.py", description=__doc__)

    def add_globals(parser):
        # SUPPRESS: unprovided flags set no attribute, so subparser parsing
        # never clobbers a value parsed before the subcommand (bpo-9351)
        parser.add_argument("--game", default=argparse.SUPPRESS,
                            help="skyrim | cp77 (validated in _resolve_ledger for exit-2 contract)")
        parser.add_argument("--ledger", default=argparse.SUPPRESS,
                            help="explicit ledger.json path (overrides --game)")

    add_globals(p)
    common = argparse.ArgumentParser(add_help=False)
    add_globals(common)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("get", parents=[common])
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("list", parents=[common])
    sp.add_argument("--active", action="store_true")
    sp.add_argument("--removed", action="store_true")
    sp.add_argument("--since")
    sp.add_argument("--count", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("validate", parents=[common])
    sp.set_defaults(func=cmd_validate)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as ex:
        safe_print(f"ERROR: {ex}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
