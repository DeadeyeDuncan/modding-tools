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
