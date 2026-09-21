"""ComfyUI nodes for the finite, disk-backed long-video execution chain."""

from fractions import Fraction
import io

from .execution import execution_count, normalize_execution_plan, segment_context
from .stitch import (
    OUTPUT_AUDIO_CHANNELS,
    OUTPUT_AUDIO_SAMPLE_RATE,
    build_mask_runtime_evidence,
    contribution_paths,
    load_previous_guide,
    persist_segment,
    validate_complete_run,
)


def _previous(value):
    if value is None or value == [] or value == [None]:
        return None
    return value


def _temp_root():
    import folder_paths
    return folder_paths.get_temp_directory()


def _native_encoder(images, audio, fps, path):
    from comfy_api.latest import InputImpl, Types
    import av

    components = Types.VideoComponents(images=images, audio=None, frame_rate=Fraction(fps))
    video = InputImpl.VideoFromComponents(components, bit_depth=8, color_space="sRGB")
    if audio is None:
        video.save_to(path, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
    else:
        # AAC packetization can decode a few samples short for some exact H3
        # frame windows (for example 85 frames at 48 kHz). Encode a bounded
        # silent guard after the logical contribution so every chunk decodes
        # to at least its exact timeline sample count. VideoFromList trims the
        # concatenated audio back to the final video duration.
        import torch

        buffer = io.BytesIO()
        video.save_to(buffer, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
        buffer.seek(0)
        waveform = audio["waveform"][0].detach().to(device="cpu", dtype=torch.float32).contiguous()
        waveform = torch.nn.functional.pad(waveform, (0, 2048))
        sample_rate = int(audio["sample_rate"])
        layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(waveform.shape[0], "stereo")
        with av.open(buffer) as source, av.open(path, mode="w", format="mp4") as output:
            source_video = source.streams.video[0]
            output_video = output.add_stream_from_template(source_video, opaque=True)
            output_audio = output.add_stream("aac", rate=sample_rate, layout=layout)
            for packet in source.demux(source_video):
                if packet.dts is None:
                    continue
                packet.stream = output_video
                output.mux(packet)
            frame = av.AudioFrame.from_ndarray(waveform.numpy(), format="fltp", layout=layout)
            frame.sample_rate = sample_rate
            frame.pts = 0
            frame.time_base = Fraction(1, sample_rate)
            output.mux(output_audio.encode(frame))
            output.mux(output_audio.encode(None))
    with av.open(path) as container:
        stream = container.streams.video[0]
        encoded_frame_count = sum(1 for _frame in container.decode(stream))
        encoded_fps = stream.average_rate or stream.guessed_rate
    audio_sample_rate = audio_sample_count = audio_channels = None
    with av.open(path) as container:
        if container.streams.audio:
            stream = container.streams.audio[0]
            audio_sample_rate = int(stream.rate)
            audio_channels = len(stream.layout.channels)
            audio_sample_count = sum(frame.samples for frame in container.decode(stream))
    probe = {
        "encoded_frame_count": encoded_frame_count,
        "fps": int(encoded_fps) if encoded_fps.denominator == 1 else float(encoded_fps),
        "audio_sample_rate": audio_sample_rate,
        "audio_content_sample_count": int(audio["waveform"].shape[-1]) if audio is not None else None,
        "decoded_audio_sample_count": audio_sample_count,
        "audio_padding_samples": audio_sample_count - int(audio["waveform"].shape[-1]) if audio is not None and audio_sample_count is not None else None,
        "audio_channels": audio_channels,
    }
    return probe


class ZVLongVideoExecutionSetup:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"execution_plan": ("ZV_SEGMENT_EXECUTION_PLAN",)}}

    RETURN_TYPES = ("INT", "STRING")
    RETURN_NAMES = ("segment_count", "report")
    FUNCTION = "setup"
    CATEGORY = "ZV/视频创作/H3长视频"

    def setup(self, execution_plan):
        count = execution_count(execution_plan)
        return count, (
            f"长视频执行计划已冻结：{count} 段；录制统一为 "
            f"{OUTPUT_AUDIO_SAMPLE_RATE} Hz/{OUTPUT_AUDIO_CHANNELS} ch，缺失音频按帧时钟补静音。"
            "Start Loop 请关闭迭代缓存。"
        )


class ZVLongVideoExecutionEntry:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "execution_plan": ("ZV_SEGMENT_EXECUTION_PLAN",),
                "iteration_index": ("INT", {"forceInput": True}),
            },
            "optional": {"previous_result": ("ZV_LONG_VIDEO_RUN", {"forceInput": True})},
        }

    RETURN_TYPES = (
        "ZV_SEGMENT_EXECUTION_CONTEXT", "ZV_H3_REFERENCE_PLAN", "STRING", "STRING",
        "FLOAT", "INT", "INT", "STRING", "BOOLEAN", "IMAGE", "AUDIO", "INT", "STRING", "STRING",
    )
    RETURN_NAMES = (
        "segment_context", "reference_plan", "user_prompt", "material_context_json",
        "duration_seconds", "frame_count", "model_length", "model_adapter", "has_guide", "guide_frames",
        "guide_audio", "guide_frame_idx", "segment_id", "report",
    )
    FUNCTION = "enter"
    CATEGORY = "ZV/视频创作/H3长视频"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def enter(self, execution_plan, iteration_index, previous_result=None):
        context = segment_context(execution_plan, iteration_index)
        frames, audio = load_previous_guide(context, _previous(previous_result), _temp_root())
        has_guide = context["incoming_guide"] is not None
        if has_guide != (frames is not None):
            raise ValueError("guide 计划与落盘结果不一致")
        report = f"第 {context['order']}/{context['segment_count']} 段：请求 {context['frame_count']} 帧，H3 模型长度 {context['model_length']} 帧"
        report += f"；已从磁盘读取 {context['incoming_guide']['frame_count']} 帧 guide。" if has_guide else "；首段或硬切，不使用 guide。"
        return (
            context, context["reference_plan"], context["user_prompt"], context["material_context_json"],
            context["duration_seconds"],
            context["frame_count"], context["model_length"], context["model_adapter"], has_guide,
            frames, audio, context["incoming_guide"]["frame_idx"] if has_guide else 0,
            context["segment_id"], report,
        )


