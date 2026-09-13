import copy
import json
from collections.abc import Mapping

from .compiler import compile_plan
from .contract import ContractError, parse_json
from .interview import InterviewError, annotate_conditioning, annotate_project_errors, build_system_prompt, compile_interview, dumps, empty_interview, normalize_interview, parse_interview
from .reference_detection import compare_detection, detect_reference_wiring, validate_reference_hub_wiring, validate_conditioning_settings
from .reference_plan import build_reference_plan, empty_reference_plan, planned_detection


def _prompt_uses_reference_hub(prompt, interview_id):
    if not isinstance(prompt, Mapping):
        return False
    wanted = str(interview_id)
    for node in prompt.values():
        if not isinstance(node, Mapping) or node.get("class_type") != "ZVH3ReferenceOutlet":
            continue
        inputs = node.get("inputs", {})
        link = inputs.get("reference_plan") if isinstance(inputs, Mapping) else None
        if (
            isinstance(link, list) and len(link) == 2
            and str(link[0]) == wanted and link[1] == 8
        ):
            return True
    return False


class ZVH3FocusCompiler:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"plan_json": ("STRING", {"multiline": True, "default": "{}"})},
            "optional": {"llm_patch_json": ("STRING", {"multiline": True, "default": ""})},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("normalized_plan_json", "final_prompt", "reverse_task_json", "human_report", "validation_report_json", "ready")
    FUNCTION = "compile"
    CATEGORY = "ZV/视频创作/H3"

    def compile(self, plan_json, llm_patch_json=""):
        try:
            result = compile_plan(parse_json(plan_json), llm_patch_json if llm_patch_json.strip() else None)
        except ContractError as exc:
            validation = {"ready": False, "errors": exc.issues, "warnings": []}
            report = "H3 计划未通过契约校验：\n" + "\n".join(f"{e['path']}：{e['message']}" for e in exc.issues)
            return ("{}", "", "{}", report, json.dumps(validation, ensure_ascii=False), False)
        dump = lambda value: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        return (dump(result["plan"]), result["final_prompt"], dump(result["reverse_tasks"]), result["human_report"], dump(result["validation"]), result["ready"])


class ZVH3InterviewForm:
    """A visual interview stored as JSON and grounded by a media-project input."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_project": ("ZV_MEDIA_PROJECT",),
                "interview_json": ("STRING", {"multiline": True, "default": dumps(empty_interview())}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    # The first eight outputs are the released contract. Keep their indices
    # stable and append the fixed-reference plan at the end.
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "FLOAT", "STRING", "STRING", "BOOLEAN", "ZV_H3_REFERENCE_PLAN")
    RETURN_NAMES = ("system_prompt", "stage1_task", "stage2_prefix", "stage3_prefix", "duration_seconds", "interview_json", "human_report", "ready", "reference_plan")
    FUNCTION = "build"
    CATEGORY = "ZV/视频创作/H3"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        # A downstream rewire does not change ordinary upstream cache keys. The
        # check itself only walks the submitted prompt graph and does no media IO.
        return float("nan")

    def build(self, media_project, interview_json, prompt=None, unique_id=None):
        from ..media_evidence import runtime
        from ..media_evidence.contract import ProjectError, normalize_project

        try:
            raw_state = parse_interview(interview_json)
            state = normalize_interview(raw_state)
            project = runtime.get_store().canonical(normalize_project(media_project))
            saved_detection = state.get("reference_detection")
            uses_reference_hub = (
                prompt is not None
                and unique_id is not None
                and _prompt_uses_reference_hub(prompt, unique_id)
            )
            result = compile_interview(state, project)
            annotate_project_errors(result, project["validation"]["errors"])
            if prompt is not None and unique_id is not None:
                if result["call_references"] and (saved_detection is None or state["alignment"] is None):
                    raise RuntimeError("H3 素材尚未建立本次机械对齐上下文。请点击采访表的“检测并对齐素材”；语义用途可留空。")
                evidence = validate_conditioning_settings(prompt, unique_id, effective_mode=result["validation"]["effective_mode"], has_drive_audio=bool(result["validation"]["counts"]["drive_audio"]), project_frame_count=project["processing_window"]["frame_count"])
                annotate_conditioning(result, project, evidence)
                if evidence["errors"]:
                    raise RuntimeError("H3 Conditioning 设置无效：" + "；".join(row["message"] for row in evidence["errors"]))
            if uses_reference_hub:
                if result["call_references"] and (saved_detection is None or state["alignment"] is None):
                    raise RuntimeError("H3 素材尚未建立本次机械对齐上下文。请点击采访表的“检测并对齐素材”；语义用途可留空。")
                hub_wiring = validate_reference_hub_wiring(prompt, unique_id)
                if hub_wiring["errors"]:
                    detail = "；".join(row.get("message", row.get("code", "固定出口接线错误")) for row in hub_wiring["errors"])
                    raise RuntimeError(f"H3 固定出口或 Conditioning 设置无效：{detail}。请点击检测同步安全参数并修复线路；模型家族需用户自行确认。")
                actual_detection = planned_detection(result, conditioning_count=hub_wiring["conditioning_count"])
            elif saved_detection is not None and prompt is not None and unique_id is not None:
                actual_detection = detect_reference_wiring(prompt, unique_id)
                if actual_detection.get("conditioning_count", 0) == 0:
                    actual_detection = None
            else:
                actual_detection = None
            stale = [row for row in result["validation"]["errors"] if row["code"] == "alignment_stale"]
            if stale:
                raise RuntimeError("H3 对齐已过期：" + "；".join(row["message"] for row in stale))
            if saved_detection is not None and actual_detection is not None:
                runtime_saved = copy.deepcopy(saved_detection)
                runtime_saved["conditioning_count"] = actual_detection["conditioning_count"]
                compared = compare_detection(runtime_saved, actual_detection)
                if not compared["match"]:
                    messages = [row.get("message", row.get("code", "线路检测失败")) for row in compared["errors"]]
                    messages.extend(f"{row['field']} 已与手动检测结果不同" for row in compared["differences"])
                    raise RuntimeError("H3 素材线路已变化：" + "；".join(messages) + "。请回到采访表点击“检测并对齐素材”。")

        except InterviewError as exc:
            state = empty_interview()
            system_prompt = build_system_prompt(state)
            report = "H3 采访数据无效：\n" + "\n".join(f"{row['path']}：{row['message']}" for row in exc.issues)
            return (
                system_prompt, "", "", "", 0.0, dumps(state, indent=2), report, False,
                empty_reference_plan(errors=[{"path": "/interview_json", "code": "interview", "message": report}]),
            )
        except ProjectError as exc:
            state = empty_interview()
            try:
                state = normalize_interview(parse_interview(interview_json))
            except InterviewError:
                pass
            report = "素材工程无效：\n" + "\n".join(f"{row['path']}：{row['message']}" for row in exc.errors)
            return (
                build_system_prompt(state), "", "", "", 0.0, dumps(state, indent=2), report, False,
                empty_reference_plan(errors=[{"path": "/media_project", "code": "project", "message": report}]),
            )
        reference_plan = build_reference_plan(project, result)
        return (
            result["system_prompt"],
            result["stage1_task"],
            result["stage2_prefix"],
            result["stage3_prefix"],
            result["duration_seconds"],
            dumps(result["state"], indent=2),
            result["human_report"],
            result["validation"]["ready"],
            reference_plan,
        )
