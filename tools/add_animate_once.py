"""Add one-pass sequential rendering without rebuilding the user's Animate graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_evidence.contract import empty_project
from tools.build_long_video_workflow import Editor, WorkflowBuildError, make_node


# All known output roots; Purge keeps its side effect and is closed into the loop.
OUTPUT_TYPES = frozenset({
    "VHS_VideoCombine", "SaveImage", "PreviewImage", "ImageAndMaskPreview",
    "easy showAnything", "PreviewAny", "PurgeVRAM_UTK",
})
MATERIAL_LOADER_TYPES = frozenset({"LoadImage", "VHS_LoadVideo", "VHS_LoadVideoPath"})
REPLACEMENTS = (
    (197, "IMAGE", 241, "source_frames", "IMAGE"),
    (203, "INT", 248, "frame_count", "INT"),
    (202, "AUDIO", 249, "source_audio", "AUDIO"),
    (204, "VHS_VIDEOINFO", 250, "video_info", "VHS_VIDEOINFO"),
    (208, "IMAGE", 268, "reference_image", "IMAGE"),
    (789, "transition_video", 1227, "transition_video", "IMAGE"),
)
MASK_REPLACEMENTS = (
    (523, "batch_index", 686, "mask_frame", "annotation_frame_idx", "INT"),
    (367, "annotation_frame_idx", 558, "mask_frame", "annotation_frame_idx", "INT"),
    (835, "text", 1117, "mask_frame", "mask_prompt", "STRING"),
    (367, "input_mask", 665, "mask_seed", "validated_seed", "MASK"),
    (19, "MASK", 449, "mask_gate", "mask", "MASK"),
    (40, "IMAGE", 446, "mask_gate", "bg_images", "IMAGE"),
    (834, "anything", 1114, "mask_gate", "bg_images", "IMAGE"),
)


def _children(editor):
    children = {identifier: set() for identifier in editor.nodes}
    for _identifier, source, _output, target, _input, _type in editor.links:
        children[source].add(target)
    setters = {
        node["widgets_values"][0]: node["id"]
        for node in editor.nodes.values()
        if node["type"] == "SetNode" and node.get("widgets_values")
    }
    for node in editor.nodes.values():
        if node["type"] == "GetNode" and node.get("widgets_values"):
            setter = setters.get(node["widgets_values"][0])
            if setter is not None:
                children[setter].add(node["id"])
    return children


def _descendants(children, start):
    found, pending = set(), [start]
    while pending:
        identifier = pending.pop()
        if identifier in found:
            continue
        found.add(identifier)
        pending.extend(children[identifier])
    return found


def _close_video_outputs(editor, start_id, end_id):
    end = editor.nodes[end_id]
    incoming = {link[4]: link for link in editor.links if link[3] == end_id}
    inputs, termination_count = [], 0
    for slot, port in enumerate(end["inputs"]):
        link = incoming.get(slot)
        if port["name"].startswith("termination"):
            if link is None:
                continue
            port = {**port, "name": f"terminations.termination{termination_count}"}
            termination_count += 1
        if link is not None:
            link[4] = len(inputs)
        inputs.append(port)
    end["inputs"] = inputs

    children = _children(editor)
    children[end_id] = set()
    loop_nodes = _descendants(children, start_id)
    connected = {link[1] for link in incoming.values()}
    for identifier in sorted(loop_nodes):
        node = editor.nodes[identifier]
        if node["type"] != "VHS_VideoCombine" or identifier in connected:
            continue
        if termination_count >= 50:
            raise WorkflowBuildError("循环输出支路超过 EndLoop 原生终止支路数量上限")
        port = f"terminations.termination{termination_count}"
        end["inputs"].append({"name": port, "type": "*", "link": None, "shape": 7})
        editor.wire(identifier, "Filenames", end_id, port, "*")
        termination_count += 1


def repair_loop_outputs(workflow):
    editor = Editor(workflow)
    ids = workflow.get("extra", {}).get("zv_animate_once", {}).get("new_node_ids", {})
    for key, kind in (("start", "StartLoop"), ("end", "EndLoop")):
        if editor.nodes.get(ids.get(key), {}).get("type") != kind:
            raise WorkflowBuildError("工作流缺少一次成片的原生循环接入点")
    _close_video_outputs(editor, ids["start"], ids["end"])
    editor.links.sort(key=lambda link: link[0])
    return editor.finish()


def _enable_mask_previews(editor, ids):
    seed = editor.nodes[ids["mask_seed"]]
    if not any(port["name"] == "reference_image" for port in seed["inputs"]):
        seed["inputs"].append({"name": "reference_image", "type": "IMAGE", "link": None, "shape": 7})
    seed["title"] = "参考帧遮罩：原图 / 叠加 / 黑白种子 → SeC"
    seed["size"] = [max(seed["size"][0], 460), max(seed["size"][1], 340)]
    link = editor.incoming(seed["id"], "reference_image")
    if link is None or link[1] != 523:
        editor.wire(523, "IMAGE", seed["id"], "reference_image", "IMAGE", replace=True)
    if 284 in editor.nodes:
        preview = editor.nodes[284]
        if preview["type"] != "VHS_VideoCombine":
            raise WorkflowBuildError("#284 不再是原遮罩背景视频预览，请检查接线")
        preview["mode"] = 0
        link = editor.incoming(284, "images")
        if link is None or link[1] != ids["mask_gate"] or link[2] != 1:
            editor.wire(ids["mask_gate"], "bg_images", 284, "images", "IMAGE", replace=True)
    # The old preview is an independent output root: enabling it bypasses the mask gate.
    if editor.nodes.get(515, {}).get("type") == "ImageAndMaskPreview":
        editor.nodes[515]["mode"] = 2


def restore_mask_previews(workflow):
    editor = Editor(repair_loop_outputs(workflow))
    ids = editor.workflow["extra"]["zv_animate_once"]["new_node_ids"]
    for key, kind in (("mask_seed", "ZVAnimateMaskSeed"), ("mask_gate", "ZVAnimateMaskGate")):
        if editor.nodes.get(ids.get(key), {}).get("type") != kind:
            raise WorkflowBuildError("工作流缺少一次成片的遮罩接入点")
    _enable_mask_previews(editor, ids)
    _close_video_outputs(editor, ids["start"], ids["end"])
    note = editor.nodes.get(ids.get("note"))
    text = "遮罩预览已恢复：种子检查节点显示原参考帧、绿色覆盖和黑白种子；#284 显示实际送入 Plus 的遮罩背景视频，每段更新。关闭遮罩总开关时两处均不执行遮罩计算。旧 #515 保持停用，避免绕过总开关。"
    if note is not None and text not in note["widgets_values"][0]:
        note["widgets_values"][0] += "\n\n" + text
    if note is not None:
        seed = editor.nodes[ids["mask_seed"]]
        note["pos"][1] = max(note["pos"][1], seed["pos"][1] + seed["size"][1] + 50)
        for group in editor.workflow.get("groups", []):
            if group.get("title") == "附加：Animate 原流一次成片（下方原工作流保留）":
                bounds = group["bounding"]
                bounds[3] = max(bounds[3], note["pos"][1] + note["size"][1] + 40 - bounds[1])
    return editor.finish()


def _check_source(editor):
    expected = {
        197: ("SetNode", "SP图像"), 203: ("SetNode", "SP帧计数"),
        202: ("SetNode", "音频"), 204: ("SetNode", "视频信息"),
        208: ("SetNode", "TU图像"), 936: ("GetNode", "帧率预设"),
        759: ("GetNode", "SP缩放宽"), 758: ("GetNode", "SP缩放高"),
        789: ("WanAnimatePlus AnimateEmbeds", None),
        700: ("ImageFromBatch", None),
        523: ("ImageFromBatch", None), 367: ("SeCVideoSegmentation", None),
        835: ("GoogleTranslateTextNode", None), 375: ("GetNode", "SP运行"),
        712: ("ImpactConditionalBranch", None), 504: ("Masks Add", None),
        370: ("BlockifyMask", None), 371: ("DrawMaskOnImage", None),
        19: ("SetNode", "抠出"), 40: ("SetNode", "背景绘制抠出"),
        834: ("PurgeVRAM_UTK", None),
    }
    for identifier, (kind, alias) in expected.items():
        node = editor.nodes.get(identifier, {})
        if node.get("type") != kind or (alias and node.get("widgets_values") != [alias]):
            raise WorkflowBuildError(f"原流接入点 #{identifier} 不再是 {kind} {alias or ''}")
    for target, name, old_id, _output, _type in REPLACEMENTS:
        link = editor.incoming(target, name)
        if link is None or link[0] != old_id:
            raise WorkflowBuildError(f"原流 #{target}.{name} 的链接 {old_id} 已改变")
    for target, name, old_id, *_ in MASK_REPLACEMENTS:
        link = editor.incoming(target, name)
        if link is None or link[0] != old_id:
            raise WorkflowBuildError(f"原遮罩接入点 #{target}.{name} 的链接 {old_id} 已改变")
    if editor.workflow.get("extra", {}).get("zv_animate_once"):
        raise WorkflowBuildError("源文件已经附加一次成片方案，请从原工作流重新制作")


def _source_fps(editor):
    """Only recognize this original graph's explicit, unchanged FPS chain."""
    constant = editor.nodes.get(430, {})
    math_node = editor.nodes.get(432, {})
    setter = editor.nodes.get(934, {})
    fps_values = constant.get("widgets_values", [])
    expressions = math_node.get("widgets_values", [])
    aliases = [node["id"] for node in editor.nodes.values()
               if node["type"] == "SetNode" and node.get("widgets_values") == ["帧率预设"]]
    valid = (constant.get("type") == "INTConstant" and len(fps_values) == 1
             and type(fps_values[0]) is int and fps_values[0] > 0
             and math_node.get("type") == "SimpleMath+" and len(expressions) == 1
             and isinstance(expressions[0], str) and "".join(expressions[0].split()) == "a*1"
             and setter.get("type") == "SetNode" and aliases == [934]
             and all(node.get("mode", 0) == 0 for node in (constant, math_node, setter, editor.nodes[936]))
             and not any(port.get("link") is not None for port in constant.get("inputs", []))
             and not any(port.get("link") is not None for port in math_node.get("inputs", []) if port["name"] == "value"))
    if valid:
        to_math, to_set = editor.incoming(432, "a"), editor.incoming(934, "INT")
        valid = (to_math is not None and to_math[1:3] == [430, 0]
                 and to_set is not None and to_set[1:3] == [432, 0])
    if not valid:
        raise WorkflowBuildError("无法静态对齐素材台帧率：需原 #430 整数 → #432 a*1 → #934/936 帧率预设；不猜测其他公式")
    return fps_values[0]


