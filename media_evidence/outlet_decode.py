"""Bounded local decoding for standard IMAGE/AUDIO outlets; no model policy."""
from bisect import bisect_right
import copy
import math
import time

from .contract import seconds_to_frame, source_message
from .outlet import MAX_OUTPUT_BYTES, MAX_OUTPUT_GIB, MAX_OUTPUT_SECONDS, MAX_VIDEO_FRAMES, SAMPLE_RATE, OutletError
from .storage import FORMATS, MediaError

MAX_AUDIO_SECONDS = MAX_OUTPUT_SECONDS
MAX_DECODE_FRAMES = 250000
MAX_DECODE_PACKETS = 500000
MAX_DECODE_SECONDS = 120
MANIFEST_FIELDS = (
    "kind", "label", "item_id", "clip_id", "asset_id", "source_handle",
    "project_window", "source_window", "requested_source_window", "target_fps",
    "frame_count", "sample_rate", "sample_count", "output_duration_seconds",
    "source_duration_seconds", "source_width", "source_height", "output_width", "output_height",
    "resize_during_decode", "resize_method", "fit_mode", "source_channels", "source_vfr",
)


def sample_pts_indices(timestamps, start_seconds, target_fps, frame_count):
    """Select the last frame at/before each CFR target, using true source PTS."""
    if not timestamps or any(type(stamp) not in (int, float) or not math.isfinite(stamp) for stamp in timestamps):
        raise OutletError("视频缺少有效 PTS，无法按真实时间采样。")
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        raise OutletError("视频 PTS 倒序，无法按真实时间采样。")
    if not math.isfinite(start_seconds) or not 0 < target_fps <= 240 or not 0 < frame_count <= MAX_VIDEO_FRAMES:
        raise OutletError("视频出口的目标帧率或帧数无效。")
    return [max(0, bisect_right(timestamps, start_seconds + index / target_fps + 1e-9) - 1) for index in range(frame_count)]


class _Budget:
    def __init__(self):
        self.started = time.monotonic()
        self.bytes = 0
        self.frames = 0
        self.packets = 0

    def check(self):
        if time.monotonic() - self.started > MAX_DECODE_SECONDS:
            raise OutletError("素材出口解码超过 120 秒，请缩短处理窗口。")

    def reserve(self, size):
        self.check()
        if size < 0 or self.bytes + size > MAX_OUTPUT_BYTES:
            raise OutletError(
                f"素材出口超过 {MAX_OUTPUT_GIB} GiB 内存上限，"
                "请缩短窗口或降低分辨率。"
            )
        self.bytes += size


def _frames(container, stream, budget):
    for packet in container.demux(stream):
        budget.check()
        budget.packets += 1
        if budget.packets > MAX_DECODE_PACKETS:
            raise OutletError("素材出口扫描的数据包过多，请缩短处理窗口。")
        for frame in packet.decode():
            budget.check()
            budget.frames += 1
            if budget.frames > MAX_DECODE_FRAMES:
                raise OutletError("素材出口扫描的帧数过多，请缩短处理窗口。")
            yield frame


def _source(store, entry, kind):
    try:
        facts = store.record(entry["source_handle"])
        source = store.resolve(entry["source_handle"])
    except MediaError as error:
        detail = source_message(error.message, "素材来源已失效、被修改或不可访问，请重新导入")
        raise OutletError("素材来源校验失败：" + detail) from None
    if kind == "audio":
        valid = facts["kind"] in {"audio", "video"} and facts["probe"]["has_audio"]
    else:
        valid = facts["kind"] == kind
    if not valid:
        raise OutletError("绑定素材的媒体种类不匹配，请检查出口绑定。")
    return source


def _verify_unchanged(store, entry):
    try:
        store.record(entry["source_handle"])
    except MediaError as error:
        detail = source_message(error.message, "素材在解码时已被修改或移除，请重新导入")
        raise OutletError("素材解码后校验失败：" + detail) from None


