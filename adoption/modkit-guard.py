#!/usr/bin/env python3
"""modkit-guard - ADVISORY PreToolUse hook for Claude Code.

Warns (NEVER blocks) when a Bash/PowerShell command in a game project or under
C:\\Modding hand-rolls a mod-install step that modkit owns. Output is an
additionalContext note naming the correct modkit command; exit code is always 0
so forensics and repair work stay possible.
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

PATTERNS = (
    (re.compile(r"\b7z(\.exe|a)?\"?\s+[xe]\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (re.compile(r"\bExpand-Archive\b", re.I),
     f"extracting an archive by hand -> use: {MODKIT} stage \"<archive>\" --game <game>"),
    (re.compile(r"\brobocopy\b[^\r\n]*\\data\b", re.I),
     f"copying into a game Data dir by hand -> use: {MODKIT} deploy --game <game>"),
    (re.compile(r"\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*plugins\.txt", re.I),
     f"editing Plugins.txt by hand -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r">>?\s*\"?[^\r\n\"|<>]*plugins\.txt", re.I),
     f"redirecting into Plugins.txt -> use: {MODKIT} plugins enable|disable --plugin <X.esp> --game skyrim"),
    (re.compile(r"(>>?\s*\"?[^\r\n\"|<>]*ledger\.json"
                r"|\b(Add-Content|Set-Content|Out-File)\b[^\r\n]*ledger\.json)", re.I),
     "writing ledger.json directly -> use: py -3 C:\\Modding\\tools\\ledger.py "
     "add/update/remove --game <game> (modkit deploy/remove call it for installs)"),
)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed input must never block anything
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cwd = str(payload.get("cwd") or "").lower().replace("/", "\\")
    if not any(h in cwd for h in GAME_HINTS):
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    hits = [advice for rx, advice in PATTERNS if rx.search(cmd)]
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


if __name__ == "__main__":
    sys.exit(main())