def build(workflow, *, output_types=OUTPUT_TYPES):
    editor = Editor(workflow)
    _check_source(editor)
    original_ids = set(editor.nodes)
    original_links = [list(editor.incoming(target, name)) for target, name, *_ in REPLACEMENTS]
    mask_links = [list(editor.incoming(target, name)) for target, name, *_ in MASK_REPLACEMENTS]
    names = ("desk", "plan", "start", "entry", "recorder", "end", "finish", "save", "report", "note", "mask_frame", "mask_seed", "mask_gate")
    ids = {name: editor.allocate() for name in names}
    x = min(float(node["pos"][0]) for node in editor.nodes.values())
    y = min(float(node["pos"][1]) for node in editor.nodes.values()) - 1600
    project = empty_project()
    project["project_clock"]["fps"] = project["processing_window"]["fps"] = _source_fps(editor)
    project_json = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    settings_json = json.dumps({"schema_version": 1, "seam_mode": "hard_cut", "mask_enabled": False, "mask_tasks": {}}, separators=(",", ":"))
    nodes = [
        make_node(ids["desk"], "ZVUniversalMediaEvidenceDesk", "① 素材台：准备已剪好的视频与逐段图片", [x, y],
                  [("project_data", "STRING"), ("width", "INT"), ("height", "INT")],
                  [("media_project", "ZV_MEDIA_PROJECT"), ("project_json", "STRING"), ("原素材来源", "ZV_ORIGINAL_SOURCES")],
                  values=[project_json], named_values={"project_data": project_json},
                  size=[1160, 1120], widget_inputs={"project_data"}),
        make_node(ids["plan"], "ZVAnimateSegmentDesk", "② Animate 配对导轨：硬切 / 21 帧承接", [x + 1250, y],
                  [("media_project", "ZV_MEDIA_PROJECT"), ("segment_data", "STRING"), ("fps", "INT,FLOAT")],
                  [("animate_plan", "ZV_ANIMATE_PLAN"), ("segment_count", "INT"), ("fps", "FLOAT"), ("report", "STRING")],
                  values=[settings_json], named_values={"segment_data": settings_json},
                  size=[1100, 640], widget_inputs={"segment_data"}),
        make_node(ids["start"], "StartLoop", "按导轨顺序执行 · 不缓存各段", [x + 1250, y + 640],
                  [("mode", "COMFY_DYNAMICCOMBO_V3"), ("mode.num_iterations", "INT"), ("cache_iterations", "BOOLEAN"),
                   ("parent_iteration", "INT"), ("initial_iteration_value", "ZV_ANIMATE_RUN")],
                  [("iteration_index", "INT"), ("is_first", "BOOLEAN"), ("is_last", "BOOLEAN"),
                   ("list_item", "*"), ("current_iteration_value", "ZV_ANIMATE_RUN")],
                  values=["simple", 1, False], named_values={"mode": "simple", "mode.num_iterations": 1, "cache_iterations": False},
                  size=[370, 250], widget_inputs={"mode", "cache_iterations"}),
        make_node(ids["entry"], "ZVAnimateExecutionEntry", "逐段入口 → 沿用下方原流", [x + 1680, y + 640],
                  [("animate_plan", "ZV_ANIMATE_PLAN"), ("iteration_index", "INT"), ("previous_result", "ZV_ANIMATE_RUN"),
                   ("width", "INT"), ("height", "INT")],
                  [("segment_context", "ZV_ANIMATE_CONTEXT"), ("source_frames", "IMAGE"), ("frame_count", "INT"),
                   ("source_audio", "AUDIO"), ("video_info", "VHS_VIDEOINFO"), ("reference_image", "IMAGE"),
                   ("transition_video", "IMAGE"), ("fps", "FLOAT"), ("has_transition", "BOOLEAN"),
                   ("segment_id", "STRING"), ("report", "STRING")], size=[420, 390]),
        make_node(ids["recorder"], "ZVAnimateSegmentRecorder", "收集原流 #700 的已裁回成品", [x + 2180, y + 640],
                  [("segment_context", "ZV_ANIMATE_CONTEXT"), ("frames", "IMAGE"),
                   ("source_audio", "AUDIO"), ("previous_result", "ZV_ANIMATE_RUN")],
                  [("run_result", "ZV_ANIMATE_RUN"), ("report", "STRING")], size=[410, 260]),
        make_node(ids["end"], "EndLoop", "完成一段再执行下一段 · 不累积图像", [x + 2660, y + 640],
                  [("output_value", "ZV_ANIMATE_RUN"), ("next_iteration_value", "ZV_ANIMATE_RUN"), ("accumulate", "BOOLEAN")],
                  [("outputs", "ZV_ANIMATE_RUN")], values=[False], named_values={"accumulate": False},
                  size=[380, 220], widget_inputs={"accumulate"}),
        make_node(ids["finish"], "ZVAnimateExecutionEnd", "③ 按实际成品顺序合并", [x + 3110, y + 640],
                  [("animate_plan", "ZV_ANIMATE_PLAN"), ("run_result", "ZV_ANIMATE_RUN")],
                  [("video", "VIDEO"), ("frame_count", "INT"), ("report", "STRING")], size=[380, 240]),
        make_node(ids["save"], "SaveVideo", "④ 保存一次成片结果", [x + 3560, y + 640],
                  [("video", "VIDEO"), ("filename_prefix", "STRING"), ("format", "COMFY_DYNAMICCOMBO_V3"),
                   ("format.codec", "COMFY_DYNAMICCOMBO_V3"), ("codec", "COMFY_DYNAMICCOMBO_V3")],
                  [("video", "VIDEO")], values=["Animate/once", "auto", "auto", "auto"],
                  named_values={"filename_prefix": "Animate/once", "format": "auto", "format.codec": "auto", "codec": "auto"},
                  size=[460, 300], widget_inputs={"filename_prefix", "format", "format.codec", "codec"}),
        make_node(ids["report"], "PreviewAny", "实际帧数与原声音频报告", [x + 2450, y],
                  [("source", "*")], [("STRING", "STRING")], size=[1570, 510]),
        make_node(ids["note"], "Note", "使用与原流保留说明", [x, y + 1450], [], [],
                  values=[""], size=[4150, 250]),
        make_node(ids["mask_frame"], "ZVAnimateMaskFrame", "逐段遮罩：源帧 → 原流前补帧索引", [x + 1250, y + 1020],
                  [("segment_context", "ZV_ANIMATE_CONTEXT"), ("frames", "IMAGE"), ("front_padding", "INT")],
                  [("annotation_frame_idx", "INT"), ("mask_prompt", "STRING")], size=[380, 160]),
        make_node(ids["mask_seed"], "ZVAnimateMaskSeed", "SAM/手绘种子检查 → SeC", [x + 1680, y + 1060],
                  [("segment_context", "ZV_ANIMATE_CONTEXT"), ("mask", "MASK")],
                  [("validated_seed", "MASK")], size=[380, 120]),
        make_node(ids["mask_gate"], "ZVAnimateMaskGate", "全局遮罩开关：关闭时跳过 SAM/SeC", [x + 2180, y + 1000],
                  [("segment_context", "ZV_ANIMATE_CONTEXT"), ("mask", "MASK"), ("bg_images", "IMAGE")],
                  [("mask", "MASK"), ("bg_images", "IMAGE")], size=[410, 180]),
    ]
    for node in nodes:
        editor.add(node)
    wire = editor.wire
    wire(ids["desk"], "media_project", ids["plan"], "media_project", "ZV_MEDIA_PROJECT")
    wire(936, "INT", ids["plan"], "fps", "INT")
    wire(759, "INT", ids["entry"], "width", "INT")
    wire(758, "INT", ids["entry"], "height", "INT")
    wire(ids["plan"], "animate_plan", ids["entry"], "animate_plan", "ZV_ANIMATE_PLAN")
    wire(ids["plan"], "animate_plan", ids["finish"], "animate_plan", "ZV_ANIMATE_PLAN")
    wire(ids["plan"], "segment_count", ids["start"], "mode.num_iterations", "INT")
    wire(ids["start"], "iteration_index", ids["entry"], "iteration_index", "INT")
    wire(ids["start"], "current_iteration_value", ids["entry"], "previous_result", "ZV_ANIMATE_RUN")
    wire(ids["start"], "current_iteration_value", ids["recorder"], "previous_result", "ZV_ANIMATE_RUN")
    wire(ids["entry"], "segment_context", ids["recorder"], "segment_context", "ZV_ANIMATE_CONTEXT")
    wire(ids["entry"], "source_audio", ids["recorder"], "source_audio", "AUDIO")
    wire(700, "IMAGE", ids["recorder"], "frames", "IMAGE")
    wire(ids["recorder"], "run_result", ids["end"], "output_value", "ZV_ANIMATE_RUN")
    wire(ids["recorder"], "run_result", ids["end"], "next_iteration_value", "ZV_ANIMATE_RUN")
    wire(ids["end"], "outputs", ids["finish"], "run_result", "ZV_ANIMATE_RUN")
    wire(ids["finish"], "video", ids["save"], "video", "VIDEO")
    wire(ids["finish"], "report", ids["report"], "source", "STRING")
    for target, name, _old_id, source_name, type_ in REPLACEMENTS:
        wire(ids["entry"], source_name, target, name, type_, replace=True)
    for key in ("mask_frame", "mask_seed", "mask_gate"):
        wire(ids["entry"], "segment_context", ids[key], "segment_context", "ZV_ANIMATE_CONTEXT")
    wire(375, "IMAGE", ids["mask_frame"], "frames", "IMAGE")
    wire(712, "*", ids["mask_frame"], "front_padding", "INT")
    wire(504, "MASKS", ids["mask_seed"], "mask", "MASK")
    wire(370, "mask", ids["mask_gate"], "mask", "MASK")
    wire(371, "images", ids["mask_gate"], "bg_images", "IMAGE")
    for target, name, _old_id, source_key, source_name, type_ in MASK_REPLACEMENTS:
        wire(ids[source_key], source_name, target, name, type_, replace=True)

    children = _children(editor)
    loop_nodes = _descendants(children, ids["entry"])
    old_material_nodes = set().union(*(
        _descendants(children, identifier) for identifier in original_ids
        if editor.nodes[identifier]["type"] in MATERIAL_LOADER_TYPES
    ))
    purge_ids = [identifier for identifier in sorted(original_ids & loop_nodes)
                 if editor.nodes[identifier]["type"] == "PurgeVRAM_UTK"
                 and editor.nodes[identifier].get("mode", 0) == 0]
    if len(purge_ids) > 50:
        raise WorkflowBuildError("循环内清理显存节点超过 EndLoop 原生终止支路数量上限")
    purge_terminations = {}
    for index, identifier in enumerate(purge_ids):
        port = f"terminations.termination{index}"
        editor.nodes[ids["end"]]["inputs"].append({"name": port, "type": "*", "link": None, "shape": 7})
        wire(identifier, "anything", ids["end"], port, "*")
        purge_terminations[port] = identifier
    original_modes = {}
    for identifier in sorted(original_ids & (loop_nodes | old_material_nodes)):
        node = editor.nodes[identifier]
        if (node.get("mode", 0) != 0 or node["type"] not in output_types
                or node["type"] == "PurgeVRAM_UTK"):
            continue
        if 700 in _descendants(children, identifier):
            raise WorkflowBuildError(f"输出节点 #{identifier} 还参与生成，不能作为预览静默关闭")
        original_modes[str(identifier)] = node.get("mode", 0)
        node["mode"] = 2
    _enable_mask_previews(editor, ids)
    original_modes.pop("284", None)
    _close_video_outputs(editor, ids["start"], ids["end"])
    muted_ids = "、".join(original_modes) or "无"
    editor.nodes[ids["note"]]["widgets_values"] = [
        "原工作流的节点、位置、参数、4n+1 前补与裁回、姿态/人脸/背景/遮罩处理和采样链全部保留。"
        "新增入口接替原加载素材与逐段遮罩参考帧/目标词；每段在原 #700 裁回之后收集。\n\n"
        "素材台先剪好视频、排列图片；导轨一段视频对应一张图片。选择硬切或固定 21 帧承接，然后运行。"
        "帧率与尺寸继续取原工作流，不在分段台另设。\n\n"
        "分段台的遮罩管道为整条视频统一开关。关闭：整条动作迁移，遮罩及带遮罩背景输出为空，不执行 SAM/SeC。"
        "开启：各段填写原视频源帧号和遮罩目标词，由原 SAM/SeC 管道处理。参考帧以素材台源帧读数为准，"
        "内部先转为当前段索引，再加原 #712 前补帧；Plus 的 21 帧承接发生在后面，不计入此索引。"
        "#304/#461 的旧全局常量不再控制一次成片。原手绘旁路保留原状态；开启手绘后仍是共享输入，需自行确认各段适用。\n\n"
        "种子检查节点显示原参考帧、绿色覆盖和黑白种子；#284 显示实际送入 Plus 的遮罩背景视频，每段更新。"
        "两处预览随遮罩总开关按需执行；旧 #515 保持停用，避免绕过总开关。\n\n"
        f"一次成片副本暂时关闭旧单段保存/预览（含独立旧素材预览，mode=2）：{muted_ids}。"
        "这些节点仍保留；原模式、素材接线和遮罩接线记录在 extra.zv_animate_once，原文件未改。\n\n"
        "原显存清理节点与循环内视频输出旁接 EndLoop 原生终止支路。重新开启旧视频预览时，每段预览完成后再进入下一段。\n\n"
        "硬切不传上一段画面；21 帧承接传上一段已裁回成品的尾帧，由原 Plus 处理。"
        "当前 Plus 承接路径可能使每段少 1 帧；不改 Plus，不另行补帧，按实际成品合并并报告帧数差异。"
        "这不是云端 GPU 质量验收。"
    ]
    result = editor.finish()
    result.setdefault("groups", []).append({
        "id": max((group.get("id", 0) for group in result["groups"]), default=0) + 1,
        "title": "附加：Animate 原流一次成片（下方原工作流保留）",
        "bounding": [x - 30, y - 70, 4250, 1820], "color": "#287b82", "font_size": 32, "flags": {},
    })
    result.setdefault("extra", {})["zv_animate_once"] = {
        "version": 2, "new_node_ids": ids, "original_links": original_links, "original_mask_links": mask_links,
        "original_modes": original_modes, "output_types": sorted(output_types),
        "purge_terminations": purge_terminations,
        "original_view": result["extra"].get("ds"),
        "frame_contract": "Original padding/crop and Plus unchanged; report actual output lengths, never synthesize missing frames.",
    }
    # Only the new copy opens on the added desks; the original graph never moves.
    scale = 0.55
    result["extra"]["ds"] = {"scale": scale, "offset": [-x + 70 / scale, -y + 90 / scale]}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--repair-loop", action="store_true", help="修复已有一次成片工作流的视频输出循环边界，保留素材及节点启停状态")
    action.add_argument("--restore-mask-previews", action="store_true", help="恢复已有一次成片工作流的种子和遮罩背景预览，保留遮罩总开关和循环边界")
    args = parser.parse_args(argv)
    try:
        if args.source.resolve() == args.output.resolve() or args.output.exists():
            raise WorkflowBuildError("必须另存为不存在的新文件；不覆盖原工作流")
        source = json.loads(args.source.read_text(encoding="utf-8-sig"))
        if args.restore_mask_previews:
            result = restore_mask_previews(source)
        else:
            result = repair_loop_outputs(source) if args.repair_loop else build(source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(args.output)


if __name__ == "__main__":
    main()