def _manifest_entry(entry):
    result = {key: copy.deepcopy(entry[key]) for key in MANIFEST_FIELDS if key in entry}
    result.update(estimated=False, zero_padded=False, zero_padding_samples=0)
    return result


def _media_origin(container):
    # One origin for all streams retains audio/video offsets within the source.
    if container.start_time is not None:
        return float(container.start_time) / 1000000
    starts = [float(stream.start_time * stream.time_base) for stream in container.streams if stream.start_time is not None and stream.time_base is not None]
    return min(starts) if starts else 0.0


def _stamp(frame, origin, media_name):
    if frame.pts is None or frame.time_base is None:
        raise OutletError(f"{media_name}缺少 PTS，不能用平均帧率或连续样本假定替代。")
    stamp = float(frame.pts * frame.time_base) - origin
    if not math.isfinite(stamp):
        raise OutletError(f"{media_name}的 PTS 无效。")
    return stamp


def _seek(container, stream, absolute_seconds):
    if stream.time_base is None:
        raise OutletError("媒体流缺少时间基，无法准确定位源窗口。")
    target = math.floor(absolute_seconds / float(stream.time_base))
    container.seek(target, backward=True, any_frame=False, stream=stream)


def _picture(store, entry, budget):
    from PIL import Image
    import numpy as np
    import torch

    source = _source(store, entry, "picture")
    with Image.open(source) as picture:
        width, height = picture.size
        if width <= 0 or height <= 0 or width * height > 50_000_000 or max(width, height) > 16384 or getattr(picture, "n_frames", 1) != 1:
            raise OutletError("图片尺寸或帧数超出素材出口支持范围。")
        budget.reserve(width * height * 3 * 4)
        values = np.asarray(picture.convert("RGB"), dtype=np.float32)[None, ...]
        values /= 255.0
    _verify_unchanged(store, entry)
    budget.check()
    result = _manifest_entry(entry)
    result.update(shape=list(values.shape), color_conversion="RGB；RGBA 丢弃透明通道，保留原始像素尺寸", frame_count=1)
    return torch.from_numpy(values), result


