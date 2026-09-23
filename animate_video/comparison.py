"""Render an optional whole-film source/result comparison after the Animate loop.

The original VHS comparison (#109) operated on the *current* loop segment.  This
node reads the completed segment files and source clips one frame at a time, so
it cannot cause SAM, SeC, or the sampler to run again and does not retain a
second batch of full-resolution images in memory.
"""

from contextlib import closing
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import av
import numpy as np

from ..media_evidence.runtime import get_store
from .assembly import AssembledVideo, SAMPLE_RATE, _probe, _temporary
from .execution import _hash, _run_dir, complete_run, ready_plan
from .plan import same_frame_rate


@lru_cache(maxsize=1)
def _opencv():
    """Keep OpenCV optional at plugin registration time on cloud hosts."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Animate 完整对照需要 OpenCV；请在运行环境安装 opencv-python") from exc
    return cv2


def _source_frames(path, start, count, source_rate, target_rate):
    """Match VHS_LoadVideo's OpenCV frame selection without making an IMAGE batch."""
    cv2 = _opencv()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened() or not capture.grab():
            raise ValueError(f"Animate 对照原视频无法读取：{path}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError(f"Animate 对照原视频帧率无效：{path}")
        base_time = 1 / fps
        target_time = base_time if same_frame_rate(source_rate, target_rate) else 1 / float(target_rate)
        time_offset = target_time
        considered = produced = 0
        while capture.isOpened() and produced < count:
            if time_offset < target_time:
                if not capture.grab():
                    break
                time_offset += base_time
            if time_offset < target_time:
                continue
            time_offset -= target_time
            considered += 1
            if considered <= start:
                continue
            ok, frame = capture.retrieve()
            if not ok:
                break
            produced += 1
            yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if produced != count:
            raise ValueError(f"Animate 对照原视频只读到 {produced}/{count} 帧：{path}")
    finally:
        capture.release()


def _fit_source(frame, width, height):
    """Fit source into the fixed generated canvas, preserving its aspect ratio."""
    cv2 = _opencv()
    source_height, source_width = frame.shape[:2]
    scale = min(width / source_width, height / source_height)
    fitted_width = max(1, min(width, round(source_width * scale)))
    fitted_height = max(1, min(height, round(source_height * scale)))
    if (fitted_width, fitted_height) != (source_width, source_height):
        method = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
        frame = cv2.resize(frame, (fitted_width, fitted_height), interpolation=method)
    panel = np.zeros((height, width, 3), dtype=np.uint8)
    x, y = (width - fitted_width) // 2, (height - fitted_height) // 2
    panel[y:y + fitted_height, x:x + fitted_width] = frame
    return panel


def render_comparison(paths, manifest, plan, completed_video, output_path, resolve_source):
    """Create one VIDEO with source on the left/top, result on the right/bottom.

    The generated film's actual frame clock is authoritative.  A short segment
    omits only that segment's original tail from the comparison; a long segment
    repeats only its own last original frame.  These adjustments never touch
    the separately saved generated film or move any later segment boundary.
    """
    if not isinstance(completed_video, AssembledVideo):
        raise ValueError("Animate 对照必须接完整合成节点的 VIDEO，不能接逐段输出")
    expected_path = (Path(paths[0]).parent / "complete.mp4").resolve()
    completed_path = completed_video._animate_path.resolve()
    fps = Fraction(str(plan["fps"])).limit_denominator(1_000_000)
    frame_count = sum(int(row["frames"]) for row in manifest["segments"])
    audio_samples = sum(int(row["audio_samples"]) for row in manifest["segments"])
    if (completed_path != expected_path or not completed_path.is_file()
            or completed_video._animate_frames != frame_count
            or completed_video._animate_fps != fps
            or completed_video._animate_samples != audio_samples):
        raise ValueError("Animate 对照输入不是本次运行的完整成片")
    height, width, channels = manifest["shape"]
    if channels != 3 or width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("Animate 对照成片画布必须是偶数尺寸 RGB")
    direction = "左右" if width <= height else "上下"
    out_width, out_height = (width * 2, height) if direction == "左右" else (width, height * 2)
    if out_width > 16384 or out_height > 16384:
        raise ValueError("Animate 对照画布超过 16384 像素，无法编码")
    assets = {row["asset_id"]: row for row in plan["media_project"]["assets"]}
    target = Path(output_path)
    partial = _temporary(target)
    video_clock = 1 / fps
    audio_clock = Fraction(1, SAMPLE_RATE)
    frame_cursor = audio_cursor = 0
    notes = []
    try:
        with av.open(str(partial), "w", format="mp4") as output:
            video = output.add_stream("libx264", rate=fps)
            video.width, video.height, video.pix_fmt = out_width, out_height, "yuv420p"
            video.time_base = video.codec_context.time_base = video_clock
            video.codec_context.max_b_frames = 0
            video.options = {"crf": "19", "preset": "fast", "tune": "zerolatency"}
            sound = output.add_stream("aac", rate=SAMPLE_RATE, layout="stereo")
            sound.time_base = sound.codec_context.time_base = audio_clock
            for index, (path, produced_row, source_row) in enumerate(zip(paths, manifest["segments"], plan["segments"])):
                expected = int(source_row["frame_count"])
                actual = int(produced_row["frames"])
                asset = assets[source_row["video_asset_id"]]
                source_path = resolve_source(asset["source_handle"])
                original = _source_frames(source_path, int(source_row["load_start_frame"]),
                                          min(expected, actual), asset["probe"].get("fps"), fps)
                last_source = None
                with closing(original), av.open(str(path)) as generated:
                    produced = 0
                    for generated_frame in generated.decode(video=0):
                        if produced >= actual:
                            raise ValueError(f"Animate 第 {index + 1} 段对照成品帧数超过清单")
                        if produced < expected:
                            last_source = next(original)
                        elif last_source is None:
                            raise ValueError(f"Animate 第 {index + 1} 段没有可供对照的原帧")
                        source_panel = _fit_source(last_source, width, height)
                        result_panel = generated_frame.to_ndarray(format="rgb24")
                        if result_panel.shape != (height, width, 3):
                            raise ValueError(f"Animate 第 {index + 1} 段成品画布与清单不同")
                        panels = (source_panel, result_panel)
                        image = np.concatenate(panels, axis=1 if direction == "左右" else 0)
                        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                        frame.pts, frame.time_base, frame.duration = frame_cursor, video_clock, 1
                        for packet in video.encode(frame):
                            output.mux(packet)
                        frame_cursor += 1
                        produced += 1
                    if produced != actual:
                        raise ValueError(f"Animate 第 {index + 1} 段对照成品只读到 {produced}/{actual} 帧")
                if actual < expected:
                    notes.append(f"第 {index + 1} 段原素材尾部少显示 {expected - actual} 帧")
                elif actual > expected:
                    notes.append(f"第 {index + 1} 段原素材尾帧重复 {actual - expected} 帧")
            for packet in video.encode(None):
                output.mux(packet)
            remaining = audio_samples
            with av.open(str(completed_path)) as complete:
                source_audio = complete.streams.audio[0]
                if source_audio.rate != SAMPLE_RATE or len(source_audio.layout.channels) != 2:
                    raise ValueError("Animate 完整成片原声不是 44100 Hz 双声道")
                for decoded in complete.decode(audio=0):
                    size = min(remaining, decoded.samples)
                    if not size:
                        break
                    if decoded.format.name != "fltp":
                        raise ValueError("Animate 完整成片原声 AAC 解码格式无效")
                    data = np.ascontiguousarray(decoded.to_ndarray()[:, :size])
                    frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
                    frame.sample_rate = SAMPLE_RATE
                    frame.pts, frame.time_base = audio_cursor, audio_clock
                    for packet in sound.encode(frame):
                        output.mux(packet)
                    audio_cursor += size
                    remaining -= size
                    if not remaining:
                        break
            if remaining:
                raise ValueError("Animate 完整成片原声短于对照时长")
            for packet in sound.encode(None):
                output.mux(packet)
        if frame_cursor != frame_count or audio_cursor != audio_samples:
            raise ValueError("Animate 对照帧数或原声长度与完整成片不一致")
        _probe(str(partial), frame_count, fps, audio_samples)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    detail = "；".join(notes) if notes else "各段原素材帧数与成片一致"
    report = (f"完整对照 {frame_count} 帧 / {float(frame_count / fps):.3f} 秒，{direction}排列；"
              "左侧/上方原素材等比适配成片画布（必要时留黑边），右侧/下方真实成片；"
              f"原声仅来自完整成片一次。{detail}。")
    return AssembledVideo(target, frame_count, fps, audio_samples), report


class ZVAnimateFinalComparison:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"animate_plan": ("ZV_ANIMATE_PLAN",),
                             "video": ("VIDEO",)}}

    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("comparison_video", "report")
    FUNCTION = "compare"
    CATEGORY = "ZV/视频创作/Animate"

    def compare(self, animate_plan, video):
        plan = ready_plan(animate_plan)
        if not isinstance(video, AssembledVideo):
            raise ValueError("Animate 对照必须接完整合成节点的 VIDEO")
        completed_path = video._animate_path.resolve()
        manifest_path = completed_path.parent / "manifest.json"
        if completed_path.name != "complete.mp4" or not manifest_path.is_file():
            raise ValueError("Animate 对照成片没有对应的运行清单")
        run_id = completed_path.parent.name
        if completed_path.parent != _run_dir(self._temp_root(), run_id):
            raise ValueError("Animate 对照成片不在本次运行目录")
        result = {"schema_version": 1, "run_id": run_id,
                  "plan_fingerprint": plan["plan_fingerprint"],
                  "completed_count": len(plan["segments"]),
                  "manifest_sha256": _hash(manifest_path)}
        paths, manifest = complete_run(plan, result, self._temp_root())
        completed = paths[0].parent / "comparison.mp4"
        store = get_store()

        def source_path(handle):
            store.record(handle)  # Reject a source replaced since the material desk ran.
            return store.resolve(handle)

        result, report = render_comparison(paths, manifest, plan, video, completed, source_path)
        return {"ui": {"text": [report]}, "result": (result, report)}

    @staticmethod
    def _temp_root():
        import folder_paths
        return folder_paths.get_temp_directory()
