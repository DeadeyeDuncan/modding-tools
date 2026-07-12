"""install.json state machine (design spec: approach C - stepwise subcommands +
per-install state). One InstallState per staging dir. All writes atomic."""
import datetime
import json
import os
import re
from pathlib import Path

STAGES = ("intake", "staged", "fomod", "dllvet", "esp", "conflicts",
          "deployed", "recorded", "verified")
VET_STAGES = ("fomod", "dllvet", "esp", "conflicts")


class StateError(Exception):
    """Missing/corrupt install.json or invalid stage name."""


def atomic_write_bytes(path, data):
    """temp + os.replace in the same dir - never a partial file."""
    path = Path(path)
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}"
    tmp.write_bytes(data)
    os.replace(tmp, path)


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def slug(name):
    out = re.sub(r"[^A-Za-z0-9.+-]+", "-", name.strip()).strip("-")
    return out or "mod"


def payload_root(staging_dir):
    """Deployable tree: payload_final\\ (FOMOD apply output, Task 6) wins over payload\\."""
    staging_dir = Path(staging_dir)
    final = staging_dir / "payload_final"
    return final if final.is_dir() else staging_dir / "payload"


def latest_staging(preset):
    """Most recent staging dir for the game (name-sorted; names start YYYYMMDD-HHMMSS)."""
    root = Path(preset.STAGING_ROOT)
    if not root.is_dir():
        return None
    dirs = sorted(d for d in root.iterdir()
                  if d.is_dir() and (d / "install.json").is_file())
    return dirs[-1] if dirs else None


class InstallState:
    def __init__(self, staging_dir, data):
        self.staging_dir = Path(staging_dir)
        self.data = data

    @classmethod
    def create(cls, staging_dir, mod, game, archive, nexus_id=None,
               version=None, applicable=None):
        data = {
            "mod": mod,
            "game": game,
            "archive": str(archive),
            "nexusId": nexus_id,
            "version": version,
            "stages": {s: None for s in STAGES},
            "applicable": applicable or {"fomod": False, "dllvet": False, "esp": False},
            "vet_results": {},
            "files": [],
        }
        st = cls(staging_dir, data)
        st.save()
        return st

    @classmethod
    def load(cls, staging_dir):
        p = Path(staging_dir) / "install.json"
        if not p.is_file():
            raise StateError(f"no install.json in {staging_dir} - run `modkit stage` first")
        try:
            data = json.loads(p.read_bytes().decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as ex:
            raise StateError(f"install.json unparseable: {p}: {ex}")
        return cls(staging_dir, data)

    def save(self):
        text = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        atomic_write_bytes(self.staging_dir / "install.json", text.encode("utf-8"))

    def stamp(self, stage):
        if stage not in STAGES:
            raise StateError(f"unknown stage {stage!r} (stages: {', '.join(STAGES)})")
        self.data["stages"][stage] = now_iso()
        self.save()

    def missing_applicable(self):
        """Applicable vet stages not yet stamped. `conflicts` is always applicable."""
        out = []
        for s in VET_STAGES:
            applicable = True if s == "conflicts" else bool(self.data["applicable"].get(s))
            if applicable and not self.data["stages"].get(s):
                out.append(s)
        return out
