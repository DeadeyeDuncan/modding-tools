<!-- reference copy; live master: C:\Users\auand\.claude\skills\mod-install\SKILL.md -->
---
name: mod-install
description: Use when the user asks to install, verify, or remove a game mod, or gives a Nexus link or a mod archive path in a game session (Skyrim SE, Cyberpunk 2077, Kenshi). Drives the modkit CLI pipeline - never hand-roll extraction, Data copies, Plugins.txt edits, or ledger writes.
---

# Mod Install (modkit pipeline)

All installs/removals go through **modkit**:
`py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim|cp77 [flags]`
(`--help` is self-documenting). ledger.py stays the sole ledger/manifest writer -
modkit calls it during deploy/remove. **NEVER hand-roll**: 7z extraction,
robocopy into Data\, Plugins.txt edits, or ledger.json writes.

## Standing rules (from sse-mod-workflow)

- **User downloads Nexus files** - downloads are account-bound. Give the exact
  mod link + file name and wait for the archive path. Never fetch mod files yourself.
- **Verify before install**: the compat sweep (runtime, masters, conflicts)
  happens BEFORE deploy, never after.
- **Conflict sweep after EVERY install** - no exceptions.
- **Launch Skyrim ONLY via skse64_loader.exe** (never Steam Play, never MO2).
- Exit codes: **0** clean, **1** hard error or verify findings, **2** warned /
  refused-pending-a-forceable-gate. Not every exit 2 is the same gate, and not
  every gate is forceable:
  - `deploy`/`remove`: a **confirmed-running game process is exit 1 and has NO
    `--force`** - the game must actually be closed, full stop.
  - `deploy`/`remove`: if the game's running-state **can't be verified**
    (tasklist failed/empty) that's exit **2**, forceable with `--force` only
    once you've confirmed by hand that the game is closed.
  - `deploy`: missing vet stamps -> exit 2, forceable. `remove`: master-dependency
    refusal -> exit 2, forceable. `intake`/`conflicts`/`esp`/`dllvet` warnings
    are exit 2 but have no `--force` flag at all - resolve them (re-download,
    `--expect-game`, research, patch) rather than trying to force past them.
  - **Treat every exit 2 as STOP AND VET.** Never pass `--force` without
    telling the user exactly what is being skipped and why it's safe here.

## Session start / resume

Run `py -3 C:\Modding\tools\modkit.py status --game <game>` at session start and
after any crash. INCOMPLETE staging dirs = resume them (finish pending vets ->
deploy -> verify) or ask the user. State lives in `<staging>\install.json`;
never redo a stamped stage - resume at the first missing stamp. After a crashed
deploy, run `verify` first to see what actually landed.

## Install pipeline - Skyrim (full preset)

1. **Intake** - `py -3 C:\Modding\tools\modkit.py intake "<archive>" --game skyrim`
   (or bare `intake --game skyrim` to scan Downloads + Vortex).
   Resolve every WARN (0-byte, wrong-game, already-installed) before continuing.
2. **Stage** - `py -3 C:\Modding\tools\modkit.py stage "<archive>" --game skyrim`
   Full-extract + count/size verify. Note the printed staging dir; later commands
   default to the latest staging, or pass `--staging <dir>` explicitly.
   The `pending vets:` line tells you which of steps 3-5 apply.
3. **FOMOD** (if pending) - `py -3 C:\Modding\tools\modkit.py fomod --game skyrim`
   then `--apply picks.json` (judgment gate below).
4. **DLL vet** (if pending) - `py -3 C:\Modding\tools\modkit.py dllvet --game skyrim`
5. **ESP vet** (if pending) - `py -3 C:\Modding\tools\modkit.py esp --game skyrim`
   Missing masters must be installed first (user downloads them; full pipeline each).