def _video(store, entry, budget):
    import av
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    source = _source(store, entry, "video")
    count, fps = entry["frame_count"], entry["target_fps"]
    if type(count) is not int or not 0 < count <= MAX_VIDEO_FRAMES or not 0 < fps <= 240:
        raise OutletError("视频出口的目标帧率或帧数无效或超限。")
    start = entry["source_window"]["start_seconds"]
    targets = [start + index / fps for index in range(count)]
    output_width = int(entry.get("output_width") or 0)
    output_height = int(entry.get("output_height") or 0)
    if output_width < 1 or output_height < 1:
        raise OutletError("视频出口缺少有效输出尺寸。")
    values, shape, previous, previous_stamp = None, None, None, None
    sampled, decoded_first, decoded_last = [], None, None
    first_repeats, tail_repeats = 0, 0
    converted_frame, converted_rgb = None, None
    with source.open("rb") as handle, av.open(handle, format=FORMATS[source.suffix[1:]], options={"protocol_whitelist": "file,pipe", "threads": "1"}) as container:
        stream = next(iter(container.streams.video), None)
        if stream is None:
            raise OutletError("绑定视频没有可解码的视频流。")
        stream.thread_type = "NONE"
        origin = _media_origin(container)
        if start > 0:
            _seek(container, stream, origin + start)

        def emit(frame, stamp):
            nonlocal values, converted_frame, converted_rgb
            budget.check()
            if values is None:
                budget.reserve(count * output_width * output_height * 3 * 4)
                values = np.empty((count, output_height, output_width, 3), dtype=np.float32)
            index = len(sampled)
            if converted_frame is not frame:
                converted_frame = frame
                if frame.width == output_width and frame.height == output_height:
                    converted_rgb = frame.to_ndarray(format="rgb24")
                else:
                    source_image = frame.to_image().convert("RGB")
                    fitted = ImageOps.fit(
                        source_image, (output_width, output_height),
                        method=Image.Resampling.BILINEAR, centering=(0.5, 0.5),
                    )
                    converted_rgb = np.asarray(fitted, dtype=np.uint8)
            np.divide(converted_rgb, 255.0, out=values[index], casting="unsafe")
            sampled.append(stamp)

        for frame in _frames(container, stream, budget):
            stamp = _stamp(frame, origin, "视频")
            if previous_stamp is not None and stamp < previous_stamp:
                raise OutletError("视频 PTS 倒序，无法按真实时间采样。")
            current_shape = (frame.height, frame.width)
            if min(current_shape) <= 0 or frame.width * frame.height > 50_000_000 or max(current_shape) > 16384:
                raise OutletError("视频帧尺寸超出素材出口支持范围。")
            if shape is not None and current_shape != shape:
                raise OutletError("同一视频的帧尺寸发生变化，无法输出统一 IMAGE 批次。")
            shape = current_shape
            decoded_first = stamp if decoded_first is None else decoded_first
            decoded_last = stamp
            while len(sampled) < count and targets[len(sampled)] < stamp - 1e-9:
                if previous is None:
                    first_repeats += 1
                emit(previous if previous is not None else frame, previous_stamp if previous is not None else stamp)
            if len(sampled) == count:
                break
            previous, previous_stamp = frame, stamp
        if previous is None and len(sampled) != count:
            raise OutletError("视频源窗口中没有可解码的画面。")
        if previous is not None:
            last_duration = float(previous.duration * previous.time_base) if previous.duration else 0.0
            coverage_end = previous_stamp + last_duration if last_duration > 0 else entry.get("source_duration_seconds")
            while len(sampled) < count:
                if coverage_end is not None and targets[len(sampled)] >= coverage_end - 1e-9:
                    tail_repeats += 1
                emit(previous, previous_stamp)
    _verify_unchanged(store, entry)
    result = _manifest_entry(entry)
    result.update(shape=list(values.shape), decoded_pts_range={"start_seconds": decoded_first, "end_seconds": decoded_last}, sampling={
        "method": "previous_pts", "target_start_seconds": start, "sampled_source_pts": sampled,
        "first_frame_repeated_count": first_repeats, "tail_frame_repeated_count": tail_repeats,
        "source_vfr": entry.get("source_vfr"),
    })
    result["color_conversion"] = "RGB float32 0–1"
    return torch.from_numpy(values), result


def _merge_ranges(ranges):
    merged = []
    for left, right in sorted(ranges):
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return merged


def _covered_samples(ranges):
    return sum(right - left for left, right in _merge_ranges(ranges))


