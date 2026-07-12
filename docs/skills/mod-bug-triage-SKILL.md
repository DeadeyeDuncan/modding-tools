---
name: mod-bug-triage
description: Use when the user reports a bug in a modded game session (Skyrim SE, Kenshi, Cyberpunk 2077, RDR2) — a crash/CTD, hard freeze, FPS drop or stutter, visual defect (purple or black textures, invisible objects or geometry, flicker, missing meshes), or broken in-game behavior. Trigger phrases include "the game is crashing", "the game froze", "textures look wrong", "invisible object", "fps tanked", "this mod broke it", or any in-game symptom reported after installing, removing, or updating mods.
---

# Mod Bug Triage

## Overview

Ground truth before hypotheses. A game relaunch is the most expensive diagnostic instrument available — spend it last, and never spend it to test a guess that cheaper evidence (console click, runtime log, ledger tail, screenshot) could confirm or kill first.

This skill is the game-modding specialization of superpowers:systematic-debugging (wiki: [[concepts/systematic-debugging-methodology]]). It exists because the worst sessions on record were serial guess-edit-relaunch loops: ~20 launch-tests in one night, five user rebukes, and a phantom bug manufactured by the loop itself.

Game-specific ground-truth surfaces (exact log paths, installed diagnostic mods, ledger coverage) live in the game project's memory — read `triage.md` there first.

## When to Use

- Any in-game symptom in a modded install: crash, freeze, FPS drop, wrong or missing visuals, broken mechanics.
- NOT for install-time verification (the install workflow owns that) and NOT for modding-GUI-tool failures (config-file-first convention owns those).

## The Protocol

### 1. Symptom questionnaire FIRST
Before any hypothesis, ask the user:
- Exactly which location / object / action shows the symptom?
- When did it start — when was it last known good?
- What changed since — installs, removals, INI edits, GUI-tool runs (DynDOLOD/BodySlide/Wrye Bash), driver or Windows updates?

Then pull the change record yourself: `py -3 C:\Modding\tools\ledger.py list --game <skyrim|cp77> --since <last-known-good-date>` (other games: `--ledger <path>` if a ledger exists, else the game's manifest dir). Questionnaires have redirected a diagnosis before the first tool call more than once, and one reported "bug" was a change the user had made deliberately between sessions.

### 2. Ground truth before hypotheses
Collect what the game itself says before proposing any cause:
- **In-game identity:** More Informative Console click on the broken object — form ID, mesh/texture path, owning plugin ([[concepts/skyrim-more-informative-console]]). MIC-first has pinned root causes in one shot, repeatedly.
- **Runtime logs:** crash log ([[concepts/skyrim-crash-log-reading]]); Papyrus.0.log ([[concepts/skyrim-papyrus-profiling-script-lag]]); Base Object Swapper runtime log ([[concepts/skyrim-base-object-swapper]]) — a BOS log once held the root cause while static-data analysis kept concluding "nothing is missing"; the in-game console. CP77 logs are decentralized per framework ([[concepts/cyberpunk-2077-crash-diagnostics]]).
- **Session memory:** scan the game project's MEMORY.md for a matching solved-symptom note BEFORE re-diagnosing — several past symptoms (TP-shop FPS, crosshair FPS, purple textures, invisible floors) have one-line answers on file.

### 3. Single-variable tests; batch fixes per relaunch
Each launch tests ONE variable. If several independent fixes are each already evidence-backed, apply them all before a single relaunch — relaunches are the scarce resource. Never bundle speculative changes; you cannot isolate what worked. A single-variable toggle once split "one bug" into two independent bugs.

### 4. HARD CAP: two failed launch-tests, then STOP
No third hypothesis. Revert to the last known-good state, then return to evidence gathering (rule 2, screenshots, wiki and memory search). Not negotiable — see [[concepts/three-failures-equals-architecture-problem]]: by the second failed launch-test the broken thing is your model of the bug, not the fix.

### 5. Research verdicts are hypotheses
Deep-research, community-thread, and adversarially-verified desk conclusions stay labeled HYPOTHESIS until one in-game test confirms them. Desk verdicts have been refuted by a single in-game test — twice in one session ([[connections/skyrim-verify-mod-artifact-not-claim]]).

### 6. Before/after screenshots early
Ask for a screenshot of the symptom before changing anything, and after each candidate fix. Screenshots have corrected multiple premature "root cause nailed" claims; the user's in-game observation outranks any static-data conclusion.

### 7. Never claim "fixed"
Until the user confirms in-game at the original location, the only permitted claim is "candidate fix applied — please verify in-game." Writing "fixed" or "root cause confirmed" before that confirmation is a protocol violation.

### 8. Force-kill count triggers a reboot gate
Track force-kills of the game process this session. After 2 or more, require a reboot before drawing ANY further conclusion. Force-killing a GPU-hung game corrupts driver/GPU state and manufactures phantom bugs; a hard freeze that survived every mod toggle once cleared on reboot (Skyrim memory: `hard-freeze-reboot-test.md`). Freeze + no crash log + no TDR event = suspect system state first, not a mod.

## First-Move Table

| Symptom | First move |
|---|---|
| Visual defect on a specific object | MIC click it (rule 2): mesh/texture path + owning mod |
| CTD | Newest crash log ([[concepts/skyrim-crash-log-reading]]) / CP77 per-framework logs |
| Hard freeze, no crash log, no TDR | Reboot test BEFORE any mod toggling (`hard-freeze-reboot-test.md`) |
| FPS drop on crosshair/HUD focus | Memory precedent `sse-morehud-crosshair-fps.md`, then single-variable HUD bisect |
| FPS drop, general | [[concepts/skyrim-performance-triage-gpu-cpu-script]] (GPU vs CPU vs script) |
| Invisible object / hole in the world | MIC nearby refs + loose-vs-BSA fallback check (`sse-over-revert-invisible-holes.md`) |
| Anything right after an install/remove | Rule 1 questionnaire + ledger tail |

## Red Flags — STOP and return to rule 2

- About to relaunch without stating which single variable this launch tests
- A third hypothesis forming after two failed launch-tests
- "Research says X, so it is fixed" without an in-game confirmation
- Writing "fixed" or "root cause confirmed" before user verification
- Reasoning about a freeze after 2+ force-kills without a reboot
