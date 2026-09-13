"""Explicit portrait ID migration, with byte backups and dry run as the default."""
import argparse
import copy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid

if __package__:
    from .migrate_zv_workflows import decode, graph_facts, string_spans
else:
    _helper_spec = importlib.util.spec_from_file_location("zi_workflow_migration_helpers", Path(__file__).with_name("migrate_zv_workflows.py"))
    _helpers = importlib.util.module_from_spec(_helper_spec)
    _helper_spec.loader.exec_module(_helpers)
    decode, graph_facts, string_spans = _helpers.decode, _helpers.graph_facts, _helpers.string_spans


OLD_ID = "ZFPortraitPromptGenerator"
NEW_ID = "ZIPortraitPromptGenerator"
NAME_FIELDS = {"Node name for S&R", "node_type", "class_type", "type", "name"}


def changes_for(value, path=()):
    changes = []

    def node_fields(node, node_path):
        if not any(node.get(key) in (OLD_ID, NEW_ID) for key in ("type", "class_type")):
            return
        for key in ("type", "class_type"):
            if node.get(key) == OLD_ID:
                changes.append({"path": node_path + (key,), "before": OLD_ID, "after": NEW_ID})
        properties = node.get("properties", {})
        if isinstance(properties, dict):
            for key, old in properties.items():
                if key in NAME_FIELDS and old == OLD_ID:
                    changes.append({"path": node_path + ("properties", key), "before": OLD_ID, "after": NEW_ID})

    if isinstance(value, dict):
        if isinstance(value.get("nodes"), list):
            for index, node in enumerate(value["nodes"]):
                if isinstance(node, dict) and "id" in node:
                    node_fields(node, path + ("nodes", index))
        if isinstance(value.get("class_type"), str) and isinstance(value.get("inputs"), dict):
            node_fields(value, path)
            return changes
        for key, child in value.items():
            if key not in {"properties", "widgets_values", "inputs", "outputs"}:
                changes.extend(changes_for(child, path + (key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            changes.extend(changes_for(child, path + (index,)))
    return changes


def migrate_bytes(raw):
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    original = decode(text)
    changes = changes_for(original)
    if not changes:
        return raw, [], {}
    spans = string_spans(text)
    updated = text
    for first, last, actual in sorted((spans[change["path"]] for change in changes), reverse=True):
        if actual != OLD_ID:
            raise ValueError("Field span mismatch")
        updated = updated[:first] + json.dumps(NEW_ID) + updated[last:]
    result = decode(updated)
    restored = copy.deepcopy(result)
    for change in changes:
        parent = restored
        for key in change["path"][:-1]:
            parent = parent[key]
        key = change["path"][-1]
        if parent[key] != NEW_ID:
            raise ValueError("Migration value mismatch")
        parent[key] = OLD_ID
    if restored != original:
        raise ValueError("Unrelated workflow data changed")
    before, after = graph_facts(original), graph_facts(result)
    if before != after:
        raise ValueError("Graph structure changed")
    migrated_nodes = {change["path"][:-1] for change in changes if change["path"][-1] in {"type", "class_type"} and "properties" not in change["path"]}
    checks = {"node_count": before["node_count"], "connection_count": before["connection_count"], "migrated_node_count": len(migrated_nodes),
              "node_ids_equal": True, "link_ids_equal": True, "connections_equal": True, "other_fields_equal": True, "byte_layout_preserved": True}
    return bom + updated.encode("utf-8"), changes, checks


def migrate_file(path, original, replacement):
    if path.read_bytes() != original:
        raise ValueError("Workflow changed since scan; rescan before migrating")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + f".zi-{stamp}-{uuid.uuid4().hex[:8]}.bak")
    with backup.open("xb") as handle:
        handle.write(original)
    if backup.read_bytes() != original:
        raise ValueError("Backup verification failed")
    with path.open("r+b") as handle:
        if handle.read() != original:
            raise ValueError("Workflow changed during backup; source was not edited")
        handle.seek(0)
        handle.write(replacement)
        handle.truncate()
    written = path.read_bytes()
    if written != replacement:
        raise ValueError("Written workflow differs from the verified plan")
    decode(written.decode("utf-8-sig"))
    return backup


def migrate_directory(root, apply=False):
    root = Path(root).resolve()
    files = sorted(root.rglob("*.json"))
    report = {"root": str(root), "scanned": len(files), "applied": apply, "hits": [], "parse_errors": [], "unmatched_unchanged": 0}
    plans, untouched = [], []
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ValueError("Workflow path escapes the specified directory")
        raw = path.read_bytes()
        try:
            replacement, changes, checks = migrate_bytes(raw)
        except (UnicodeError, ValueError, RecursionError) as error:
            report["parse_errors"].append({"file": str(path), "error": str(error)})
            continue
        if changes:
            plans.append((path, raw, replacement, changes, checks))
        else:
            untouched.append((path, hashlib.sha256(raw).hexdigest()))
    if apply and report["parse_errors"]:
        raise ValueError("Some workflows could not be parsed; nothing was modified")
    for path, raw, replacement, changes, checks in plans:
        backup = migrate_file(path, raw, replacement) if apply else None
        report["hits"].append({"file": str(path), "backup": str(backup) if backup else None, "fields": changes, "checks": checks,
                               "before_sha256": hashlib.sha256(raw).hexdigest(), "after_sha256": hashlib.sha256(replacement).hexdigest()})
    for path, digest in untouched:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("An unmatched workflow changed during the scan")
    report["unmatched_unchanged"] = len(untouched)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate_directory(args.root, args.apply), ensure_ascii=True, indent=2))
