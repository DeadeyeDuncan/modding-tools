# modkit memory pins - provenance copy; live masters in C:\Users\auand\.claude\projects\<slug>\memory\modkit.md / snapshot.md

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
**How to apply:** NEVER hand-roll 7z x / Expand-Archive / robocopy-to-Data / Plugins.txt writes / ledger.json edits - modkit owns them. ledger.py stays the sole ledger writer (modkit calls it). An advisory PreToolUse guard (`C:\Modding\tools\adoption\modkit-guard.py`) is active and flags hand-rolled extraction/Data-copy/Plugins.txt/ledger.json edits mid-session - it never blocks, only warns. Config: C:\Modding\tools\modkit.json. Spec/plan: C:\Modding\tools\docs\2026-07-11-modkit-*.md.
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

## Snapshot — Skyrim

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\snapshot.md`

```markdown
---
name: snapshot
description: session-state snapshots + open-items via modkit — diff & openitems list at session START, take at session END / after installs; unexplained deltas = ASK THE USER, not bugs
metadata:
  type: project
---

Session-state drift and pending fixes are managed by modkit
(`py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim`):

- **Session START (every modding session):**
  `py -3 C:\Modding\tools\modkit.py snapshot diff --game skyrim`
  `py -3 C:\Modding\tools\modkit.py openitems list --game skyrim`
  Exit 2 from diff = drift or warnings — read the report. **Unexplained deltas
  are questions for the user ("what did you change manually?"), NOT bugs to
  fix** (Precision.esp was disabled by choice 2026-07-01 and a session-start
  audit wrongly flagged it as an urgent bug).
- **Session END and after every install batch:**
  `py -3 C:\Modding\tools\modkit.py snapshot take --game skyrim`
- Any root-caused-but-not-executed fix gets
  `py -3 C:\Modding\tools\modkit.py openitems add --game skyrim "<item>"`
  BEFORE the session ends (XPMSE/Bashed-Patch fixes sat unexecuted for weeks
  when they lived only in prose notes).
- Snapshots: `C:\Modding\skyrim-manual\snapshots\snapshot-<ts>.json` (plugin
  list + normalized SHA256 + counts, SKSE DLL list, watched INI keys, watched
  ENB flags, ledger counts, Steam AutoUpdateBehavior). Open items:
  `C:\Modding\skyrim-manual\open-items.md` (checkbox markdown; hand-edits are
  fine — the parser is tolerant).
- Steam AutoUpdateBehavior must stay **1** ("only update when I launch") —
  anything else risks an unattended update breaking the SKSE loader chain
  (RDR2 was 10 hours from exactly that, 2026-07-01). take/diff WARN when it
  is not 1. **Live 2026-07-12: it is currently 0 ("always keep updated") —
  fix in Steam > Properties > Updates before the next launch.**
- Watched INI/ENB key lists live in `C:\Modding\tools\modkit.json` under
  `snapshot.skyrim` — extend by editing config, not code.

