# LOD/Bake Regen Runbook (Skyrim SE) — `modkit lodregen`

The regen ritual is PGPatcher → TexGen → DynDOLOD with the DynDOLOD trio
(`DynDOLOD.esm`, `DynDOLOD.esp`, `Occlusion.esp`) OUT of the game for the
duration. `modkit lodregen` brackets it: **all GUI runs are manual — Claude
never launches, drives, clicks, or screenshots a generator GUI.** Claude's
jobs are the brackets, config-file prep, and disk-artifact verification.

Ground truth: wiki `concepts/skyrim-dyndolod-generation`,
`concepts/skyrim-pgpatcher`, `connections/skyrim-pgpatcher-dyndolod-order`.

## CLI flags (verified against `--help`, 2026-07-12)

- `lodregen pre --game GAME [--no-pgpatcher] [--clean-texgen] [--force]`
  `--no-pgpatcher` = this pass skips PGPatcher. `--clean-texgen` = ALSO
  quarantine old TexGen output — default is **never** (see step 1 below);
  only pass this if you deliberately want a from-scratch TexGen clean.
  `--force` = proceed past a pending-run refusal or a missing tool exe.
- `lodregen post --game GAME [--stage {texgen,full}] [--run RUN] [--force]`
  `--stage texgen` = mid-ritual TexGen_Output deploy (step 6); `full`
  (default) = after DynDOLOD (step 8). `--run` targets a specific run dir
  instead of the latest pending one. `--force` = proceed past a
  freshness/masters failure, recorded as a warning — see the Failure
  playbook for which failures this is (and is not) safe to do.
- `lodregen status --game GAME` — no flags beyond `--game`.

## When is a regen needed?

Per the standing rule (sse-dyndolod-rerun-rule memory), every mod install
gets a DynDOLOD verdict. Triggers: tree/flora overhauls, grass LOD changes,
new worldspaces/cities/large exterior statics, mountain/landscape mesh
overhauls, water LOD. Non-triggers: textures, LOD-neutral meshes, sound,
UI, gameplay, NPC face/body, interiors, SKSE DLLs.

## Pre-requisites (check BEFORE bracketing)

- ~30–60+ min of user time; do NOT start at the tail of an all-nighter
  (the stale-LOD-up-close incident was an all-nighter regen).
- Load order FINALIZED — the regen bakes against it.
- Cleaned DLC masters in place (xEdit QuickAutoClean), or DynDOLOD
  hard-stops with "Deleted large references found".
- If PGPatcher is part of this pass: the post-deploy re-run wall — PGPatcher
  refuses with `PGPatcher meshes exist in your data directory, please delete
  before re-running.` if a previous bake is deployed. Clearing that wall
  means wiping all baked meshes and re-opens the orphaned-loose-mesh trap;
  residual visual fixes are usually per-mesh reverts, NOT re-bakes. Decide
  deliberately; when in doubt run `--no-pgpatcher`.
- Grass cache: an existing `Data\grass\*.cgid` cache is reused; only grass
  mesh/record/iMinGrassSize changes force a re-bake (separate procedure,
  sse-grass-lod-plan memory).
- **Verify protected patterns against your real install.** `pre`'s guarded
  clean skips (never deletes) any old-output manifest line matching
  `modkit.json` → `lodregen.<game>.protected_inputs`
  (e.g. `*landscape\statics\rocks01*`). These are `fnmatch` globs and need
  CONTIGUOUS literal path segments to match — if the real install nests an
  extra directory inside a pattern's literal segment, the pattern silently
  fails to match and the file it was meant to protect gets quarantined like
  any other stale output instead. This is a known limitation flagged in
  review (Task 3), not something the code can fully guard against — before
  trusting a clean on a given machine, sanity-check the `protected_inputs`
  list against that machine's actual DynDOLOD/TexGen output tree layout at
  least once. `pre`'s printed `PROTECTED (kept; ...)` lines only tell you
  what WAS matched, not what should have been but wasn't.

## The ritual

1. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen pre --game skyrim`
   (add `--no-pgpatcher` if this pass skips PGPatcher).
   This: refuses if game/tools are running or a regen is already pending;
   snapshots Plugins.txt; DISABLES the trio lines AND MOVES the trio plugin
   files to the holding dir (from-scratch requires the files gone, or
   DynDOLOD errors "DynDOLOD.esp already exists"); quarantines the old
   DynDOLOD output via its ledger manifest — **anything matching the
   protected-inputs list is skipped and reported** (the 9×-recurring clean
   trap: `dyndolodtreelod*`, `dyndolodbackgroundtreelod*`, `holycow*`,
   `mxtundra*`, `version.ini`, `defaultdiffuse*`, `texgen_sse.ini`,
   `statics_e.dds`, `landscape\statics\rocks01*`); checks exes,
   `DynDOLOD_SSE.ini` Wizard=0, NG markers; prints the GUI handoff script.
   TexGen output is NEVER pre-cleaned by default (wiki supersede
   2026-06-25) — `--clean-texgen` overrides this and is not recommended.
2. **[if PGPatcher] Claude:** verify `<PGPatcher>\cfg\settings.json`
   (output dir OUTSIDE Data; Mod Manager = None; no leading TAB in the
   output path). Config-file-first: the user only clicks Start.
3. **[if PGPatcher] USER:** double-clicks `PGPatcher.exe`, clicks Patch,
   reports completion.
4. **[if PGPatcher] Claude:** inspect the output (a run is a de-facto
   dry-run — the output dir is outside Data), then deploy it:
   `robocopy "C:\Modding\PGPatcher\PGPatcher-Output" "<DATA_DIR>" /E`
   (exit <8 = success). The bake does NOTHING until deployed — the June
   0/6610 failure. Record it in the ledger (dated entry, same pattern
   `lodregen post` uses for the LOD outputs). Note: `lodregen post` never
   touches the PGPatcher output itself (it only freshness-gates/deploys
   `texgen` and `dyndolod`) — this deploy-and-record step is manual, always.
5. **USER:** double-clicks `TexGenx64.exe`, runs it. The "Found stitched
   object LOD textures" warning is HARMLESS → click **Ignore**.
6. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen post --game skyrim --stage texgen`
   — freshness-gates TexGen_Output (non-empty, newer than pre; the
   empty-TexGen-exit trap) and deploys it. DynDOLOD must read the DEPLOYED
   textures.
7. **USER:** double-clicks `DynDOLODx64.exe` (user-launched — programmatic
   launches have opened the window off-screen/unclickable). Advanced mode;
   select ALL worldspaces (the selection can reset); Grass LOD ticked with
   Mode matching `GrassControl.ini` (this build: Mode 1) — hover the
   checkbox to confirm it found the .cgid cache; generate.
8. **Claude:** `py -3 C:\Modding\tools\modkit.py lodregen post --game skyrim`
   — freshness-gates DynDOLOD_Output (min file count, newer than pre, trio
   plugins present, fresh `ParallaxGen_Diff.json` if PGPatcher ran);
   verifies the new trio's TES4 masters BEFORE enabling anything (a failure
   here means launching would CTD — this is the guard for the post-reboot
   Plugins.txt-rewrite incident); deploys; re-enables the trio
   `DynDOLOD.esm → DynDOLOD.esp → Occlusion.esp` with Occlusion absolute
   last and verifies the tail; prints the Plugins.txt diff vs the pre
   snapshot (expected: ONLY the trio cycled — anything else = investigate
   before launch); records dated ledger entries.
9. **USER:** launches the game, checks distant LOD (mountains, trees,
   city silhouettes) and reports. Claude tails `ledger.py check --game
   skyrim` for new errors.

## Failure playbook

- **`pre` reports PROTECTED hits** — the old output manifest is polluted
  with input/stand-in files. The files were kept. Re-author the manifest
  from actual tool output only; if an input is missing anyway, no-clobber
  restore from `C:\Modding\tmp\dyndolod-resources` (fills gaps, overwrites
  nothing).
- **`post` FRESHNESS FAIL** — the tool didn't run / wrote elsewhere / exited
  empty. Re-run that GUI stage. Never `--force` past a texgen freshness
  fail into DynDOLOD.
- **`post` MASTERS FAIL** — a master of the new trio is missing/disabled.
  The trio was NOT enabled; the game is safe to leave alone but NOT
  regen-complete. Restore the master (or regen again without it), re-run
  post. Read the printed diff for what changed behind the bracket.
- **TAIL VERIFY FAIL** — something reordered Plugins.txt mid-bracket
  (Wrye Bash scramble class). Fix order with `modkit plugins`, re-run post.
- **Interrupted mid-ritual (crash/reboot/session death)** — the run stays
  PENDING: `modkit lodregen status --game skyrim` at session start shows
  it (exit 2). Do NOT launch the game while pending (trio held aside =
  no distant LOD; a launcher/reboot Plugins.txt rewrite while pending is
  the armed-CTD scenario `post` exists to catch). Resume at the step the
  state shows: `texgen_deployed: null` → resume at step 5/6, else step 7/8.
- **Abandoning a regen** — copy the trio files back from
  `<run_dir>\trio\` into Data, re-enable via `modkit plugins` in trio
  order, restore quarantined output from `<run_dir>\quarantine\`, then
  mark the run: it stays in history; record the abandonment as a ledger
  note on the still-active output entries. (Everything was moved, never
  deleted, so full rollback is always possible.)

## Post-regen leftovers

`<holding_root>\<run_id>\` keeps: the pre/post Plugins.txt snapshots
(via pluginstxt backups), `trio\` (pre-regen plugin files), `quarantine\`
(old output files), `deploy-*.txt` lists, `plugins-diff.txt`, and
`lodregen-run.json`. Prune old run dirs manually once a regen is verified
in-game — never automatically.
