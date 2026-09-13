"""Versioned, JSON-only H3 plans. No ComfyUI or media dependencies."""

import copy
import json
import math
import re
from pathlib import Path


SCHEMA_VERSION = "h3-focus-plan-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "h3-focus-plan.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
KINDS = {"picture": "Picture", "video": "Video", "audio": "Audio"}
LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio) ([1-9][0-9]*)>")
ALIAS_RE = re.compile(r"【\s*(图片|图|视频|音频|人物|主体)\s*([1-9][0-9]*)\s*】")
ALIASES = {"图片": "Picture", "图": "Picture", "视频": "Video", "音频": "Audio", "人物": "Subject", "主体": "Subject"}
PROTECTED_RE = re.compile(r'(<d>.*?</d>|"[^"\n]*")', re.S)
SECRET_RE = re.compile(r"(?i)(?:\b(?:api[_-]?key|translation[_-]?key|access[_-]?token)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{16,})")
COMMAND_RE = re.compile(r"(?im)^\s*(?:ffmpeg\s+-|(?:cmd(?:\.exe)?\s+/c|powershell(?:\.exe)?\s+-|pwsh\s+-|(?:ba)?sh\s+-c)\s)")


class ContractError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("; ".join(f"{i['path']}: {i['message']}" for i in issues))


def issue(path, code, message):
    return {"path": path, "code": code, "message": message}


