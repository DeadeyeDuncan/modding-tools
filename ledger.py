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


def main(argv=None):
    return 0


if __name__ == "__main__":
    sys.exit(main())
