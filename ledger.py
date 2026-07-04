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


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def main(argv=None):
    return 0


if __name__ == "__main__":
    sys.exit(main())
