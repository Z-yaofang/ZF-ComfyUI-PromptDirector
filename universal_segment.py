import json

from comfy_execution.graph import ExecutionBlocker

from .animate_video.nodes import ZVAnimateSegmentDesk
from .animate_video.plan import default_settings as animate_settings
from .long_video.plan import default_settings as h3_settings
from .long_video.plan_node import ZVLongVideoSegmentDesk


def default_settings():
    return {"schema_version": 1, "h3": h3_settings(), "animate": animate_settings()}


class ZVUniversalSegmentDesk:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "media_project": ("ZV_MEDIA_PROJECT",),
            "target_mode": (["H3", "Animate"], {"default": "H3"}),
            "segment_data": ("STRING", {"multiline": True, "default": json.dumps(default_settings(), ensure_ascii=False)}),
        }, "optional": {"fps": ("INT,FLOAT", {"forceInput": True})}}

    RETURN_TYPES = ("ZV_SEGMENT_PLAN", "STRING", "ZV_ANIMATE_PLAN", "INT", "FLOAT")
    RETURN_NAMES = ("segment_plan", "report", "animate_plan", "segment_count", "fps")
    FUNCTION = "build"
    CATEGORY = "ZV/视频创作/分段"

    @classmethod
    def IS_CHANGED(cls, target_mode="H3", **_kwargs):
        return float("nan")

    def build(self, media_project, target_mode, segment_data, fps=None):
        if target_mode not in ("H3", "Animate"):
            raise ValueError("请选择 H3 或 Animate 分段模式")
        try:
            settings = json.loads(segment_data)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("通用分段设置不是有效 JSON 对象") from error
        if not isinstance(settings, dict):
            raise ValueError("通用分段设置必须是 JSON 对象")
        if "h3" in settings or "animate" in settings:
            if settings.get("schema_version") != 1 or not isinstance(settings.get(target_mode.lower()), dict):
                raise ValueError("通用分段设置版本或当前模式配置无效")
            settings = settings[target_mode.lower()]
        if target_mode == "H3":
            plan, report = ZVLongVideoSegmentDesk().build(media_project, json.dumps(settings, ensure_ascii=False))
            if not isinstance(plan, dict):
                return plan, report, ExecutionBlocker("当前 H3 分段计划不可用"), 0, 0.0
            return plan, report, ExecutionBlocker("当前选择 H3，请勿连接 Animate 计划输出"), len(plan["segments"]), float(plan["fps"])
        plan, count, rate, report = ZVAnimateSegmentDesk().build(media_project, json.dumps(settings, ensure_ascii=False), fps=fps)
        return ExecutionBlocker("当前选择 Animate，请勿连接 H3 计划输出"), report, plan, count, rate
