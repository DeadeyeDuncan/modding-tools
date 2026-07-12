# modkit — Cross-Game Mod Install Toolkit: Design Spec

**Date:** 2026-07-11
**Status:** Approved (brainstormed interactively; user approved adoption layers, layout, scope, orchestration)
**Origin:** `H:\DeadMind V.3\reflection-notes.md` cluster #1 (top-leverage verdict). Item #3 of the reflection build order (after trivial batch + ledger.py).

## Problem

The install pipeline — locate download → inspect → extract → vet → deploy → Plugins.txt → manifest → ledger → verify → conflict sweep — is re-improvised in fresh inline PowerShell in **every** install session across all 4 games (Skyrim SE, Kenshi, RDR2, CP77), and its known failure modes keep re-firing (see reflection-notes.md §1 for full evidence: FO4 mix-ups ×3, include-pattern extraction failures ×4, Plugins.txt anchor slips ×2, wrong-runtime DLLs shipped, half-installs undetected for days).

## Locked decisions

1. **All 4 adoption layers** (user choice): single CLI + per-game memory pins + `mod-install` skill + advisory PreToolUse hook.
2. **Cross-game single CLI with `--game` presets** (ledger.py pattern), NOT per-game kits.
3. **Scope: Skyrim preset full, CP77 preset thin.** Kenshi/RDR2 presets deferred.
4. **Orchestration approach C: stepwise subcommands + per-install state tracking.** Judgment gates (compat research verdicts, FOMOD picks, conflict decisions) stay with Claude/user between mechanical steps. Warn-not-block gates with `--force` escape.

## Why tools get used (adoption rationale)

ledger.py is used in practice because: ONE command name, ONE memory file per game pinned at the top of MEMORY.md, hard rule ("NEVER hand-edit"). Loose multi-script kits die because discovery cost (recall 8 names + args) exceeds improvisation cost. Hence: one `modkit` entry point, self-documenting `--help`, skill that fires at install-request time with exact commands inline, and a hook that catches hand-rolling attempts mid-session — the only *active* layer.

## Architecture

```
C:\Modding\tools\                      (existing git repo; ledger.py lives here)
  modkit.py                            entry shim: py -3 C:\Modding\tools\modkit.py <cmd> --game skyrim
  modkit\
    __init__.py
    cli.py                             argparse dispatch
    state.py                           install.json state machine
    config.py                          modkit.json loader
    archive.py                         7z wrapper: list/full-extract/verify counts
    peparse.py                         DLL PE parse (runtime range, Address Library dep)
    tes4.py                            ESP/ESM TES4 header parse (masters, ESL flag)
    fomod.py                           ModuleConfig.xml parse + picks apply
    pluginstxt.py                      Plugins.txt manager (BOM/CRLF-safe, anchors, snapshot/diff)
    deploy.py                          robocopy deploy + ledger handoff
    verify.py                          archive-vs-Data diff, _SWAP/_DISTR checks
    conflicts.py                       file-overlap sweep vs Data\ + manifests
    ledger_bridge.py                   subprocess wrapper around ledger.py (sole ledger writer)
    games\
      __init__.py                      preset registry
      skyrim.py                        full preset
      cp77.py                         thin preset
  modkit.json                          machine config: 7z.exe path, Downloads dirs, Vortex dir,
                                       game roots, runtime versions (e.g. skyrim: 1.6.1170)
  tests\test_modkit\*.py               pytest suite (stdlib + pytest, fixtures = synthetic archives)
C:\Modding\staging\<game>\<YYYYMMDD-HHMMSS>-<modslug>\
  payload\                             extracted files
  install.json                         state
```

- **Python 3.13, stdlib only** (ledger.py precedent). External processes: `7z.exe`, `robocopy`, `tasklist`, `py -3 ledger.py`.
- **modkit wraps ledger.py via subprocess** — ledger.py remains the sole ledger/manifest writer. modkit never re-implements or bypasses it.
- Config paths live in `modkit.json`, NOT in code (SSD/multi-machine portability; see deadmind-ssd-multi-machine-portability memory).

## State machine (approach C)

`install.json` per staged install:

```json
{
  "mod": "Simple Dual Sheath",
  "game": "skyrim",
  "archive": "C:\\Users\\auand\\Downloads\\Simple Dual Sheath-50049-1-5-2-1170.7z",
  "nexusId": 50049,
  "stages": { "intake": "<ts>", "staged": "<ts>", "fomod": null, "dllvet": null,
              "esp": null, "conflicts": null, "deployed": null, "recorded": null,
              "verified": null },
  "applicable": { "fomod": false, "dllvet": true, "esp": true },
  "vet_results": {},
  "files": []
}
```

- Applicability computed at `stage` time from payload contents (ModuleConfig.xml present → fomod applicable; `*.dll` under SKSE path → dllvet; `*.es[pml]` → esp). `conflicts` always applicable.
- `deploy` **warns** (does not block) when any applicable vet stamp is missing; `--force` suppresses. Exit code distinguishes clean (0) from warned (2) — the skill tells Claude to treat 2 as "stop and vet".
- `modkit status --game skyrim` lists all staging dirs with incomplete stage chains + last verify result. Run at session start and after crashes — kills the half-install-undetected-for-days class (ICRFixes) and the mid-pipeline session-death class.
- State writes atomic (temp + `os.replace`), ledger.py pattern.

## Subcommands

### Skyrim (full preset)