def _audio(store, entry, budget):
    import av
    import numpy as np

    source = _source(store, entry, "audio")
    count = entry["sample_count"]
    if type(count) is not int or not 0 < count <= MAX_AUDIO_SECONDS * SAMPLE_RATE or entry["sample_rate"] != SAMPLE_RATE:
        raise OutletError("音频出口样本数无效或超过 600 秒上限。")
    budget.reserve(2 * count * 4)
    values = np.zeros((2, count), dtype=np.float32)
    start = entry["source_window"]["start_seconds"]
    end = start + count / SAMPLE_RATE
    requested = entry.get("requested_source_window") or entry["source_window"]
    valid_end = min(end, requested["end_seconds"])
    if entry.get("source_duration_seconds") is not None:
        valid_end = min(valid_end, entry["source_duration_seconds"])
    valid_count = max(0, min(count, seconds_to_frame(valid_end - start, SAMPLE_RATE)))
    ranges, first, last = [], None, None
    previous_stamp, previous_end, resampler = None, None, None
    channels = None
    with source.open("rb") as handle, av.open(handle, format=FORMATS[source.suffix[1:]], options={"protocol_whitelist": "file,pipe", "threads": "1"}) as container:
        stream = next(iter(container.streams.audio), None)
        if stream is None:
            raise OutletError("绑定素材没有可解码的音频流。")
        origin = _media_origin(container)
        if start > 1:
            _seek(container, stream, origin + start - 1)

        def consume(chunk):
            nonlocal first, last
            budget.check()
            stamp = _stamp(chunk, origin, "重采样音频")
            data = chunk.to_ndarray()
            if data.shape[0] == 1:
                data = np.repeat(data, 2, axis=0)
            if data.ndim != 2 or data.shape[0] != 2 or not np.isfinite(data).all():
                raise OutletError("音频解码得到无效声道或非有限样本。")
            offset = seconds_to_frame(stamp - start, SAMPLE_RATE)
            left, right = max(0, offset), min(valid_count, offset + data.shape[1])
            if left < right:
                values[:, left:right] = data[:, left - offset:right - offset]
                ranges.append((left, right))
                first = stamp if first is None else min(first, stamp)
                last = max(last or stamp, stamp + data.shape[1] / SAMPLE_RATE)

        for frame in _frames(container, stream, budget):
            stamp = _stamp(frame, origin, "音频")
            if previous_stamp is not None and stamp < previous_stamp - 1e-9:
                raise OutletError("音频 PTS 倒序，无法保留源时间位置。")
            if frame.sample_rate <= 0 or not 0 < len(frame.layout.channels) <= 64:
                raise OutletError("音频采样率或声道无效。")
            if stamp >= valid_end + .1:
                break
            frame_channels = len(frame.layout.channels)
            if channels is not None and channels != frame_channels:
                raise OutletError("同一音频的声道数发生变化，请先转换源文件。")
            channels = frame_channels
            # Reset the filter across real PTS gaps; never join disjoint audio in time.
            if resampler is not None and abs(stamp - previous_end) > 1.5 / frame.sample_rate:
                for chunk in resampler.resample(None):
                    consume(chunk)
                resampler = None
            if resampler is None:
                resampler = av.AudioResampler(format="fltp", layout="mono" if channels == 1 else "stereo", rate=SAMPLE_RATE)
            for chunk in resampler.resample(frame):
                consume(chunk)
            previous_stamp, previous_end = stamp, stamp + frame.samples / frame.sample_rate
        if resampler is not None:
            for chunk in resampler.resample(None):
                consume(chunk)
    _verify_unchanged(store, entry)
    padding = count - _covered_samples(ranges)
    result = _manifest_entry(entry)
    result.update(shape=[1, 2, count], channels=2, sample_rate=SAMPLE_RATE, sample_count=count,
                  zero_padded=padding > 0, zero_padding_samples=padding,
                  decoded_sample_ranges=_merge_ranges(ranges),
                  source_read_limit={"start_seconds": start, "end_seconds": valid_end},
                  decoded_pts_range={"start_seconds": first, "end_seconds": last},
                  channel_conversion="单声道复制为双声道；双声道原样；多声道按 FFmpeg 默认 stereo 矩阵重混")
    return values, result


def _audio_result(values):
    import torch
    return {"waveform": torch.from_numpy(values[None, ...]), "sample_rate": SAMPLE_RATE}


