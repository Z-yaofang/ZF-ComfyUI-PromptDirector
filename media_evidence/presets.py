"""Versioned processing rules; compatibility never changes the project range."""
import copy
import json
import math
from pathlib import Path

BUILTIN_PRESETS = json.loads((Path(__file__).resolve().parents[1] / "web" / "media_processing_presets.json").read_text(encoding="utf-8"))


def builtin(preset_id="builtin.generic"):
    return copy.deepcopy(next(p for p in BUILTIN_PRESETS if p["preset_id"] == preset_id))


def normalize_snapshot(snapshot):
    result = copy.deepcopy(snapshot)
    if isinstance(result, dict) and isinstance(result.get("rules"), dict):
        # Earlier snapshots used the request exactly; never infer alignment from an ID.
        result["rules"].setdefault("overlap_alignment", "exact")
    return result


def effective_overlap_frames(rules):
    requested = rules["overlap_frames"]
    if rules.get("overlap_alignment", "exact") == "h3_guide":
        # TimelineDirector experimental_latent_guide._valid_guide_frames.
        return 1 if requested < 5 else 5 + 17 * ((requested - 5) // 17)
    return requested


def rule_errors(snapshot):
    errors = []
    if not isinstance(snapshot, dict) or set(snapshot) != {"name", "description", "strategy", "rules"}:
        return ["预设必须包含名称、用途说明、策略和完整规则"]
    if not isinstance(snapshot["name"], str) or not snapshot["name"].strip() or len(snapshot["name"]) > 80:
        errors.append("预设名称不能为空，且最多 80 个字符")
    if not isinstance(snapshot["description"], str) or len(snapshot["description"]) > 1000:
        errors.append("模型/用途说明最多 1000 个字符")
    if snapshot["strategy"] not in ("single_window", "auto_segment"):
        errors.append("请选择单窗口或自动分段策略")
    rules = snapshot["rules"]
    fields = {"target_fps", "min_frames", "max_frames", "max_seconds", "align_to_grid", "segment_min_seconds", "segment_max_seconds", "overlap_frames", "overlap_alignment"}
    if not isinstance(rules, dict) or set(rules) != fields:
        return errors + ["预设规则字段不完整或包含未知字段"]
    titles = {"target_fps": "目标 fps", "min_frames": "最少帧", "max_frames": "最多帧", "max_seconds": "最长秒数", "segment_min_seconds": "单段最少秒数", "segment_max_seconds": "单段最多秒数", "overlap_frames": "请求重叠帧"}
    for key, title in titles.items():
        value = rules[key]
        if value is None and key != "overlap_frames":
            continue
        maximum = 240 if key == "target_fps" else 10368000 if "frames" in key else 43200
        if type(value) not in (int, float) or not math.isfinite(value) or not (0 if key == "overlap_frames" else 1 if key == "target_fps" else 1e-9) <= value <= maximum:
            errors.append(f"{title}必须是合法有限数值，不能为负或超过 {maximum}")
        elif "frames" in key and int(value) != value:
            errors.append(f"{title}必须为整数")
    if type(rules["align_to_grid"]) is not bool:
        errors.append("帧网格对齐必须为开关值")
    if rules["overlap_alignment"] not in ("exact", "h3_guide"):
        errors.append("请选择按请求值或 H3 Guide 网格的重叠对齐策略")
    if errors:
        return errors
    fps, minimum, maximum = rules["target_fps"], rules["min_frames"], rules["max_frames"]
    segmented = snapshot["strategy"] == "auto_segment"
    if fps is None and (minimum is not None or maximum is not None or rules["align_to_grid"] or segmented):
        return ["帧数限制、帧网格对齐或自动分段需要设置目标 fps"]
    if segmented:
        if rules["overlap_alignment"] == "h3_guide" and rules["overlap_frames"] < 1:
            return ["H3 Guide 请求重叠帧至少为 1"]
        if rules["segment_min_seconds"] is None or rules["segment_max_seconds"] is None:
            return ["自动分段必须设置单段最少和最多秒数"]
        minimum = max(minimum or 1, math.ceil(rules["segment_min_seconds"] * fps - 1e-9))
        maximum = min(maximum or math.inf, math.floor(rules["segment_max_seconds"] * fps + 1e-9))
        overlap = effective_overlap_frames(rules)
        if overlap >= minimum:
            errors.append(f"实际重叠 {overlap:g} 帧必须小于有效单段最少帧数 {minimum:g}")
        if rules["max_seconds"] is not None and rules["max_seconds"] * fps < minimum - 1e-9:
            errors.append("总任务最长秒数不能小于有效单段最短时长")
    else:
        if rules["segment_min_seconds"] is not None or rules["segment_max_seconds"] is not None or rules["overlap_frames"] or rules["overlap_alignment"] != "exact":
            errors.append("单窗口策略不能保存分段秒数、重叠帧或专用重叠对齐策略")
        if rules["max_seconds"] is not None and fps:
            maximum = min(maximum or math.inf, math.floor(rules["max_seconds"] * fps + 1e-9))
    if maximum is not None and (maximum < 1 or (minimum is not None and minimum > maximum)):
        errors.append("最少帧/单段最短时长超过更严格的有效上限，规则冲突")
    return errors


def compatibility(window, preset):
    snapshot, rules = preset["snapshot"], preset["snapshot"]["rules"]
    fps = rules["target_fps"] or window["fps"]
    start, end = window["start_seconds"], window["end_seconds"]
    duration = end - start
    first, last = math.floor(start*fps+.5), math.floor(end*fps+.5)
    count = max(0, last-first)
    issues = []
    def issue(code, message):
        issues.append({"path": "/processing_window", "code": code, "message": message})
    segmented = snapshot["strategy"] == "auto_segment"
    minimum, maximum = rules["min_frames"], rules["max_frames"]
    seconds_cap = rules["segment_max_seconds"] if segmented else rules["max_seconds"]
    if segmented:
        minimum = max(minimum or 1, math.ceil(rules["segment_min_seconds"]*fps-1e-9))
    if seconds_cap is not None and rules["target_fps"]:
        maximum = min(maximum or math.inf, math.floor(seconds_cap*fps+1e-9))
    effective_seconds = min(seconds_cap or math.inf, maximum/fps if maximum is not None else math.inf)
    if rules["target_fps"] and abs(window["fps"]-fps) > 1e-9:
        issue("preset_fps", f"窗口参考帧率 {window['fps']:g} fps 与预设目标 {fps:g} fps 不符")
    if rules["align_to_grid"] and (abs(first/fps-start)>1e-6 or abs(last/fps-end)>1e-6):
        issue("preset_grid", f"起止位置未对齐 {fps:g} fps 网格；范围未被改写")
    current = f"当前 {duration:.3f} 秒 / {count} 帧"
    seconds_over = rules["max_seconds"] is not None and duration > rules["max_seconds"]+1e-9
    if not segmented and maximum is not None and (count > maximum or duration > effective_seconds+1e-9):
        issue("preset_seconds" if seconds_over else "preset_max_frames", f"{current}，超出{snapshot['name']}有效上限 {effective_seconds:g} 秒 / {maximum:g} 帧（多 {max(0, duration-effective_seconds):.3f} 秒 / {max(0,count-maximum):g} 帧）")
    elif seconds_over:
        limit = f"{rules['max_seconds']:g} 秒" + (f" / {maximum:g} 帧" if maximum is not None and not segmented else "")
        issue("preset_seconds", f"{current}，超出{snapshot['name']}上限 {limit}（多 {duration-rules['max_seconds']:.3f} 秒）")
    segments = overlap = stride = None
    if segmented:
        overlap = effective_overlap_frames(rules)
        stride = maximum-overlap
        segments = max(1, math.ceil((count-overlap)/stride))
        if count + (segments-1)*overlap < segments*minimum:
            issue("preset_segments", f"{current}，无法按每段 {minimum:g}–{maximum:g} 帧、实际重叠 {overlap:g} 帧覆盖；需调整范围或分段规则")
    else:
        if minimum is not None and count < minimum:
            issue("preset_min_frames", f"{current}，不足最少 {minimum:g} 帧（少 {minimum-count:g} 帧）")
    return {"compatible": not issues, "issues": issues, "target_fps": fps, "frame_count": count, "effective_min_frames": minimum, "effective_max_frames": maximum,
            "effective_max_seconds": None if math.isinf(effective_seconds) else effective_seconds, "segment_count": segments, "rules_only": segmented,
            "requested_overlap_frames": rules["overlap_frames"] if segmented else None, "effective_overlap_frames": overlap, "segment_stride_frames": stride}
