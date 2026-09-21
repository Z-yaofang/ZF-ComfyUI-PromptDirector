"""Bind mask annotations to authored clips and lazily select the original mask path."""

import torch


class ZVAnimateMaskFrame:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"segment_context": ("ZV_ANIMATE_CONTEXT",), "frames": ("IMAGE",),
                             "front_padding": ("INT", {"forceInput": True})}}

    RETURN_TYPES = ("INT", "STRING")
    RETURN_NAMES = ("annotation_frame_idx", "mask_prompt")
    FUNCTION = "align"
    CATEGORY = "ZV/视频创作/Animate"

    def align(self, segment_context, frames, front_padding):
        row = segment_context["segment"]
        task = row["mask_task"]
        label = f"第 {row['ordinal']} 段"
        if not segment_context["mask_enabled"] or task is None:
            raise ValueError(f"{label}：遮罩管道未开启或尚未填写")
        if task["asset_id"] != row["video_asset_id"]:
            raise ValueError(f"{label}：参考帧不属于当前视频，请重新填写")
        local = task["local_index"]
        if type(front_padding) is not int or front_padding < 0 or not 0 <= local < row["frame_count"]:
            raise ValueError(f"{label}：遮罩参考帧或原流前补帧数无效")
        index = front_padding + local
        if frames.ndim != 4 or len(frames) < front_padding + row["frame_count"] or index >= len(frames):
            raise ValueError(f"{label}：原流图像批次无法对齐源帧 {task['source_frame'] + 1}，请检查前补帧接线")
        # Plus adds its transition canvas later, after SAM/SeC. Only use original pre-padding here.
        return index, task["prompt"]


class ZVAnimateMaskSeed:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"segment_context": ("ZV_ANIMATE_CONTEXT",), "mask": ("MASK",)}}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("validated_seed",)
    FUNCTION = "validate"
    CATEGORY = "ZV/视频创作/Animate"

    def validate(self, segment_context, mask):
        row = segment_context["segment"]
        task = row["mask_task"]
        label = f"第 {row['ordinal']} 段（源帧 {task['source_frame'] + 1}，目标：{task['prompt']}）"
        if mask.ndim not in (2, 3) or (mask.ndim == 3 and len(mask) != 1):
            raise ValueError(f"{label}：SeC 需要单帧种子遮罩，请关闭 SAM 独立遮罩输出或先合并")
        if not torch.isfinite(mask).all().item() or not (mask > .5).any().item():
            raise ValueError(f"{label}：参考帧未得到有效遮罩。请修改目标词、换参考帧或修补遮罩，再运行。")
        return (mask,)


class ZVAnimateMaskGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"segment_context": ("ZV_ANIMATE_CONTEXT",),
                             "mask": ("MASK", {"lazy": True}),
                             "bg_images": ("IMAGE", {"lazy": True})}}

    RETURN_TYPES = ("MASK", "IMAGE")
    RETURN_NAMES = ("mask", "bg_images")
    FUNCTION = "route"
    CATEGORY = "ZV/视频创作/Animate"

    def check_lazy_status(self, segment_context, mask=None, bg_images=None):
        if not segment_context["mask_enabled"]:
            return []
        return [name for name, value in (("mask", mask), ("bg_images", bg_images)) if value is None]

    def route(self, segment_context, mask=None, bg_images=None):
        if not segment_context["mask_enabled"]:
            return None, None
        if mask is None or bg_images is None:
            raise ValueError(f"第 {segment_context['index'] + 1} 段：遮罩管道缺少遮罩或背景图像，请检查原流接线")
        if mask.ndim != 3 or bg_images.ndim != 4 or tuple(mask.shape) != tuple(bg_images.shape[:3]):
            raise ValueError(f"第 {segment_context['index'] + 1} 段：遮罩帧数/尺寸与原流背景图像不一致")
        return mask, bg_images