class ZVLongVideoSegmentRecorder:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segment_context": ("ZV_SEGMENT_EXECUTION_CONTEXT",),
                "frames": ("IMAGE",),
            },
            "optional": {
                "generated_audio": ("AUDIO",),
                "final_audio": ("AUDIO",),
                "previous_result": ("ZV_LONG_VIDEO_RUN", {"forceInput": True}),
                "guide_application_note": ("STRING", {"default": ""}),
                "mask_source_evidence": ("STRING", {"default": ""}),
                "mask_high_evidence": ("STRING", {"default": ""}),
                "mask_compose_evidence": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("ZV_LONG_VIDEO_RUN", "STRING")
    RETURN_NAMES = ("run_result", "report")
    FUNCTION = "record"
    CATEGORY = "ZV/视频创作/H3长视频"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def record(
        self,
        segment_context,
        frames,
        generated_audio=None,
        final_audio=None,
        previous_result=None,
        guide_application_note="",
        mask_source_evidence="",
        mask_high_evidence="",
        mask_compose_evidence="",
    ):
        audio = final_audio if final_audio is not None else generated_audio
        mask_runtime = build_mask_runtime_evidence(
            segment_context,
            mask_source_evidence,
            mask_high_evidence,
            mask_compose_evidence,
        )
        result = persist_segment(
            segment_context, frames, audio, _previous(previous_result), _temp_root(), _native_encoder,
            guide_application_evidence=guide_application_note,
            mask_runtime_evidence=mask_runtime,
        )
        selected = (
            "final_audio 内容优先"
            if final_audio is not None
            else "generated_audio"
            if generated_audio is not None
            else "同步静音"
        )
        audio_entry = result["results"][-1]
        contract = (
            f"{audio_entry['audio_sample_rate']} Hz/"
            f"{audio_entry['audio_channels']} ch"
        )
        status = result["results"][-1]["guide_application"]["status"]
        return result, (
            f"第 {segment_context['order']} 段已精确裁切并落盘；音频：{selected}，"
            f"已按全局帧时钟归一为 {contract}；guide 状态：{status}。"
        )


class ZVLongVideoExecutionEnd:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "execution_plan": ("ZV_SEGMENT_EXECUTION_PLAN",),
            "run_result": ("ZV_LONG_VIDEO_RUN",),
        }}

    RETURN_TYPES = ("VIDEO", "INT", "STRING")
    RETURN_NAMES = ("video", "frame_count", "report")
    FUNCTION = "finish"
    CATEGORY = "ZV/视频创作/H3长视频"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def finish(self, execution_plan, run_result):
        from comfy_api.latest import InputImpl, Types

        plan = normalize_execution_plan(execution_plan)
        manifest = validate_complete_run(plan, run_result, _temp_root())
        paths = contribution_paths(plan, manifest, _temp_root())
        fps = plan["segment_plan"]["fps"]
        chunks = []
        for path, row in zip(paths, manifest["results"]):
            if row["has_audio"]:
                rate = row["audio_sample_rate"]
                samples = (
                    round(row["output_end_frame"] * rate / fps)
                    - round(row["output_start_frame"] * rate / fps)
                )
                # VideoFromFile trims decoded audio with int(duration * rate).
                # Express the global rounded sample interval directly and add
                # a sub-sample guard against binary-float underflow. The value
                # remains far inside the adjacent video-frame boundary.
                duration = (samples + 0.25) / rate
            else:
                duration = row["contribution_frames"] / fps
            chunks.append(InputImpl.VideoFromFile(path, duration=duration))
        video = InputImpl.VideoFromList(chunks, codec=Types.VideoCodec.AUTO)
        target = plan["segment_plan"]["target_frame_count"]
        pending = sum(row["guide_application"]["status"] != "not_required" for row in manifest["results"])
        report = f"长视频已按 {len(paths)} 个磁盘分段精确拼接为 {target} 帧 native VIDEO。"
        if pending:
            report += f" {pending} 个 guide 接缝仅记录了声明，外接 AddGuide 的实际应用以工作流接线/GPU复验为准。"
        return video, target, report


__all__ = [
    "ZVLongVideoExecutionEnd", "ZVLongVideoExecutionEntry", "ZVLongVideoExecutionSetup",
    "ZVLongVideoSegmentRecorder",
]
