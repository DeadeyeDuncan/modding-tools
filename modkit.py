#!/usr/bin/env python3
"""modkit entry shim. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modkit.cli import main

if __name__ == "__main__":
    sys.exit(main())
