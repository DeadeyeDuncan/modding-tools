# mod-bug-triage Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a user-level `mod-bug-triage` Claude Code skill that encodes the 8-rule diagnostics-first triage protocol from `H:\DeadMind V.3\reflection-notes.md` section 7, seed per-game memory pointers so every game-dir session finds it, and version a copy in the C:\Modding\tools repo.

**Architecture:** This is a pure DOCUMENT build — four prose deliverables, zero code. The skill lives at user level (`C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md`) so it loads in every game-dir session regardless of drive letter. It references existing wiki articles by `[[wikilink]]` and per-game memory files by filename instead of duplicating their content. Per-game `triage.md` memory files carry the game-specific ground-truth surfaces (log paths, tool availability) that the game-agnostic skill cannot hardcode.

**Tech Stack:** Markdown only. PowerShell 5.1 / built-in tools for verification commands. Git for the repo-copy commit (repo: `C:\Modding\tools` — confirmed a git repo).

## Global Constraints

- **Advisory prose only.** No scripts, no code files, no executable components. The skill instructs; existing tools (`ledger.py`, MIC, logs) do the work.
- **No wholesale duplication.** Wiki content is referenced by `[[wikilink]]`, memory files by filename. Never paste article bodies into the skill.
- **SKILL.md ≤ ~150 lines total** (frontmatter included) so it loads cheap. Verify with a line count.
- **All 8 protocol rules** from reflection-notes section 7 must be present and individually identifiable (numbered).
- **Frontmatter:** `name: mod-bug-triage`; `description` in third person, starts with "Use when", triggering conditions ONLY (no workflow summary — per superpowers:writing-skills SDO rules), total frontmatter under 1024 chars.
- **Repo boundary:** only files under `C:\Modding\tools` get committed. The live SKILL.md and all memory files live OUTSIDE the repo and are never git-tracked. The repo carries a versioned COPY at `docs\skills\mod-bug-triage-SKILL.md`.
- **Do not edit wiki files** under `H:\DeadMind V.3\claude-memory-compiler\knowledge\` — wiki edits belong to the compile-memory pipeline.
- **Kenshi seeding targets `E--SteamLibrary-steamapps-common-Kenshi` only.** The `G--...-Kenshi` project dir is stale (last touched 2026-06-08; the 2026-07-04 trivial-batch memories went to E:).
- **ledger.py invocation must match the verified CLI:** subcommand `list` exists (flags `--active`, `--removed`, `--since`, `--count`); `--game` accepts ONLY `skyrim | cp77`; any other game needs `--ledger <path>`. Do not write `--game kenshi` anywhere.
- **Windows shell conventions apply** (per-game memory `windows-shell-conventions.md`): use the Write/Edit tools for file content — never shell heredocs; beware PS 5.1 default ANSI encoding when appending to UTF-8 files (use the Edit tool for MEMORY.md appends).

## File Structure

| File | Role | Git-tracked? |
|---|---|---|
| `C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md` | The live skill (user-level; dir does not exist yet — create it) | No |
| `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\triage.md` | Skyrim ground-truth pointers | No |
| `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\triage.md` | CP77 ground-truth pointers | No |
| `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\triage.md` | Kenshi ground-truth pointers | No |
| 3 × `memory\MEMORY.md` | One appended pointer line each | No |
| `C:\Modding\tools\docs\skills\mod-bug-triage-SKILL.md` | Versioned copy of the skill | **Yes** |
| `C:\Modding\tools\docs\2026-07-11-mod-bug-triage-skill-plan.md` | This plan | **Yes** |

---

### Task 1: Write the SKILL.md

**Files:**
- Create: `C:\Users\auand\.claude\skills\mod-bug-triage\` (directory)
- Create: `C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the canonical SKILL.md text. Task 2's triage.md files refer to the skill by name `mod-bug-triage`; Task 3 copies this exact file byte-for-byte; Task 4's rubric is scored against this text.

- [ ] **Step 1: Create the skill directory**

