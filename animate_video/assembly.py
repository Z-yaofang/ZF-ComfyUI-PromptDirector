"""Bounded-memory Animate assembly with an explicit video/audio clock.

Do not use VideoFromList here: some Comfy releases copy source packet durations
into the encoder's different time base, inflating the last frame of a chunk.
"""

from fractions import Fraction
import io
import json
from pathlib import Path
import uuid

import av
import numpy as np
from comfy_api.latest import InputImpl, Types


SAMPLE_RATE = 44100


def encode_video_chunk(images, audio, fps, path):
    """Persist final workflow frames unchanged on their rational frame clock."""
    rate = Fraction(str(fps)).limit_denominator(1_000_000)
    clock = 1 / rate
    waveform = audio["waveform"][0].detach().cpu().float().numpy()
    samples = waveform.shape[-1]
    waveform = np.pad(waveform, ((0, 0), (0, 2048)))
    with av.open(path, "w", format="mp4") as output:
        # Intermediate RGB chunks are lossless after the normal 8-bit conversion.
        # Only the completed movie is encoded to delivery-quality YUV/H264.
        video = output.add_stream("libx264rgb", rate=rate)
        video.width, video.height, video.pix_fmt = images.shape[2], images.shape[1], "rgb24"
        video.time_base = video.codec_context.time_base = clock
        video.codec_context.max_b_frames = 0
        video.options = {"crf": "0", "preset": "medium", "tune": "zerolatency"}
        sound = output.add_stream("aac", rate=SAMPLE_RATE, layout="stereo")
        for index, image in enumerate(images):
            pixels = np.rint(np.clip(image.detach().cpu().float().numpy(), 0, 1) * 255).astype(np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base, frame.duration = index, clock, 1
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode(None):
            output.mux(packet)
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(waveform), format="fltp", layout="stereo")
        frame.sample_rate, frame.pts, frame.time_base = SAMPLE_RATE, 0, Fraction(1, SAMPLE_RATE)
        for packet in sound.encode(frame):
            output.mux(packet)
        for packet in sound.encode(None):
            output.mux(packet)
    with av.open(path) as source:
        stream = source.streams.video[0]
        if stream.average_rate != rate or stream.duration * stream.time_base != len(images) / rate:
            raise ValueError("Animate 分段编码帧时钟不正确")
        encoded_frames = 0
        for frame in source.decode(video=0):
            if frame.pts * frame.time_base != encoded_frames / rate:
                raise ValueError("Animate 分段编码时间戳不连续")
            encoded_frames += 1
    with av.open(path) as source:
        audio_samples = sum(frame.samples for frame in source.decode(audio=0))
    return {"encoded_frame_count": encoded_frames, "fps": float(rate),
            "audio_sample_rate": SAMPLE_RATE, "audio_channels": 2,
            "audio_content_sample_count": samples, "decoded_audio_sample_count": audio_samples}


def _probe(path, frame_count, fps, audio_samples):
    """Validate the encoded clock, including the often overlooked last duration."""
    if isinstance(path, io.BytesIO):
        path.seek(0)
    with av.open(path) as source:
        if len(source.streams.video) != 1 or len(source.streams.audio) != 1:
            raise ValueError("Animate 合并文件必须包含一条视频及一条原声音轨")
        video = source.streams.video[0]
        if video.average_rate != fps or video.duration is None:
            raise ValueError("Animate 合并视频帧率或时长无效")
        if video.duration * video.time_base != Fraction(frame_count, 1) / fps:
            raise ValueError("Animate 合并视频末帧时长不正确")
        count = 0
        for frame in source.decode(video=0):
            if frame.pts is None or frame.pts * frame.time_base != Fraction(count, 1) / fps:
                raise ValueError("Animate 合并视频时间戳不连续")
            count += 1
        if count != frame_count:
            raise ValueError("Animate 合并视频帧数不正确")
    if isinstance(path, io.BytesIO):
        path.seek(0)
    with av.open(path) as source:
        audio = source.streams.audio[0]
        if audio.rate != SAMPLE_RATE or len(audio.layout.channels) != 2:
            raise ValueError("Animate 合并音轨格式不正确")
        samples = 0
        for frame in source.decode(audio=0):
            if frame.pts is None or frame.pts * frame.time_base != Fraction(samples, SAMPLE_RATE):
                raise ValueError("Animate 合并音轨时间戳不连续")
            samples += frame.samples
        if samples < audio_samples or samples > audio_samples + 2048:
            raise ValueError("Animate 合并音轨样本不足或包含多余分段尾音")
    if isinstance(path, io.BytesIO):
        path.seek(0)


def _temporary(target):
    return target.with_name(f".{target.stem}.{uuid.uuid4().hex}.partial.mp4")


def _remux(source_path, target, metadata):
    """Preserve PTS, DTS AND duration in the source stream's clock."""
    with av.open(str(source_path)) as source, av.open(
            target, "w", format="mp4", options={"movflags": "use_metadata_tags"}) as output:
        output.metadata.update(source.metadata)
        for key, value in (metadata or {}).items():
            output.metadata[key] = value if isinstance(value, str) else json.dumps(value)
        streams = {}
        for stream in source.streams:
            if stream.type in {"video", "audio"}:
                copied = output.add_stream_from_template(stream, opaque=True)
                copied.time_base = stream.time_base
                streams[stream.index] = copied
        for packet in source.demux():
            if packet.dts is None or packet.stream.index not in streams:
                continue
            clock = packet.time_base
            pts, dts, duration = packet.pts, packet.dts, packet.duration
            packet.stream = streams[packet.stream.index]
            packet.time_base = clock
            packet.pts, packet.dts, packet.duration = pts, dts, duration
            output.mux(packet)


