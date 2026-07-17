# modding-tools

Command-line tooling for managing a **manual** (mod-manager-free) game-mod setup on Windows. Instead of hand-rolling `7z x`, `robocopy` into a game's `Data` folder, and hand-edits to `Plugins.txt`, this repo drives each of those steps through small, auditable Python CLIs that verify their own work, keep a validated install ledger, and never delete anything (removals quarantine).

It targets **Skyrim Special Edition** (full support), **Cyberpunk 2077** (thin preset, no plugin system), and **Kenshi** (staging only), plus a read-only Skyrim **forensics** kit for chasing missing-mesh / missing-texture bugs.

Everything is pure Python standard library — there are no third-party packages to install. Machine-specific paths live in `modkit.json`, never in code, so the same checkout runs on any machine by editing one config file.

## Requirements

- **Windows.** The tools shell out to `robocopy` and `tasklist`, use backslash paths, handle the cp1252 console, and are launched with the `py` launcher.
- **Python 3.8+** (uses `pathlib`, `os.replace` atomic writes, `Path.unlink(missing_ok=…)`). No external Python dependencies.
- **External programs**, only for the features that use them (paths configured in `modkit.json`):
  - [7-Zip](https://www.7-zip.org/) (`7z.exe`) — archive intake/staging.
  - `BSArch64.exe` — the BSA-index forensics tool.
  - Optionally the DynDOLOD / TexGen / PGPatcher GUIs — the `lodregen` guards bracket those manual runs (they are never launched or driven automatically).

## Layout

```
modkit.py            # entry shim -> modkit/cli.py
ledger.py            # standalone mod-ledger CLI (the sole ledger writer)
modkit.json          # all machine paths + per-game presets (config, not code)
modkit/              # the modkit package
  cli.py             # argparse dispatch for every subcommand
  config.py          # modkit.json loader (explicit path / MODKIT_CONFIG env / repo default)
  games/             # per-game presets: skyrim (full), cp77 (thin), generic (fallback)
  archive.py         # 7z list / full-extract / count+size verify
  fomod.py           # FOMOD ModuleConfig.xml parse + picks apply
  tes4.py            # ESP/ESM/ESL header parse (masters, ESL flag)
  peparse.py         # minimal PE parser for DLL vetting (SKSE version data)
  pluginstxt.py      # BOM/CRLF-safe Plugins.txt enable/disable/snapshot/diff
  conflicts.py       # payload-vs-Data + manifest overlap sweep
  deploy.py          # robocopy deploy + Plugins.txt + ledger; quarantine-based remove
  verify.py          # post-deploy payload-vs-Data diff
  state.py           # per-install install.json state machine
  lodregen.py        # pre/post guards around a manual LOD-regen ritual
  snapshot.py        # session-state snapshot/diff + open-items tracker
  ledger_bridge.py   # subprocess wrapper that calls ledger.py
forensics/           # read-only Skyrim asset forensics (standalone scripts)
  bsa_index.py       # BSArch-backed BSA content index (build/query/stats)
  esp_tools.py       # plugin masters / MODL extraction / header-only "gut"
  nif_texrefs.py     # NIF texture-reference audit vs loose + BSA
adoption/            # Claude Code adoption assets: advisory PreToolUse hook, skill + memory-pin copies
docs/                # design specs, implementation plans, runbooks
tests/               # pytest suites (test_modkit/, test_forensics/, test_ledger.py)
```

## Configuration

All paths and per-game settings come from `modkit.json`, resolved in this order: an explicit `--config` flag, the `MODKIT_CONFIG` environment variable, then the copy next to the code. Required top-level keys are `sevenzip`, `staging_root`, and `games`; each game entry needs at least `process_names` and `backups_dir`. A trimmed skeleton:

```json
{
  "sevenzip": "<path-to>\\7z.exe",
  "downloads": ["<your-downloads-dir>"],
  "staging_root": "<scratch>\\staging",
  "games": {
    "skyrim": {
      "data_dir": "<...>\\Skyrim Special Edition\\Data",
      "plugins_txt": "<...>\\Skyrim Special Edition\\Plugins.txt",
      "process_names": ["SkyrimSE.exe", "skse64_loader.exe"],
      "runtime": "1.6.1170",
      "backups_dir": "<...>\\skyrim-manual\\backups",
      "manifests_dir": "<...>\\skyrim-manual\\manifests"
    }
  }
}
```

Optional `lodregen`, `forensics`, and `snapshot` sections configure those features (tool exe paths, output dirs, watched INI/ENB keys, Steam appmanifest). A game with a `null` `data_dir` (e.g. Kenshi) only supports `intake` / `stage` / `status`; commands that touch game dirs refuse it.

## modkit — the install pipeline

Invoke as `py -3 modkit.py <command> --game <game>`. Global flags: `--game` (preset name) and `--config` (explicit `modkit.json`).

Typical Skyrim install flow — each step writes to a timestamped staging dir and records its result in `install.json`; the judgment gates (DLL verdicts, FOMOD picks, conflict decisions) are yours between steps:

```
intake -> stage -> fomod (if present) -> dllvet -> esp -> conflicts -> deploy -> verify
```

**Exit codes are meaningful:** `0` clean, `1` error or verify findings, `2` warned / drift / refused-pending-vets (usually overridable with `--force`).

| Command | What it does |
|---|---|
| `intake ["<archive>"]` `[--expect-game G] [--limit N]` | Scan Downloads/Vortex (or one file): 0-byte check, Nexus filename parse, wrong-game gate, already-in-ledger check |
| `stage <archive>` `[--name NAME]` | Full-extract to a fresh staging dir and verify file count/size vs the archive listing (never partial/include-pattern extracts) |
| `fomod` `[--apply PICKS.json] [--staging DIR]` | Print the FOMOD option tree as JSON; `--apply` materializes the chosen files into `payload_final\` |
| `dllvet` `[--staging DIR]` | PE-parse payload DLLs: architecture, declared SKSE runtime vs config, Address Library independence, pre-AE detection |
| `esp` `[--staging DIR]` | TES4 header vet: masters list, ESL flag, missing-master check against Data + payload |
| `plugins {list\|enable\|disable\|snapshot\|diff}` | Manage `Plugins.txt` (BOM/CRLF-safe; DynDOLOD block stays last). `enable` takes `--plugin` and optional `--anchor` |
| `conflicts` `[--staging DIR]` | File-overlap sweep of payload vs Data + manifests; names the losing mod per overlap |
| `deploy` `[--anchor "X.esp"] [--force] [--staging DIR]` | Game-not-running check, robocopy payload → Data, `Plugins.txt` enable, ledger add. Refuses (exit 2) if vet stages are missing unless `--force` |
| `remove "<Name>" --reason "..."` `[--force]` | Manifest-driven removal: quarantine (never delete), master-dependency check before disabling, ledger remove |
| `verify` `[--staging DIR]` | Unfiltered payload-vs-Data diff + `_SWAP`/`_DISTR` plugin-exists checks + ledger check tail |
| `status` `[--all]` | Staging dirs with incomplete stage chains + last verify result (run at session start / after crashes) |

Examples:

```powershell
py -3 modkit.py status --game skyrim
py -3 modkit.py stage "C:\dl\SomeMod-12345-1-0.7z" --game skyrim
py -3 modkit.py dllvet --game skyrim
py -3 modkit.py deploy --game skyrim --anchor "SkyUI_SE.esp"
py -3 modkit.py verify --game skyrim
py -3 modkit.py remove "Some Mod" --reason "replaced by newer version" --game skyrim
```

### Extra modkit subcommands

- **`lodregen pre|post|status --game skyrim`** — brackets a manual PGPatcher → TexGen → DynDOLOD LOD regeneration. `pre` snapshots `Plugins.txt`, pulls the DynDOLOD trio aside, guard-cleans old output, and prints the manual GUI ritual; `post` freshness-gates the tool output, deploys it, re-enables the trio (Occlusion last) with a masters/order verify, diffs `Plugins.txt`, and records the result. Flags include `--no-pgpatcher`, `--clean-texgen`, `--stage texgen|full`, `--force`.
- **`snapshot take|diff --game <g>`** — capture live session state (Plugins.txt hash, SKSE DLL list, watched INI/ENB keys, ledger counts, Steam auto-update behavior) to `<game>-manual\snapshots\`, and diff the latest (or `--against` a file) against live. Drift exits 2; the report explicitly reminds you that unexplained deltas are questions for the user, not automatic bugs.
- **`openitems add|done|list --game <g>`** — a tolerant checkbox-markdown tracker (`<game>-manual\open-items.md`) for pending fixes.

## ledger.py — the mod ledger

A standalone CLI for validated reads/writes of a JSON install ledger (`--game skyrim|cp77`, or `--ledger <path>`). `modkit` calls this via subprocess so ledger validation, timestamped backups, and atomic writes always apply — `ledger.py` is the *only* thing that writes the ledger or manifests. Exit codes: `0` OK, `1` validation/check findings, `2` a refused (invalid) write.

```powershell
py -3 ledger.py list --game skyrim --active
py -3 ledger.py get --name "SkyUI" --game skyrim
py -3 ledger.py add --name "SkyUI" --nexus-id 12604 --version 5.2 --plugin SkyUI_SE.esp --game skyrim
py -3 ledger.py update --name "SkyUI" --append-note "reinstalled after wipe" --game skyrim
py -3 ledger.py remove --name "SkyUI" --reason "no longer needed" --to "<backup-dir>" --game skyrim
py -3 ledger.py validate --game skyrim      # structural check
py -3 ledger.py check    --game skyrim      # cross-check vs Plugins.txt + manifests on disk
py -3 ledger.py migrate  --game skyrim      # dry-run field-drift normalizer; add --apply to write
```

The validator is *structure-strict, vocabulary-open*: required shapes (unique `name`, `YYYY-MM-DD` `installed`, `removed` requires a `removedReason`, typed fields) are enforced while unknown extra keys are left alone. File lists become UTF-8/CRLF manifest files under `manifests\`.

## forensics/ — read-only Skyrim asset audit

Standalone scripts, each launched directly (`py -3 forensics/<tool>.py …`). They **never modify game directories** — they report. Config comes from `modkit.json`'s `forensics` section.

```powershell
# BSA content index (needs BSArch); build once, then query.
py -3 forensics\bsa_index.py build --game skyrim
py -3 forensics\bsa_index.py query "meshes\clutter\sack01.nif" --raw-confirm
py -3 forensics\bsa_index.py stats

# Plugin forensics: masters, MODL model-paths, header-only "gut" stub.
py -3 forensics\esp_tools.py masters SomeMod.esp --json
py -3 forensics\esp_tools.py modl SomeMod.esp
py -3 forensics\esp_tools.py gut Bloated.esp -o out\Bloated-stub.esp   # refuses to write under Data\

# NIF texture-reference audit vs loose Data + BSAs.
py -3 forensics\nif_texrefs.py "Data\meshes\smim" --check
```

`bsa_index` cross-checks BSArch's listing against its own "Files: N" banner and falls back to an unpack+walk on any mismatch; a raw filename byte-scan (`--raw-confirm`) backstops the known BSArch folder-pairing quirk so real vanilla assets aren't falsely reported missing.

## Safety model

- **Four commands mutate game state; everything else only reads it.** `deploy` (robocopy into `Data` + enable in `Plugins.txt` + ledger add), `remove` (quarantine out of `Data` + disable in `Plugins.txt` + ledger remove), `lodregen` (`pre` pulls the DynDOLOD trio out of `Data` and disables it; `post` deploys LOD output into `Data` and re-enables the trio), and `plugins enable`/`disable` (edit `Plugins.txt`). The vets (`dllvet`, `esp`), plus `intake`, `stage`, `conflicts`, `verify`, `status`, `snapshot`, `openitems`, and every tool in `forensics/`, are read-only against game dirs.
- **`ledger.py` is the sole ledger/manifest writer.** `modkit` shells out to it via `ledger_bridge`, so validation, backups (last 20 kept), and atomic temp-file replacement always apply.
- **Removals quarantine, never delete** — files move to a timestamped backup dir, and removal refuses (unless `--force`) when another enabled plugin still lists the mod as a master.
- **robocopy exit `< 8` is success**; `>= 8` raises. Writes are atomic (`os.replace`) and text files preserve BOM/CRLF where the game expects it.
- **No GUI automation.** `lodregen` prints the manual PGPatcher/TexGen/DynDOLOD steps for a human to run and only brackets them with pre/post guards — it never launches or drives the tools themselves.

`adoption/modkit-guard.py` is an **advisory** Claude Code `PreToolUse` hook: it warns (never blocks, always exits 0) when a shell command in a modding context hand-rolls a step modkit owns (`7z x`, `Expand-Archive`, robocopy-into-Data, `Plugins.txt`/`ledger.json` edits).

## Testing

Tests use `pytest` (standard library only otherwise). They run against synthetic fixtures wired through the `MODKIT_CONFIG` env var and `tmp_path`, so **no test touches real game directories**; tests needing 7-Zip are skipped when it isn't installed.

```powershell
py -3 -m pytest        # from the repo root
```

There are roughly 320 test functions across 23 test files covering the modkit pipeline, ledger, and forensics tools.

## Status

Built in July 2026 as five sequenced "builds" (see `docs/2026-07-11-BUILD-ORDER.md`): the modkit core + install pipeline, a mod-bug-triage skill, `lodregen`, `snapshot`/`openitems`, and the forensics kit. There are no release tags or a package version — the git history is the record. The Kenshi preset is intentionally staging-only for now, and the forensics kit currently ships three of the originally planned tools.