Run (PowerShell):
```powershell
New-Item -ItemType Directory -Force "C:\Users\auand\.claude\skills\mod-bug-triage"
```
Expected: directory created (the `C:\Users\auand\.claude\skills` parent does not exist yet either; `-Force` creates the chain).

- [ ] **Step 2: Write SKILL.md with exactly this content**

Use the Write tool. File: `C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md`. Content (everything inside the fence, verbatim):

```markdown
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
```

- [ ] **Step 3: Verify size and frontmatter**

Run (PowerShell):
```powershell
(Get-Content "C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md" | Measure-Object -Line).Lines
Select-String -Path "C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md" -Pattern "^name: mod-bug-triage$", "^description: Use when"
```
Expected: line count ≤ 150 (content above is 73 lines); both frontmatter patterns match. If line count exceeds 150, trim the Overview — never the eight numbered rules.

- [ ] **Step 4: Verify every wikilink resolves in the wiki**

The skill references exactly these 8 slugs. Confirm each exists in `titles.tsv`:
```powershell
$slugs = "concepts/systematic-debugging-methodology","concepts/skyrim-more-informative-console","concepts/skyrim-crash-log-reading","concepts/skyrim-papyrus-profiling-script-lag","concepts/skyrim-base-object-swapper","concepts/cyberpunk-2077-crash-diagnostics","concepts/three-failures-equals-architecture-problem","connections/skyrim-verify-mod-artifact-not-claim"
$tsv = Get-Content "H:\DeadMind V.3\claude-memory-compiler\knowledge\titles.tsv"
$slugs | ForEach-Object { $s=$_; if ($tsv -match [regex]::Escape($s)) { "OK  $s" } else { "MISSING  $s" } }
```
Expected: 8 × `OK`. (All 8 were verified present on 2026-07-11 while authoring this plan. If H: is mounted under a different letter on this machine, resolve the wiki root per the drive-map line injected at session start.) If any prints `MISSING`, fix the wikilink in SKILL.md to the nearest real slug — do not invent slugs.

*(No commit — this file lives outside any git repo. The versioned copy is committed in Task 3.)*

---

### Task 2: Seed per-game memory pointers (Skyrim, CP77, Kenshi)

**Files:**
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\triage.md`
- Modify: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\MEMORY.md` (append 1 line; current last line is the `[EngineFixes Dismember Crash Watch]` bullet)
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\triage.md`
- Modify: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\MEMORY.md` (append 1 line; current last line is the `[DeadMind wiki location]` bullet)
- Create: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\triage.md`
- Modify: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\MEMORY.md` (append 1 line; current last line is the `[Big Business Xtreme clean mod]` bullet)

**Interfaces:**
- Consumes: the skill name `mod-bug-triage` and the rule numbers from Task 1 (referenced, not restated).
- Produces: three `triage.md` files named exactly `triage.md`, each linked from its MEMORY.md via the exact pointer lines below. Task 4's rubric assumes these filenames.

- [ ] **Step 1: Verify Skyrim log paths on disk before writing them into memory**

The SKSE crash-log location has historically cost 6 wrong probes in one session — pin it from disk, not from recall:
```powershell
Get-ChildItem "$env:USERPROFILE\Documents\My Games\Skyrim Special Edition\SKSE\crash-*.log" -ErrorAction SilentlyContinue | Select-Object -Last 2 -ExpandProperty FullName
Get-ChildItem "$env:USERPROFILE\Documents\My Games\Skyrim Special Edition\SKSE\po3_BaseObjectSwapper.log" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
Get-ChildItem "$env:USERPROFILE\Documents\My Games\Skyrim Special Edition\Logs\Script\Papyrus.0.log" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
```
Expected: three real paths print. If any prints nothing, search once with `Get-ChildItem -Recurse -Filter <name> "$env:USERPROFILE\Documents\My Games"` and substitute the found path in Step 2's content. Only the path lines may change; all other content is fixed.

