"""Replace the legacy per-material/ZFI test wiring with one fixed H3 outlet.

This is intentionally a saved-workflow migration, not runtime graph mutation.
It preserves every unrelated node and link, writes one recoverable ``.bak``
copy, and validates both sides of every link before replacing the JSON file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


HUB_TYPE = "ZVH3ReferenceOutlet"
HUB_OUTPUTS = (
    ("first_frame", "IMAGE"),
    ("last_frame", "IMAGE"),
    *((f"ref_image_{index}", "IMAGE") for index in range(1, 10)),
    *((f"ref_video_{index}", "IMAGE") for index in range(1, 4)),
    *((f"ref_video_audio_{index}", "AUDIO") for index in range(1, 4)),
    ("drive_audio", "AUDIO"),
    ("final_audio", "AUDIO"),
    *((f"ref_audio_{index}", "AUDIO") for index in range(1, 4)),
    ("reference_plan_json", "STRING"),
    ("report", "STRING"),
)

# These IDs belong to the named test workflow and are asserted before removal.
LEGACY_NODE_TYPES = {
    173: "ZFI",
    174: "ZFI",
    175: "ZFI",
    176: "ZVPictureOutlet",
    177: "ZVVideoOutlet",
}


def _nodes_by_id(workflow):
    return {int(node["id"]): node for node in workflow["nodes"]}


def _input(node, name):
    for index, value in enumerate(node.get("inputs", [])):
        if value.get("name") == name:
            return index, value
    raise ValueError(f"node {node.get('id')} ({node.get('type')}) lacks input {name}")


def _output(node, name):
    for index, value in enumerate(node.get("outputs", [])):
        if value.get("name") == name:
            return index, value
    raise ValueError(f"node {node.get('id')} ({node.get('type')}) lacks output {name}")


def _append_optional_input(node, name, value_type):
    try:
        return _input(node, name)[0]
    except ValueError:
        node.setdefault("inputs", []).append(
            {
                "label": name,
                "localized_name": name,
                "name": name,
                "shape": 7,
                "type": value_type,
                "link": None,
            }
        )
        return len(node["inputs"]) - 1


def _widget_names(node):
    return [
        value.get("widget", {}).get("name")
        for value in node.get("inputs", [])
        if isinstance(value.get("widget"), dict) and value["widget"].get("name")
    ]


def _set_widget(node, name, value):
    names = _widget_names(node)
    if name not in names:
        raise ValueError(f"node {node.get('id')} lacks widget {name}")
    index = names.index(name)
    widgets = node.get("widgets_values")
    if not isinstance(widgets, list) or index >= len(widgets):
        raise ValueError(f"node {node.get('id')} has no saved value for widget {name}")
    widgets[index] = value
    named = node.get("widgets_values_named")
    if isinstance(named, dict):
        named[name] = value


def _widget_value(node, name):
    named = node.get("widgets_values_named")
    if isinstance(named, dict) and name in named:
        return named[name]
    names = _widget_names(node)
    widgets = node.get("widgets_values")
    if name not in names or not isinstance(widgets, list):
        return None
    index = names.index(name)
    return widgets[index] if index < len(widgets) else None


def _hub_node(node_id):
    return {
        "id": node_id,
        "type": HUB_TYPE,
        "pos": [-5550, 1510],
        "size": [440, 650],
        "flags": {},
        "order": 30,
        "mode": 0,
        "inputs": [
            {
                "localized_name": "reference_plan",
                "name": "reference_plan",
                "type": "ZV_H3_REFERENCE_PLAN",
                "link": None,
            }
        ],
        "outputs": [
            {
                "localized_name": name,
                "name": name,
                "type": value_type,
                "links": [],
            }
            for name, value_type in HUB_OUTPUTS
        ],
        "title": "ZV H3 素材对齐出口 · 官方完整容量",
        "properties": {
            "aux_id": "Z-yaofang/ZF-ComfyUI-PromptDirector",
            "Node name for S&R": HUB_TYPE,
        },
        "widgets_values": [],
    }


def _remove_links(workflow, removed_node_ids):
    removed_link_ids = {
        int(link[0])
        for link in workflow["links"]
        if int(link[1]) in removed_node_ids or int(link[3]) in removed_node_ids
    }
    workflow["links"] = [
        link for link in workflow["links"] if int(link[0]) not in removed_link_ids
    ]
    for node in workflow["nodes"]:
        for value in node.get("inputs", []):
            if value.get("link") in removed_link_ids:
                value["link"] = None
        for value in node.get("outputs", []):
            if isinstance(value.get("links"), list):
                value["links"] = [
                    link_id for link_id in value["links"] if link_id not in removed_link_ids
                ]


def _connect(workflow, link_id, source, source_name, target, target_name):
    source_slot, source_output = _output(source, source_name)
    target_slot, target_input = _input(target, target_name)
    if target_input.get("link") is not None:
        raise ValueError(
            f"refusing to overwrite node {target['id']} input {target_name}: "
            f"link {target_input.get('link')} remains"
        )
    source_links = source_output.get("links")
    if not isinstance(source_links, list):
        source_links = []
        source_output["links"] = source_links
    source_links.append(link_id)
    target_input["link"] = link_id
    workflow["links"].append(
        [link_id, source["id"], source_slot, target["id"], target_slot, source_output["type"]]
    )


def _validate(workflow):
    nodes = _nodes_by_id(workflow)
    if len(nodes) != len(workflow["nodes"]):
        raise ValueError("duplicate node ID")
    links = {int(link[0]): link for link in workflow["links"]}
    if len(links) != len(workflow["links"]):
        raise ValueError("duplicate link ID")
    for link_id, link in links.items():
        _id, source_id, source_slot, target_id, target_slot, value_type = link
        if source_id not in nodes or target_id not in nodes:
            raise ValueError(f"link {link_id} points to a missing node")
        source = nodes[source_id]
        target = nodes[target_id]
        if not 0 <= source_slot < len(source.get("outputs", [])):
            raise ValueError(f"link {link_id} has an invalid source slot")
        if not 0 <= target_slot < len(target.get("inputs", [])):
            raise ValueError(f"link {link_id} has an invalid target slot")
        output = source["outputs"][source_slot]
        target_input = target["inputs"][target_slot]
        if link_id not in (output.get("links") or []):
            raise ValueError(f"link {link_id} is missing from its source output")
        if target_input.get("link") != link_id:
            raise ValueError(f"link {link_id} is missing from its target input")
        # Existing third-party workflow links occasionally carry a historical
        # wildcard/type label.  Enforce the new contract without rewriting or
        # rejecting unrelated legacy links.
        if source.get("type") in {HUB_TYPE, "ZVH3InterviewForm"} and output.get("type") != value_type:
            raise ValueError(f"link {link_id} type differs from its source output")

    hub = next((node for node in workflow["nodes"] if node.get("type") == HUB_TYPE), None)
    if hub is None:
        raise ValueError("fixed H3 outlet was not created")
    if tuple((row["name"], row["type"]) for row in hub["outputs"]) != HUB_OUTPUTS:
        raise ValueError("fixed H3 outlet output contract is incomplete")
    if any(node_id in nodes for node_id in LEGACY_NODE_TYPES):
        raise ValueError("legacy outlet/ZFI nodes remain")

    def require_connection(source, source_name, target, target_name):
        source_slot, _source_output = _output(source, source_name)
        target_slot, target_input = _input(target, target_name)
        link_id = target_input.get("link")
        link = links.get(int(link_id)) if isinstance(link_id, int) else None
        expected = (source["id"], source_slot, target["id"], target_slot)
        actual = tuple(link[index] for index in (1, 2, 3, 4)) if link else None
        if actual != expected:
            raise ValueError(
                f"{target['id']}.{target_name} must connect to "
                f"{source['id']}.{source_name}; got {actual}"
            )

    require_connection(nodes[172], "reference_plan", hub, "reference_plan")
    conditioning_map = [
        ("first_frame", "first_frame"),
        ("last_frame", "last_frame"),
        *((f"ref_image_{index + 1}", f"ref_images.ref_image_{index}") for index in range(9)),
        *((f"ref_video_{index + 1}", f"ref_videos.ref_video_{index}") for index in range(3)),
        *((f"ref_video_audio_{index + 1}", f"ref_video_audios.ref_video_audio_{index}") for index in range(3)),
        ("drive_audio", "drive_audio"),
        ("final_audio", "final_audio"),
        *((f"ref_audio_{index + 1}", f"ref_audios.ref_audio_{index}") for index in range(3)),
    ]
    for node_id in (7, 14):
        for source_name, target_name in conditioning_map:
            require_connection(hub, source_name, nodes[node_id], target_name)
    for index in range(11):
        require_connection(hub, HUB_OUTPUTS[index][0], nodes[146], f"image{index + 1}")
    for index, target_name in enumerate(("video_frames", "video_frames2", "video_frames3")):
        require_connection(hub, f"ref_video_{index + 1}", nodes[146], target_name)

    desk = nodes[165]
    if _input(desk, "width")[1].get("link") is None or _input(desk, "height")[1].get("link") is None:
        raise ValueError("material desk width/height are not connected")
    for node_id in (7, 14):
        conditioning = nodes[node_id]
        if _widget_value(conditioning, "add_source_as_reference") is not True:
            raise ValueError(f"node {node_id} must keep add_source_as_reference=true")
        if _widget_value(conditioning, "prompt_primary_audio_ordinal") != 0:
            raise ValueError(f"node {node_id} must keep prompt_primary_audio_ordinal=0")


def migrate(workflow):
    nodes = _nodes_by_id(workflow)
    required = {
        7: "MiniMaxH3AudioConditioningT8",
        14: "MiniMaxH3AudioConditioningT8",
        146: "ZFPromptDirectorLocalLLM",
        165: "ZVUniversalMediaEvidenceDesk",
        172: "ZVH3InterviewForm",
        **LEGACY_NODE_TYPES,
    }
    for node_id, expected_type in required.items():
        actual = nodes.get(node_id, {}).get("type")
        if actual != expected_type:
            raise ValueError(f"node {node_id}: expected {expected_type}, got {actual!r}")
    if any(node.get("type") == HUB_TYPE for node in workflow["nodes"]):
        raise ValueError("workflow already contains a fixed H3 outlet")

    _remove_links(workflow, set(LEGACY_NODE_TYPES))
    workflow["nodes"] = [
        node for node in workflow["nodes"] if int(node["id"]) not in LEGACY_NODE_TYPES
    ]
    nodes = _nodes_by_id(workflow)

    interview = nodes[172]
    if len(interview.get("outputs", [])) == 8:
        interview["outputs"].append(
            {
                "localized_name": "reference_plan",
                "name": "reference_plan",
                "type": "ZV_H3_REFERENCE_PLAN",
                "links": [],
            }
        )
    reference_slot, reference_output = _output(interview, "reference_plan")
    if reference_slot != 8 or reference_output.get("type") != "ZV_H3_REFERENCE_PLAN":
        raise ValueError("interview reference_plan must remain append-only output 8")

    hub_id = max(int(workflow.get("last_node_id", 0)), *(int(node["id"]) for node in workflow["nodes"])) + 1
    hub = _hub_node(hub_id)
    workflow["nodes"].append(hub)
    nodes[hub_id] = hub

    stage1 = nodes[146]
    _append_optional_input(stage1, "image10", "IMAGE")
    _append_optional_input(stage1, "image11", "IMAGE")
    for conditioning_id in (7, 14):
        conditioning = nodes[conditioning_id]
        for index in range(2, 9):
            _append_optional_input(conditioning, f"ref_images.ref_image_{index}", "IMAGE")
        _append_optional_input(conditioning, "ref_video_audios.ref_video_audio_2", "AUDIO")
        _set_widget(conditioning, "add_source_as_reference", True)
        _set_widget(conditioning, "prompt_primary_audio_ordinal", 0)

    next_link = max(
        int(workflow.get("last_link_id", 0)),
        *(int(link[0]) for link in workflow["links"]),
    ) + 1

    def connect(source, source_name, target, target_name):
        nonlocal next_link
        _connect(workflow, next_link, source, source_name, target, target_name)
        next_link += 1

    connect(interview, "reference_plan", hub, "reference_plan")

    conditioning_map = [
        ("first_frame", "first_frame"),
        ("last_frame", "last_frame"),
        *((f"ref_image_{index + 1}", f"ref_images.ref_image_{index}") for index in range(9)),
        *((f"ref_video_{index + 1}", f"ref_videos.ref_video_{index}") for index in range(3)),
        *((f"ref_video_audio_{index + 1}", f"ref_video_audios.ref_video_audio_{index}") for index in range(3)),
        ("drive_audio", "drive_audio"),
        ("final_audio", "final_audio"),
        *((f"ref_audio_{index + 1}", f"ref_audios.ref_audio_{index}") for index in range(3)),
    ]
    for conditioning_id in (7, 14):
        for source_name, target_name in conditioning_map:
            connect(hub, source_name, nodes[conditioning_id], target_name)

    for index in range(11):
        connect(hub, HUB_OUTPUTS[index][0], stage1, f"image{index + 1}")
    for index, target_name in enumerate(("video_frames", "video_frames2", "video_frames3")):
        connect(hub, f"ref_video_{index + 1}", stage1, target_name)

    workflow["last_node_id"] = max(int(workflow.get("last_node_id", 0)), hub_id)
    workflow["last_link_id"] = next_link - 1

    workflow["groups"] = [group for group in workflow.get("groups", []) if int(group.get("id", -1)) != 57]
    for group in workflow.get("groups", []):
        if int(group.get("id", -1)) == 56:
            group["title"] = "H3 官方固定素材出口 · 一次预接"
            group["bounding"] = [-5600, 1460, 540, 760]

    _validate(workflow)
    return workflow


def repair_existing(workflow):
    nodes = _nodes_by_id(workflow)
    hubs = [node for node in workflow["nodes"] if node.get("type") == HUB_TYPE]
    if len(hubs) != 1:
        raise ValueError(f"expected one existing fixed H3 outlet, got {len(hubs)}")
    for node_id in (7, 14):
        _set_widget(nodes[node_id], "add_source_as_reference", True)
        _set_widget(nodes[node_id], "prompt_primary_audio_ordinal", 0)
    _validate(workflow)
    return workflow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repair-existing", action="store_true")
    args = parser.parse_args()
    path = args.workflow.resolve()
    original = path.read_bytes()
    workflow = json.loads(original.decode("utf-8"))
    migrated = repair_existing(workflow) if args.repair_existing else migrate(workflow)
    if args.dry_run:
        hub = next(node for node in migrated["nodes"] if node.get("type") == HUB_TYPE)
        print(
            f"validated {HUB_TYPE}: node={hub['id']} outputs={len(hub['outputs'])} "
            f"nodes={len(migrated['nodes'])} links={len(migrated['links'])}"
        )
        return
    backup = path.with_suffix(path.suffix + ".before-h3-official-outlet.bak")
    if not backup.exists():
        shutil.copyfile(path, backup)
    path.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wired {HUB_TYPE}: nodes={len(migrated['nodes'])} "
        f"links={len(migrated['links'])} backup={backup}"
    )


if __name__ == "__main__":
    main()
