# modkit memory pins - provenance copy; live masters in C:\Users\auand\.claude\projects\<slug>\memory\modkit.md

## Skyrim

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\modkit.md`

```markdown
---
name: modkit
description: ALL mod installs/removals go through the modkit CLI at C:\Modding\tools\modkit.py - never hand-roll extraction, Data\ copies, Plugins.txt edits, or ledger writes
metadata:
  type: project
---

Installs and removals are driven by **modkit**: `py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim`. Per-install state lives in `C:\Modding\staging\skyrim\<ts>-<mod>\install.json`; `status` shows incomplete pipelines (run it at session start / after crashes). The `mod-install` skill has the full playbook.

Command crib:
- `intake ["<archive>"]` - 0-byte / wrong-game / already-installed gates (Downloads + Vortex scan)
- `stage "<archive>"` - full-extract to fresh staging + count/size verify (NEVER 7z include-patterns)
- `fomod [--apply picks.json]` - option tree as JSON; picks are a judgment gate
- `dllvet` - runtime 1.6.1170 check via SKSE version struct; WRONG_RUNTIME/RESEARCH = research before deploy
- `esp` - TES4 masters + ESL flag; missing masters get installed first
- `conflicts` - overlap sweep vs Data + manifests, names the losing mod (run after EVERY install)
- `deploy [--anchor "X.esp"] [--force]` - robocopy + Plugins.txt enable + ledger add; exit 2 = STOP AND VET
- `verify` - unfiltered payload-vs-Data diff + _SWAP/_DISTR checks + ledger check tail
- `remove "<Name>" --reason "..."` - quarantine (never delete) + masters-check + ledger remove
- `plugins list|enable|disable|snapshot|diff` - BOM/CRLF-safe Plugins.txt; snapshot/diff around Wrye Bash/xEdit/DynDOLOD

