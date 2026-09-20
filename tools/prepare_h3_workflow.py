"""Prepare a prompt-only copy of a current H3 interview workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_long_video_workflow import Editor, WorkflowBuildError, _one


STAGES = ("素材理解", "中文意图整理", "H3提示词生成")


def build(source, *, prompt_only=False):
    editor = Editor(source)
    form = _one(editor.workflow["nodes"], "ZVH3InterviewFormV2")
    stages = [node for node in editor.nodes.values() if node["type"] == "ZVH3ReverseStage"]
    by_stage = {node.get("widgets_values", [None])[0]: node for node in stages}
    if len(stages) != 3 or set(by_stage) != set(STAGES):
        raise WorkflowBuildError("工作流必须包含素材理解、中文意图整理、H3提示词生成三个独立阶段")
    llms = []
    for label in STAGES:
        stage = by_stage[label]
        for name in ("user_prompt", "material_context_json"):
            edge = editor.incoming(stage["id"], name)
            if edge is None or edge[1] != form["id"] or form["outputs"][edge[2]]["name"] != name:
                raise WorkflowBuildError(f"{label} 未连接采访表的 {name}")
        task = editor.outgoing(stage["id"], "user_task")
        if len(task) != 1:
            raise WorkflowBuildError(f"{label} 必须连接一个反推模型节点")
        llms.append(editor.nodes[task[0][3]])
    previews = []
    for origin, port in ((form, "user_prompt"), *[(llm, llm["outputs"][0]["name"]) for llm in llms]):
        targets = [edge[3] for edge in editor.outgoing(origin["id"], port)
                   if editor.nodes[edge[3]]["type"] == "PreviewAny"]
        if len(targets) != 1:
            raise WorkflowBuildError("表格原稿及三个模型结果必须各有一个文字预览")
        previews.extend(targets)
    metadata = {"version": 2, "form_id": form["id"],
                "reverse_stage_ids": [by_stage[label]["id"] for label in STAGES],
                "llm_ids": [node["id"] for node in llms], "preview_ids": previews,
                "prompt_only": prompt_only}
    if prompt_only:
        needed = set(previews)
        while True:
            expanded = needed | {edge[1] for edge in editor.links if edge[3] in needed}
            if expanded == needed:
                break
            needed = expanded
        if any(node["type"] in ("SamplerCustomAdvanced", "MiniMaxH3AVDecodeT8", "VHS_VideoCombine", "SaveVideo")
               and node["id"] in needed for node in editor.nodes.values()):
            raise WorkflowBuildError("只反推工作流仍依赖采样、解码或保存节点")
        for node in editor.nodes.values():
            if node["id"] not in needed:
                node["mode"] = 2
    editor.workflow.setdefault("extra", {})["zv_interview_v2"] = metadata
    return editor.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-only-output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    outputs = [args.output.resolve(), args.prompt_only_output.resolve()]
    if source in outputs or outputs[0] == outputs[1] or any(path.exists() for path in outputs):
        parser.error("仅创建新文件；源文件、两个输出必须不同，输出不得已存在")
    workflow = json.loads(source.read_text(encoding="utf-8-sig"))
    results = [build(workflow), build(workflow, prompt_only=True)]
    for path, result in zip(outputs, results):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"{path}: {len(result['nodes'])} nodes / {len(result['links'])} links")


if __name__ == "__main__":
    main()
