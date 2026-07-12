# Modding-Tools Build Order — Session Handoff

**Date:** 2026-07-11. Plans produced from `H:\DeadMind V.3\reflection-notes.md` verdicts (clusters 1, 6, 7, 8, 9) + the approved modkit design spec (`2026-07-11-modkit-design.md`). Each plan is self-contained: a fresh session executes it with superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

## The five builds

| # | Plan file (docs\) | Deliverable | Depends on |
|---|---|---|---|
| 1 | `2026-07-11-modkit-plan.md` | modkit CLI (Skyrim full + CP77 thin) + mod-install skill + memory pins + advisory hook | ledger.py (shipped) |
| 2 | `2026-07-11-mod-bug-triage-skill-plan.md` | mod-bug-triage skill + memory pins | nothing |
| 3 | `2026-07-11-lod-regen-plan.md` | `modkit lodregen pre/post` + runbook | Build 1 (Tasks 1-2, 9) |
| 4 | `2026-07-11-snapshot-plan.md` | `modkit snapshot` / `openitems` + memory pins | Build 1 (Tasks 1-2, 9) |
| 5 | `2026-07-11-forensics-kit-plan.md` | `forensics\` kit (8 tools) + README + memory pin | Build 1 (Tasks 1, 7) |

## Ordering & collision rules

**All five write to this repo (`C:\Modding\tools`).** Per the wiki lesson [[connections/parallel-sessions-one-working-tree]] (two real collisions on 2026-07-09: foreign edits mid-fix-round, chips queued against a deleted branch), sessions sharing one working tree collide mid-plan.

- **Run Build 1 first, alone.** Everything else consumes its interfaces.
- **Build 2 may run concurrently** with Build 1 — its deliverables live outside the repo — EXCEPT its final "commit versioned copy to docs\skills\" task. Do that step only when `git status` in this repo is clean and no other build session is active.
- **Builds 3, 4, 5: after Build 1 merges, one at a time.** Builds 3 and 4 both edit `modkit\cli.py` dispatch and `modkit.json` schema — parallel = guaranteed conflict. Build 5 only imports from modkit; it could run parallel to 3 or 4 via a git worktree, but sequential is the safe default.
- Commit to `master` directly (repo convention — ledger.py was built the same way) or use a feature branch per build; if branching, delete promptly and never leave two build sessions on different branches of this repo simultaneously.

## Session spawn prompts (copy-paste)

Start each session with cwd `C:\Modding\tools`.

**Build 1:** `Execute the implementation plan at docs\2026-07-11-modkit-plan.md. Read the plan header first — it names the required sub-skill. Design spec at docs\2026-07-11-modkit-design.md is binding. Final acceptance task requires me (the user) present for the live install — pause and tell me when you reach it.`

**Build 2:** `Execute the implementation plan at docs\2026-07-11-mod-bug-triage-skill-plan.md. Read the plan header first — it names the required sub-skill. Hold the final commit-to-repo task until git status here is clean and no other build session is running.`

**Build 3:** `Execute the implementation plan at docs\2026-07-11-lod-regen-plan.md. Read the plan header first. Verify modkit core (docs\2026-07-11-modkit-plan.md) Tasks 1-2 and 9 are merged before starting — run: py -3 C:\Modding\tools\modkit.py --help.`

**Build 4:** `Execute the implementation plan at docs\2026-07-11-snapshot-plan.md. Read the plan header first. Verify modkit core Tasks 1-2 and 9 are merged before starting — run: py -3 C:\Modding\tools\modkit.py --help.`

**Build 5:** `Execute the implementation plan at docs\2026-07-11-forensics-kit-plan.md. Read the plan header first. Verify modkit core Tasks 1 and 7 are merged before starting.`

## Resume discipline

If a build session dies mid-plan (usage limits, PC restart): the plans use checkbox tracking — resume by re-opening the same plan file in a fresh session with the same spawn prompt plus `Resume from the first unchecked step; run the repo's tests first to confirm where reality is.` (Precedent: pause/resume pipeline failure 2026-07-04 — never rely on a scheduled resume; leave yourself an explicit resume line.)

## After each build ships

- Refresh the durable backup mirror (`C:\Users\auand\DeadMind-backup-2026-07-01` refresh applies to the DeadMind repo; this repo's remote/backup convention: commit history is the record).
- The memory-pin tasks inside each plan handle per-game adoption. Wiki articles compile automatically via SessionEnd capture + next /compile-memory.