| Cmd | Behavior | Failure mode it kills |
|---|---|---|
| `intake [path]` | Scan Downloads + Vortex dir (or given file); flag 0-byte; parse Nexus `Name-<modid>-<version>` filename; wrong-game gate (heuristics + `--expect-game`); already-installed check via `ledger.py get/list` | 0-byte downloads ×4; FO4 archives installed as Skyrim ×3; re-downloading installed mods |
| `stage <archive>` | Full-extract via 7z to fresh timestamped staging (**never** include-patterns); verify extracted count/size vs archive listing; create install.json | include-pattern failures ×4; 1-file stub extractions |
| `fomod [--apply picks.json]` | Parse ModuleConfig.xml → option tree (JSON to stdout for Claude/user); `--apply` materializes chosen file map into payload | FOMOD hand-decoded ~8×; parser written + discarded 2× |
| `dllvet` | PE-parse payload DLLs: declared runtime range vs config runtime (skyrim: 1.6.1170), Address Library dependency, NG detect; verdict per DLL | wrong-runtime DLL blocked launch (SDS 07-04); AMR lesson |
| `esp` | TES4 header parse: masters list, ESL flag (0x200); missing-master check vs Data\ + Plugins.txt | improvised ≥4×; missing-master CTDs |
| `conflicts` | File-overlap sweep payload vs Data\ + existing manifests; name the losing mod per overlap | user demands sweep after EVERY install |
| `deploy` | Game-not-running check (`tasklist` for SkyrimSE.exe); robocopy payload → Data\ (exit <8 = success); Plugins.txt insert: case-insensitive anchor match, DynDOLOD-block-stays-last rule, BOM/CRLF-safe, backup first; then `ledger.py add --files-from <staged list>` (writes manifest); stamps deployed+recorded | anchor slips ×2; batch-append-after-DynDOLOD bug; robocopy false errors ×25; unledgered installs |
| `verify` | Payload-vs-Data\ diff — NO extension filtering; `_SWAP.ini`/`_DISTR.ini` referenced-plugin-exists check; `ledger.py check` tail for the game; stamps verified | MCM Helper burn (filtered .txt/.json); ICRFixes half-install |
| `remove <mod>` | Manifest-driven; quarantine to `C:\Modding\skyrim-manual\backups\removed-<mod>-<ts>\` (never delete); count-reconciled; **masters-check-before-disable** (refuse if other present plugins master it); `ledger.py remove --reason` | re-improvised 3×; masters check prevented CTDs 3× |
| `plugins list|enable|disable|snapshot|diff` | Plugins.txt manager; snapshot/diff brackets external GUI tools | Wrye Bash silent scramble (disabled a plugin once) |
| `status` | Incomplete installs + last verify results across staging | half-installs; crash resume |

### CP77 (thin preset)

`intake` / `stage` / `conflicts` / `deploy` / `verify` / `remove` / `status`. No fomod/dllvet/esp/plugins. Conflicts = `archive\pc\mod\` prefix ordering + `red4ext\plugins\` dir overlap. Deploy targets game root subdirs (archive/, red4ext/, r6/), ledger `--game cp77`.

### Out of scope

Record-level (plugin-record) conflict resolution — stays xEdit territory. Kenshi/RDR2 presets — later builds. LOD regen and snapshot — separate plans (lodregen/snapshot subcommands added by their own builds on top of this core).

## Adoption stack (built as final tasks of the modkit plan)

1. **CLI** — the above.
2. **Memory pins** — new `modkit.md` memory file in the Skyrim, CP77, and Kenshi Claude project memory dirs (`C:\Users\auand\.claude\projects\<slug>\memory\`), ledger-cli.md style: "installs/removals go through modkit; never hand-roll extraction, Data\ copies, or Plugins.txt edits", with command crib. Indexed at TOP of each MEMORY.md. Kenshi pin notes preset not yet built (intake/stage still useful).
3. **`mod-install` skill** — `C:\Users\auand\.claude\skills\mod-install\SKILL.md`. Triggers: install/verify/remove-mod requests, Nexus links, archive paths in game sessions. Contains: pipeline checklist with exact modkit commands, judgment-gate guidance (what to research at dllvet/conflicts verdicts, how to present FOMOD picks), remove + status/resume flows, standing rules from sse-mod-workflow memory (user downloads — account-bound; verify before install; conflict sweep every install).
4. **Advisory PreToolUse hook** — `modkit-guard.py` wired into user `settings.json` PreToolUse (matcher `Bash|PowerShell`). When cwd is a game project or `C:\Modding*`, regex the command for hand-roll patterns (`7z x`, `Expand-Archive`, `robocopy ... Data`, `Add-Content/Set-Content ...Plugins.txt`, direct `ledger.json` writes) → emit additionalContext warning naming the modkit command to use instead. Never blocks (forensics/repair work must stay possible).

## Safety

- Only `deploy` and `remove` touch game dirs; everything else reads.
- Every Plugins.txt write: backup first, atomic replace, re-read + validate after.
- `remove` quarantines, never deletes; refuses on master-dependency unless `--force`.
- All state/ledger writes atomic; ledger writes only via ledger.py (its validation + backups apply).
- Game-not-running check before deploy/remove.

## Testing & acceptance

- TDD throughout (ledger.py precedent: tests grew 14 → 58). Fixtures: synthetic zip/7z archives (incl. FOMOD tree, fake wrong-game payload), crafted minimal PE stubs for dllvet, synthetic TES4 headers, BOM/CRLF Plugins.txt fixtures.
- No test touches real game dirs — all preset paths injectable via modkit.json fixture configs.
- Final gate (ledger precedent): independent reviewer rehearses a real install end-to-end on a **scratch copy** of Data\ + Plugins.txt before the real acceptance install; real acceptance = one live Skyrim mod install driven only by modkit commands, then `modkit status` clean and `ledger.py check` no new errors.
- Acceptance for the hook: hand-roll attempt in a test session produces the advisory warning; normal forensics commands produce none.
