"""Explicit development-ID migration; dry run by default, byte layout preserved."""
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import uuid

IDS = {"ZFUniversalMediaEvidenceDesk": "ZVUniversalMediaEvidenceDesk"}
NAME_FIELDS = {"Node name for S&R", "node_type", "class_type", "type", "name"}
SPACE = re.compile(r"[ \t\r\n]*")


def decode(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_value): raise ValueError("Non-finite JSON value")
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def changes_for(value, path=()):
    changes = []
    if isinstance(value, dict):
        owned = {old for old, new in IDS.items() if any(value.get(field) in (old, new) for field in ("type", "class_type"))}
        if owned and ("id" in value or "inputs" in value or "class_type" in value):
            for field in ("type", "class_type"):
                old = value.get(field)
                if isinstance(old, str) and old in IDS:
                    changes.append({"path": path+(field,), "before": old, "after": IDS[old]})
            properties = value.get("properties", {})
            if isinstance(properties, dict):
                for key, old in properties.items():
                    if key in NAME_FIELDS and isinstance(old, str) and old in owned:
                        changes.append({"path": path+("properties", key), "before": old, "after": IDS[old]})
        for key, child in value.items():
            if key not in {"properties", "widgets_values"}:
                changes.extend(changes_for(child, path+(key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value): changes.extend(changes_for(child, path+(index,)))
    return changes


def string_spans(text):
    spans, decoder = {}, json.JSONDecoder()
    def value_at(pos, path):
        pos = SPACE.match(text, pos).end()
        if text[pos] == "{":
            pos = SPACE.match(text, pos+1).end()
            while text[pos] != "}":
                key, pos = decoder.raw_decode(text, pos)
                pos = SPACE.match(text, pos).end()
                pos = value_at(pos+1, path+(key,))
                pos = SPACE.match(text, pos).end()
                if text[pos] == "}": break
                pos = SPACE.match(text, pos+1).end()
            return pos+1
        if text[pos] == "[":
            pos, index = SPACE.match(text, pos+1).end(), 0
            while text[pos] != "]":
                pos = SPACE.match(text, value_at(pos, path+(index,))).end(); index += 1
                if text[pos] == "]": break
                pos = SPACE.match(text, pos+1).end()
            return pos+1
        item, end = decoder.raw_decode(text, pos)
        if isinstance(item, str): spans[path] = (pos, end, item)
        return end
    value_at(0, ())
    return spans


def graph_facts(value):
    nodes, links, api_nodes = [], [], []
    def visit(item, path=()):
        if isinstance(item, dict):
            if isinstance(item.get("nodes"), list):
                nodes.extend((path, node.get("id")) for node in item["nodes"] if isinstance(node, dict))
                links.extend((path, link) for link in item.get("links", []))
            if "class_type" in item and "inputs" in item: api_nodes.append(path)
            for key, child in item.items():
                if key != "widgets_values": visit(child, path+(key,))
        elif isinstance(item, list):
            for index, child in enumerate(item): visit(child, path+(index,))
    visit(value)
    canonical = lambda rows: sorted(json.dumps(row, ensure_ascii=True, sort_keys=True) for row in rows)
    link_ids = [(path, link[0] if isinstance(link, list) else link.get("id")) for path, link in links]
    return {"node_count": len(nodes), "connection_count": len(links), "node_ids": canonical(nodes), "link_ids": canonical(link_ids), "connections": canonical(links), "api_node_keys": canonical(api_nodes)}


def migrate_bytes(raw):
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    original = decode(text); changes = changes_for(original)
    if not changes: return raw, [], {}
    spans = string_spans(text)
    replacements = []
    for change in changes:
        first, last, actual = spans[change["path"]]
        if actual != change["before"]: raise ValueError("Field span mismatch")
        replacements.append((first, last, json.dumps(change["after"])))
    updated = text
    for first, last, replacement in sorted(replacements, reverse=True):
        updated = updated[:first] + replacement + updated[last:]
    result = decode(updated); restored = copy.deepcopy(result)
    for change in changes:
        parent = restored
        for key in change["path"][:-1]: parent = parent[key]
        key = change["path"][-1]
        if parent[key] != change["after"]: raise ValueError("Migration value mismatch")
        parent[key] = change["before"]
    if restored != original: raise ValueError("Unrelated workflow data changed")
    before, after = graph_facts(original), graph_facts(result)
    if before != after: raise ValueError("Graph structure changed")
    checks = {"node_count": before["node_count"], "connection_count": before["connection_count"], "node_ids_equal": True, "link_ids_equal": True, "connections_equal": True, "other_fields_equal": True, "byte_layout_preserved": True}
    return bom+updated.encode("utf-8"), changes, checks


def migrate_file(path, original, replacement):
    if path.read_bytes() != original: raise ValueError("Workflow changed since scan; rescan before migrating")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + f".zv-{stamp}-{uuid.uuid4().hex[:8]}.bak")
    with backup.open("xb") as handle: handle.write(original)
    if backup.read_bytes() != original: raise ValueError("Backup verification failed")
    # Preserve CRLF, indentation, key order and opaque widget strings. Only the
    # parsed string-value spans selected by migrate_bytes have changed.
    with path.open("r+b") as handle:
        if handle.read() != original: raise ValueError("Workflow changed during backup; source was not edited")
        handle.seek(0); handle.write(replacement); handle.truncate()
    if path.read_bytes() != replacement: raise ValueError("Written workflow differs from the verified plan")
    decode(replacement.decode("utf-8-sig"))
    return backup


def migrate_directory(root, apply=False):
    root = Path(root).resolve()
    files = sorted(root.rglob("*.json"))
    report = {"root": str(root), "scanned": len(files), "applied": apply, "hits": [], "parse_errors": [], "unmatched_unchanged": 0}
    untouched = []
    for path in files:
        if not path.resolve().is_relative_to(root): raise ValueError("Workflow path escapes the specified directory")
        raw = path.read_bytes()
        try: replacement, changes, checks = migrate_bytes(raw)
        except (UnicodeError, ValueError, RecursionError) as error:
            report["parse_errors"].append({"file": str(path), "error": str(error)}); continue
        if not changes:
            untouched.append((path, hashlib.sha256(raw).hexdigest())); continue
        backup = migrate_file(path, raw, replacement) if apply else None
        report["hits"].append({"file": str(path), "backup": str(backup) if backup else None, "fields": changes, "checks": checks,
                               "before_sha256": hashlib.sha256(raw).hexdigest(), "after_sha256": hashlib.sha256(replacement).hexdigest()})
    for path, digest in untouched:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise ValueError("An unmatched workflow changed during the scan")
    report["unmatched_unchanged"] = len(untouched)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate_directory(args.root, args.apply), ensure_ascii=True, indent=2))
