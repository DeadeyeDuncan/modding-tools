"""File-overlap sweep: payload vs Data\\ + existing manifests. Names the losing
mod per overlap (standing rule: sweep after EVERY install). Read-only."""
from pathlib import Path


def manifest_owners(manifests_dir):
    """{data-relative-lower-backslash-path: manifest-stem}. Tolerates legacy
    Data\\ prefixes and #-comment lines (ledger.py manifest conventions)."""
    owners = {}
    mdir = Path(manifests_dir) if manifests_dir else None
    if not mdir or not mdir.is_dir():
        return owners
    for mf in sorted(mdir.glob("*.txt")):
        try:
            text = mf.read_bytes().decode("utf-8-sig")
        except OSError:
            continue
        for line in text.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rel = line.replace("/", "\\")
            if rel.lower().startswith("data\\"):
                rel = rel[5:]
            owners[rel.lower()] = mf.stem
    return owners


def sweep(preset, payload_dir):
    """Every payload file already present in Data -> overlap hit with owner."""
    if preset.DATA_DIR is None:
        return []
    data_dir = Path(preset.DATA_DIR)
    owners = manifest_owners(getattr(preset, "MANIFESTS_DIR", None))
    payload_dir = Path(payload_dir)
    hits = []
    for f in sorted(payload_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(payload_dir))
        if (data_dir / rel).is_file():
            hits.append({"path": rel, "on_disk": True,
                         "owner": owners.get(rel.replace("/", "\\").lower())})
    return hits