**Why:** stale baselines cost ~30 tool calls per session-start re-audit
(reflection-notes.md #9). **How:** never hand-write snapshot files; snapshot
never writes into game dirs (reads only).
```

## Snapshot — Cyberpunk 2077

`C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\snapshot.md`

```markdown
---
name: snapshot
description: session-state snapshots + open-items via modkit — diff & openitems list at session START, take at session END / after installs; unexplained deltas = ASK THE USER, not bugs
metadata:
  type: project
---

Session-state drift and pending fixes are managed by modkit
(`py -3 C:\Modding\tools\modkit.py <cmd> --game cp77`):

- **Session START (every modding session):**
  `py -3 C:\Modding\tools\modkit.py snapshot diff --game cp77`
  `py -3 C:\Modding\tools\modkit.py openitems list --game cp77`
  Exit 2 from diff = drift or warnings — read the report. **Unexplained deltas
  are questions for the user ("what did you change manually?"), NOT bugs to
  fix** (Skyrim lesson 2026-07-01: Precision.esp was disabled by choice and
  got flagged as an urgent bug).
- **Session END and after every install batch:**
  `py -3 C:\Modding\tools\modkit.py snapshot take --game cp77`
- Any root-caused-but-not-executed fix gets
  `py -3 C:\Modding\tools\modkit.py openitems add --game cp77 "<item>"`
  BEFORE the session ends.
- Snapshots: `C:\Modding\cyberpunk-manual\snapshots\snapshot-<ts>.json`;
  open items: `C:\Modding\cyberpunk-manual\open-items.md` (checkbox markdown;
  hand-edits are fine — the parser is tolerant).
- CP77 is the THIN preset: the snapshot currently captures ledger counts +
  Steam AutoUpdateBehavior only (no Plugins.txt/SKSE/ENB/INI equivalents
  configured). Plugin/DLL/INI/ENB watch sections appear automatically if
  configured later under `snapshot.cp77` in `C:\Modding\tools\modkit.json`
  (e.g. `dllDir` pointed at `red4ext\plugins`).
- Steam AutoUpdateBehavior must stay **1** ("only update when I launch") —
  anything else risks an unattended update breaking the RED4ext loader chain
  (RDR2 was 10 hours from exactly that, 2026-07-01). take/diff WARN when it
  is not 1. **Live 2026-07-12: it is currently 0 ("always keep updated") —
  fix in Steam > Properties > Updates before the next launch.**

**Why:** stale baselines cost ~30 tool calls per session-start re-audit
(reflection-notes.md #9). **How:** never hand-write snapshot files; snapshot
never writes into game dirs (reads only).
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

Skyrim (Task 9, 2026-07-12) — inserted as the new first list item, above the modkit install-toolkit line above:

```markdown
- [Snapshot + open items](snapshot.md) — session START: `modkit snapshot diff` + `openitems list`; session END/installs: `snapshot take`; unexplained deltas = ASK THE USER, not bugs; Steam AutoUpdateBehavior must stay 1
```

Cyberpunk 2077 (Task 9, 2026-07-12) — inserted as the new first list item, above the modkit install-toolkit line above:

```markdown
- [Snapshot + open items](snapshot.md) — session START: `modkit snapshot diff` + `openitems list`; session END/installs: `snapshot take`; unexplained deltas = ASK THE USER, not bugs; Steam AutoUpdateBehavior must stay 1
```

## Accuracy corrections vs. task-17-brief.md

The brief's Kenshi pin (both `modkit.md` body and index line) described only "no vets/deploy/verify/remove for Kenshi yet" without detail. Verified against the as-built tool (`modkit/games/__init__.py` reads `data_dir` from `modkit.json`; Kenshi's entry has `"data_dir": null`; `modkit/conflicts.py:sweep()` returns `[]` immediately when `preset.DATA_DIR is None`, so `conflicts --game kenshi` prints `"no file overlaps vs Data"` at exit 0 without ever comparing files) and against `adoption/mod-install-SKILL.md`'s Kenshi section (same finding, already corrected there in commit 930ad99). The pins above were written to match: `deploy`/`remove`/`verify` hard-error at exit 1 (not just "unavailable"), and `conflicts --game kenshi` is called out explicitly as a **silent no-op that must not be trusted** — resolving a real gap between the brief and the shipped behavior before it could propagate into session-start recall.

## Task 9 addition (2026-07-12): real snapshot config + memory pins

`task-9-brief.md` did not explicitly ask for a provenance copy of the snapshot pins in this file — only the two live `~/.claude/projects/.../memory/snapshot.md` files + their `MEMORY.md` index lines were specified. This section was added on top of the brief, matching the established convention this file already set for the `modkit.md` pins (Task 17), so the snapshot pins have the same durable, versioned record. `py -3 C:\Modding\tools\modkit.py snapshot take` was run once for real against both games during verification (read-only against game dirs, writes only under `<game>-manual\snapshots\`); it surfaced a genuine live finding baked into the pins above: Steam `AutoUpdateBehavior` is currently `0` ("always keep updated") for BOTH Skyrim and Cyberpunk 2077, not the required `1` — this is exactly the RDR2-near-miss failure mode the plan's warning exists to catch, and is a real action item for the user, not a config bug.