- [ ] **Step 2: Write the Skyrim triage.md**

Use the Write tool. File: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\triage.md`. Content (substitute paths ONLY if Step 1 found them elsewhere):

```markdown
# Mod Bug Triage — Skyrim ground truth

The user-level `mod-bug-triage` skill applies to any in-game bug report. Skyrim-specific surfaces for its rules 1-2:

- MIC (More Informative Console, Nexus 19250) IS INSTALLED — click the broken object in-console first.
- Crash logs: `%USERPROFILE%\Documents\My Games\Skyrim Special Edition\SKSE\crash-*.log` (Crash Logger SSE — NOT .NET Script Framework).
- Papyrus log: `%USERPROFILE%\Documents\My Games\Skyrim Special Edition\Logs\Script\Papyrus.0.log` (needs Papyrus logging enabled in Skyrim.ini).
- BOS runtime log: `%USERPROFILE%\Documents\My Games\Skyrim Special Edition\SKSE\po3_BaseObjectSwapper.log` — check whenever a `_SWAP.ini` mod is in play; it once held a root cause static data called impossible.
- Ledger tail: `py -3 C:\Modding\tools\ledger.py list --game skyrim --since <date>`.
- Hard freeze, no crash log, no TDR: reboot test FIRST — see [hard-freeze-reboot-test.md](hard-freeze-reboot-test.md).
- Before re-diagnosing anything, scan MEMORY.md for the matching solved note: TP-shop FPS (`sse-tp-shop-fps-enb-shadow.md`), crosshair FPS (`sse-morehud-crosshair-fps.md`), purple textures (`sse-parallax-removal-purple.md`), invisible floors (`sse-over-revert-invisible-holes.md`).
```

- [ ] **Step 3: Append the Skyrim MEMORY.md pointer line**

Use the Edit tool on `...\Skyrim-Special-Edition\memory\MEMORY.md` (Read it first; anchor on its current final line — the `[EngineFixes Dismember Crash Watch]` bullet — and append after it). Exact new line:

```
- [Mod Bug Triage](triage.md) — user-level `mod-bug-triage` skill governs ALL in-game bug reports (questionnaire → ground truth → 2-failed-launch cap); Skyrim surfaces: MIC-first, SKSE crash-*.log / Papyrus.0.log / BOS log paths, ledger tail, freeze = reboot-test
```

- [ ] **Step 4: Write the CP77 triage.md**

Use the Write tool. File: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\triage.md`. Content:

```markdown
# Mod Bug Triage — CP77 ground truth

The user-level `mod-bug-triage` skill applies to any in-game bug report. CP77-specific surfaces for its rules 1-2:

- Crash/runtime logs are DECENTRALIZED per framework — no single crash log. Check each installed framework's own log (red4ext, ArchiveXL/TweakXL, CET) and bisect by framework; see wiki [[concepts/cyberpunk-2077-crash-diagnostics]].
- Ledger tail: `py -3 C:\Modding\tools\ledger.py list --game cp77 --since <date>`.
- Baseline: game v2.31, manual/no-VFS install discipline, staging at `C:\Modding\cyberpunk-manual` (see `project_cp2077_modding_start.md`).
- No MIC equivalent exists here — object-level ground truth comes from archive-prefix conflict scans and framework logs, not console clicks.
```

- [ ] **Step 5: Append the CP77 MEMORY.md pointer line**

Use the Edit tool on `...\Cyberpunk-2077\memory\MEMORY.md` (Read first; anchor on its current final line — the `[DeadMind wiki location]` bullet). Exact new line:

```
- [Mod Bug Triage](triage.md) — user-level `mod-bug-triage` skill governs ALL in-game bug reports (questionnaire → ground truth → 2-failed-launch cap); CP77 surfaces: per-framework logs (no single crash log), ledger tail via --game cp77
```

- [ ] **Step 6: Write the Kenshi triage.md**

Use the Write tool. File: `C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\triage.md`. Content:

