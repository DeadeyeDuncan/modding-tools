"""7z wrapper: list / FULL extract / count+size verify.
Never include-pattern extracts (4 recorded include-pattern failures; the
Genesis 1-file-stub burn is exactly what verify_extraction() catches)."""
import subprocess
from pathlib import Path


class ArchiveError(Exception):
    """7z missing, non-zero exit, or unreadable archive."""


def _run(sevenzip, args):
    if not Path(sevenzip).is_file():
        raise ArchiveError(f"7z.exe not found: {sevenzip} (fix modkit.json 'sevenzip')")
    proc = subprocess.run([str(sevenzip), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_slt(text):
    """Parse `7z l -slt -ba` blocks -> [{"path", "size", "is_dir"}]."""
    entries, cur = [], {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if cur.get("Path"):
                entries.append(cur)
            cur = {}
            continue
        if " = " in line:
            k, _, v = line.partition(" = ")
            cur[k] = v
    if cur.get("Path"):
        entries.append(cur)
    out = []
    for e in entries:
        is_dir = "D" in e.get("Attributes", "") or e.get("Folder") == "+"
        size = int(e["Size"]) if e.get("Size", "").isdigit() else 0
        out.append({"path": e["Path"], "size": size, "is_dir": is_dir})
    return out


def listing(sevenzip, archive_path):
    code, out = _run(sevenzip, ["l", "-slt", "-ba", str(archive_path)])
    if code != 0:
        raise ArchiveError(f"7z l failed ({code}) on {archive_path}:\n{out[-2000:]}")
    return parse_slt(out)


def extract_all(sevenzip, archive_path, dest):
    """FULL extract to dest. Callers pass a FRESH timestamped staging payload dir."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    code, out = _run(sevenzip, ["x", "-y", f"-o{dest}", str(archive_path)])
    if code != 0:
        raise ArchiveError(f"7z x failed ({code}) on {archive_path}:\n{out[-2000:]}")


def verify_extraction(entries, dest):
    """Every listed file must exist at dest with the listed size. [] = OK."""
    dest = Path(dest)
    problems = []
    for e in entries:
        if e["is_dir"]:
            continue
        target = dest / e["path"]
        if not target.is_file():
            problems.append(f"missing after extract: {e['path']}")
        elif target.stat().st_size != e["size"]:
            problems.append(f"size mismatch: {e['path']} (archive {e['size']}, "
                            f"disk {target.stat().st_size})")
    return problems
