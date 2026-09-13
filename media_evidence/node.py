import json
from .contract import ProjectError, empty_project, parse_project
from .original_sources import original_sources
from .outlet import OutletError
from .storage import MediaError


class ZVUniversalMediaEvidenceDesk:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_data": ("STRING", {"multiline": True, "default": json.dumps(empty_project())}),
            },
            "optional": {
                "width": ("INT", {
                    "forceInput": True, "min": 32, "max": 16384, "step": 32,
                    "tooltip": "连接实际生成画布宽度；与高度同时连接后，所有视频素材出口默认在解码时适配该尺寸。",
                }),
                "height": ("INT", {
                    "forceInput": True, "min": 32, "max": 16384, "step": 32,
                    "tooltip": "连接实际生成画布高度；与宽度必须成对连接。",
                }),
            },
        }

    RETURN_TYPES = ("ZV_MEDIA_PROJECT", "STRING", "ZV_ORIGINAL_SOURCES")
    RETURN_NAMES = ("media_project", "project_json", "原素材来源")
    FUNCTION = "export_project"
    CATEGORY = "ZV/视频创作/素材取证"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Files may have changed outside ComfyUI; verify the private registry each run.
        return float("nan")

    def export_project(self, project_data, width=None, height=None):
        from .runtime import get_store
        from .outlet import _video_target_size

        try:
            sources = original_sources(project_data)
        except OutletError as error:
            from comfy_execution.graph_utils import ExecutionBlocker
            sources = ExecutionBlocker(str(error))
        try:
            source = parse_project(project_data)
            if width is not None or height is not None:
                target_width, target_height = _video_target_size(width, height)
                source["output_canvas"] = {"width": target_width, "height": target_height}
            project = get_store().canonical(source)
            return project, json.dumps(project, ensure_ascii=False, allow_nan=False, separators=(",", ":")), sources
        except (ProjectError, OutletError, MediaError, UnicodeError) as error:
            # Core execution is imported after plugin registration to avoid its
            # nodes import cycle; each invalid output is blocked independently.
            from comfy_execution.graph_utils import ExecutionBlocker
            message = str(error)
            if isinstance(error, ProjectError):
                message = '工程无法输出：' + '；'.join(row['message'] for row in error.errors)
            blocked = ExecutionBlocker(message)
            return blocked, blocked, sources
