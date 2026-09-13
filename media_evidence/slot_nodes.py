"""Fixed socket nodes resolve project-owned slots in the forward data path."""
import json

from .contract import ProjectError, normalize_project
from .outlet import OutletError
from .outlet_nodes import _Outlet, _export, ZVPictureOutlet, ZVVideoOutlet, ZVAudioOutlet

NAMES = {"picture": "图片", "video": "视频", "audio": "音频"}


def resolve_slot(media_project, slot_id, kind):
    try:
        project = normalize_project(media_project)
    except ProjectError:
        raise OutletError("素材工程或出口槽位结构无效，请在素材台修正") from None
    slot = next((s for s in project.get("outlet_slots", {}).get("items", []) if s["slot_id"] == slot_id), None)
    if slot is None or slot["kind"] != kind:
        raise OutletError("槽位未指定或类型不符，请在素材台选择对应出口槽位")
    label = f"{NAMES[kind]}{slot['ordinal']}"
    if slot["binding_id"] is None:
        raise OutletError(f"{label} 槽位未指定素材，请选中轨道素材后发送到此槽位")
    key = "item_id" if kind == "picture" else "clip_id"
    item = next((c for c in project[kind + "_track"] if c[key] == slot["binding_id"]), None)
    if item is None:
        raise OutletError(f"{label} 的素材已不存在或类型不符，请重新指定素材")
    if kind == "audio" and item["linked_video_clip_id"]:
        raise OutletError(f"{label} 的音频仍关联视频，请使用视频槽位或先解绑音频")
    return {**slot, "label": label}


class _SlotOutlet(_Outlet):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",), "slot_id": ("STRING", {"default": ""})}}

    def export_media(self, media_project, slot_id):
        slot = resolve_slot(media_project, slot_id, self.KIND)
        result = list(_export(media_project, self.KIND, slot["binding_id"]))
        manifest_index = 2 if self.KIND == "video" else 1
        manifest = json.loads(result[manifest_index])
        manifest["outlet_slot"] = slot
        result[manifest_index] = json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        result[-1] = f"{slot['label']}（{slot_id}）：" + result[-1]
        return tuple(result)


class ZVPictureSlotOutlet(_SlotOutlet):
    KIND = "picture"
    RETURN_TYPES = ZVPictureOutlet.RETURN_TYPES
    RETURN_NAMES = ZVPictureOutlet.RETURN_NAMES


class ZVVideoSlotOutlet(_SlotOutlet):
    KIND = "video"
    RETURN_TYPES = ZVVideoOutlet.RETURN_TYPES
    RETURN_NAMES = ZVVideoOutlet.RETURN_NAMES


class ZVAudioSlotOutlet(_SlotOutlet):
    KIND = "audio"
    RETURN_TYPES = ZVAudioOutlet.RETURN_TYPES
    RETURN_NAMES = ZVAudioOutlet.RETURN_NAMES
