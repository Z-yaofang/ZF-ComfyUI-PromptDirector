"""Apply only exact, empty, explicitly authorized prose slots."""

import copy

from .contract import (
    ContractError, matches_type, normalize_plan, parse_json, paths_overlap,
    pointer_get, pointer_owner, pointer_set, unsafe_strings,
)
from .validation import editable_gap_path, empty, validate_plan


def apply_llm_patch(plan, patch):
    result = normalize_plan(plan)
    report = {"accepted": [], "rejected": []}
    if isinstance(patch, str):
        try:
            patch = parse_json(patch)
        except ContractError:
            report["rejected"].append({"path": "", "reason": "invalid_json"})
            return result, report
    if isinstance(patch, dict):
        operations = [{"op": "replace", "path": path, "value": value} for path, value in patch.items()]
    elif isinstance(patch, list):
        operations = patch
    else:
        report["rejected"].append({"path": "", "reason": "expected_field_map_or_patch_array"})
        return result, report
    for index, op in enumerate(operations):
        path = op.get("path", "") if isinstance(op, dict) else ""
        record = {"index": index, "path": path if isinstance(path, str) else ""}
        reason = None
        if not isinstance(op, dict) or set(op) != {"op", "path", "value"} or op["op"] != "replace":
            reason = "only_replace_with_exact_path_and_value"
        elif not isinstance(path, str):
            reason = "invalid_path"
        else:
            try:
                current = pointer_get(result, path)
            except (ValueError, KeyError, IndexError):
                reason = "unknown_path"
        if reason is None:
            try:
                locked = any(paths_overlap(path, lock["path"]) for lock in result["locks"])
                stale_lock = any(pointer_owner(result, lock["path"]) != lock.get("target_id") for lock in result["locks"])
            except (ValueError, KeyError, IndexError):
                locked = True
                stale_lock = True
            gaps = [g for g in result["gaps"] if g["path"] == path]
            if stale_lock:
                reason = "stale_lock_binding"
            elif locked:
                reason = "locked_path"
            elif not editable_gap_path(path):
                reason = "structural_path_not_patchable"
            elif len(gaps) != 1 or gaps[0]["status"] != "pending":
                reason = "unauthorized_gap"
            elif pointer_owner(result, path) != gaps[0].get("target_id"):
                reason = "stale_gap_binding"
            elif not empty(current):
                reason = "existing_content_cannot_be_rewritten"
            elif gaps[0]["value_type"] != "string" or not matches_type(op["value"], "string"):
                reason = "type_mismatch"
            elif empty(op["value"]):
                reason = "empty_value"
            elif unsafe_strings(op["value"]):
                reason = "unsafe_payload"
        if reason is None:
            candidate = copy.deepcopy(result)
            pointer_set(candidate, path, op["value"])
            next(g for g in candidate["gaps"] if g["path"] == path)["status"] = "resolved"
            before = {(e["path"], e["code"]) for e in validate_plan(result)["errors"]}
            introduced = [e for e in validate_plan(candidate)["errors"] if (e["path"], e["code"]) not in before]
            if introduced:
                reason = "validation_regression"
                record["issues"] = introduced
            else:
                result = candidate
                report["accepted"].append({**record, "reason": "authorized_gap_filled"})
        if reason:
            report["rejected"].append({**record, "reason": reason})
    result["ready"] = validate_plan(result)["ready"]
    return result, report
