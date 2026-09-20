"""Build a long-video example from the current H3 interview workflow."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


class WorkflowBuildError(ValueError):
    pass


def _port_index(node, side, name):
    rows = node.get(side)
    if not isinstance(rows, list):
        raise WorkflowBuildError(f"{node.get('type')} 缺少 {side} 端口数组")
    found = [index for index, row in enumerate(rows) if row.get("name") == name]
    if len(found) != 1:
        raise WorkflowBuildError(f"{node.get('type')} 的 {name} 端口不存在或不唯一")
    return found[0]


def _one(nodes, kind):
    found = [node for node in nodes if node.get("type") == kind]
    if len(found) != 1:
        raise WorkflowBuildError(f"源工作流必须恰好包含 1 个 {kind}，实际 {len(found)} 个")
    return found[0]


def _input(name, type_, widget=False):
    row = {"name": name, "type": type_, "link": None}
    if widget:
        row["widget"] = {"name": name}
    return row


def _output(name, type_):
    return {"name": name, "type": type_, "links": []}


def make_node(identifier, kind, title, position, inputs, outputs, *, values=None,
              named_values=None, size=None, widget_inputs=()):
    node = {
        "id": identifier, "type": kind, "title": title, "pos": position,
        "size": size or [360, 180], "flags": {}, "order": 0, "mode": 0,
        "inputs": [_input(name, type_, name in widget_inputs) for name, type_ in inputs],
        "outputs": [_output(name, type_) for name, type_ in outputs],
        "properties": {"Node name for S&R": kind},
        "widgets_values": [] if values is None else values,
    }
    if named_values is not None:
        node["widgets_values_named"] = named_values
    return node


class Editor:
    def __init__(self, workflow):
        self.workflow = copy.deepcopy(workflow)
        if not isinstance(self.workflow, dict) or not isinstance(self.workflow.get("nodes"), list) or not isinstance(self.workflow.get("links"), list):
            raise WorkflowBuildError("源文件不是 ComfyUI 工作流")
        self.nodes = {node.get("id"): node for node in self.workflow["nodes"]}
        if None in self.nodes or len(self.nodes) != len(self.workflow["nodes"]):
            raise WorkflowBuildError("源工作流节点 ID 缺失或重复")
        self.links = [list(link) for link in self.workflow["links"]]
        if any(len(link) != 6 for link in self.links) or len({link[0] for link in self.links}) != len(self.links):
            raise WorkflowBuildError("源工作流链接无效或 ID 重复")
        self.next_node = max(self.nodes, default=0) + 1
        self.next_link = max((link[0] for link in self.links), default=0) + 1
        self.validate()

    def validate(self):
        links = {link[0]: link for link in self.links}
        for link_id, source, output, target, input_slot, _type in self.links:
            if source not in self.nodes or target not in self.nodes:
                raise WorkflowBuildError(f"链接 {link_id} 的端点不存在")
            source_node, target_node = self.nodes[source], self.nodes[target]
            if not 0 <= output < len(source_node.get("outputs", [])) or not 0 <= input_slot < len(target_node.get("inputs", [])):
                raise WorkflowBuildError(f"链接 {link_id} 的端口越界")
            if target_node["inputs"][input_slot].get("link") != link_id:
                raise WorkflowBuildError(f"链接 {link_id} 的输入端记录不一致")
            if link_id not in (source_node["outputs"][output].get("links") or []):
                raise WorkflowBuildError(f"链接 {link_id} 的输出端记录不一致")
        for node in self.nodes.values():
            for row in node.get("inputs", []):
                if row.get("link") is not None and row["link"] not in links:
                    raise WorkflowBuildError(f"{node.get('type')} 输入引用不存在的链接")

    def allocate(self):
        value = self.next_node
        self.next_node += 1
        return value

    def add(self, node):
        if node["id"] in self.nodes:
            raise WorkflowBuildError(f"新节点 ID {node['id']} 冲突")
        self.workflow["nodes"].append(node)
        self.nodes[node["id"]] = node

    def incoming(self, node_id, input_name):
        slot = _port_index(self.nodes[node_id], "inputs", input_name)
        found = [link for link in self.links if link[3] == node_id and link[4] == slot]
        if len(found) > 1:
            raise WorkflowBuildError(f"{self.nodes[node_id]['type']}.{input_name} 有多个输入")
        return found[0] if found else None

    def outgoing(self, node_id, output_name):
        slot = _port_index(self.nodes[node_id], "outputs", output_name)
        return [link for link in self.links if link[1] == node_id and link[2] == slot]

    def disconnect(self, link_id):
        self.links = [link for link in self.links if link[0] != link_id]

    def wire(self, source, output_name, target, input_name, type_, replace=False):
        source_slot = _port_index(self.nodes[source], "outputs", output_name)
        target_slot = _port_index(self.nodes[target], "inputs", input_name)
        old = [link for link in self.links if link[3] == target and link[4] == target_slot]
        if old and not replace:
            raise WorkflowBuildError(f"{self.nodes[target]['type']}.{input_name} 已有连接")
        for link in old:
            self.disconnect(link[0])
        self.links.append([self.next_link, source, source_slot, target, target_slot, type_])
        self.next_link += 1

    def remove_nodes(self, identifiers):
        identifiers = set(identifiers)
        self.workflow["nodes"] = [node for node in self.workflow["nodes"] if node["id"] not in identifiers]
        self.nodes = {node["id"]: node for node in self.workflow["nodes"]}
        self.links = [link for link in self.links if link[1] not in identifiers and link[3] not in identifiers]

    def finish(self):
        for node in self.nodes.values():
            for row in node.get("inputs", []):
                row["link"] = None
            for row in node.get("outputs", []):
                row["links"] = []
        for link_id, source, output, target, input_slot, _type in self.links:
            self.nodes[source]["outputs"][output]["links"].append(link_id)
            self.nodes[target]["inputs"][input_slot]["link"] = link_id
        for order, node in enumerate(self.workflow["nodes"]):
            node["order"] = order
        self.workflow["links"] = sorted(self.links, key=lambda row: row[0])
        self.workflow["last_node_id"] = max(self.nodes, default=0)
        self.workflow["last_link_id"] = max((link[0] for link in self.links), default=0)
        self.validate()
        return self.workflow


def _sanitize_desk(desk):
    values = desk.get("widgets_values")
    if not isinstance(values, list) or not values or not isinstance(values[0], str):
        raise WorkflowBuildError("素材台缺少 project_data JSON")
    try:
        project = json.loads(values[0])
    except (ValueError, TypeError) as error:
        raise WorkflowBuildError("素材台 project_data 不是有效 JSON") from error
    if not isinstance(project, dict) or project.get("schema_version") != 2:
        raise WorkflowBuildError("素材台必须使用 ZV_MEDIA_PROJECT v2")
    for key in ("assets", "picture_track", "video_track", "audio_track"):
        project[key] = []
    project.pop("outlet_slots", None)
    for key in ("validation", "preset_compatibility", "label_map"):
        project.pop(key, None)
    values[0] = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    if isinstance(desk.get("widgets_values_named"), dict):
        desk["widgets_values_named"]["project_data"] = values[0]


def _set_named_widget(node, name, value):
    named = node.get("widgets_values_named")
    values = node.get("widgets_values")
    if not isinstance(named, dict) or name not in named or not isinstance(values, list):
        raise WorkflowBuildError(f"{node.get('type')} 缺少可写控件 {name}")
    keys = list(named)
    index = keys.index(name)
    if index >= len(values):
        raise WorkflowBuildError(f"{node.get('type')} 的控件数组与具名控件不一致")
    named[name] = value
    values[index] = value


def _rewrite_notes(nodes, *, mask_mode=False):
    notes = sorted(
        (node for node in nodes if node.get("type") == "Note"),
        key=lambda node: (float(node.get("pos", [0, 0])[0]), node["id"]),
    )
    if len(notes) != 3:
        raise WorkflowBuildError(f"源工作流说明 Note 应为 3 个，实际 {len(notes)} 个")
    content = [
        (
            "① 长视频使用步骤｜按顺序操作",
            "1. 在素材台预载图片、视频、音频；只有拖入三条轨道的素材才参加任务。\n\n"
            "2. 到分段台点击获取三轨。自动源分段会按素材时长计算段数；也可切换手工源分段逐段调整。\n\n"
            "3. 检查每段范围、重叠与稳定 segment_id。H3 每次调用仍遵守单次参考和生成窗口限制；整条长视频不受单次 15 秒上限约束。\n\n"
            "4. 到分段采访表填写全局要求和逐段要求，点击检测并对齐全部分段。修改素材、范围、用途或文字后必须重新对齐。\n\n"
            "5. 确认执行计划 ready 后运行。有限循环每次只生成一段，上一段尾部 guide 从磁盘送入下一段。\n\n"
            "6. 执行终点按全局帧钟裁掉重叠和模型补帧，再输出完整 native VIDEO。",
        ),
        (
            "② 运行前检查｜分段与循环",
            "• source_auto 的“段数”由素材时长、单段帧数和重叠自动计算，界面中的生成段数只用于 generation_count。\n\n"
            "• H3 Guide 重叠必须是 1 帧或 5+17k 帧；推荐保留“H3 衔接帧对齐”。\n\n"
            "• Start Loop 已固定 cache_iterations=false，End Loop 已固定 accumulate=false，避免缓存旧段或累积全分辨率张量。\n\n"
            "• Recorder 的 final_audio 是 drive/reuse 内容优先口；独立参考音频不走此口。没有复用音频时回退 generated_audio。两支在选定后统一重采样为 44100 Hz/2 ch，再按全局帧时钟裁切；缺失音频补同钟静音，超过 2 声道会明确拒绝。\n\n"
            "• 若末段真实参考过短，自动分段会向前回摆边界；仍不足 48 帧时会明确阻断。",
        ),
        (
            "③ 验证边界｜先看再跑",
            "普通分段链已通过隔离 H3 GPU 双段实跑：124+76=200 帧，39 帧 Guide，44.1 kHz 双声道音频连续。\n\n"
            + (
                "本 C1 支路已完成隔离 GPU 全黑、全白和半幅双段验收。冻结源 IMAGE、实际 MASK 与原声按当前分段接入 H3 nested AV latent；LOW→HIGH 边界恢复同一 1x 源 latent 与目标网格 MASK，解码后按像素回贴黑区源画面，Recorder 只接回贴后的画面与逻辑 final_audio。\n\n"
                if mask_mode else
                "下方蒙版支路只演示冻结源时钟、标准 MASK 绑定与逐段取片协议；它没有接入当前普通生成路径。需要实际 H3 蒙版 latent 时请使用独立 C1 蒙版工作流。\n\n"
            )
            + "以上是历史机械链验收；当前采访原稿 → 素材理解 → 中文意图 → H3 提示词链仍需真实模型复测。ImageToMask 只是全帧同几何接口示例，不能代替 SAM3、SeC 或手绘遮罩。",
        ),
    ]
    for node, (title, text) in zip(notes, content):
        node["title"] = title
        node["widgets_values"] = [text]
        node["widgets_values_named"] = {"text": text}


def build(workflow, *, mask_mode=False):
    editor = Editor(workflow)
    original_max_id = max(editor.nodes, default=0)
    nodes = list(editor.nodes.values())
    desk = _one(nodes, "ZVUniversalMediaEvidenceDesk")
    old_interview = _one(nodes, "ZVH3InterviewFormV2")
    if len([node for node in nodes if node.get("type") == "ZVH3ReverseStage"]) != 3:
        raise WorkflowBuildError("源工作流必须包含三个独立反推阶段")
    old_window = _one(nodes, "ZVProcessingWindowOutlet")
    outlet = _one(nodes, "ZVH3ReferenceOutlet")
    decoder = _one(nodes, "MiniMaxH3AVDecodeT8")
    resolution = _one(nodes, "ResolutionSelector")
    reconcile = _one(nodes, "MiniMaxH3TwoPassLatentReconcileT8Advanced")
    conditionings = [node for node in nodes if node.get("type") == "MiniMaxH3AudioConditioningT8"]
    if len(conditionings) != 2:
        raise WorkflowBuildError("源工作流必须恰好包含 LOW/HIGH 两个 MiniMaxH3AudioConditioningT8")
    for conditioning in conditionings:
        _set_named_widget(conditioning, "task_type", "auto")
    if editor.incoming(old_interview["id"], "media_project") is None:
        raise WorkflowBuildError("旧采访表没有连接素材台")
    reference_link = editor.incoming(outlet["id"], "reference_plan")
    if reference_link is None or reference_link[1] != old_interview["id"] or old_interview["outputs"][reference_link[2]].get("name") != "reference_plan":
        raise WorkflowBuildError("参考出口没有连接旧采访表 reference_plan")

    low = high = low_consumer = high_consumer = None
    for conditioning in conditionings:
        for link in editor.outgoing(conditioning["id"], "positive"):
            target = editor.nodes[link[3]]
            input_name = target["inputs"][link[4]].get("name")
            if target.get("type") == "BasicGuider" and input_name == "conditioning":
                if low is not None:
                    raise WorkflowBuildError("LOW conditioning 消费者不唯一")
                low, low_consumer = conditioning, target
            if target["id"] == reconcile["id"] and input_name == "positive":
                if high is not None:
                    raise WorkflowBuildError("HIGH conditioning 消费者不唯一")
                high, high_consumer = conditioning, target
    if low is None or high is None:
        raise WorkflowBuildError("无法从真实消费者识别 LOW/HIGH conditioning")

    for port in ("width", "height"):
        desk_size = editor.incoming(desk["id"], port)
        low_size = editor.incoming(low["id"], port)
        if desk_size is None or low_size is None or desk_size[1:3] != low_size[1:3]:
            raise WorkflowBuildError(f"素材台 {port} 必须与 LOW conditioning 使用同一尺寸来源")

    upscaler = _one(nodes, "MiniMaxH3LearnedLatentUpscaleT8Advanced")
    if mask_mode:
        for port in ("width", "height"):
            high_size = editor.incoming(high["id"], port)
            expected_output = _port_index(upscaler, "outputs", port)
            if high_size is None or high_size[1:3] != [upscaler["id"], expected_output]:
                raise WorkflowBuildError(f"C1 HIGH {port} 必须来自 learned upscaler 的同名输出")
        named = upscaler.get("widgets_values_named") or {}
        scale_link = editor.incoming(upscaler["id"], "scale_by")
        if scale_link is None:
            scale_value = named.get("scale_by")
        else:
            scale_node = editor.nodes[scale_link[1]]
            scale_named = scale_node.get("widgets_values_named") or {}
            scale_value = scale_named.get("value")
        if named.get("size_mode") != "scale_by" or scale_value != 1:
            raise WorkflowBuildError("C1 当前只支持 LOW/HIGH 同画布 1x；learned upscaler 的有效 scale_by 必须为 1")

    vae_sources = {}
    for label, conditioning in (("low", low), ("high", high)):
        for port in ("video_vae", "audio_vae"):
            link = editor.incoming(conditioning["id"], port)
            if link is None:
                raise WorkflowBuildError(f"{label} conditioning 未连接 {port}")
            vae_sources[(label, port)] = (link[1], editor.nodes[link[1]]["outputs"][link[2]]["name"])

    old_math = None
    for conditioning in conditionings:
        link = editor.incoming(conditioning["id"], "length")
        if link is None or editor.nodes[link[1]].get("type") != "ComfyMathExpression":
            raise WorkflowBuildError("H3 length 必须来自旧 ComfyMathExpression，才能安全替换")
        if old_math is None:
            old_math = editor.nodes[link[1]]
        elif old_math["id"] != link[1]:
            raise WorkflowBuildError("LOW/HIGH length 没有共享同一旧表达式")
    window_link = editor.incoming(old_math["id"], "values.a")
    if window_link is None or window_link[1] != old_window["id"]:
        raise WorkflowBuildError("旧长度表达式没有连接 processing window")

    savers = []
    for node in nodes:
        if node.get("type") != "VHS_VideoCombine":
            continue
        image, audio = editor.incoming(node["id"], "images"), editor.incoming(node["id"], "audio")
        if image and audio and image[1] == decoder["id"] and audio[1] == decoder["id"]:
            savers.append(node)
    if len(savers) != 1:
        raise WorkflowBuildError("无法唯一识别旧 H3 视频保存节点")
    old_saver = savers[0]
    debug_outputs = {node["id"] for node in nodes if node.get("type") in ("easy showAnything", "PreviewAny")}
    removable = {old_window["id"], old_math["id"], old_saver["id"], *debug_outputs}
    for node in (old_window, old_math, old_saver):
        allowed = removable | {low["id"], high["id"]}
        external = [link for link in editor.links if link[1] == node["id"] and link[3] not in allowed]
        if external:
            raise WorkflowBuildError(f"{node['type']} 还有未识别消费者，拒绝静默删除")

    _sanitize_desk(desk)
    _rewrite_notes(nodes, mask_mode=mask_mode)
    names = (
        "plan", "interview", "setup", "start", "entry", "recorder", "end", "finish", "save",
        "low_guide", "low_switch", "high_guide", "high_switch",
        "mask_source", "image_to_mask", "mask_bundle", "mask_slice",
    )
    if mask_mode:
        names += ("mask_adapter", "mask_high_restore", "mask_compose")
    ids = {name: editor.allocate() for name in names}
    assert min(ids.values()) > original_max_id

    settings = {
        "schema_version": 1, "mode": "source_auto", "fps": 24, "segment_frames": 360,
        "overlap_frames": 48, "overlap_alignment": "h3_guide", "segment_count": 3,
        "segments": [], "range_start_frame": None, "range_end_frame": None,
        "source_snapshot": None, "source_fingerprint": None, "refresh_sources": False,
    }
    state = {"schema_version": 1, "global": {}, "segments": {}, "alignment": None}
    settings_json, state_json = json.dumps(settings, ensure_ascii=False), json.dumps(state, ensure_ascii=False)
    x, y = float(desk.get("pos", [0, 0])[0]) + 1250, float(desk.get("pos", [0, 0])[1])
    new_nodes = [
        make_node(ids["plan"], "ZVLongVideoSegmentDesk", "① 分段台：排列长视频片段", [x, y],
                  [("media_project", "ZV_MEDIA_PROJECT"), ("segment_data", "STRING")],
                  [("segment_plan", "ZV_SEGMENT_PLAN"), ("report", "STRING")], values=[settings_json],
                  named_values={"segment_data": settings_json}, size=[1080, 760], widget_inputs={"segment_data"}),
        make_node(ids["interview"], "ZVSegmentInterview", "② 分段采访：检测并对齐全部分段", [x, y + 850],
                  [("segment_plan", "ZV_SEGMENT_PLAN"), ("interview_data", "STRING")],
                  [("execution_plan", "ZV_SEGMENT_EXECUTION_PLAN"), ("检查报告", "STRING"), ("ready", "BOOLEAN")],
                  values=[state_json], named_values={"interview_data": state_json}, size=[1080, 820], widget_inputs={"interview_data"}),
        make_node(ids["setup"], "ZVLongVideoExecutionSetup", "③ 冻结执行计划 / 段数", [x + 1200, y + 900],
                  [("execution_plan", "ZV_SEGMENT_EXECUTION_PLAN")], [("segment_count", "INT"), ("report", "STRING")]),
        make_node(ids["start"], "StartLoop", "逐段循环开始 · cache_iterations=false", [x + 1650, y + 900],
                  [("mode", "COMFY_DYNAMICCOMBO_V3"), ("mode.num_iterations", "INT"), ("cache_iterations", "BOOLEAN"),
                   ("parent_iteration", "INT"), ("initial_iteration_value", "ZV_LONG_VIDEO_RUN")],
                  [("iteration_index", "INT"), ("is_first", "BOOLEAN"), ("is_last", "BOOLEAN"),
                   ("list_item", "*"), ("current_iteration_value", "ZV_LONG_VIDEO_RUN")],
                  values=["simple", 3, False], named_values={"mode": "simple", "mode.num_iterations": 3, "cache_iterations": False},
                  size=[380, 250], widget_inputs={"mode", "cache_iterations"}),
        make_node(ids["entry"], "ZVLongVideoExecutionEntry", "每次只取当前段与前段 guide", [x + 2100, y + 850],
                  [("execution_plan", "ZV_SEGMENT_EXECUTION_PLAN"), ("iteration_index", "INT"), ("previous_result", "ZV_LONG_VIDEO_RUN")],
                  [("segment_context", "ZV_SEGMENT_EXECUTION_CONTEXT"), ("reference_plan", "ZV_H3_REFERENCE_PLAN"),
                   ("user_prompt", "STRING"), ("material_context_json", "STRING"),
                   ("duration_seconds", "FLOAT"), ("frame_count", "INT"),
                   ("model_length", "INT"), ("model_adapter", "STRING"), ("has_guide", "BOOLEAN"),
                   ("guide_frames", "IMAGE"), ("guide_audio", "AUDIO"), ("guide_frame_idx", "INT"),
                   ("segment_id", "STRING"), ("report", "STRING")], size=[430, 500]),
        make_node(ids["recorder"], "ZVLongVideoSegmentRecorder", "逐段精确裁切并落盘", [x + 5000, y + 850],
                  [("segment_context", "ZV_SEGMENT_EXECUTION_CONTEXT"), ("frames", "IMAGE"), ("generated_audio", "AUDIO"),
                   ("final_audio", "AUDIO"), ("previous_result", "ZV_LONG_VIDEO_RUN"), ("guide_application_note", "STRING"),
                   ("mask_source_evidence", "STRING"), ("mask_high_evidence", "STRING"), ("mask_compose_evidence", "STRING")],
                  [("run_result", "ZV_LONG_VIDEO_RUN"), ("report", "STRING")],
                  values=["LOW/HIGH 均通过 lazy switch 接入 MiniMaxH3AddGuide；实际 GPU 应用仍需复验"],
                  named_values={"guide_application_note": "LOW/HIGH 均通过 lazy switch 接入 MiniMaxH3AddGuide；实际 GPU 应用仍需复验"},
                  size=[430, 290], widget_inputs={"guide_application_note"}),
        make_node(ids["end"], "EndLoop", "逐段循环结束 · accumulate=false", [x + 5500, y + 850],
                  [("output_value", "ZV_LONG_VIDEO_RUN"), ("next_iteration_value", "ZV_LONG_VIDEO_RUN"), ("accumulate", "BOOLEAN")],
                  [("outputs", "ZV_LONG_VIDEO_RUN")], values=[False], named_values={"accumulate": False},
                  size=[360, 210], widget_inputs={"accumulate"}),
        make_node(ids["finish"], "ZVLongVideoExecutionEnd", "④ 拼接为完整 native VIDEO", [x + 5920, y + 850],
                  [("execution_plan", "ZV_SEGMENT_EXECUTION_PLAN"), ("run_result", "ZV_LONG_VIDEO_RUN")],
                  [("video", "VIDEO"), ("frame_count", "INT"), ("report", "STRING")]),
        make_node(ids["save"], "SaveVideo", "保存完整长视频", [x + 6360, y + 850],
                  [("video", "VIDEO"), ("filename_prefix", "STRING"), ("format", "COMFY_DYNAMICCOMBO_V3"),
                   ("format.codec", "COMFY_DYNAMICCOMBO_V3"), ("codec", "COMFY_DYNAMICCOMBO_V3")],
                  [("video", "VIDEO")], values=["MiniMaxH3/long_video", "auto", "auto", "auto"],
                  named_values={"filename_prefix": "MiniMaxH3/long_video", "format": "auto", "format.codec": "auto", "codec": "auto"},
                  size=[460, 300], widget_inputs={"filename_prefix", "format", "format.codec", "codec"}),
    ]
    for label, conditioning in (("low", low), ("high", high)):
        gx, gy = float(conditioning["pos"][0]) + 430, float(conditioning["pos"][1]) + 360
        new_nodes += [
            make_node(ids[label + "_guide"], "MiniMaxH3AddGuide", f"{label.upper()} · 应用前段尾部 Guide", [gx, gy],
                      [("positive", "CONDITIONING"), ("vae", "VAE"), ("audio_vae", "VAE"), ("latent", "LATENT"),
                       ("image", "IMAGE"), ("audio", "AUDIO"), ("frame_idx", "INT")], [("positive", "CONDITIONING")],
                      values=[0], named_values={"frame_idx": 0}, size=[390, 300], widget_inputs={"frame_idx"}),
            make_node(ids[label + "_switch"], "ComfySwitchNode", f"{label.upper()} · 首段/硬切与 Guide 懒切换", [gx + 430, gy],
                      [("switch", "BOOLEAN"), ("on_false", "CONDITIONING"), ("on_true", "CONDITIONING")],
                      [("output", "CONDITIONING")], size=[360, 190]),
        ]
    new_nodes += [
        make_node(ids["mask_source"], "ZVSegmentVideoMaskSource", "可选遮罩协议：读取冻结源时钟", [x + 1200, y + 1850],
                  [("segment_plan", "ZV_SEGMENT_PLAN"), ("clip_id", "STRING"), ("range_mode", "COMBO"), ("segment_index", "INT")],
                  [("frames", "IMAGE"), ("source_info", "ZV_MASK_SOURCE"), ("source_audio", "AUDIO")], values=["", "全片", 1],
                  named_values={"clip_id": "", "range_mode": "全片", "segment_index": 1}, size=[430, 250],
                  widget_inputs={"clip_id", "range_mode", "segment_index"}),
        make_node(ids["image_to_mask"], "ImageToMask", "示意：请替换为 SAM3 / SeC / 手绘 MASK", [x + 1680, y + 1850],
                  [("image", "IMAGE"), ("channel", "COMBO")], [("MASK", "MASK")], values=["red"],
                  named_values={"channel": "red"}, size=[430, 190], widget_inputs={"channel"}),
        make_node(ids["mask_bundle"], "ZVMaskedSegmentBundle", "绑定 MASK 与冻结来源时钟", [x + 2160, y + 1850],
                  [("segment_plan", "ZV_SEGMENT_PLAN"), ("mask", "MASK"), ("source_info", "ZV_MASK_SOURCE"), ("mode", "COMBO")],
                  [("masked_segments", "ZV_MASKED_SEGMENT_BUNDLE"), ("report", "STRING")], values=["逐帧"],
                  named_values={"mode": "逐帧"}, size=[430, 230], widget_inputs={"mode"}),
        make_node(ids["mask_slice"], "ZVSegmentMaskSlice", "按当前分段输出标准 MASK（协议示例）", [x + 2640, y + 1850],
                  [("masked_segments", "ZV_MASKED_SEGMENT_BUNDLE"), ("segment_plan", "ZV_SEGMENT_PLAN"), ("segment_index", "INT")],
                  [("mask", "MASK"), ("clock_evidence_json", "STRING")], size=[430, 210]),
    ]
    if mask_mode:
        new_nodes.append(make_node(
                  ids["mask_adapter"], "ZVH3MaskedSegmentLatent", "C1 · 全帧同几何 H3 蒙版 Latent", [x + 3120, y + 1850],
                  [("segment_plan", "ZV_SEGMENT_PLAN"), ("segment_index", "INT"), ("source_frames", "IMAGE"),
                   ("source_audio", "AUDIO"), ("masked_segments", "ZV_MASKED_SEGMENT_BUNDLE"),
                   ("video_vae", "VAE"), ("audio_vae", "VAE"), ("no_source_audio_policy", "COMBO")],
                  [("av_latent", "LATENT"), ("model_frames", "IMAGE"), ("model_mask", "MASK"),
                   ("model_audio", "AUDIO"), ("final_audio", "AUDIO"),
                   ("clock_evidence_json", "STRING"), ("model_length", "INT")],
                  values=["clocked_silence"], named_values={"no_source_audio_policy": "clocked_silence"},
                  size=[470, 360], widget_inputs={"no_source_audio_policy"}))
        new_nodes += [
            make_node(ids["mask_high_restore"], "ZVH3MaskedLatentRestore", "C1 · HIGH 同画布源与 MASK 恢复", [x + 4080, y + 1850],
                      [("av_latent", "LATENT"), ("source_latent", "LATENT"), ("model_mask", "MASK")],
                      [("av_latent", "LATENT"), ("evidence_json", "STRING")], size=[440, 220]),
            make_node(ids["mask_compose"], "ZVH3MaskedFrameCompose", "C1 · 解码后黑区源像素回贴", [x + 4560, y + 1850],
                      [("generated_frames", "IMAGE"), ("source_frames", "IMAGE"), ("model_mask", "MASK")],
                      [("frames", "IMAGE"), ("evidence_json", "STRING")], size=[440, 220]),
        ]
    for node in new_nodes:
        editor.add(node)

    interview_map = {
        "user_prompt": "user_prompt", "material_context_json": "material_context_json",
        "duration_seconds": "duration_seconds", "reference_plan": "reference_plan",
    }
    for link in list(editor.links):
        if link[1] == old_interview["id"]:
            output_name = old_interview["outputs"][link[2]].get("name")
            if output_name not in interview_map:
                raise WorkflowBuildError(f"旧采访表输出 {output_name} 仍有消费者，无法无损迁移")
            link[1] = ids["entry"]
            link[2] = _port_index(editor.nodes[ids["entry"]], "outputs", interview_map[output_name])
    editor.remove_nodes({old_interview["id"], old_window["id"], old_math["id"], old_saver["id"], *debug_outputs})

    def wire(source, out_name, target, in_name, type_, replace=False):
        editor.wire(source, out_name, target, in_name, type_, replace)

    wire(desk["id"], "media_project", ids["plan"], "media_project", "ZV_MEDIA_PROJECT")
    wire(ids["plan"], "segment_plan", ids["interview"], "segment_plan", "ZV_SEGMENT_PLAN")
    wire(ids["interview"], "execution_plan", ids["setup"], "execution_plan", "ZV_SEGMENT_EXECUTION_PLAN")
    wire(ids["interview"], "execution_plan", ids["entry"], "execution_plan", "ZV_SEGMENT_EXECUTION_PLAN")
    wire(ids["setup"], "segment_count", ids["start"], "mode.num_iterations", "INT")
    wire(ids["start"], "iteration_index", ids["entry"], "iteration_index", "INT")
    wire(ids["start"], "current_iteration_value", ids["entry"], "previous_result", "ZV_LONG_VIDEO_RUN")
    wire(ids["entry"], "segment_context", ids["recorder"], "segment_context", "ZV_SEGMENT_EXECUTION_CONTEXT")
    wire(ids["start"], "current_iteration_value", ids["recorder"], "previous_result", "ZV_LONG_VIDEO_RUN")
    frame_source = ids["mask_compose"] if mask_mode else decoder["id"]
    wire(frame_source, "frames", ids["recorder"], "frames", "IMAGE")
    wire(decoder["id"], "generated_audio", ids["recorder"], "generated_audio", "AUDIO")
    final_audio_source = ids["mask_adapter"] if mask_mode else outlet["id"]
    wire(final_audio_source, "final_audio", ids["recorder"], "final_audio", "AUDIO")
    wire(ids["recorder"], "run_result", ids["end"], "output_value", "ZV_LONG_VIDEO_RUN")
    wire(ids["recorder"], "run_result", ids["end"], "next_iteration_value", "ZV_LONG_VIDEO_RUN")
    wire(ids["end"], "outputs", ids["finish"], "run_result", "ZV_LONG_VIDEO_RUN")
    wire(ids["interview"], "execution_plan", ids["finish"], "execution_plan", "ZV_SEGMENT_EXECUTION_PLAN")
    wire(ids["finish"], "video", ids["save"], "video", "VIDEO")
    for label, conditioning, consumer, consumer_input in (
        ("low", low, low_consumer, "conditioning"), ("high", high, high_consumer, "positive"),
    ):
        guide, switch = ids[label + "_guide"], ids[label + "_switch"]
        wire(conditioning["id"], "positive", guide, "positive", "CONDITIONING")
        latent_source = ids["mask_adapter"] if mask_mode and label == "low" else conditioning["id"]
        wire(latent_source, "av_latent", guide, "latent", "LATENT")
        for source_port, guide_port in (("video_vae", "vae"), ("audio_vae", "audio_vae")):
            source, output_name = vae_sources[(label, source_port)]
            wire(source, output_name, guide, guide_port, "VAE")
        wire(ids["entry"], "guide_frames", guide, "image", "IMAGE")
        wire(ids["entry"], "guide_audio", guide, "audio", "AUDIO")
        wire(ids["entry"], "guide_frame_idx", guide, "frame_idx", "INT", True)
        wire(ids["entry"], "has_guide", switch, "switch", "BOOLEAN")
        wire(conditioning["id"], "positive", switch, "on_false", "CONDITIONING")
        wire(guide, "positive", switch, "on_true", "CONDITIONING")
        wire(switch, "output", consumer["id"], consumer_input, "CONDITIONING", True)
        length_source = ids["mask_adapter"] if mask_mode else ids["entry"]
        wire(length_source, "model_length", conditioning["id"], "length", "INT", True)

    wire(ids["plan"], "segment_plan", ids["mask_source"], "segment_plan", "ZV_SEGMENT_PLAN")
    wire(ids["mask_source"], "frames", ids["image_to_mask"], "image", "IMAGE")
    wire(ids["plan"], "segment_plan", ids["mask_bundle"], "segment_plan", "ZV_SEGMENT_PLAN")
    wire(ids["image_to_mask"], "MASK", ids["mask_bundle"], "mask", "MASK")
    wire(ids["mask_source"], "source_info", ids["mask_bundle"], "source_info", "ZV_MASK_SOURCE")
    wire(ids["mask_bundle"], "masked_segments", ids["mask_slice"], "masked_segments", "ZV_MASKED_SEGMENT_BUNDLE")
    wire(ids["plan"], "segment_plan", ids["mask_slice"], "segment_plan", "ZV_SEGMENT_PLAN")
    wire(ids["start"], "iteration_index", ids["mask_slice"], "segment_index", "INT")
    if mask_mode:
        wire(ids["plan"], "segment_plan", ids["mask_adapter"], "segment_plan", "ZV_SEGMENT_PLAN")
        wire(ids["start"], "iteration_index", ids["mask_adapter"], "segment_index", "INT")
        wire(ids["mask_source"], "frames", ids["mask_adapter"], "source_frames", "IMAGE")
        wire(ids["mask_source"], "source_audio", ids["mask_adapter"], "source_audio", "AUDIO")
        wire(ids["mask_bundle"], "masked_segments", ids["mask_adapter"], "masked_segments", "ZV_MASKED_SEGMENT_BUNDLE")
        for port in ("video_vae", "audio_vae"):
            source, output_name = vae_sources[("low", port)]
            wire(source, output_name, ids["mask_adapter"], port, "VAE")
        for link in editor.links:
            if link[1] != low["id"]:
                continue
            output = low["outputs"][link[2]].get("name")
            if output == "av_latent":
                link[1] = ids["mask_adapter"]
                link[2] = _port_index(editor.nodes[ids["mask_adapter"]], "outputs", "av_latent")
        high_links = [
            link for link in editor.links
            if link[1] == reconcile["id"]
            and reconcile["outputs"][link[2]].get("name") == "av_latent"
        ]
        for link in high_links:
            link[1] = ids["mask_high_restore"]
            link[2] = _port_index(editor.nodes[ids["mask_high_restore"]], "outputs", "av_latent")
        wire(reconcile["id"], "av_latent", ids["mask_high_restore"], "av_latent", "LATENT")
        wire(ids["mask_adapter"], "av_latent", ids["mask_high_restore"], "source_latent", "LATENT")
        wire(ids["mask_adapter"], "model_mask", ids["mask_high_restore"], "model_mask", "MASK")
        wire(decoder["id"], "frames", ids["mask_compose"], "generated_frames", "IMAGE")
        wire(ids["mask_adapter"], "model_frames", ids["mask_compose"], "source_frames", "IMAGE")
        wire(ids["mask_adapter"], "model_mask", ids["mask_compose"], "model_mask", "MASK")
        wire(ids["mask_adapter"], "clock_evidence_json", ids["recorder"], "mask_source_evidence", "STRING")
        wire(ids["mask_high_restore"], "evidence_json", ids["recorder"], "mask_high_evidence", "STRING")
        wire(ids["mask_compose"], "evidence_json", ids["recorder"], "mask_compose_evidence", "STRING")

    result = editor.finish()
    result["groups"] = []
    extra = result.setdefault("extra", {})
    extra.pop("zv_interview_v2", None)
    extra["workflow_title"] = "H3焦点访谈 长视频蒙版" if mask_mode else "H3焦点访谈 长视频分段"
    extra["zv_long_video"] = {
        "version": 1,
        "verification": (
            "isolated H3 GPU C1 black/white/half-mask acceptance at 256x416, including a two-segment 200-frame run"
            if mask_mode else
            "isolated H3 GPU two-segment 200-frame generation with 39-frame guide and continuous 44.1 kHz stereo audio"
        ),
        "mask_status": (
            "C1 full-frame source IMAGE/MASK/AUDIO is connected at LOW, restored after HIGH reconcile on the same 1x canvas, and pixel-composed after decode; external SAM3/SeC tracking remains C2"
            if mask_mode else
            "mask clock/bundle/slice protocol only; no mask adapter is connected to the ordinary generation path"
        ),
        "source_resolution_node_id": resolution["id"], "new_node_ids": ids,
    }
    return result


def build_masked(workflow):
    return build(workflow, mask_mode=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mask-mode", action="store_true", help="生成激活 H3 C1 蒙版 latent 的独立工作流")
    args = parser.parse_args(argv)
    try:
        if args.source.resolve() == args.output.resolve():
            raise WorkflowBuildError("输出必须另存为新工作流")
        if args.output.exists():
            raise WorkflowBuildError("输出文件已存在；默认拒绝覆盖")
        source = json.loads(args.source.read_text(encoding="utf-8-sig"))
        value = build(source, mask_mode=args.mask_mode)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError, WorkflowBuildError) as error:
        parser.error(str(error))
    print(f"{len(value['nodes'])} nodes, {len(value['links'])} links: {args.output}")


if __name__ == "__main__":
    main()
