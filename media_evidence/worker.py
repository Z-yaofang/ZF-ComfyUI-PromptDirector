"""Bounded, disposable media worker. No ComfyUI or project-model dependency."""
import json
import math
from pathlib import Path
import sys

FORMATS = {"mp4": "mov", "mov": "mov", "m4a": "mov", "mkv": "matroska", "webm": "matroska", "avi": "avi", "wav": "wav", "mp3": "mp3", "flac": "flac", "ogg": "ogg"}
PICTURES = {"png", "jpg", "jpeg", "webp", "bmp"}
MAX_PIXELS = 50_000_000
MAX_DURATION = 3600


def run(operation, filename, output, source_seconds=None):
    path = Path(filename)
    ext = path.suffix[1:].lower()
    if operation == "screenshot" and (ext not in FORMATS or ext in {"wav", "mp3", "m4a", "flac", "ogg"}):
        raise ValueError("capture_video")
    facts = dict(size_bytes=path.stat().st_size, duration_seconds=None, width=None, height=None, fps=None, frame_count=None, frame_count_exact=False, vfr=None, has_audio=False, sample_rate=None, channels=None, codec="")
    if ext in PICTURES:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(path) as picture:
            w, h = picture.size
            if w * h > MAX_PIXELS or max(w, h) > 16384 or getattr(picture, "n_frames", 1) != 1:
                raise ValueError("image_limit")
            picture.load()
            facts.update(width=w, height=h, codec=picture.format or ext)
            if operation == "thumbnail":
                picture.thumbnail((480, 270))
                picture.convert("RGB").save(output, "JPEG", quality=78)
        return {"kind": "picture", "probe": facts}
    import av
    import numpy as np
    with path.open("rb") as source, av.open(source, format=FORMATS[ext], options={"protocol_whitelist": "file,pipe", "threads": "1"}) as container:
        video = next(iter(container.streams.video), None)
        audio = next(iter(container.streams.audio), None)
        if not video and not audio:
            raise ValueError("no_stream")
        duration = float(container.duration / av.time_base) if container.duration is not None else None
        primary = video or audio
        if duration is None and primary.duration is not None:
            duration = float(primary.duration * primary.time_base)
        if duration is None or not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
            raise ValueError("duration_limit")
        facts.update(duration_seconds=duration, has_audio=audio is not None, codec=primary.codec_context.name)
        if audio:
            if not 0 < audio.codec_context.sample_rate <= 768000 or not 0 < audio.codec_context.channels <= 64:
                raise ValueError("audio_limit")
            facts.update(sample_rate=audio.codec_context.sample_rate, channels=audio.codec_context.channels)
        if video:
            w, h = video.codec_context.width, video.codec_context.height
            rate = float(video.average_rate or video.guessed_rate or 0)
            if not w or not h or w*h > MAX_PIXELS or max(w, h) > 16384 or not 0 < rate <= 1000:
                raise ValueError("video_limit")
            facts.update(width=w, height=h, fps=rate, frame_count=video.frames or round(duration*rate))
        if operation == "screenshot":
            if not video:
                raise ValueError("capture_video")
            target = float(source_seconds)
            if not math.isfinite(target) or not 0 <= target < duration:
                raise ValueError("capture_time")
            video.codec_context.thread_count = 1
            origin = float((video.start_time or 0) * video.time_base)
            container.seek(int((target+origin)/video.time_base), stream=video, backward=True)
            selected = None; selected_time = None
            for index, frame in enumerate(container.decode(video)):
                if index >= 2000 or frame.time is None:
                    raise ValueError("capture_decode_limit")
                at = float(frame.time)-origin
                if at > target+1e-9:
                    break
                selected, selected_time = frame, max(0, at)
            if selected is None:
                raise ValueError("capture_no_frame")
            picture = selected.to_image()
            matrix_data = next((data for data in selected.side_data if data.type.name == "DISPLAYMATRIX"), None)
            if matrix_data is not None:
                from PIL import Image
                matrix = np.frombuffer(bytes(matrix_data), dtype="<i4", count=9)
                a,b,c,d = [float(matrix[index])/65536 for index in (0,1,3,4)]
                length = math.hypot(a,b)
                if not length or matrix[2] or matrix[5] or not math.isclose(length,math.hypot(c,d),rel_tol=.001) or abs(a*c+b*d)>.001*length*length:
                    raise ValueError("capture_orientation")
                if a*d-b*c < 0:
                    picture = picture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    a,b = -a,-b
                angle = math.degrees(math.atan2(-b,a))
                if abs(angle) > 1e-6:
                    picture = picture.rotate(angle, expand=True)
            if picture.width*picture.height > MAX_PIXELS or max(picture.size) > 16384:
                raise ValueError("image_limit")
            picture.save(output, "PNG")
            return {"frame_seconds": selected_time, "width": picture.width, "height": picture.height}
        if operation == "peaks":
            if not audio:
                return {"peaks": [], "duration_seconds": duration}
            resampler = av.AudioResampler(format="s16", layout="mono", rate=8000)
            peaks = np.zeros(1024, dtype=np.float32)
            sample_offset = 0
            def consume(frame):
                nonlocal sample_offset
                values = np.abs(frame.to_ndarray().reshape(-1).astype(np.float32)) / 32768
                bins = np.minimum(1023, ((np.arange(len(values)) + sample_offset) * 1024 / (duration*8000)).astype(np.int64))
                np.maximum.at(peaks, bins, values)
                sample_offset += len(values)
                if sample_offset > (MAX_DURATION+2)*8000:
                    raise ValueError("duration_limit")
            for frame in container.decode(audio):
                for chunk in resampler.resample(frame):
                    consume(chunk)
            for chunk in resampler.resample(None):
                consume(chunk)
            return {"peaks": [round(float(p), 5) for p in peaks], "duration_seconds": duration}
        if video:
            stamps, complete = [], True
            for frame in container.decode(video):
                if operation == "thumbnail":
                    picture = frame.to_image()
                    picture.thumbnail((480, 270))
                    picture.save(output, "JPEG", quality=78)
                    break
                if len(stamps) == 120:
                    complete = False
                    break
                stamps.append(float(frame.pts * frame.time_base) if frame.pts is not None else None)
            usable = len(stamps) > 1 and all(p is not None for p in stamps)
            varied = usable and any(abs((b-a)-1/rate) > max(.001, .02/rate) for a, b in zip(stamps, stamps[1:]))
            facts.update(vfr=True if varied else (False if complete and usable else None), frame_count_exact=bool(complete and usable and not varied))
            if complete and operation != "thumbnail":
                facts["frame_count"] = len(stamps)
        return {"kind": "video" if video else "audio", "probe": facts}


if __name__ == "__main__":
    try:
        answer = {"ok": True, "result": run(*sys.argv[1:])}
    except ImportError:
        answer = {"ok": False, "error": "dependency_missing"}
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and str(error) in {"image_limit", "duration_limit", "video_limit", "audio_limit", "no_stream", "capture_video", "capture_time", "capture_decode_limit", "capture_no_frame", "capture_orientation"} else "invalid_media"
        answer = {"ok": False, "error": code}
    print(json.dumps(answer, ensure_ascii=True, allow_nan=False))
