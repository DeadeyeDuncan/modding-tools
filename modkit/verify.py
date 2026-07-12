"""Post-deploy verification. NO extension filtering on the payload-vs-Data diff
(the MCM Helper burn). _SWAP/_DISTR referenced plugins must exist in Data.
Read-only: verify never writes to game dirs."""
import re
from pathlib import Path

from modkit import deploy, ledger_bridge, state

PLUGIN_REF_RE = re.compile(r"[\w .'()\[\]-]+\.es[pml]\b", re.IGNORECASE)


def diff_payload_vs_data(preset, pay_root):
    """[(rel, problem)] for payload files missing or size-mismatched in Data."""
    data_dir = Path(preset.DATA_DIR)
    pay_root = Path(pay_root)
    problems = []
    for f in sorted(pay_root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(pay_root))
        target = data_dir / rel
        if not target.is_file():
            problems.append((rel, "missing in Data"))
        elif target.stat().st_size != f.stat().st_size:
            problems.append((rel, f"size differs (payload {f.stat().st_size}, "
                                  f"Data {target.stat().st_size})"))
    return problems


def swap_distr_refs(pay_root):
    """Plugin filenames referenced by payload *_SWAP.ini / *_DISTR.ini files.
    ';' starts a comment (BOS/SPID convention)."""
    refs = set()
    for ini in Path(pay_root).rglob("*.ini"):
        low = ini.name.lower()
        if not (low.endswith("_swap.ini") or low.endswith("_distr.ini")):
            continue
        text = ini.read_bytes().decode("utf-8-sig", "replace")
        for line in text.splitlines():
            line = line.split(";", 1)[0]
            for m in PLUGIN_REF_RE.findall(line):
                refs.add(m.strip().lstrip("~|"))
    return sorted(refs)


def run_verify(preset, staging_dir, log):
    st = state.InstallState.load(str(staging_dir))
    if preset.DATA_DIR is None:
        log(f"ERROR: game {preset.NAME!r} has no data_dir - verify unsupported")
        return 1
    pay = deploy.data_root(preset, state.payload_root(staging_dir))
    problems = diff_payload_vs_data(preset, pay)
    for rel, why in problems[:50]:
        log(f"BAD {rel}: {why}")
    if len(problems) > 50:
        log(f"... and {len(problems) - 50} more")
    data_dir = Path(preset.DATA_DIR)
    missing_refs = [r for r in swap_distr_refs(pay) if not (data_dir / r).is_file()]
    for r in missing_refs:
        log(f"BAD _SWAP/_DISTR references missing plugin: {r}")
    code, out = ledger_bridge.run(["check", *ledger_bridge.game_args(preset)])
    tail = "\n".join(out.strip().splitlines()[-8:])
    log(f"ledger check (exit {code}):\n{tail}")
    ok = not problems and not missing_refs
    st.data["vet_results"]["verify"] = {
        "ok": ok, "missing_or_mismatched": len(problems),
        "missing_swap_refs": missing_refs, "ledger_check_exit": code,
        "ts": state.now_iso()}
    if ok:
        st.stamp("verified")
        log("verify OK")
        return 0
    st.save()
    log(f"verify FAILED: {len(problems)} file problems, "
        f"{len(missing_refs)} missing _SWAP/_DISTR refs")
    return 1
