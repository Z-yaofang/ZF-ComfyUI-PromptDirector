"""Convert a saved ComfyUI canvas to an API prompt without executing it.

This utility is deliberately offline: it never calls /prompt, starts a server,
or constructs a PromptExecutor. The optional loop check is only a structural
precheck: server-side input validation can discover fewer reachable nodes,
especially through custom dynamic inputs, and can reject a graph that passes
the precheck.
"""

import argparse
import json
from pathlib import Path
import sys


COMFY_ROOT = Path(__file__).resolve().parents[3]
NON_EXECUTING_TYPES = {"GetNode", "SetNode", "Note", "MarkdownNote", "Reroute"}
OUTPUT_TYPES = {
    "SaveVideo", "VHS_VideoCombine", "SaveImage", "PreviewImage",
    "ImageAndMaskPreview", "easy showAnything", "PreviewAny", "PurgeVRAM_UTK",
    "MathExpression|pysssss",
}


class ConversionError(ValueError):
    pass


def ui_to_api_prompt(workflow):
    """Resolve same-canvas Set/Get nodes and mode=4 bypass into API links."""
    nodes = {str(node["id"]): node for node in workflow["nodes"]}
    if len(nodes) != len(workflow["nodes"]):
        raise ConversionError("duplicate node IDs")
    links = {row[0]: row for row in workflow["links"]}
    setters = {}
    for node in workflow["nodes"]:
        if node["type"] == "SetNode" and node.get("widgets_values"):
            alias = node["widgets_values"][0]
            if alias in setters:
                raise ConversionError(f"ambiguous SetNode alias: {alias}")
            setters[alias] = node

    def resolve_input(node, slot, visited):
        port = node.get("inputs", [])[slot]
        link_id = port.get("link")
        if link_id is None:
            return None
        link = links.get(link_id)
        if link is None or str(link[3]) != str(node["id"]) or link[4] != slot:
            raise ConversionError(f"broken input link {link_id} on node {node['id']}")
        source = nodes.get(str(link[1]))
        if source is None:
            raise ConversionError(f"missing source node {link[1]} for link {link_id}")
        return resolve_output(source, link[2], visited)

    def resolve_output(node, slot, visited):
        marker = (node["id"], slot)
        if marker in visited:
            raise ConversionError(f"Set/Get or bypass cycle at node {node['id']} output {slot}")
        visited = visited | {marker}
        if node.get("mode", 0) == 2:
            return None
        if node.get("mode", 0) == 4 or node["type"] == "Reroute":
            outputs = node.get("outputs", [])
            if slot >= len(outputs):
                raise ConversionError(f"missing output {slot} on bypass node {node['id']}")
            output_type = outputs[slot]["type"]
            for index, port in enumerate(node.get("inputs", [])):
                if port["type"] in (output_type, "*") or output_type == "*":
                    return resolve_input(node, index, visited)
            return None
        if node["type"] == "GetNode":
            values = node.get("widgets_values") or []
            setter = setters.get(values[0]) if values else None
            return resolve_input(setter, slot, visited) if setter else None
        if node["type"] == "SetNode":
            return resolve_input(node, slot, visited)
        if slot >= len(node.get("outputs", [])):
            raise ConversionError(f"missing output {slot} on node {node['id']}")
        return [str(node["id"]), slot]

    prompt = {}
    for node in workflow["nodes"]:
        kind = node["type"]
        if node.get("mode", 0) in (2, 4) or kind in NON_EXECUTING_TYPES or kind.startswith("Fast Groups"):
            continue
        named = node.get("widgets_values_named")
        values = node.get("widgets_values")
        if named is not None and not isinstance(named, dict):
            raise ConversionError(f"invalid named widgets on node {node['id']}")
        if named is None and isinstance(values, dict):
            named = values
        if named is None and isinstance(values, list) and values:
            raise ConversionError(f"node {node['id']} ({kind}) has positional widgets without names")
        inputs = {key: value for key, value in (named or {}).items() if key != "videopreview"}
        for index, port in enumerate(node.get("inputs", [])):
            source = resolve_input(node, index, set())
            if source is not None:
                inputs[port["name"]] = source
        prompt[str(node["id"])] = {
            "class_type": kind,
            "inputs": inputs,
            "_meta": {"title": node.get("title") or kind},
        }
    return prompt


def native_loop_check(prompt, extra_roots=()):
    """Precheck loop structure, optimistically treating all nodes as validated."""
    sys.path.insert(0, str(COMFY_ROOT))
    from comfy_execution.validation import validate_loops

    roots = {node_id for node_id, node in prompt.items() if node["class_type"] in OUTPUT_TYPES}
    roots.update(map(str, extra_roots))
    if not roots:
        raise ConversionError("no output roots for native loop validation")
    starts = {node_id for node_id, node in prompt.items() if node["class_type"] == "StartLoop"}
    ends = {node_id for node_id, node in prompt.items() if node["class_type"] == "EndLoop"}
    return validate_loops(prompt, roots, set(prompt), starts, ends), sorted(roots)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path, help="saved UI workflow JSON")
    parser.add_argument("--output", type=Path, help="write the converted API prompt JSON")
    parser.add_argument("--validate-loop", action="store_true", help="run structural loop precheck; not server-side prompt validation")
    parser.add_argument("--output-root", action="append", default=[], help="additional output node ID for loop validation")
    args = parser.parse_args()
    workflow = json.loads(args.workflow.read_text(encoding="utf-8-sig"))
    prompt = ui_to_api_prompt(workflow)
    report = {"source": str(args.workflow), "node_count": len(prompt)}
    ids = workflow.get("extra", {}).get("zv_animate_once", {}).get("new_node_ids", {})
    if ids:
        report["final_chain"] = {
            name: {"id": str(ids[name]), "present": str(ids[name]) in prompt}
            for name in ("end", "finish", "save") if name in ids
        }
    if args.validate_loop:
        pairs, roots = native_loop_check(prompt, args.output_root)
        report["structural_loop_precheck"] = {
            "pairs": pairs, "output_roots": roots,
            "assumes_all_nodes_validated": True,
            "server_validation_required": True,
        }
    if args.output:
        args.output.write_text(json.dumps(prompt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["output"] = str(args.output)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