```markdown
# Mod Bug Triage — Kenshi ground truth

The user-level `mod-bug-triage` skill applies to any in-game bug report. Kenshi-specific surfaces for its rules 1-2:

- ledger.py has NO kenshi registration (`--game` accepts skyrim|cp77 only) — mod-state ground truth is `Data\mods.cfg` + per-mod folders; pass `--ledger <path>` only if a Kenshi ledger.json is ever created.
- Load-order / missing-master issues: check `.mod` header masters first — see [kenshi-mod-dependency-strip.md](kenshi-mod-dependency-strip.md).
- Crash precedent: the recurring desert crash was DRIVE FAILURE, not a mod (wiki [[concepts/kenshi-desert-crash-drive-failure]]) — rule out hardware/system state before mod bisection, matching skill rule 8.
- After any mod change, re-run the conflict sweep (`kenshi_conflict_sweep.ps1`) before blaming a new mod for an old overlap.
```

- [ ] **Step 7: Append the Kenshi MEMORY.md pointer line**

Use the Edit tool on `...\E--SteamLibrary-steamapps-common-Kenshi\memory\MEMORY.md` (Read first; anchor on its current final line — the `[Big Business Xtreme clean mod]` bullet). Exact new line:

```
- [Mod Bug Triage](triage.md) — user-level `mod-bug-triage` skill governs ALL in-game bug reports (questionnaire → ground truth → 2-failed-launch cap); Kenshi surfaces: mods.cfg not ledger.py, .mod master checks, desert-crash = drive-failure precedent
```

- [ ] **Step 8: Verify all six memory artifacts**

```powershell
$files = @(
  "C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Skyrim-Special-Edition\memory\triage.md",
  "C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Cyberpunk-2077\memory\triage.md",
  "C:\Users\auand\.claude\projects\E--SteamLibrary-steamapps-common-Kenshi\memory\triage.md"
)
$files | ForEach-Object { if (Test-Path $_) { "OK  $_" } else { "MISSING  $_" } }
$files | ForEach-Object { Select-String -Path ($_ -replace "triage\.md$","MEMORY.md") -Pattern "Mod Bug Triage" | Select-Object -First 1 }
```
Expected: 3 × `OK`, then 3 matching MEMORY.md lines. Also visually confirm the appended lines render as list bullets (leading `- `) and the em dashes did not mojibake (open each MEMORY.md with the Read tool; `—` must appear as an em dash).

*(No commit — all six files live outside any git repo by policy.)*

---

### Task 3: Commit the versioned copies into C:\Modding\tools

