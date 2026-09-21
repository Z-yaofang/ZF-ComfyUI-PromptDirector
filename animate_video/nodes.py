"""A finite outer loop around the user's original Animate workflow."""

import json

from ..media_evidence.runtime import get_store
from .plan import default_settings
from .server import prepare_plan
from .execution import complete_run, decode_segment, load_guide, persist_segment, ready_plan, segment_context
from .assembly import assemble_video


def _temp_root():
    import folder_paths
    return folder_paths.get_temp_directory()


def _previous(value):
    if isinstance(value, list):
        if not value:
            return None
        if len(value) != 1:
            raise ValueError("Animate 循环请关闭 accumulate，只传递上一段运行记录")
        return value[0]
    return value


class ZVAnimateSegmentDesk:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_project": ("ZV_MEDIA_PROJECT",),
            "segment_data": ("STRING", {"default": json.dumps(default_settings()), "multiline": True})},
            "optional": {"fps": ("INT,FLOAT", {"forceInput": True})}}

    RETURN_TYPES = ("ZV_ANIMATE_PLAN", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("animate_plan", "segment_count", "fps", "report")
    FUNCTION = "build"
    CATEGORY = "ZV/视频创作/Animate"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def build(self, media_project, segment_data, fps=None):
        plan = ready_plan(prepare_plan(media_project, json.loads(segment_data), fps=fps))
        count = len(plan["segments"])
        mode = "整条遮罩替换" if plan["settings"]["mask_enabled"] else "整条动作迁移"
        return plan, count, float(plan["fps"]), f"{mode}；{count} 段按素材台左右顺序执行，输入片段合计 {plan['target_frame_count']} 帧；补帧与裁回均由原工作流负责，成片以原流实际输出为准。"


class ZVAnimateExecutionEntry:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"animate_plan": ("ZV_ANIMATE_PLAN",), "iteration_index": ("INT", {"forceInput": True})},
            "optional": {"previous_result": ("ZV_ANIMATE_RUN", {"forceInput": True}),
                "width": ("INT", {"forceInput": True, "min": 0}),
                "height": ("INT", {"forceInput": True, "min": 0})}}

    RETURN_TYPES = ("ZV_ANIMATE_CONTEXT", "IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO", "IMAGE", "IMAGE", "FLOAT", "BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("segment_context", "source_frames", "frame_count", "source_audio", "video_info", "reference_image", "transition_video", "fps", "has_transition", "segment_id", "report")
    FUNCTION = "enter"
    CATEGORY = "ZV/视频创作/Animate"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def enter(self, animate_plan, iteration_index, previous_result=None, width=None, height=None):
        plan = ready_plan(animate_plan)
        context = segment_context(plan, iteration_index)
        guide = load_guide(context, _previous(previous_result), _temp_root())
        picture, frames, audio, info = decode_segment(plan, context, get_store(), width, height)
        report = f"第 {iteration_index + 1} 段：原 VHS 加载 {len(frames)} 帧；未补帧、未改切点。"
        report += f"承接上一段成品尾部 {len(guide)} 帧，由 Plus 原生处理。" if guide is not None else "首段或硬切，不接过渡视频。"
        if context["mask_enabled"]:
            task = context["segment"]["mask_task"]
            report += f" 遮罩目标：{task['prompt']}；源帧 {task['source_frame'] + 1} → 本段第 {task['local_index'] + 1} 帧（同素材台，从 1 起；原流前补偏移另计）。"
        return context, frames, len(frames), audio, info, picture, guide, float(context["fps"]), guide is not None, context["segment"]["segment_id"], report


class ZVAnimateSegmentRecorder:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"segment_context": ("ZV_ANIMATE_CONTEXT",), "frames": ("IMAGE",)},
            "optional": {"source_audio": ("AUDIO",), "previous_result": ("ZV_ANIMATE_RUN", {"forceInput": True})}}

    RETURN_TYPES = ("ZV_ANIMATE_RUN", "STRING")
    RETURN_NAMES = ("run_result", "report")
    FUNCTION = "record"
    CATEGORY = "ZV/视频创作/Animate"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def record(self, segment_context, frames, source_audio=None, previous_result=None):
        result = persist_segment(segment_context, frames, source_audio, _previous(previous_result), _temp_root())
        row = result["last_segment"]
        report = f"第 {segment_context['index'] + 1} 段：计划 {row['expected_frame_count']} 帧，原流实际 {row['frames']} 帧，差值 {row['frame_delta']:+d}；已原样落盘，未补/裁视频。"
        if row["frame_delta"]:
            report = "⚠ 帧数差异：" + report
        fit = row["audio_fit"]
        if fit["source_sample_rate"] not in (None, 44100):
            report += f" 原声 {fit['source_sample_rate']} Hz→44100 Hz，未变速。"
        if fit["silent_track"]:
            report += " 本段未启用原声，按实际视频时长输出静音轨。"
        elif fit["trimmed_tail_samples"] or fit["padded_silence_samples"]:
            report += f" 原声尾裁 {fit['trimmed_tail_samples']} 采样，尾补静音 {fit['padded_silence_samples']} 采样（44100 Hz）。"
        return result, report


class ZVAnimateExecutionEnd:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"animate_plan": ("ZV_ANIMATE_PLAN",), "run_result": ("ZV_ANIMATE_RUN",)}}

    RETURN_TYPES = ("VIDEO", "INT", "STRING")
    RETURN_NAMES = ("video", "frame_count", "report")
    FUNCTION = "finish"
    CATEGORY = "ZV/视频创作/Animate"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def finish(self, animate_plan, run_result):
        plan = ready_plan(animate_plan)
        paths, manifest = complete_run(plan, _previous(run_result), _temp_root())
        video = assemble_video(paths, manifest, paths[0].parent / "complete.mp4", plan["fps"])
        count = manifest["actual_frame_count"]
        report = f"已合成 {len(paths)} 段，计划 {plan['target_frame_count']} 帧，实际 {count} 帧 / {count / plan['fps']:.3f} 秒；原流行为未改。"
        differences = [f"第 {index + 1} 段 {row['expected_frame_count']}→{row['frames']}（{row['frame_delta']:+d}）" for index, row in enumerate(manifest["segments"]) if row["frame_delta"]]
        if differences:
            report = "⚠ 帧数差异：" + "；".join(differences) + "。" + report
        trims = sum(row["audio_fit"]["trimmed_tail_samples"] for row in manifest["segments"])
        pads = sum(row["audio_fit"]["padded_silence_samples"] for row in manifest["segments"] if not row["audio_fit"]["silent_track"])
        if trims or pads:
            report += f" 原声合计尾裁 {trims} 采样、尾补静音 {pads} 采样（44100 Hz）；未重复上一段原声。"
        silent = sum(row["audio_fit"]["silent_track"] for row in manifest["segments"])
        if silent:
            report += f" {silent} 段未启用原声，按各段实际视频时长输出静音轨。"
        rates = sorted({row["audio_fit"]["source_sample_rate"] for row in manifest["segments"]} - {None, 44100})
        if rates:
            report += f" 原声 {', '.join(str(rate) for rate in rates)} Hz→44100 Hz，未变速。"
        return video, count, report