class AssembledVideo(InputImpl.VideoFromFile):
    """Native lazy VIDEO, with safe default SaveVideo remux and logical audio."""

    def __init__(self, path, frame_count, fps, audio_samples):
        self._animate_path = Path(path)
        self._animate_frames = frame_count
        self._animate_fps = Fraction(str(fps)).limit_denominator(1_000_000)
        self._animate_samples = audio_samples
        super().__init__(str(path))

    def get_components(self):
        components = super().get_components()
        if components.audio is None or components.audio["waveform"].shape[-1] < self._animate_samples:
            raise ValueError("Animate 合并视频原声音轨不足")
        # AAC has codec padding, which is not part of the user's source timeline.
        components.audio["waveform"] = components.audio["waveform"][..., :self._animate_samples]
        return components

    def save_to(self, path, format=Types.VideoContainer.AUTO, codec=Types.VideoCodec.AUTO,
                metadata=None, bit_depth=None, crf=None, color_space=None, preset=None):
        mp4_path = not isinstance(path, (str, Path)) or Path(path).suffix.lower() not in {".mkv", ".webm"}
        if (format not in {Types.VideoContainer.AUTO, Types.VideoContainer.MP4}
                or (format == Types.VideoContainer.AUTO and not mp4_path)
                or codec not in {Types.VideoCodec.AUTO, Types.VideoCodec.H264}
                or bit_depth not in {None, 8} or crf is not None
                or color_space is not None or preset is not None):
            return super().save_to(path, format=format, codec=codec, metadata=metadata,
                                   bit_depth=bit_depth, crf=crf, color_space=color_space, preset=preset)
        if isinstance(path, io.BytesIO):
            _remux(self._animate_path, path, metadata)
            _probe(path, self._animate_frames, self._animate_fps, self._animate_samples)
            return
        target = Path(path)
        partial = _temporary(target)
        try:
            _remux(self._animate_path, str(partial), metadata)
            _probe(str(partial), self._animate_frames, self._animate_fps, self._animate_samples)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


def assemble_video(paths, manifest, output_path, fps):
    """Assemble already-trimmed contributions, retaining one decoded frame at a time."""
    fps = Fraction(str(fps)).limit_denominator(1_000_000)
    rows = manifest["segments"]
    if not rows or len(paths) != len(rows) or Fraction(str(manifest["fps"])).limit_denominator(1_000_000) != fps or fps <= 0:
        raise ValueError("Animate 合并分段清单或帧率不一致")
    frame_count = sum(int(row["frames"]) for row in rows)
    audio_samples = sum(int(row["audio_samples"]) for row in rows)
    if any(int(row["frames"]) < 1 or int(row["audio_samples"]) < 1 for row in rows):
        raise ValueError("Animate 合并分段不能为空")
    height, width, channels = manifest["shape"]
    if channels != 3 or width % 2 or height % 2:
        raise ValueError("Animate 合并画布不符合 H264 尺寸要求")
    target = Path(output_path)
    partial = _temporary(target)
    video_clock = 1 / fps
    audio_clock = Fraction(1, SAMPLE_RATE)
    video_cursor = audio_cursor = 0
    try:
        with av.open(str(partial), "w", format="mp4") as output:
            video = output.add_stream("libx264", rate=fps)
            video.width, video.height, video.pix_fmt = width, height, "yuv420p"
            video.time_base = video.codec_context.time_base = video_clock
            video.codec_context.max_b_frames = 0
            video.options = {"crf": "18", "preset": "medium", "tune": "zerolatency"}
            audio = output.add_stream("aac", rate=SAMPLE_RATE, layout="stereo")
            audio.time_base = audio.codec_context.time_base = audio_clock
            for path, row in zip(paths, rows):
                count = 0
                with av.open(str(path)) as source:
                    for frame in source.decode(video=0):
                        if frame.width != width or frame.height != height:
                            raise ValueError("Animate 分段画布不同，不能隐式缩放合并")
                        frame = frame.reformat(format="yuv420p")
                        frame.pts, frame.time_base = video_cursor, video_clock
                        # Source duration belongs to its muxer time base, NOT ours.
                        frame.duration = 1
                        for packet in video.encode(frame):
                            output.mux(packet)
                        video_cursor += 1
                        count += 1
                if count != int(row["frames"]):
                    raise ValueError("Animate 分段实际帧数与清单不同")
                remaining = int(row["audio_samples"])
                with av.open(str(path)) as source:
                    stream = source.streams.audio[0]
                    if stream.rate != SAMPLE_RATE or len(stream.layout.channels) != 2:
                        raise ValueError("Animate 分段原声必须为 44100 Hz 双声道")
                    for decoded in source.decode(audio=0):
                        size = min(remaining, decoded.samples)
                        if not size:
                            break
                        if decoded.format.name != "fltp":
                            raise ValueError("Animate 分段 AAC 解码格式无效")
                        data = np.ascontiguousarray(decoded.to_ndarray()[:, :size])
                        frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
                        frame.sample_rate = SAMPLE_RATE
                        frame.pts, frame.time_base = audio_cursor, audio_clock
                        for packet in audio.encode(frame):
                            output.mux(packet)
                        audio_cursor += size
                        remaining -= size
                        if not remaining:
                            break
                if remaining:
                    raise ValueError("Animate 分段原声音轨短于有效源样本")
            for packet in video.encode(None):
                output.mux(packet)
            for packet in audio.encode(None):
                output.mux(packet)
        _probe(str(partial), frame_count, fps, audio_samples)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return AssembledVideo(target, frame_count, fps, audio_samples)
