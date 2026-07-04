# Ledger CLI — Design

**Date:** 2026-07-04
**Origin:** `H:\DeadMind V.3\reflection-notes.md` item #2 — ledger/manifest writes are the most error-prone high-frequency step in the modding workflow (~30+ throwaway append scripts, 2 corruption incidents, 7 manual validate passes in one session, schema drift, one real ledger↔Plugins.txt divergence).
**Approved:** 2026-07-04 by user (scope, migration strategy, check-in-v1, approach all confirmed).

## Purpose

One durable, validated command for every read/write against the mod-install ledgers, replacing per-session improvised PowerShell/heredoc JSON editing. Also the drift detector between ledger, Plugins.txt, manifests, and disk.

## Scope

- **v1 games:** Skyrim SE (`C:\Modding\skyrim-manual\ledger.json`, 234 entries) and Cyberpunk 2077 (`C:\Modding\cyberpunk-manual\ledger.json`, 11 entries). Same JSON shape: header object + `mods[]`.
- **Out of scope:** Kenshi (`mods.cfg`) and RDR2 (`mods.xml`) — different data models; installing files, editing Plugins.txt, writing memory (those belong to the install-toolkit build, reflection item #1).

## Layout & invocation

- `C:\Modding\tools\ledger.py` — single file, Python stdlib only. Runs via `py -3` (the `python` Store alias is never used). Lives on C: so it works when the H: SSD is unplugged mid-gaming session.
- `C:\Modding\tools\tests\test_ledger.py` — stdlib `unittest`, run via `py -3 -m unittest discover -s C:\Modding\tools\tests`.
- Invocation: `py -3 C:\Modding\tools\ledger.py <command> --game skyrim|cp77 [flags]`. Baked-in game→ledger-path presets; `--ledger <path>` overrides (future games or copies under test).

## Canonical entry schema

Ledger file = header object (game-specific keys, preserved untouched) + `mods` array.

Entry fields:

| Field | Type | Rule |
|---|---|---|
| `name` | str | **required**, unique across `mods[]` (case-insensitive compare for dup detection) |
| `installed` | str | **required**, `YYYY-MM-DD` |
| `nexusId` | int or null | optional |
| `version` | str | optional |
| `source` | str | optional (archive filename) |
| `plugin` | str, list, or null | optional (esp/esm/esl name(s); CP77 entries omit it) |
| `esl` | bool | optional |
| `masters` | list | optional |
| `requires` | list or str | optional |
| `role` / `type` | str | optional (both accepted; not merged — they mean different things across games) |
| `options` | any | optional (FOMOD picks etc.) |
| `note` | str | optional |
| `manifest` | str | optional — pointer `manifests\<file>.txt` |
| `fileCount` | int | optional |
| `removed` | str | optional, `YYYY-MM-DD`; **when present, `removedReason` required** |
| `removedReason` | str | required iff `removed` |
| `removedTo` | str | optional backup path |

**Vocabulary open, structure strict:** unknown extra keys (e.g. `facegenSkipped`, `aka`, `author`, `tool`) are preserved verbatim and never warned about. Validation errors only on: missing/duplicate `name`, missing/malformed `installed`, wrong type on a known field, `removed` without `removedReason`, unparseable JSON.

## Migration (one-time, `migrate` command)

Normalizes the drift-era Skyrim entries:

1. `nexus` → `nexusId` (~40 entries)
2. `notes` → `note` (~6; if both exist, merge with newline)
3. `esp` / `esm` → `plugin` (~13)
4. Inline `files` arrays (~41 entries) → written to `manifests\<sanitized-name>.txt` (existing convention: UTF-8 **with BOM**, CRLF, one Data-relative backslash path per line), entry gets `manifest` + `fileCount`, `files` key dropped. If a manifest file with that name already exists and differs, abort that entry with a report line (no silent overwrite).

`migrate` is **dry-run by default** (prints per-entry change report); `--apply` executes with backup-first. Idempotent: second run reports zero changes.

## Commands

| Command | Behavior |
|---|---|
| `add` | New entry from flags (`--name`, `--nexus-id`, `--version`, `--source`, `--plugin` repeatable, `--esl`, `--note`, `--role`, …). Auto `installed`=today (override `--installed`). Refuses duplicate name (points to `update`). `--files-from <txt>` writes `manifests\<name>.txt` from a staged file list and sets `manifest`+`fileCount`. |
| `update` | `--name` + any field flags; `--append-note "text"` appends `[YYYY-MM-DD] text` to `note`. Unknown-name → error listing closest matches. |
| `remove` | `--name --reason "…" [--to <backup-path>]` → sets `removed`=today, `removedReason`, `removedTo`. Entry never deleted; errors if already removed. |
| `get` | `--name` → entry as JSON to stdout. |
| `list` | `--active` / `--removed` / `--since YYYY-MM-DD` / default all; one line per entry (name, version, installed, plugin, removed-flag); `--count` for totals. |
| `validate` | Schema pass over header presence + all entries. Exit 0 clean / 1 violations (printed). |
| `check` | Cross-consistency (below). Exit 0 clean / 1 findings. |
| `migrate` | As above. |

## `check` cross-consistency

Paths resolved from the ledger header (`pluginsTxt`, `dataDir` for Skyrim; `installDir` for CP77) — already recorded there. Severities:

- **ERROR** — active entry's `plugin` not present in Plugins.txt; entry's `manifest` pointer file missing; `validate`-level schema violations; duplicate `plugin` claimed by two active entries.
- **WARN** — Plugins.txt line no active ledger entry owns (unowned-plugin class: the Beards-for-HPH drift); active entry's manifest lists paths missing on disk (reported per-entry with missing count, capped listing).
- **INFO** — removed entry's manifest paths still present on disk (legitimate when a later mod overwrote the same paths — swap pattern).

Plugins.txt parsing: `*`-prefix = enabled convention, comments/blank lines ignored, BOM-safe, case-insensitive filename compare. CP77 runs the manifest/disk checks only (no plugin system).

## Safety & error handling

- Every mutating command: copy ledger to `backups\ledger.json.bak-<yyyyMMdd-HHmmss>` (in the ledger's own dir; prune to newest 20) → build new JSON → **validate the result in memory** → write temp file in same dir → `os.replace` (atomic). A failed validation aborts before any write.
- Encoding: read via `utf-8-sig`; write UTF-8 (no BOM — matches current ledger), CRLF preserved, indent 4. The current file carries PowerShell ConvertTo-Json quirks (double space after colon); the first mutating write normalizes the whole file to standard `json.dumps` formatting — a one-time reformat, protected by the backup.
- Console output ASCII-safe (no Unicode that dies on cp1252).
- Exit codes: `0` success/clean, `1` findings/violations, `2` usage or I/O error.

## Testing

- TDD with stdlib `unittest`; fixtures = synthetic ledgers in temp dirs, including drift-era entries (`nexus`, `notes`, `esp`, inline `files`), a fake Plugins.txt, fake manifests/Data tree.
- Cover: each command's happy path; dup-name refusal; removed-without-reason rejection; migrate idempotency; migrate collision abort; atomicity (validation failure leaves original untouched); BOM/CRLF round-trip; check severity classification incl. unowned plugin and swap-pattern INFO.
- Acceptance: `migrate --dry-run` against a **copy** of the real Skyrim ledger, diff reviewed by user before `--apply` on the real file; `validate` + `check` run against the live Skyrim setup; `validate` against the live CP77 ledger.

## Non-goals / future

- No install/copy/uninstall of actual mod files (install-toolkit, reflection #1 — this CLI is its recording layer).
- No Kenshi/RDR2 adapters in v1.
- No auto-fix mode in `check` (report only; fixes stay human-approved).