**Why:** the hand-rolled install pipeline re-fired its known failure modes every session (reflection-notes #1: FO4 mix-ups x3, include-pattern failures x4, anchor slips x2, wrong-runtime DLLs, half-installs undetected for days).
**How to apply:** NEVER hand-roll 7z x / Expand-Archive / robocopy-to-Data / Plugins.txt writes / ledger.json edits - modkit owns them. ledger.py stays the sole ledger writer (modkit calls it). An advisory PreToolUse guard to flag hand-rolling is planned but not yet shipped. Config: C:\Modding\tools\modkit.json. Spec/plan: C:\Modding\tools\docs\2026-07-11-modkit-*.md.
```

## Cyberpunk 2077

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\modkit.md`

```markdown
---
name: modkit
description: ALL mod installs/removals go through the modkit CLI at C:\Modding\tools\modkit.py - never hand-roll extraction or game-root copies
metadata:
  type: project
---

Installs and removals are driven by **modkit** (thin CP77 preset): `py -3 C:\Modding\tools\modkit.py <cmd> --game cp77`. Pipeline: `intake -> stage -> conflicts -> deploy -> verify` (no fomod/dllvet/esp/plugins - no plugin system). Per-install state in `C:\Modding\staging\cp77\...\install.json`; run `status --game cp77` at session start. The `mod-install` skill has the full playbook.

- `deploy` targets the four top-level game-root dirs: archive, red4ext, r6, bin (CP77 mod files live under archive\pc\mod\ within archive, not as a separate top-level target); stray top-level payload files make it refuse - restage properly instead of forcing.
- `conflicts` reports .archive alphabetical ordering in archive\pc\mod plus file overlaps (red4ext plugin dir collisions included).
- `remove "<Name>" --reason "..."` quarantines to C:\Modding\cyberpunk-manual\backups (never deletes) and records via ledger.py.

**Why:** the Skyrim install discipline was re-improvised from scratch for ~16 CP77 mods on 07-03 (reflection-notes #1).
**How to apply:** NEVER hand-roll 7z x / Expand-Archive / robocopy into the game root / ledger.json edits. ledger.py stays the sole ledger writer. Config: C:\Modding\tools\modkit.json.
```

## Kenshi

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\modkit.md`

```markdown
---
name: modkit
description: modkit CLI (C:\Modding\tools\modkit.py) handles archive intake/staging for Kenshi; full preset not built yet - never hand-roll 7z extraction; conflicts --game kenshi is a silent no-op, do not trust it
metadata:
  type: project
---

**Kenshi preset is NOT built yet** - modkit (the cross-game install toolkit) currently gives Kenshi:
- `py -3 C:\Modding\tools\modkit.py intake "<archive>" --game kenshi` - 0-byte / wrong-game / Nexus-parse gates
- `py -3 C:\Modding\tools\modkit.py stage "<archive>" --game kenshi` - full-extract to C:\Modding\staging\kenshi\ + count/size verify
- `py -3 C:\Modding\tools\modkit.py status --game kenshi` - incomplete-staging report

`deploy`/`remove`/`verify` hard-error at exit 1 for Kenshi (no `data_dir` configured in modkit.json - genuinely gated, not forceable). **`conflicts --game kenshi` does NOT error and does NOT check anything** - `data_dir` is null so the sweep short-circuits and always prints "no file overlaps vs Data" at exit 0, even with real conflicts present. Never trust that as a clean sweep - after staging, hand the deploy decision to the user and follow the existing manual Kenshi conflict-sweep workflow instead. The `mod-install` skill's Kenshi section has the full detail.

**How to apply:** even without the full preset, NEVER hand-roll 7z extraction - stage through modkit so counts are verified and the staging dir is tracked. Full deploy/verify/remove/real-conflicts support lands when the Kenshi preset is built (data_dir + mods.cfg/.mod-header masters checks); this pin gets updated then.
```

## MEMORY.md index lines

Skyrim — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\MEMORY.md`, inserted as the new first list item (above the Ledger CLI line):

```markdown
- [modkit install toolkit](modkit.md) — ALL installs/removals via `py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim` (intake→stage→fomod/dllvet/esp→conflicts→deploy→verify); NEVER hand-roll 7z/robocopy-to-Data/Plugins.txt/ledger writes; run `status` at session start
```

Cyberpunk 2077 — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\MEMORY.md`, inserted as the new first list item (above the Ledger CLI line):

```markdown
- [modkit install toolkit](modkit.md) — ALL installs/removals via `py -3 C:\Modding\tools\modkit.py <cmd> --game cp77` (intake→stage→conflicts→deploy→verify, thin preset); NEVER hand-roll extraction or game-root copies; run `status` at session start
```

Kenshi — `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\MEMORY.md`, inserted as the new first list item (above the Windows tooling paths line):

```markdown
- [modkit install toolkit](modkit.md) — preset NOT built yet: only intake/stage/status work with `--game kenshi` (verified full-extract staging); deploy/remove/verify hard-error, conflicts is a silent no-op (never trust it — use the manual conflict-sweep workflow); NEVER hand-roll 7z extraction
```

## Accuracy corrections vs. task-17-brief.md

The brief's Kenshi pin (both `modkit.md` body and index line) described only "no vets/deploy/verify/remove for Kenshi yet" without detail. Verified against the as-built tool (`modkit/games/__init__.py` reads `data_dir` from `modkit.json`; Kenshi's entry has `"data_dir": null`; `modkit/conflicts.py:sweep()` returns `[]` immediately when `preset.DATA_DIR is None`, so `conflicts --game kenshi` prints `"no file overlaps vs Data"` at exit 0 without ever comparing files) and against `adoption/mod-install-SKILL.md`'s Kenshi section (same finding, already corrected there in commit 930ad99). The pins above were written to match: `deploy`/`remove`/`verify` hard-error at exit 1 (not just "unavailable"), and `conflicts --game kenshi` is called out explicitly as a **silent no-op that must not be trusted** — resolving a real gap between the brief and the shipped behavior before it could propagate into session-start recall.
