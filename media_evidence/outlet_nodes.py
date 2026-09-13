"""Small standard ComfyUI outputs bound to stable track item IDs."""

import json

from .contract import ProjectError, normalize_project
from .outlet import OutletError, build_outlet_plan, require_valid_project
from .storage import MediaError


def _export(media_project, kind, binding_id=None, target_width=None, target_height=None):
    from .runtime import get_store
    from .outlet_decode import execute_outlet
    store = get_store()
    try:
        project = store.canonical(media_project)
        require_valid_project(project)
        plan = build_outlet_plan(
            project, kind, binding_id,
            target_width=target_width, target_height=target_height,
        )
        media, original, manifest, report = execute_outlet(store, plan)
    except ProjectError:
        raise OutletError("素材工程结构、处理窗口或目标帧率无效，请先在素材台修正") from None
    except MediaError:
        raise OutletError("素材来源失效或已改变，请在素材台重新导入") from None
    metadata = json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (media, original, metadata, report) if kind == "video" else (media, metadata, report)


class _Outlet:
    CATEGORY = "ZV/视频创作/素材取证"
    FUNCTION = "export_media"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Respect the desk's per-execution registry check, including external edits.
        return float("nan")


class ZVPictureOutlet(_Outlet):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",), "item_id": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "manifest_json", "report")

    def export_media(self, media_project, item_id):
        return _export(media_project, "picture", item_id)


class ZVVideoOutlet(_Outlet):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_project": ("ZV_MEDIA_PROJECT",),
                "clip_id": ("STRING", {"default": ""}),
            },
            "optional": {
                "target_width": ("INT", {
                    "forceInput": True, "min": 32, "max": 16384, "step": 32,
                    "tooltip": "连接生成画布宽度；与高度同时连接后，视频在解码时逐帧适配，避免先构造原尺寸帧批次。",
                }),
                "target_height": ("INT", {
                    "forceInput": True, "min": 32, "max": 16384, "step": 32,
                    "tooltip": "连接生成画布高度；采用保持比例、居中裁切、铺满画布。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("frames", "original_audio", "manifest_json", "report")

    def export_media(self, media_project, clip_id, target_width=None, target_height=None):
        return _export(
            media_project, "video", clip_id,
            target_width=target_width, target_height=target_height,
        )


class ZVAudioOutlet(_Outlet):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",), "clip_id": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("audio", "manifest_json", "report")

    def export_media(self, media_project, clip_id):
        return _export(media_project, "audio", clip_id)


class ZVTimelineAudioOutlet(_Outlet):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",)}}

    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("timeline_audio", "manifest_json", "report")

    def export_media(self, media_project):
        return _export(media_project, "timeline_audio")


class ZVProcessingWindowOutlet(_Outlet):
    """Expose the desk's canonical processing window without decoding media."""

    FUNCTION = "export_window"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",)}}

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "FLOAT", "INT")
    RETURN_NAMES = ("start_seconds", "end_seconds", "duration_seconds", "fps", "frame_count")

    def export_window(self, media_project):
        try:
            project = normalize_project(media_project)
            require_valid_project(project)
        except ProjectError:
            raise OutletError("素材工程结构、处理窗口或目标帧率无效，请先在素材台修正") from None
        window = project["processing_window"]
        start = float(window["start_seconds"])
        end = float(window["end_seconds"])
        return (start, end, end - start, float(window["fps"]), int(window["frame_count"]))
