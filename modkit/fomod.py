"""FOMOD ModuleConfig.xml parse + picks apply. Covers the real-world subset:
requiredInstallFiles, installSteps/optionalFileGroups/plugins (files, folders,
conditionFlags), conditionalFileInstalls flag patterns. Namespace-tolerant.
Choosing picks is a judgment gate - Claude/user decide, modkit materializes."""
import shutil
from pathlib import Path
from xml.etree import ElementTree


class FomodError(Exception):
    """No/invalid ModuleConfig.xml, or picks that don't fit the tree."""


def find_config(payload_dir):
    """Locate fomod/ModuleConfig.xml under payload (case-insensitive)."""
    for p in Path(payload_dir).rglob("*"):
        if (p.is_file() and p.name.lower() == "moduleconfig.xml"
                and p.parent.name.lower() == "fomod"):
            return p
    return None


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _files_of(node):
    out = []
    if node is None:
        return out
    for child in node:
        kind = _local(child.tag)
        if kind in ("file", "folder"):
            out.append({"kind": kind, "source": child.get("source", ""),
                        "destination": child.get("destination", "")})
    return out


def parse(payload_dir):
    cfg_path = find_config(payload_dir)
    if cfg_path is None:
        raise FomodError(f"no fomod/ModuleConfig.xml under {payload_dir}")
    try:
        root = ElementTree.parse(cfg_path).getroot()
    except ElementTree.ParseError as ex:
        raise FomodError(f"ModuleConfig.xml unparseable: {ex}")
    tree = {"moduleName": "", "required": [], "steps": [], "conditional": []}
    for node in root:
        tag = _local(node.tag)
        if tag == "modulename":
            tree["moduleName"] = (node.text or "").strip()
        elif tag == "requiredinstallfiles":
            tree["required"] = _files_of(node)
        elif tag == "installsteps":
            for step in node:
                if _local(step.tag) != "installstep":
                    continue
                s = {"name": step.get("name", ""), "groups": []}
                for ofg in step:
                    if _local(ofg.tag) != "optionalfilegroups":
                        continue
                    for grp in ofg:
                        if _local(grp.tag) != "group":
                            continue
                        g = {"name": grp.get("name", ""),
                             "type": grp.get("type", "SelectAny"), "plugins": []}
                        for plugs in grp:
                            if _local(plugs.tag) != "plugins":
                                continue
                            for plug in plugs:
                                if _local(plug.tag) != "plugin":
                                    continue
                                pl = {"name": plug.get("name", ""), "description": "",
                                      "files": [], "flags": {}}
                                for item in plug:
                                    it = _local(item.tag)
                                    if it == "description":
                                        pl["description"] = (item.text or "").strip()
                                    elif it == "files":
                                        pl["files"] = _files_of(item)
                                    elif it == "conditionflags":
                                        for fl in item:
                                            if _local(fl.tag) == "flag":
                                                pl["flags"][fl.get("name", "")] = \
                                                    (fl.text or "").strip()
                                g["plugins"].append(pl)
                        s["groups"].append(g)
                tree["steps"].append(s)
        elif tag == "conditionalfileinstalls":
            for patterns in node:
                if _local(patterns.tag) != "patterns":
                    continue
                for pat in patterns:
                    if _local(pat.tag) != "pattern":
                        continue
                    entry = {"flags": {}, "files": []}
                    for part in pat:
                        pt = _local(part.tag)
                        if pt == "dependencies":
                            for dep in part.iter():
                                if _local(dep.tag) == "flagdependency":
                                    entry["flags"][dep.get("flag", "")] = dep.get("value", "")
                        elif pt == "files":
                            entry["files"] = _files_of(part)
                    tree["conditional"].append(entry)
    return tree


def selected_plugins(tree, picks):
    """Resolve picks -> plugin dicts. Enforces group-type cardinality."""
    chosen = []
    for step in tree["steps"]:
        for group in step["groups"]:
            key = f"{step['name']}::{group['name']}"
            names = list(picks.get(key, []))
            by_name = {p["name"]: p for p in group["plugins"]}
            for n in names:
                if n not in by_name:
                    raise FomodError(f"pick {n!r} not in group {key!r} "
                                     f"(options: {', '.join(by_name)})")
            gtype = group["type"].lower()
            if gtype == "selectexactlyone" and len(names) != 1:
                raise FomodError(f"group {key!r} is SelectExactlyOne - got {len(names)} picks")
            if gtype == "selectatmostone" and len(names) > 1:
                raise FomodError(f"group {key!r} is SelectAtMostOne - got {len(names)} picks")
            if gtype == "selectall":
                names = list(by_name)
            chosen += [by_name[n] for n in names]
    return chosen


def apply(payload_dir, staging_dir, picks):
    """Materialize required + picked + flag-matched conditional files into
    <staging_dir>\\payload_final\\ (Data-relative). Returns file count."""
    payload_dir = Path(payload_dir)
    tree = parse(payload_dir)
    chosen = selected_plugins(tree, picks)
    flags = {}
    for p in chosen:
        flags.update(p["flags"])
    file_specs = list(tree["required"])
    for p in chosen:
        file_specs += p["files"]
    for cond in tree["conditional"]:
        if cond["flags"] and all(flags.get(k) == v for k, v in cond["flags"].items()):
            file_specs += cond["files"]
    dest_root = Path(staging_dir) / "payload_final"
    if dest_root.exists():
        shutil.rmtree(dest_root)  # staging-only tree; safe to rebuild on re-apply
    dest_root.mkdir(parents=True)
    src_base = find_config(payload_dir).parent.parent
    count = 0
    for spec in file_specs:
        src = src_base / spec["source"].replace("\\", "/").rstrip("/")
        dst_rel = spec["destination"].replace("\\", "/").lstrip("/")
        if spec["kind"] == "folder":
            if not src.is_dir():
                raise FomodError(f"folder source missing: {spec['source']}")
            for f in src.rglob("*"):
                if f.is_file():
                    target = dest_root / dst_rel / f.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
                    count += 1
        else:
            if not src.is_file():
                raise FomodError(f"file source missing: {spec['source']}")
            target = (dest_root / dst_rel) if dst_rel else (dest_root / src.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            count += 1
    return count
