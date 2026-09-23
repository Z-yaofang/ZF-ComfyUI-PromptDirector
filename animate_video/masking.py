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
        return {"required": {"segment_context": ("ZV_ANIMATE_CONTEXT",), "mask": ("MASK",)},
                "optional": {"reference_image": ("IMAGE",)}}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("validated_seed",)
    FUNCTION = "validate"
    CATEGORY = "ZV/视频创作/Animate"

    def validate(self, segment_context, mask, reference_image=None):
        row = segment_context["segment"]
        task = row["mask_task"]
        label = f"第 {row['ordinal']} 段（源帧 {task['source_frame'] + 1}，目标：{task['prompt']}）"
        if mask.ndim not in (2, 3) or (mask.ndim == 3 and len(mask) != 1):
            raise ValueError(f"{label}：SeC 需要单帧种子遮罩，请关闭 SAM 独立遮罩输出或先合并")
        if not torch.isfinite(mask).all().item() or not (mask > .5).any().item():
            raise ValueError(f"{label}：参考帧未得到有效遮罩。请修改目标词、换参考帧或修补遮罩，再运行。")
        if reference_image is not None:
            if (reference_image.ndim != 4 or len(reference_image) != 1
                    or reference_image.shape[-1] not in (3, 4)):
                raise ValueError(f"{label}：遮罩预览需要单张 RGB 或 RGBA 参考帧")
            import nodes
            preview = nodes.NODE_CLASS_MAPPINGS.get("PreviewImage")
            if preview is None:
                raise ValueError("Animate 遮罩预览需要 ComfyUI 的 PreviewImage 节点")
            image = reference_image[..., :3].detach().to(device="cpu", dtype=torch.float32)
            seed = mask.detach().reshape(1, 1, *mask.shape[-2:]).to(device="cpu", dtype=torch.float32)
            if tuple(seed.shape[-2:]) != tuple(image.shape[1:3]):
                seed = torch.nn.functional.interpolate(seed, size=image.shape[1:3], mode="nearest")
            seed = seed.permute(0, 2, 3, 1)
            alpha = seed.clamp(0, 1) * .6
            overlay = image * (1 - alpha)
            overlay[..., 1:2] += alpha
            binary = (seed > .5).to(dtype=image.dtype).expand(-1, -1, -1, 3)
            comparison = torch.cat((image, overlay, binary), dim=2)
            result = preview().save_images(comparison, filename_prefix=f"Animate-mask-seed-{row['ordinal']}")
            return {"ui": result["ui"], "result": (mask,)}
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
            return {"ui": {"gifs": []}, "result": (None, None)}
        if mask is None or bg_images is None:
            raise ValueError(f"第 {segment_context['index'] + 1} 段：遮罩管道缺少遮罩或背景图像，请检查原流接线")
        if mask.ndim != 3 or bg_images.ndim != 4 or tuple(mask.shape) != tuple(bg_images.shape[:3]):
            raise ValueError(f"第 {segment_context['index'] + 1} 段：遮罩帧数/尺寸与原流背景图像不一致")
        import nodes
        preview = nodes.NODE_CLASS_MAPPINGS.get("VHS_VideoCombine")
        if preview is None:
            raise ValueError("Animate 遮罩背景预览需要 VideoHelperSuite 的 VHS_VideoCombine 节点")
        ordinal = segment_context["segment"]["ordinal"]
        result = preview().combine_video(
            images=bg_images, frame_rate=segment_context["fps"], loop_count=0,
            filename_prefix=f"Animate-mask-bg-segment-{ordinal}", format="video/h264-mp4",
            pingpong=False, save_output=False,
        )
        return {"ui": result["ui"], "result": (mask, bg_images)}
