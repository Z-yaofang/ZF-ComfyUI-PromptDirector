import json

from ..media_evidence.contract import ProjectError
from .plan import SegmentPlanError, build_segment_plan, canonical_task_project, default_settings


class ZVLongVideoSegmentDesk:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_project": ("ZV_MEDIA_PROJECT",),
                "segment_data": ("STRING", {"multiline": True, "default": json.dumps(default_settings(), ensure_ascii=False)}),
            },
        }

    RETURN_TYPES = ("ZV_SEGMENT_PLAN", "STRING")
    RETURN_NAMES = ("segment_plan", "report")
    FUNCTION = "build"
    CATEGORY = "ZV/视频创作/H3长视频"

    def build(self, media_project, segment_data):
        try:
            settings = json.loads(segment_data)
            if not isinstance(settings, dict):
                raise SegmentPlanError([{
                    "path": "/settings", "code": "type", "message": "分段设置必须是 JSON 对象",
                }])
            from ..media_evidence.runtime import get_store
            project = canonical_task_project(media_project, get_store())
            if settings.get("source_snapshot") is not None and settings.get("refresh_sources") is not True:
                settings["source_snapshot"] = canonical_task_project(settings["source_snapshot"], get_store())
            plan = build_segment_plan(project, settings)
        except (json.JSONDecodeError, ProjectError, SegmentPlanError, TypeError, UnicodeError) as error:
            from comfy_execution.graph_utils import ExecutionBlocker
            if isinstance(error, SegmentPlanError):
                message = "分段计划无效：" + "；".join(row["message"] for row in error.issues)
            elif isinstance(error, ProjectError):
                message = "分段素材工程无效，请重新导入或刷新素材"
            else:
                message = "分段设置不是有效 JSON 对象"
            blocked = ExecutionBlocker(message)
            return blocked, message
        validation = plan["validation"]
        status = "可执行" if validation["ready"] else "不可执行"
        report = f"长视频分段：{len(plan['segments'])} 段，目标 {plan['target_frame_count']} 帧 / {plan['fps']} fps；请求重叠 {plan['requested_overlap_frames']} 帧，实际 {plan['effective_overlap_frames']} 帧；{status}。"
        if plan["stale"]:
            report += " 上游素材已变化，当前仍使用冻结副本；请显式刷新。"
        if validation["errors"]:
            report += " " + "；".join(row["message"] for row in validation["errors"])
        return plan, report