def escape_pointer(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def pointer_parts(path):
    if not isinstance(path, str) or (path and not path.startswith("/")) or re.search(r"~(?![01])", path):
        raise ValueError("Expected a canonical JSON Pointer")
    return [] if not path else [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def pointer_get(document, path):
    value = document
    for part in pointer_parts(path):
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("Array index is not canonical")
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("Pointer crosses a scalar")
    return value


def pointer_set(document, path, value):
    parts = pointer_parts(path)
    if not parts:
        raise ValueError("Whole-plan replacement is not allowed")
    parent_path = "/" + "/".join(escape_pointer(p) for p in parts[:-1]) if len(parts) > 1 else ""
    parent = pointer_get(document, parent_path)
    key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    parent[key] = value


def pointer_owner(document, path):
    owner = None
    prefix = ""
    for part in pointer_parts(path):
        prefix += "/" + escape_pointer(part)
        value = pointer_get(document, prefix)
        if isinstance(value, dict):
            for key in ("asset_id", "subject_id", "id"):
                if key in value:
                    owner = value[key]
                    break
    return owner


def paths_overlap(a, b):
    left, right = pointer_parts(a), pointer_parts(b)
    return left[:len(right)] == right or right[:len(left)] == left


def matches_type(value, expected):
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "string": isinstance(value, str),
        "number": type(value) is int or (type(value) is float and math.isfinite(value)),
        "integer": type(value) is int,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }[expected]


def resolve_schema(schema):
    return pointer_get(SCHEMA, schema["$ref"][1:]) if "$ref" in schema else schema


def schema_errors(value, schema=None, path=""):
    """Validate the deliberately small schema vocabulary used by our resource."""
    schema = resolve_schema(SCHEMA if schema is None else schema)
    errors = []
    if "anyOf" in schema:
        if not any(not schema_errors(value, branch, path) for branch in schema["anyOf"]):
            errors.append(issue(path, "schema_type", "Value does not match the allowed object or null shape"))
        return errors
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds and not any(matches_type(value, kind) for kind in kinds):
        return [issue(path, "schema_type", "Expected " + "/".join(kinds))]
    if "const" in schema and value != schema["const"]:
        errors.append(issue(path, "schema_const", "Unsupported schema version"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append(issue(path, "schema_enum", "Value is outside the allowed choices"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(issue(path + "/" + escape_pointer(key), "schema_required", "Required field is missing"))
        for key, child in value.items():
            child_path = path + "/" + escape_pointer(key)
            if key in props:
                errors.extend(schema_errors(child, props[key], child_path))
            elif schema.get("additionalProperties") is False:
                errors.append(issue(child_path, "unknown_field", "Unknown fields cannot be saved in this contract"))
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(issue(path, "schema_length", "Too few entries"))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(issue(path, "schema_unique", "Duplicate entries"))
        if "items" in schema:
            for index, child in enumerate(value):
                errors.extend(schema_errors(child, schema["items"], f"{path}/{index}"))
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(issue(path, "schema_length", "Value cannot be empty"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(issue(path, "schema_pattern", "Invalid field format"))
    elif type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            errors.append(issue(path, "non_finite", "Numbers must be finite"))
        for rule, compare in (("minimum", lambda a, b: a < b), ("exclusiveMinimum", lambda a, b: a <= b), ("maximum", lambda a, b: a > b)):
            if rule in schema and compare(value, schema[rule]):
                errors.append(issue(path, "schema_range", "Value is outside the allowed numeric range"))
    return errors


def unsafe_strings(value, path=""):
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(issue(path, "non_json", "JSON object keys must be strings"))
                continue
            if re.sub(r"[^a-z]", "", key.lower()) in {"apikey", "translationkey", "translationapikey", "accesskey", "accesstoken", "shellcommand", "cutcommand", "command", "commands"}:
                errors.append(issue(path + "/" + escape_pointer(key), "unsafe_payload", "Credential and executable-command fields cannot be saved"))
            errors.extend(unsafe_strings(child, path + "/" + escape_pointer(key)))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            errors.extend(unsafe_strings(child, f"{path}/{i}"))
    elif isinstance(value, str) and (SECRET_RE.search(value) or COMMAND_RE.search(value)):
        errors.append(issue(path, "unsafe_payload", "Credentials and executable command strings cannot be saved"))
    elif type(value) is float and not math.isfinite(value):
        errors.append(issue(path, "non_finite", "Numbers must be finite"))
    elif value is not None and not isinstance(value, (str, bool, int, float, dict, list)):
        errors.append(issue(path, "non_json", "Only JSON data can be saved"))
    return errors


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_number)
    except (ValueError, TypeError, RecursionError):
        raise ContractError([issue("", "invalid_json", "Expected strict JSON without duplicate keys or non-finite numbers")]) from None


def invalid_number(value):
    raise ValueError("Non-finite JSON number")


def normalize_labels(text):
    if not text:
        return ""
    return "".join(part if index % 2 else ALIAS_RE.sub(lambda m: f"<{ALIASES[m[1]]} {m[2]}>", part)
                   for index, part in enumerate(PROTECTED_RE.split(text)))


def referenced_labels(text):
    text = normalize_labels(text)
    prose = "".join(part for index, part in enumerate(PROTECTED_RE.split(text)) if not index % 2)
    return {match.group(0) for match in LABEL_RE.finditer(prose)}


def selected_asset_ids(plan):
    if plan["segmentation"]["strategy"] != "none":
        return {s["asset_id"] for segment in plan["segmentation"]["segments"] for s in segment["selections"]}
    return {a["asset_id"] for a in plan["media_assets"] if a["selected"]}


def resolve_mode(plan):
    if plan.get("mode_override"):
        return plan["mode_override"]
    if plan["mode"] != "auto":
        return plan["mode"]
    active = selected_asset_ids(plan)
    assets = [a for a in plan["media_assets"] if a["asset_id"] in active]
    roles = sorted(a["role"] for a in assets)
    if not assets:
        return "T2VA"
    if not plan["subjects"] and all(a["kind"] == "picture" for a in assets):
        return {("first_frame",): "I2VA", ("last_frame",): "L2VA", ("first_frame", "last_frame"): "FL2VA"}.get(tuple(roles), "Ref2VA")
    return "Ref2VA"


def normalize_plan(plan):
    if not isinstance(plan, dict):
        raise ContractError([issue("", "schema_type", "Plan must be an object")])
    result = copy.deepcopy(plan)
    result.pop("ready", None)
    result.pop("effective_mode", None)
    errors = schema_errors(result) + unsafe_strings(result)
    if errors:
        raise ContractError(errors)
    counters = result.setdefault("label_counters", {kind: 0 for kind in ("Picture", "Video", "Audio", "Subject")})
    groups = [(a, KINDS[a["kind"]], a["asset_id"]) for a in result["media_assets"]]
    groups += [(s, "Subject", s["subject_id"]) for s in result["subjects"]]
    for item, kind, _ in groups:
        match = LABEL_RE.fullmatch(item.get("official_label", ""))
        if match and match[1] == kind:
            item.setdefault("ordinal", int(match[2]))
        if "ordinal" in item:
            counters[kind] = max(counters[kind], item["ordinal"])
    for item, kind, stable_id in sorted(groups, key=lambda row: (row[1], row[2])):
        if "ordinal" not in item:
            counters[kind] += 1
            item["ordinal"] = counters[kind]
        item.setdefault("official_label", f"<{kind} {item['ordinal']}>")
    result["effective_mode"] = resolve_mode(result)
    for item in result["locks"] + result["gaps"]:
        try:
            item.setdefault("target_id", pointer_owner(result, item["path"]))
        except (ValueError, KeyError, IndexError):
            pass
    result["ready"] = False
    return result


def serialize_plan(plan):
    # Public serialization always derives readiness, including when called directly.
    from .validation import validate_plan

    normalized = normalize_plan(plan)
    normalized["ready"] = validate_plan(normalized)["ready"]
    return json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False)
