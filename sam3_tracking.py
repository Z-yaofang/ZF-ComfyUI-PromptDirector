"""Render official SAM3 tracks to a disk-backed native VIDEO, without re-tracking.

The consumer is ComfyUI's standard SaveVideo node. Rendering alone deliberately
does not advertise a temporary preview as a downloadable application result.
"""

import colorsys
from fractions import Fraction
import math
from numbers import Integral, Real
import os
from pathlib import Path
import uuid


_COLORS = (
    (0.12, 0.47, 0.71), (1.0, 0.5, 0.05), (0.17, 0.63, 0.17),
    (0.84, 0.15, 0.16), (0.58, 0.4, 0.74), (0.55, 0.34, 0.29),
    (0.89, 0.47, 0.76), (0.5, 0.5, 0.5), (0.74, 0.74, 0.13),
    (0.09, 0.75, 0.81), (0.94, 0.76, 0.06), (0.42, 0.68, 0.84),
)
_DIGITS = (
    ("111", "101", "101", "101", "111"),
    ("010", "110", "010", "010", "111"),
    ("111", "001", "111", "100", "111"),
    ("111", "001", "111", "001", "111"),
    ("101", "101", "111", "001", "001"),
    ("111", "100", "111", "001", "111"),
    ("111", "100", "111", "101", "111"),
    ("111", "001", "010", "010", "010"),
    ("111", "101", "111", "101", "111"),
    ("111", "101", "111", "001", "111"),
)


def _color(index):
    return _COLORS[index] if index < len(_COLORS) else colorsys.hsv_to_rgb(
        (index * 0.618033988749895) % 1.0, 0.75, 0.95)


def _finite_number(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name}必须是有限数值")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}需要在 {minimum} 到 {maximum} 之间")
    return value


def _validate(track_data, images, fps, opacity, label_scale, show_scores):
    import torch

    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError("images 需要非空的 RGB IMAGE 帧批次 [帧数, 高, 宽, 3]")
    if not torch.is_floating_point(images) or min(images.shape[:3]) < 1:
        raise ValueError("images 需要非空的浮点 RGB IMAGE 帧批次")
    if not isinstance(track_data, dict):
        raise ValueError("track_data 需要官方 SAM3_VideoTrack 的跟踪数据")
    count = track_data.get("n_frames")
    if isinstance(count, bool) or not isinstance(count, Integral) or count < 1:
        raise ValueError("跟踪数据的 n_frames 必须是正整数")
    if count != images.shape[0]:
        raise ValueError("跟踪数据与原片帧数不一致，请连接同一次加载的视频帧")
    size = track_data.get("orig_size")
    if not isinstance(size, (tuple, list)) or len(size) != 2 or any(
        isinstance(x, bool) or not isinstance(x, Integral) or x < 1 for x in size
    ):
        raise ValueError("跟踪数据缺少有效的 orig_size")
    if "packed_masks" not in track_data:
        raise ValueError("跟踪数据缺少 packed_masks，请连接官方 SAM3_VideoTrack")
    packed = track_data["packed_masks"]
    objects = 0
    if packed is not None:
        if not isinstance(packed, torch.Tensor) or packed.dtype != torch.uint8 or packed.ndim != 4:
            raise ValueError("packed_masks 需要官方 uint8 位压缩遮罩 [帧数, 对象数, 高, 压缩宽]")
        if packed.shape[0] != count or packed.shape[2] < 1 or packed.shape[3] < 1:
            raise ValueError("位压缩遮罩帧数或尺寸无效")
        objects = packed.shape[1]
    fps = _finite_number(fps, "帧率", 1.0, 240.0)
    opacity = _finite_number(opacity, "遮罩不透明度", 0.0, 1.0)
    if isinstance(label_scale, bool) or not isinstance(label_scale, Integral) or not 0 <= label_scale <= 20:
        raise ValueError("编号字号需要是 0 到 20 的整数；0 为自动")
    if not isinstance(show_scores, bool):
        raise ValueError("show_scores 需要布尔值")
    scores = track_data.get("scores", [])
    if show_scores:
        if not isinstance(scores, (list, tuple)) or len(scores) != objects:
            raise ValueError("显示置信度需要与对象数一致的 scores 列表")
        scores = [_finite_number(value, "置信度", 0.0, 1.0) for value in scores]
    return packed, int(count), int(objects), Fraction(str(fps)).limit_denominator(100000), opacity, int(label_scale), scores


