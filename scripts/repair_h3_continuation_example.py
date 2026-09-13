"""Repair the saved continuation example used by the local H3 test workflow.

The workflow is intentionally selected by path; this script never searches or
rewrites other workflow files.  It preserves the requested output duration,
moves that window to the tail of Video 1, and makes the saved interview recipe
match its written continuation intent.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _one(nodes, node_type):
    matches = [node for node in nodes if node.get("type") == node_type]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {node_type}, found {len(matches)}")
    return matches[0]


def _widget_text(node):
    value = node.get("widgets_values")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    raise ValueError(f"node {node.get('id')} does not contain one JSON text widget")


def _set_widget_text(node, value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if isinstance(node.get("widgets_values"), list):
        node["widgets_values"][0] = encoded
    else:
        node["widgets_values"] = encoded


def repair(workflow):
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("workflow does not contain a node list")
    desk = _one(nodes, "ZVUniversalMediaEvidenceDesk")
    interview = _one(nodes, "ZVH3InterviewForm")
    _one(nodes, "ZVH3ReferenceOutlet")

    project = json.loads(_widget_text(desk))
    state = json.loads(_widget_text(interview))
    videos = project.get("video_track") or []
    if len(videos) != 1:
        raise ValueError(f"continuation example expects one video on the track, found {len(videos)}")
    video = videos[0]
    clip_id = video.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id:
        raise ValueError("Video 1 has no stable clip id")

    window = project.get("processing_window") or {}
    fps = float(window.get("fps", 24))
    if abs(fps - 24) > 1e-9:
        raise ValueError(f"continuation example expects a 24 fps H3 window, found {fps}")
    old_frames = window.get("frame_count")
    if not isinstance(old_frames, int):
        old_frames = int(round((float(window["end_seconds"]) - float(window["start_seconds"])) * fps))
    if not 48 <= old_frames <= 360:
        raise ValueError(f"saved H3 window must be 48–360 frames, found {old_frames}")

    timeline_end = float(video["timeline_in_seconds"]) + float(video["source_out_seconds"]) - float(video["source_in_seconds"])
    end_frame = math.floor(timeline_end * fps + 1e-9)
    start_frame = end_frame - old_frames
    if start_frame < math.ceil(float(video["timeline_in_seconds"]) * fps - 1e-9):
        raise ValueError("Video 1 is too short to preserve the saved H3 window duration")
    window.update({
        "start_seconds": start_frame / fps,
        "end_seconds": end_frame / fps,
        "fps": fps,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "frame_count": old_frames,
    })

    state["recipe"] = "video_continue"
    state["mode"] = "auto"
    state["media_roles"] = {clip_id: ["video_continue"]}
    snapshot = state.get("reference_detection")
    if not isinstance(snapshot, dict) or [row.get("item_id") for row in snapshot.get("videos", [])] != [clip_id]:
        # The saved graph is still fixed and correct, but a mismatched snapshot
        # must be recreated explicitly in the interview UI.
        state["reference_detection"] = None

    _set_widget_text(desk, project)
    _set_widget_text(interview, state)
    return {
        "desk_id": desk.get("id"),
        "interview_id": interview.get("id"),
        "clip_id": clip_id,
        "window": [start_frame / fps, end_frame / fps, old_frames],
        "recipe": state["recipe"],
        "detection_preserved": state.get("reference_detection") is not None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--backup-suffix", default=".before-node182-state-fix.bak")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = args.workflow.read_bytes()
    workflow = json.loads(raw.decode("utf-8-sig"))
    result = repair(workflow)
    if not args.dry_run:
        backup = Path(str(args.workflow) + args.backup_suffix)
        if backup.exists():
            raise FileExistsError(f"refusing to overwrite backup: {backup}")
        backup.write_bytes(raw)
        encoded = json.dumps(workflow, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        temporary = Path(str(args.workflow) + ".node182-fix.tmp")
        temporary.write_bytes(encoded)
        temporary.replace(args.workflow)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