def execute_outlet(store, plan):
    """Decode an already canonicalized pure plan; return only standard CPU media."""
    budget = _Budget()
    manifest = {"schema_version": 1, "kind": plan["kind"], "binding_id": plan["binding_id"],
                "processing_window": copy.deepcopy(plan["window"]), "items": [], "original_audio": None}
    original_audio = None
    try:
        import numpy as np

        kind = plan["kind"]
        if kind == "picture":
            media, item = _picture(store, plan["items"][0], budget)
            manifest["items"].append(item)
            report = f"已输出 {item['label']} 原图，{media.shape[2]} × {media.shape[1]}，RGB float32；保留原始尺寸。"
        elif kind == "video":
            media, item = _video(store, plan["items"][0], budget)
            manifest["items"].append(item)
            report = f"已输出 {item['label']}：{item['frame_count']} 帧，{item['target_fps']:g} fps CFR，按真实 PTS 采样。"
            if item.get("resize_during_decode"):
                report += (
                    f" 解码时逐帧适配为 {item['output_width']} × {item['output_height']}，"
                    "保持比例、居中裁切并铺满画布；未先构造原尺寸批次。"
                )
            else:
                report += f" 保留源尺寸 {item['output_width']} × {item['output_height']}。"
            if plan["original_audio"] is not None:
                values, original = _audio(store, plan["original_audio"], budget)
                original_audio = _audio_result(values)
                manifest["original_audio"] = original
                report += f" 原声 {original['sample_count']} 样本，与视频帧窗同长；补零 {original['zero_padding_samples']} 样本。"
            else:
                report += " 原声未启用或来源无音频，原声口为空。"
            repeated = item["sampling"]["first_frame_repeated_count"] + item["sampling"]["tail_frame_repeated_count"]
            if repeated:
                report += f" 源边界重复画面 {repeated} 帧，详见清单。"
        elif kind == "audio":
            values, item = _audio(store, plan["items"][0], budget)
            media = _audio_result(values)
            manifest["items"].append(item)
            report = f"已输出 {item['label']}：44100 Hz 双声道，{item['sample_count']} 样本；补零 {item['zero_padding_samples']} 样本。"
        elif kind == "timeline_audio":
            count = plan["window"]["sample_count"]
            if type(count) is not int or not 0 < count <= MAX_AUDIO_SECONDS * SAMPLE_RATE:
                raise OutletError("时间线混音窗口无效或超过 600 秒上限。")
            budget.reserve(2 * count * 4)
            mixed = np.zeros((2, count), dtype=np.float32)
            covered, decoded_covered = [], []
            for entry in plan["items"]:
                values, item = _audio(store, entry, budget)
                offset = seconds_to_frame(entry["project_window"]["start_seconds"] - plan["window"]["start_seconds"], SAMPLE_RATE)
                left, right = max(0, offset), min(count, offset + values.shape[1])
                if left < right:
                    mixed[:, left:right] += values[:, left - offset:right - offset]
                    covered.append((left, right))
                    decoded_covered.extend((max(0, offset + begin), min(count, offset + finish))
                                           for begin, finish in item["decoded_sample_ranges"]
                                           if min(count, offset + finish) > max(0, offset + begin))
                item["timeline_offset_samples"] = offset
                manifest["items"].append(item)
                budget.bytes -= values.nbytes
                del values
            if not np.isfinite(mixed).all():
                raise OutletError("混音产生非有限样本，无法输出有效音频。")
            peak = float(np.max(np.abs(mixed)))
            gain = .98 / peak if peak > .98 else 1.0
            mixed *= gain
            silence = count - _covered_samples(covered)
            padding = count - _covered_samples(decoded_covered)
            manifest["mix"] = {"strategy": "peak_limit", "peak_before_gain": peak, "gain": gain, "peak_limit": .98,
                               "channels": 2, "sample_rate": SAMPLE_RATE, "sample_count": count,
                               "timeline_gap_samples": silence, "zero_padded": padding > 0, "zero_padding_samples": padding,
                               "shape": [1, 2, count]}
            media = _audio_result(mixed)
            report = f"时间线混音：{len(plan['items'])} 条已启用音频，44100 Hz 双声道，{count} 样本；轨道空白 {silence} 样本。峰值超过 0.98 时统一缩放，增益 {gain:.6g}，不改变时间位置。"
        else:
            raise OutletError("不支持的素材出口类型。")
        budget.check()
        return media, original_audio, manifest, report
    except OutletError:
        raise
    except ImportError:
        raise OutletError("素材出口缺少 PyAV、Pillow、NumPy 或 PyTorch，请检查 ComfyUI 的现有运行环境。") from None
    except Exception:
        # Backend exceptions often contain absolute source paths; keep them private.
        raise OutletError("素材解码失败，请检查源文件可解码性、时间戳和可用内存。") from None