**Files:**
- Create: `C:\Modding\tools\docs\skills\` (directory)
- Create: `C:\Modding\tools\docs\skills\mod-bug-triage-SKILL.md` (byte-for-byte copy of the live SKILL.md)
- Commit: the copy + `C:\Modding\tools\docs\2026-07-11-mod-bug-triage-skill-plan.md` (this plan)

**Interfaces:**
- Consumes: `C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md` from Task 1 (final, post-verification text).
- Produces: a git-tracked snapshot. Future skill edits must re-copy here and re-commit (note this in the commit body).

- [ ] **Step 1: Copy the skill into the repo**

```powershell
New-Item -ItemType Directory -Force "C:\Modding\tools\docs\skills"
Copy-Item "C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md" "C:\Modding\tools\docs\skills\mod-bug-triage-SKILL.md" -Force
```
Expected: file exists; `Get-FileHash` of source and copy match.

- [ ] **Step 2: Stage exactly the two intended files**

```powershell
git -C C:\Modding\tools add "docs/skills/mod-bug-triage-SKILL.md" "docs/2026-07-11-mod-bug-triage-skill-plan.md"
git -C C:\Modding\tools status --short
```
Expected: exactly two `A ` (or one `A ` + one `M ` if the plan was pre-committed) entries for those paths. If unrelated files show as staged, unstage them — this commit carries only the triage-skill docs. (An untracked `docs/2026-07-11-modkit-design.md` may exist in the worktree — leave it alone.)

- [ ] **Step 3: Commit**

```powershell
git -C C:\Modding\tools commit -m "docs: add mod-bug-triage skill (plan + versioned SKILL.md copy)"
```
Commit body (second `-m`): `Live skill is at C:\Users\auand\.claude\skills\mod-bug-triage\SKILL.md (user-level, not git-tracked). docs/skills/mod-bug-triage-SKILL.md is the versioned snapshot - re-copy on every future skill edit. Encodes reflection-notes.md section 7 (8-rule triage protocol).`
Expected: clean commit; `git -C C:\Modding\tools status --short` shows the two files gone from staging.

---

### Task 4: Dry-run verification rubric (the skill's "test suite")

A prose skill cannot be unit-tested, and live pressure-testing needs an actual game session. The substitute gate: replay three historical bug reports against the finished SKILL.md and confirm the text routes each to the documented right first move. Preferred execution: dispatch one fresh subagent per scenario with ONLY (a) the full SKILL.md text and (b) the scenario paragraph, asking "what is your first move?" — a fresh reader is a stronger test than self-review. Self-review by re-reading the skill is the acceptable fallback.

**Files:**
- Modify: `C:\Modding\tools\docs\2026-07-11-mod-bug-triage-skill-plan.md` (append results under this rubric)

**Interfaces:**
- Consumes: final SKILL.md text (Task 1), memory filenames (Task 2).
- Produces: a recorded PASS/FAIL per scenario, committed to the repo.

**Scenario A — invisible geometry** (history: the 06-27→29 Embershard/over-revert saga; `sse-over-revert-invisible-holes.md`).
User report: *"There's a hole in the floor in Embershard Mine — I walked in and fell straight through the world. There's also a boulder floating near the entrance. This worked fine last week; since then we did that big parallax mesh revert."*
**Expected routing:** Rule 1 questionnaire is largely pre-answered (location, timing, the revert as the change) → the skill must NOT relaunch or start toggling mods; first move is rule 2 / First-Move-Table row "Invisible object / hole in the world": MIC click nearby visible refs to identify the cell's mesh paths, then the loose-vs-BSA fallback check against the reverted mesh list (per `sse-over-revert-invisible-holes.md` — deleted MOD-named meshes with no BSA fallback). FAIL if the first move is a hypothesis about a specific mod, a mod toggle, or a relaunch.

**Scenario B — crosshair FPS drop** (history: the 06-30→07-01 TrueHUD/moreHUD/BTPS investigation; `sse-morehud-crosshair-fps.md`).
User report: *"FPS tanks the second my crosshair lands on anything — items, doors, NPCs. Looking at empty terrain it's buttery smooth. It's been like this for a few days."*
**Expected routing:** Rule 1 questionnaire (when did it start, what changed) + ledger tail for that window; then rule 2 "session memory" step MUST surface `sse-morehud-crosshair-fps.md` (two stacked causes precedent — moreHUD removed, BTPS GFx cache fixed, TrueHUD = NPC-only contributor to KEEP) before any uninstall; any launch-testing that follows must be a single-variable HUD bisect (rule 3). FAIL if the skill text leads to uninstalling a HUD mod before the memory scan, or to bundled removals.

**Scenario C — hard freeze** (history: the 06-25/26 freeze whack-a-mole night; `hard-freeze-reboot-test.md`, `sse-vram-budget.md`).
User report: *"Game hard-froze near Whiterun — full lockup, had to force-kill it. That's the second force-kill tonight. No crash log showed up."*
**Expected routing:** Rule 8 fires: 2 force-kills + no crash log → require a reboot BEFORE any further conclusion; rule 2 limited to confirming the absence of `crash-*.log` and of a TDR event; explicitly NO mod toggling and NO relaunch loop (the 06-25 freeze survived mod toggles and cleared on reboot — system state, not a mod). FAIL if the first move is a mod hypothesis, a VRAM conclusion, or a relaunch.

- [ ] **Step 1: Run the three scenarios** (subagent-per-scenario preferred; fresh self-read fallback) and record each first move verbatim.

- [ ] **Step 2: Score against expected routing** — one PASS/FAIL per scenario with a one-line justification. Any FAIL: fix the SKILL.md wording that misrouted (usually the First-Move Table or an over-general rule), re-copy to `docs\skills\mod-bug-triage-SKILL.md`, and re-run that scenario.

- [ ] **Step 3: Protocol-coverage checklist** — confirm in the final SKILL.md:
  - [ ] All 8 rules present as numbered `### N.` sections matching reflection-notes section 7 intent
  - [ ] `ledger.py list` command appears with the `<skyrim|cp77>` constraint (rule 1)
  - [ ] MIC + BOS/SKSE-crash/Papyrus/console all named (rule 2)
  - [ ] The 2-failed-launch hard cap says STOP + revert + no third hypothesis (rule 4)
  - [ ] No placeholder text anywhere (`TBD`, `TODO`, `fill in`, `etc. as needed`)
  - [ ] Line count still ≤ 150 after any fixes

