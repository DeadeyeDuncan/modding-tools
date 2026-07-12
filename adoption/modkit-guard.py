#!/usr/bin/env python3
"""modkit-guard - ADVISORY PreToolUse hook for Claude Code.

Warns (NEVER blocks) when a Bash/PowerShell command in a game project or under
C:\\Modding hand-rolls a mod-install step that modkit owns. Output is an
additionalContext note naming the correct modkit command; exit code is always 0
so forensics and repair work stay possible.

Malformed or unexpected-shape stdin (non-JSON, a JSON scalar/array instead of
an object, a tool_input that isn't an object, etc.) must never crash this
hook or print a traceback -- it must exit 0 with no output.
Wired from C:\\Users\\auand\\.claude\\settings.json (PreToolUse, Bash|PowerShell).
"""
import json
import re
import sys

MODKIT = r"py -3 C:\Modding\tools\modkit.py"

GAME_HINTS = (
    r"steamlibrary\steamapps\common\skyrim special edition",
    r"steamlibrary\steamapps\common\cyberpunk 2077",
    r"steamlibrary\steamapps\common\kenshi",
    r"steamlibrary\steamapps\common\red dead redemption 2",
    r"c:\modding",
)


def _tokenize(cmd):
    """Split a command line into words, keeping quoted segments intact."""
    return re.findall(r'"[^"]*"|\'[^\']*\'|\S+', cmd)


def _strip_quotes(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _robocopy_targets_data(cmd):
    """True only when robocopy's DESTINATION (2nd path arg) is a Data dir.

    robocopy's own argument order is <source> <destination> [files] [opts].
    Reading *out* of a Data dir (Data as source) is a normal backup/rescue
    op and must stay silent; deploying *into* Data (Data as dest) is the
    hand-rolled step modkit should own.
    """
    tokens = [_strip_quotes(t) for t in _tokenize(cmd)]
    idx = None
    for i, tok in enumerate(tokens):
        if re.search(r"(^|[\\/])robocopy(\.exe)?$", tok, re.I):
            idx = i
            break
    if idx is None:
        return False
    paths = [t for t in tokens[idx + 1:] if not t.startswith(("/", "-"))][:2]
    if len(paths) < 2:
        return False  # can't tell source from dest -> don't guess, stay quiet
    dest = paths[1]
    return any(part.strip().lower() == "data" for part in dest.split("\\"))


PATTERNS = (
    (re.compile(r"\b7z(\.exe|a)?\"?\s+[xe]\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (re.compile(r"\bExpand-Archive\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (_robocopy_targets_data,
     f"copying into a game Data dir by hand -> use: {MODKIT} deploy --game <game>"),
    (re.compile(r"\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*plugins\.txt(?!\.[A-Za-z0-9]+)", re.I),
     f"editing Plugins.txt by hand -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r">>?\s*\"?[^\r\n\"|<>]*plugins\.txt(?!\.[A-Za-z0-9]+)", re.I),
     f"redirecting into Plugins.txt -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r"(>>?\s*\"?[^\r\n\"|<>]*ledger\.json(?!\.[A-Za-z0-9]+)"
                r"|\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*ledger\.json(?!\.[A-Za-z0-9]+))", re.I),
     "writing ledger.json directly -> use: py -3 C:\\Modding\\tools\\ledger.py "
     "add/update/remove --game <game> (modkit deploy/remove call it for installs)"),
)


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0  # top-level JSON wasn't an object -- nothing to inspect
        if payload.get("tool_name") not in ("Bash", "PowerShell"):
            return 0
        cwd = str(payload.get("cwd") or "").lower().replace("/", "\\")
        if not any(h in cwd for h in GAME_HINTS):
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0  # tool_input wasn't an object -- nothing to inspect
        cmd = str(tool_input.get("command") or "")
        hits = []
        for matcher, advice in PATTERNS:
            matched = matcher(cmd) if callable(matcher) else matcher.search(cmd)
            if matched:
                hits.append(advice)
        if not hits:
            return 0
        context = ("modkit-guard (ADVISORY, does not block): this command looks like a "
                   "hand-rolled mod-install step. "
                   + " | ".join(dict.fromkeys(hits))
                   + " | modkit tracks per-install state (intake/vet/verify + ledger); "
                     "hand-rolled steps bypass all of it. If this is forensics or "
                     "repair work, carry on.")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "additionalContext": context}}))
        return 0
    except Exception:
        return 0  # advisory-only: never crash, never block, never leak a traceback


if __name__ == "__main__":
    sys.exit(main())