def _draw_number(frame, number, cx, cy, scale):
    """Draw portable bitmap digits on a single float RGB frame, with a black edge."""
    import numpy as np

    text = str(number)
    height, width = frame.shape[:2]
    scale = max(1, min(scale, max(1, height // 5), max(1, width // (4 * len(text) - 1))))
    glyphs = [np.array([[c == "1" for c in row] for row in _DIGITS[int(d)]]) for d in text]
    gap = np.zeros((5, 1), dtype=bool)
    strips = []
    for i, glyph in enumerate(glyphs):
        if i:
            strips.append(gap)
        strips.append(glyph)
    mask = np.repeat(np.repeat(np.concatenate(strips, axis=1), scale, axis=0), scale, axis=1)
    mask_height, mask_width = mask.shape
    left = min(max(0, int(cx) - mask_width // 2), max(0, width - mask_width))
    top = min(max(0, int(cy) - mask_height // 2), max(0, height - mask_height))
    padded = np.pad(mask, 1)
    outline = np.zeros_like(padded)
    for dy in range(3):
        for dx in range(3):
            outline[dy:dy + mask_height, dx:dx + mask_width] |= mask
    for pixels, x, y, color in ((outline, left - 1, top - 1, 0.0), (mask, left, top, 1.0)):
        ph, pw = pixels.shape
        x1, y1, x2, y2 = max(x, 0), max(y, 0), min(x + pw, width), min(y + ph, height)
        if x2 > x1 and y2 > y1:
            frame[y1:y2, x1:x2][pixels[y1 - y:y2 - y, x1 - x:x2 - x]] = color


def _render_frame(image, packed_frame, opacity, label_scale, show_scores, scores):
    """Keep only one frame and one object's expanded mask resident at a time."""
    import numpy as np
    import torch

    frame = image.detach().to(device="cpu", dtype=torch.float32).numpy().copy()
    if not np.isfinite(frame).all():
        raise ValueError("视频帧包含非有限像素，无法编码")
    np.clip(frame, 0.0, 1.0, out=frame)
    height, width = frame.shape[:2]
    labels = []
    if packed_frame is not None and packed_frame.shape[0]:
        mask_height, mask_width = packed_frame.shape[1], packed_frame.shape[2] * 8
        rows = np.arange(height, dtype=np.int64) * mask_height // height
        cols = np.arange(width, dtype=np.int64) * mask_width // width
        claimed = np.zeros((height, width), dtype=bool)
        for index in range(packed_frame.shape[0]):
            packed_object = packed_frame[index].detach().to(device="cpu").numpy()
            bits = np.unpackbits(packed_object, axis=-1, bitorder="little")
            mask = bits[rows[:, None], cols].astype(bool)
            visible = mask & ~claimed
            claimed |= mask
            if not visible.any():
                continue
            frame[visible] = frame[visible] * (1.0 - opacity) + np.asarray(_color(index), dtype=np.float32) * opacity
            yy, xx = np.nonzero(visible)
            labels.append((index, int(xx.mean()), int(yy.mean())))
        scale = label_scale or max(2, height // 240)
        for index, cx, cy in labels:
            _draw_number(frame, index, cx, cy, scale)
            if show_scores:
                _draw_number(frame, int(round(scores[index] * 100)), cx, cy + 5 * scale + 3, max(1, scale * 2 // 3))
    pixels = (frame * 255.0).round().astype(np.uint8)
    if height % 2 or width % 2:
        pixels = np.pad(pixels, ((0, height % 2), (0, width % 2), (0, 0)), mode="edge")
    return pixels


def _check_interruption():
    from comfy.model_management import throw_exception_if_processing_interrupted

    throw_exception_if_processing_interrupted()


def _native_video(path):
    from comfy_api.latest import InputImpl

    return InputImpl.VideoFromFile(str(path))


class ZVSAM3TrackVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "track_data": ("SAM3_TRACK_DATA",),
            "images": ("IMAGE",),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.01}),
            "opacity": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
            "label_scale": ("INT", {"default": 6, "min": 0, "max": 20, "tooltip": "0 为自动；6 约为 30 像素高。"}),
            "show_scores": ("BOOLEAN", {"default": False}),
        }}

    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("video", "report")
    FUNCTION = "render_video"
    CATEGORY = "ZV/视频创作/SAM3"
    DESCRIPTION = "将官方 SAM3 跟踪数据叠到同一批原片帧，保持对象编号；VIDEO 接标准 SaveVideo 导出。"

    def render_video(self, track_data, images, fps=24.0, opacity=0.5, label_scale=6, show_scores=False):
        import av
        import folder_paths

        packed, count, objects, rate, opacity, label_scale, scores = _validate(
            track_data, images, fps, opacity, label_scale, show_scores)
        root = Path(folder_paths.get_temp_directory()).resolve()
        root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        final = root / f"zv_sam3_tracks_{token}.mp4"
        partial = root / f"zv_sam3_tracks_{token}.partial.mp4"
        height, width = images.shape[1:3]
        encoded_height, encoded_width = height + height % 2, width + width % 2
        try:
            with av.open(str(partial), mode="w", format="mp4") as output:
                stream = output.add_stream("libx264", rate=rate)
                stream.width, stream.height, stream.pix_fmt = encoded_width, encoded_height, "yuv420p"
                stream.options = {"crf": "18", "preset": "fast"}
                for index in range(count):
                    _check_interruption()
                    pixels = _render_frame(images[index], None if packed is None else packed[index], opacity, label_scale, show_scores, scores)
                    frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                    frame.pts, frame.time_base = index, Fraction(rate.denominator, rate.numerator)
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            os.replace(partial, final)
            video = _native_video(final)
        except BaseException:
            for owned in (partial, final):
                try:
                    owned.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        padding = f"；右/下边缘补齐为 {encoded_width}×{encoded_height}" if (encoded_width, encoded_height) != (width, height) else ""
        report = (
            f"已生成彩色编号视频：{count} 帧，{width}×{height}，{float(rate):g} fps，"
            f"{objects} 个跟踪槽位，编号与 SAM3 TrackToMask 一致{padding}。"
            "未重新跟踪；无音轨。请将 video 接标准 SaveVideo 保存为应用可导出的 MP4。"
        )
        return video, report