6. **Conflicts** (always) - `py -3 C:\Modding\tools\modkit.py conflicts --game skyrim`
7. **Deploy** - `py -3 C:\Modding\tools\modkit.py deploy --game skyrim [--anchor "Plugin.esp"]`
   Game must be closed - if it's confirmed running this refuses at exit 1 and
   `--force` cannot override it (close the game and re-run). Refuses at exit 2
   while vets are pending, or if the closed-game check itself couldn't run
   (tasklist failure) - only force the latter after checking by hand.
8. **Verify** - `py -3 C:\Modding\tools\modkit.py verify --game skyrim`
   Must end `verify OK`. Then report to the user: what was installed, where the
   plugin sits in the load order, and whether a DynDOLOD/TexGen regen is implied
   (see the sse-dyndolod-rerun-rule memory).

## Judgment gates (yours, not modkit's)

- **dllvet verdicts**: `OK` -> proceed. `WRONG_RUNTIME` or `RESEARCH` -> research
  the mod page/posts for a 1.6.1170/AE/NG build (WebSearch; never WebFetch
  nexusmods.com - it 403s; verify any Nexus ID against the live page title before
  giving the user a link). `INFO` (no SKSE exports - ENB/preloader/other non-SKSE
  DLL) doesn't warn or block, but still eyeball it - confirm it's the tool the
  user actually meant to install, not a mis-vetted plugin, and vet by source if
  unsure. `BAD_ARCH`/`UNPARSEABLE` -> stop and tell the user.
- **FOMOD picks**: run `fomod` without `--apply`, read the JSON tree, and present
  each step/group as a compact list - option names, descriptions, your
  recommendation and why. On the user's choice, Write `picks.json`
  (`{"<step>::<group>": ["Plugin Name"]}`) and run `fomod --apply picks.json`.
- **Conflict decisions**: for each OVERLAP line, name the currently-owning mod
  and state that deploying makes the new mod win. Expected overlaps (patches,
  texture replacers) can proceed; unexpected ones need a user decision. If a
  record-level conflict is likely, search for a compatibility patch (exact
  module match) and give the user the link - they download, then it gets the
  full pipeline too. Record-level conflict resolution itself stays xEdit territory.

## Cyberpunk 2077 (thin preset)

Same flow minus fomod/dllvet/esp/plugins (they're no-ops for this preset anyway -
no plugin system):
intake -> stage -> conflicts -> deploy -> verify, all with `--game cp77`.
Deploy targets the game-root subdirs (archive/red4ext/r6/bin); stray top-level
payload files make deploy refuse at exit 2 - technically forceable, but restage
properly instead of forcing.

## Kenshi

Preset not built yet: `intake`/`stage`/`status` work with `--game kenshi`;
vets/deploy/remove do not (no `data_dir` configured -> they hard-error). Stage,
then hand the deploy decision to the user and follow the existing Kenshi manual
workflow.

## Remove flow

1. `py -3 C:\Modding\tools\modkit.py remove "<Ledger Name>" --game skyrim --reason "<why>"`
2. Exit 2 has two possible causes: a **master-dependency refusal** (tell the
   user WHICH enabled plugins depend on it; `--force` only after they accept
   the consequences) or an **unverifiable game-closed state** (force only after
   confirming by hand). A **confirmed-running game is exit 1 and not forceable**
   at all - close it first.
3. Files are quarantined under `C:\Modding\skyrim-manual\backups\removed-<mod>-<ts>\`
   (never deleted) - mention the path in your report.
4. Finish with `status --game skyrim`.

## External GUI tools (Wrye Bash, xEdit, DynDOLOD)

Bracket every GUI run that can touch the load order:
`py -3 C:\Modding\tools\modkit.py plugins snapshot --game skyrim --tag pre-<tool>`
before, and after it exits:
`py -3 C:\Modding\tools\modkit.py plugins diff <snapshot-path> "C:\Users\auand\AppData\Local\Skyrim Special Edition\Plugins.txt"`
Report any ADDED/REMOVED/STATE/ORDER lines to the user (the Wrye Bash
silent-scramble class).
