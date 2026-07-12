import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "adoption" / "modkit-guard.py"
GAME_CWD = r"E:\SteamLibrary\steamapps\common\Skyrim Special Edition"


def run_guard(tool_name, cwd, command):
    payload = json.dumps({"tool_name": tool_name, "cwd": cwd,
                          "tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, str(GUARD)], input=payload,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stdout.strip()


def test_hand_roll_extract_warns_with_modkit_command():
    code, out = run_guard("Bash", GAME_CWD, '7z x "C:\\dl\\mod.7z" -oC:\\tmp')
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PreToolUse"
    assert "modkit.py stage" in ctx["additionalContext"]
    assert "ADVISORY" in ctx["additionalContext"]


def test_all_pattern_classes_match():
    cases = [
        ("Expand-Archive -Path mod.zip -Dest x", "stage"),
        (r'robocopy C:\tmp\payload "E:\SteamLibrary\steamapps\common\Skyrim Special Edition\Data" /E', "deploy"),
        (r'Add-Content "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt" "*New.esp"', "plugins"),
        (r'echo *New.esp >> "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt"', "plugins"),
        (r'Set-Content C:\Modding\skyrim-manual\ledger.json $json', "ledger.py"),
    ]
    for command, expected in cases:
        code, out = run_guard("PowerShell", GAME_CWD, command)
        assert code == 0 and out, f"no warning for: {command}"
        assert expected in json.loads(out)["hookSpecificOutput"]["additionalContext"], command


def test_forensics_and_non_game_cwd_stay_silent():
    code, out = run_guard("Bash", GAME_CWD, "rg -n 'MODL' Data/meshes")
    assert code == 0 and out == ""
    code, out = run_guard("Bash", r"H:\DeadMind V.3", "7z x archive.7z")
    assert code == 0 and out == ""
    code, out = run_guard("Read", GAME_CWD, "7z x archive.7z")
    assert code == 0 and out == ""


def test_garbage_stdin_never_blocks():
    proc = subprocess.run([sys.executable, str(GUARD)], input="not json",
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0 and proc.stdout.strip() == ""