- [ ] **Step 4: Append results to this plan under "## Dry-Run Results (appended at execution)"** — scenario, first move observed, PASS/FAIL, fixes made.

- [ ] **Step 5: Commit the results (and the re-copied skill snapshot, if Step 2 changed it)**

```powershell
git -C C:\Modding\tools add "docs/2026-07-11-mod-bug-triage-skill-plan.md" "docs/skills/mod-bug-triage-SKILL.md"
git -C C:\Modding\tools commit -m "docs: record mod-bug-triage dry-run results (3 scenarios)"
```
Expected: clean commit.

---

## Execution Handoff

**Plan complete and saved to `C:\Modding\tools\docs\2026-07-11-mod-bug-triage-skill-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using superpowers:executing-plans, batch execution with checkpoints.

**Which approach?**

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development
- Fresh subagent per task + two-stage review

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans
- Batch execution with checkpoints for review

## Dry-Run Results (appended at execution) — 2026-07-11

Method: fresh subagent per scenario (general-purpose), given ONLY the SKILL.md text + the scenario paragraph, asked "what is your first move?". 3/3 PASS.

- **Scenario A (invisible geometry / Embershard hole post parallax-revert):** PASS. First move: pull the change record (ledger tail) + read triage.md, explicitly refused any relaunch/toggle/mod-hypothesis, and named `sse-over-revert-invisible-holes.md` as the precedent to scan. No FAIL condition (no mod hypothesis, no toggle, no relaunch) triggered. Note: routed via rule-1 ledger-first rather than leading with the First-Move-Table "Invisible object" MIC/loose-vs-BSA row — acceptable (change is pre-stated, ledger confirms exactly what the revert touched, then feeds the loose-vs-BSA check), no wording change made.
- **Scenario B (crosshair FPS drop):** PASS. First move: ledger tail (--since a-few-days-ago) + scan the named memory precedent `sse-morehud-crosshair-fps.md` before any uninstall; no bundled removals. Matches expected routing exactly.
- **Scenario C (hard freeze, 2nd force-kill, no crash log):** PASS. First move: require a reboot before any diagnosis/toggle/conclusion — cited both rule 8 (2+ force-kill gate) and the First-Move-Table hard-freeze row. Matches expected routing exactly.

Protocol-coverage checklist (against final SKILL.md, 52 counted lines / ≤150):
- [x] All 8 rules present as numbered ### N. sections
- [x] `ledger.py list` with `<skyrim|cp77>` constraint (rule 1)
- [x] MIC + BOS/SKSE-crash/Papyrus/console named (rule 2)
- [x] 2-failed-launch hard cap = STOP + revert + no third hypothesis (rule 4)
- [x] No placeholder text
- [x] Line count ≤ 150

No SKILL.md fixes required (0 FAIL). SKILL.md unchanged since authoring — the docs/skills copy in Task 3 is current.
