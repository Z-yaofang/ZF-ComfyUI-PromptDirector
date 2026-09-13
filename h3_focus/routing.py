"""Mechanical bindings and alignment context. No semantic roles or media IO."""

import copy
import json
from pathlib import Path


RULES = json.loads(Path(__file__).with_name("rules.json").read_text(encoding="utf-8"))
BANKS_BY_KIND = {
    "picture": ("ref_images", "first_frame", "last_frame"),
    "video": ("ref_videos",),
    "audio": ("ref_audios", "drive_audio"),
}
DEFAULT_BANK = {kind: banks[0] for kind, banks in BANKS_BY_KIND.items()}


def model_frame_count(frames):
    length = RULES["local_length"]
    frames = max(length["min"], frames)
    return frames + (length["remainder"] - frames) % length["step"]


def binding_for(state, row):
    return state.get("bindings", {}).get(row["item_id"], {
        "item_id": row["item_id"],
        "participates": bool(row["enabled"] and not row["linked_video_clip_id"] and not (state.get("migration") or {}).get("freeze_pending")),
        "banks": [DEFAULT_BANK[row["kind"]]],
    })


def align_bindings(state, inventory):
    """Materialize defaults only when the user explicitly aligns materials."""
    state["bindings"] = {
        row["item_id"]: copy.deepcopy(binding_for(state, row)) for row in inventory
    }
    return state


def freeze_legacy_selection(state, inventory):
    migration = state.get("migration") or {}
    if not migration.get("freeze_pending"):
        return state
    for row in inventory:
        binding = copy.deepcopy(binding_for(state, row))
        if binding["banks"] == ["reference"]:
            binding["banks"] = [DEFAULT_BANK[row["kind"]]]
        state["bindings"][row["item_id"]] = binding
    if migration.get("legacy_drive_pending"):
        drive = next((row for row in inventory if row["kind"] == "audio" and not row["linked_video_clip_id"]
                      and state["bindings"][row["item_id"]]["participates"]
                      and any(role in {"speech_lipsync", "audio_reuse"} for role in state["media_roles"].get(row["item_id"], []))), None)
        if drive is not None:
            state["bindings"][drive["item_id"]]["banks"] = ["drive_audio"]
    state["migration"] = {"from": "zv-h3-interview-v1"}
    return state


def mechanical_entries(state, inventory):
    result = {"pictures": [], "videos": [], "audios": []}
    active = [row for row in inventory if binding_for(state, row)["participates"]]
    for bank, origin in (("first_frame", "first_frame"), ("last_frame", "last_frame"), ("ref_images", "reference")):
        result["pictures"].extend(
            {"item_id": row["item_id"], "origin": origin}
            for row in active if row["kind"] == "picture" and bank in binding_for(state, row)["banks"]
        )
    videos = [row for row in active if row["kind"] == "video" and "ref_videos" in binding_for(state, row)["banks"]]
    result["videos"] = [{"item_id": row["item_id"], "origin": "reference"} for row in videos]
    result["audios"].extend(
        {"item_id": row["item_id"], "origin": "video_soundtrack"}
        for row in videos if row["source_audio_enabled"] and row["audio_link_id"]
    )
    for bank, origin in (("drive_audio", "drive_audio"), ("ref_audios", "standalone")):
        result["audios"].extend(
            {"item_id": row["item_id"], "origin": origin}
            for row in active if row["kind"] == "audio" and not row["linked_video_clip_id"]
            and bank in binding_for(state, row)["banks"]
        )
    return result


