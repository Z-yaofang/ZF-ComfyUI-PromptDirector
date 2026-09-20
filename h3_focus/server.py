"""Local planning endpoint: no files are imported, decoded, or modified."""

from aiohttp import web
import copy
import math

from ..media_evidence.contract import ProjectError, normalize_project
from ..media_evidence.runtime import get_store
from ..media_evidence.outlet import OutletError, _video_target_size
from .interview import InterviewError, annotate_conditioning, annotate_project_errors, compile_interview
from .reference_plan import planned_detection
from .reference_detection import validate_reference_hub_wiring, validate_conditioning_settings, detect_reference_wiring, detection_snapshot
from .routing import align_bindings
from .preset_server import register_preset_routes


def _static_dimension(value, prompt):
    if type(value) in (int, float) and math.isfinite(value):
        return value
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("尺寸输入没有可核实的静态值")
    node = prompt.get(str(value[0]), {})
    inputs = node.get("inputs", {})
    if node.get("class_type") in {"PrimitiveInt", "INTConstant"} and value[1] == 0:
        number = inputs.get("value")
        if type(number) is int:
            return number
    if node.get("class_type") == "ResolutionSelector" and type(value[1]) is int and value[1] in (0, 1):
        ratios = {"1:1 (Square)": (1, 1), "2:3 (Portrait Photo)": (2, 3), "3:2 (Photo)": (3, 2), "3:4 (Portrait Standard)": (3, 4), "4:3 (Standard)": (4, 3), "9:16 (Portrait Widescreen)": (9, 16), "16:9 (Widescreen)": (16, 9), "21:9 (Ultrawide)": (21, 9)}
        ratio = ratios.get(inputs.get("aspect_ratio"))
        megapixels, multiple = inputs.get("megapixels", 1.0), inputs.get("multiple", 8)
        if ratio and type(megapixels) in (int, float) and math.isfinite(megapixels) and megapixels > 0 and type(multiple) is int and multiple > 0:
            scale = math.sqrt(megapixels * 1024 * 1024 / (ratio[0] * ratio[1]))
            return round(ratio[value[1]] * scale / multiple) * multiple
    raise ValueError("上游尺寸来源是动态值或不支持静态核实")


def _planning_project(project, prompt, interview_id):
    """Resolve only known static desk dimensions; never execute upstream nodes."""
    if not isinstance(prompt, dict):
        return project
    link = prompt.get(interview_id, {}).get("inputs", {}).get("media_project")
    if not isinstance(link, list) or len(link) != 2:
        return project
    desk = prompt.get(str(link[0]), {})
    if desk.get("class_type") != "ZVUniversalMediaEvidenceDesk" or link[1] != 0:
        return project
    inputs = desk.get("inputs", {})
    if "width" not in inputs and "height" not in inputs:
        return project
    try:
        width = _static_dimension(inputs.get("width"), prompt)
        height = _static_dimension(inputs.get("height"), prompt)
        width, height = _video_target_size(width, height)
    except (ValueError, TypeError, OverflowError, OutletError) as error:
        raise ProjectError([{"path": "/media_project/output_canvas", "code": "canvas_unverified", "message": f"生成画布尚未核实：{error}；请成对连接静态宽高，或取消两条尺寸连接后重新检测"}]) from error
    project["output_canvas"] = {"width": width, "height": height}
    return project


def plan_interview(value, *, prepared_project=None):
    state = copy.deepcopy(value["state"])
    prompt = value.get("prompt")
    interview_id = str(value.get("interview_id", ""))
    has_hub = prompt is not None and any(node.get("class_type") == "ZVH3ReferenceOutlet" and node.get("inputs", {}).get("reference_plan") in ([interview_id, 6], [value.get("interview_id"), 6]) for node in prompt.values())
    wiring = None
    if value.get("align"):
        state["reference_detection"] = None
        state["alignment"] = None
        if prompt is not None and not has_hub:
            wiring = detect_reference_wiring(prompt, interview_id)
            if wiring["conditioning_count"]:
                state["reference_detection"] = detection_snapshot(wiring)
    project = prepared_project if prepared_project is not None else _planning_project(normalize_project(value["media_project"]), prompt, interview_id)
    result = compile_interview(state, project)
    if value.get("align"):
        align_bindings(result["state"], result["inventory"])
        result["state"]["alignment"] = result["alignment_context"]
        result = compile_interview(result["state"], project, confirm_references=True)
    annotate_project_errors(result, project["validation"]["errors"])
    if prompt is not None:
        wiring = validate_reference_hub_wiring(prompt, interview_id) if has_hub else detect_reference_wiring(prompt, interview_id)
        evidence = validate_conditioning_settings(prompt, interview_id, effective_mode=result["validation"]["effective_mode"], has_drive_audio=bool(result["validation"]["counts"]["drive_audio"]), project_frame_count=project["processing_window"]["frame_count"])
        annotate_conditioning(result, project, evidence)
        result["validation"]["errors"].extend(wiring["errors"])
        result["validation"]["ready"] = not result["validation"]["errors"]
    return {key: result[key] for key in ("state", "validation", "alignment_context", "rules", "call_references", "user_prompt", "material_context_json")} | {
        "wiring": wiring,
        "routing_errors": [row for row in result["validation"]["errors"] if row["code"] in {"media_limit", "bank_kind", "audio_duplicate", "soundtrack_pair", "stale_media", "detection_source_missing"}],
        "snapshot": planned_detection(result, conditioning_count=value.get("conditioning_count", 0)),
    }


def register_interview_routes(routes):
    register_preset_routes(routes)
    @routes.post("/zf-prompt-director/h3-interview/plan")
    async def plan(request):
        try:
            value = await request.json()
            project = _planning_project(normalize_project(value["media_project"]), value.get("prompt"), str(value.get("interview_id", "")))
            project = get_store().canonical(project)
            return web.json_response(plan_interview(value, prepared_project=project))
        except (InterviewError, ProjectError) as exc:
            return web.json_response({"errors": getattr(exc, "issues", getattr(exc, "errors", []))}, status=400)
        except (KeyError, TypeError, ValueError):
            return web.json_response({"errors": [{"code": "plan_request", "message": "采访计划请求缺少合法 state/media_project"}]}, status=400)
