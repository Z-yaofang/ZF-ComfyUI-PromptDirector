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
        "participates": bool(row["enabled"] and not row["linked_video_clip_id"]),
        "banks": [DEFAULT_BANK[row["kind"]]],
    })


def align_bindings(state, inventory):
    """Materialize defaults only when the user explicitly aligns materials."""
    state["bindings"] = {
        row["item_id"]: copy.deepcopy(binding_for(state, row)) for row in inventory
    }
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


def reusable_template(state, inventory):
    """Future presets use typed slots, never actual media/project/detection data."""
    fields = ("mode", "director_focus", "intent", "style", "must_keep", "must_change", "ending", "forbidden", "performance", "camera", "dialogue", "visible_text", "soundscape", "music")
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