def alignment_context(state, project, inventory):
    assets = {asset["asset_id"]: asset for asset in project.get("assets", [])}
    items = []
    for row in inventory:
        asset = assets.get(row["asset_id"], {})
        items.append({
            "item_id": row["item_id"], "kind": row["kind"], "asset_id": row["asset_id"],
            "source_handle": asset.get("source_handle"), "probe": copy.deepcopy(asset.get("probe", {})),
            "enabled": row["enabled"], "in_window": row["in_window"],
            "linked_video_clip_id": row["linked_video_clip_id"],
            "source_audio_enabled": row["source_audio_enabled"], "audio_link_id": row["audio_link_id"],
            **{key: row[key] for key in ("timeline_in_seconds", "timeline_out_seconds", "source_in_seconds", "source_out_seconds")},
            "binding": copy.deepcopy(binding_for(state, row)),
        })
    return {
        "version": 1, "items": items,
        "window": copy.deepcopy(project.get("processing_window", {})),
        "canvas": copy.deepcopy(project.get("output_canvas")),
        "preset": copy.deepcopy(project.get("processing_preset", {})),
    }


def migrate_v1(value):
    """Freeze historical explicit selections; preserve all text and snapshot data."""
    result = copy.deepcopy(value)
    if value.get("schema_version") != "zv-h3-interview-v1":
        return result
    result["schema_version"] = "zv-h3-interview-v2"
    bindings = {}
    detection = value.get("reference_detection")
    if isinstance(detection, dict):
        for plural, default in (("pictures", "ref_images"), ("videos", "ref_videos"), ("audios", "ref_audios")):
            for entry in detection.get(plural, []):
                if not isinstance(entry, dict) or entry.get("origin") == "video_soundtrack":
                    continue
                item_id = entry.get("item_id")
                if not isinstance(item_id, str):
                    continue
                origin = entry.get("origin")
                bank = origin if origin in {"first_frame", "last_frame", "drive_audio"} else default
                binding = bindings.setdefault(item_id, {"item_id": item_id, "participates": True, "banks": []})
                if bank not in binding["banks"]:
                    binding["banks"].append(bank)
    roles_by_id = value.get("media_roles", {})
    for item_id, roles in (roles_by_id.items() if isinstance(roles_by_id, dict) else []):
        if not roles:
            continue
        roles = [roles] if isinstance(roles, str) else roles
        if not isinstance(roles, list):
            continue
        anchors = [bank for bank in ("first_frame", "last_frame") if bank in roles]
        if isinstance(detection, dict):
            # A real snapshot is the physical authority. Keep old roles as
            # semantics without adding interfaces the model did not receive.
            continue
        # Missing kind is resolved against the actual track during compilation.
        bindings[item_id] = {"item_id": item_id, "participates": True, "banks": anchors or ["reference"]}
        if anchors and any(role not in {"first_frame", "last_frame"} for role in roles):
            bindings[item_id]["banks"].append("ref_images")
    result["bindings"] = bindings
    result["media_purposes"] = {}
    result["alignment"] = None
    result["migration"] = {"from": "zv-h3-interview-v1"}
    if bindings or isinstance(detection, dict):
        result["migration"]["freeze_pending"] = True
        if detection is None:
            result["migration"]["legacy_drive_pending"] = True
    return result


def reusable_template(state, inventory):
    """Future presets use typed slots, never actual media/project/detection data."""
    fields = ("recipe", "mode", "director_focus", "intent", "style", "must_keep", "must_change", "ending", "forbidden", "performance", "camera", "dialogue", "visible_text", "soundscape", "music")
    slots = []
    counters = {kind: 0 for kind in BANKS_BY_KIND}
    for row in inventory:
        if row["linked_video_clip_id"]:
            continue
        counters[row["kind"]] += 1
        binding = binding_for(state, row)
        slots.append({"kind": row["kind"], "slot": counters[row["kind"]],
                      "participates": binding["participates"], "banks": list(binding["banks"]),
                      "roles": list(state.get("media_roles", {}).get(row["item_id"], [])),
                      "purpose": state.get("media_purposes", {}).get(row["item_id"], "")})
    return {"schema_version": "zv-h3-template-v1", "fields": {key: state[key] for key in fields}, "slots": slots}
