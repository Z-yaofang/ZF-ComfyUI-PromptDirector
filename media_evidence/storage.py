"""Private media storage, bounded subprocesses and immutable preview caches."""
from collections import OrderedDict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid

from .contract import SOURCE_MESSAGES, normalize_project, problem, source_message

MAX_UPLOAD = 512 * 1024 * 1024
MAX_FILES_BYTES = 8 * 1024 * 1024 * 1024
MAX_FRAME_PREVIEW_BYTES = 32 * 1024 * 1024
HANDLE = re.compile(r"originals/[a-f0-9]{32}\.(png|jpg|jpeg|webp|bmp|mp4|mov|mkv|webm|avi|wav|mp3|m4a|flac|ogg)")
FORMATS = {"mp4": "mov", "mov": "mov", "m4a": "mov", "mkv": "matroska", "webm": "matroska", "avi": "avi", "wav": "wav", "mp3": "mp3", "flac": "flac", "ogg": "ogg"}
MAX_VERIFIED_SOURCES = 256


class MediaError(ValueError):
    def __init__(self, code, message, *, asset_committed=False, reason=None):
        self.code, self.message = code, message
        self.asset_committed = asset_committed
        self.reason = reason
        super().__init__(message)


def _source_error(reason):
    return MediaError("source_unavailable", SOURCE_MESSAGES[reason], reason=reason)


def _stat_signature(info):
    return (
        info.st_size,
        info.st_mtime_ns,
        getattr(info, "st_dev", None),
        getattr(info, "st_ino", None),
    )


def _stable_sha256(path):
    """Hash one path while proving that the opened file and path stayed stable."""
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            digest = hashlib.sha256()
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(source.fileno())
        current = path.stat()
    except FileNotFoundError:
        raise _source_error("source_missing") from None
    except OSError:
        raise _source_error("source_unreadable") from None
    if _stat_signature(before) != _stat_signature(after) or _stat_signature(after) != _stat_signature(current):
        raise _source_error("source_unstable")
    return current, digest.hexdigest()


def remove_owned_files(paths):
    """Try each known-owned file twice; one Windows sharing error cannot block others."""
    failed = []
    for path in paths:
        for attempt in range(2):
            try:
                path.unlink(missing_ok=True)
                break
            except OSError:
                if attempt == 1:
                    failed.append(path)
    return failed


class MediaStore:
    def __init__(self, input_directory, python_executable=None, ffmpeg_executable=None):
        self.input_root = Path(input_directory).resolve()
        self.root = self.input_root / "zf_media_evidence"
        self.python = python_executable or sys.executable
        self.ffmpeg = ffmpeg_executable
        self.jobs = threading.BoundedSemaphore(2)
        self.import_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.integrity_lock = threading.Lock()
        self.verified_sources = OrderedDict()
        for directory in (self.root, self.root / "originals", self.root / "cache"):
            directory.mkdir(parents=True, exist_ok=True)
            self.safe(directory)

    def safe(self, path):
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.input_root) or not resolved.is_relative_to(self.root.absolute()):
            raise MediaError("unsafe_path", "Media path must remain inside the dedicated input directory")
        return resolved

    def resolve(self, handle):
        if not isinstance(handle, str) or not HANDLE.fullmatch(handle):
            raise MediaError("unsafe_handle", "Invalid media source handle")
        return self.safe(self.root / handle)

    def allocate(self, display_name):
        name = re.sub(r"[\x00-\x1f\x7f]", "", str(display_name).replace("\\", "/").rsplit("/", 1)[-1])[:180]
        ext = Path(name).suffix.lower()
        handle = "originals/" + uuid.uuid4().hex + ext
        return self.resolve(handle), handle, name

    def worker(self, operation, path, output="", *, source_seconds=None):
        if not self.jobs.acquire(blocking=False):
            raise MediaError("busy", "Two media operations are already running; retry shortly")
        try:
            args = [self.python, str(Path(__file__).with_name("worker.py")), operation, str(path), str(output)]
            if source_seconds is not None:
                args.append(str(source_seconds))
            result = subprocess.run(args, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(result.stdout.decode("utf-8"))
            if not data.get("ok"):
                raise MediaError(data.get("error", "invalid_media"), "Media could not be decoded within the supported limits")
            return data["result"]
        except subprocess.TimeoutExpired:
            raise MediaError("probe_timeout", "Media operation exceeded 30 seconds") from None
        except (OSError, ValueError) as error:
            if isinstance(error, MediaError):
                raise
            raise MediaError("worker_failed", "Media worker did not return valid results") from None
        finally:
            self.jobs.release()

    def quota(self):
        total = sum(p.stat().st_size for p in self.safe(self.root / "originals").iterdir() if p.is_file())
        if total >= MAX_FILES_BYTES:
            raise MediaError("storage_limit", "Original media storage has reached the 8 GiB limit")
        return MAX_FILES_BYTES - total

    def finish_import(self, path, handle, name, *, capture=None, source_sha256=None):
        if source_sha256 is None:
            _before, source_sha256 = _stable_sha256(path)
        elif not isinstance(source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
            raise MediaError("invalid_digest", "Imported media digest is invalid")
        info = self.worker("probe", path)
        source_stat, verified_sha256 = _stable_sha256(path)
        if verified_sha256 != source_sha256:
            raise _source_error("source_content_changed")
        asset = {"asset_id": "asset_" + path.stem, "name": name, "source_handle": handle, **info}
        if capture is not None:
            asset["capture"] = capture
        record = {
            "asset": asset,
            "size": source_stat.st_size,
            "mtime_ns": source_stat.st_mtime_ns,
            "source_sha256": verified_sha256,
        }
        target = self.safe(self.root / "cache" / (path.stem + ".json"))
        temporary = self.safe(target.with_name(uuid.uuid4().hex + ".partial.json"))
        owned = committed = False
        try:
            with temporary.open("x", encoding="utf-8") as output:
                owned = True
                output.write(json.dumps(record, allow_nan=False))
            os.link(temporary, target)
            committed = True
        finally:
            if owned and remove_owned_files([temporary]):
                raise MediaError("cleanup_failed", "素材登记临时文件未能清理，请稍后检查本地素材目录", asset_committed=committed)
        return asset

    def capture_frame(self, source_handle, timeline_in_seconds, source_in_seconds, source_out_seconds, playhead_seconds):
        times = [timeline_in_seconds, source_in_seconds, source_out_seconds, playhead_seconds]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in times):
            raise MediaError("capture_time", "截图时间必须为有限数值")
        if not 0 <= timeline_in_seconds <= playhead_seconds < timeline_in_seconds + source_out_seconds-source_in_seconds <= 43200:
            raise MediaError("capture_window", "黄色播放头不在该视频片段内")
        if not self.import_lock.acquire(blocking=False):
            raise MediaError("busy", "素材正在导入或截图，请稍后重试")
        path = temporary = None; temporary_owned = owned = registered = complete = False; failure = None
        try:
            source_asset = self.record(source_handle)
            if source_asset["kind"] != "video":
                raise MediaError("capture_video", "截图只接受已注册的原视频")
            if not 0 <= source_in_seconds < source_out_seconds <= source_asset["probe"]["duration_seconds"]:
                raise MediaError("capture_window", "选段源入出点超出原视频范围")
            source_seconds = source_in_seconds + playhead_seconds-timeline_in_seconds
            available = self.quota()
            name = f"{Path(source_asset['name']).stem[:130]} 截图 {source_seconds:.3f}s.png"
            path, handle, name = self.allocate(name)
            temporary = self.safe(path.with_name(path.stem + ".partial.png"))
            with temporary.open("xb"):
                temporary_owned = True
            frame = self.worker("screenshot", self.resolve(source_handle), temporary, source_seconds=source_seconds)
            self.record(source_handle)
            if temporary.stat().st_size > min(MAX_UPLOAD, available):
                raise MediaError("capture_limit", "截图超出单文件或素材存储上限")
            os.link(temporary, path); owned = True
            capture = {"method": "video_frame", "source_handle": source_handle, "source_seconds": source_seconds, "frame_seconds": frame["frame_seconds"], "playhead_seconds": playhead_seconds}
            asset = self.finish_import(path, handle, name, capture=capture); registered = True
            self.record(source_handle)
            complete = True
            return asset
        except MediaError as error:
            if error.asset_committed:
                registered = True
            messages = {"unsafe_handle": "截图来源必须是已注册的受控视频", "unsafe_path": "截图来源路径无效", "probe_timeout": "截图解码超过30秒，请换较短或更易解码的视频", "worker_failed": "截图解码失败", "invalid_media": "原视频无法解码截图", "video_limit": "原视频尺寸或帧率超限", "image_limit": "截图尺寸超限", "capture_orientation": "视频包含不支持的方向变换，无法保留原画面截图", "storage_limit": "素材存储已达到8 GiB上限", "busy": "素材处理繁忙，请稍后重试"}
            message = (
                source_message(error.message, "原视频丢失或已改变，请重新导入后截图")
                if error.code == "source_unavailable"
                else messages.get(error.code, error.message)
            )
            failure = MediaError(error.code, message, asset_committed=error.asset_committed, reason=error.reason)
            raise failure from None
        finally:
            failed = []
            record_remains = registered
            try:
                if temporary_owned:
                    failed.extend(remove_owned_files([temporary]))
                if registered and not complete:
                    failures = remove_owned_files([self.safe(self.root / "cache" / (path.stem + ".json"))])
                    failed.extend(failures);record_remains = bool(failures)
                # Keep the complete PNG if its committed record could not be removed.
                if owned and not complete and not record_remains:
                    failed.extend(remove_owned_files([path]))
            finally:
                self.import_lock.release()
            if failure is not None:
                failure.asset_committed = record_remains
            if failed:
                raise MediaError("capture_cleanup", "截图事务结束，但本次新文件未能全部清理；已有素材保留，请稍后检查本地素材目录", asset_committed=record_remains)

    def frame_preview(self, source_handle, source_seconds):
        """Decode one original-video frame without importing it or creating a cache asset.

        The worker selects the last decoded frame at the requested source time,
        allowing only half a stream timestamp tick for PTS rounding. Its
        returned frame_seconds is relative to the video's first timestamp,
        independent of any preview proxy. Persistent screenshots remain strict.
        """
        if type(source_seconds) not in (str, int, float):
            raise MediaError("frame_time", "预览帧时间必须是有限数值")
        try:
            seconds = float(source_seconds)
        except (ValueError, OverflowError):
            raise MediaError("frame_time", "预览帧时间必须是有限数值") from None
        if not math.isfinite(seconds):
            raise MediaError("frame_time", "预览帧时间必须是有限数值")
        asset = self.record(source_handle)
        if asset["kind"] != "video":
            raise MediaError("frame_video", "预览帧只接受已注册的原视频")
        duration = asset["probe"]["duration_seconds"]
        if not 0 <= seconds < duration:
            raise MediaError("frame_time", "预览帧时间超出原视频范围")

        temporary = self.safe(self.root / "cache" / (uuid.uuid4().hex + ".frame.png"))
        owned = False
        try:
            with temporary.open("xb"):
                owned = True
            result = self.worker("frame_preview", self.resolve(source_handle), temporary, source_seconds=seconds)
            # Detect a changed or removed source before returning pixels from it.
            self.record(source_handle)
            frame_seconds = result["frame_seconds"]
            tolerance = result.get("timestamp_tolerance_seconds", 0)
            if (type(tolerance) not in (int, float) or not math.isfinite(tolerance)
                    or not 0 <= tolerance <= 0.5 / asset["probe"]["fps"] + 1e-9):
                raise MediaError("frame_failed", "预览帧时间戳精度无效")
            if type(frame_seconds) not in (int, float) or not math.isfinite(frame_seconds) or not 0 <= frame_seconds <= seconds + tolerance + 1e-9:
                raise MediaError("frame_failed", "预览帧时间戳无效")
            with temporary.open("rb") as frame_file:
                data = frame_file.read(MAX_FRAME_PREVIEW_BYTES + 1)
            if len(data) > MAX_FRAME_PREVIEW_BYTES:
                raise MediaError("frame_limit", "预览帧超过 32 MiB 上限")
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise MediaError("frame_failed", "预览帧解码结果不是 PNG")
            return data, frame_seconds
        finally:
            if owned and remove_owned_files([temporary]):
                raise MediaError("frame_cleanup", "预览帧临时文件未能清理")

    def _load_record(self, handle, path):
        target = self.safe(self.root / "cache" / (path.stem + ".json"))
        try:
            raw = target.read_bytes()
        except FileNotFoundError:
            raise _source_error("registry_missing") from None
        except OSError:
            raise _source_error("registry_unreadable") from None
        try:
            record = json.loads(raw.decode("utf-8"))
            if not isinstance(record, dict) or record["asset"]["source_handle"] != handle:
                raise ValueError()
            if type(record["size"]) is not int or record["size"] < 1 or type(record["mtime_ns"]) is not int:
                raise ValueError()
            digest = record.get("source_sha256")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                raise ValueError()
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            raise _source_error("registry_invalid") from None
        return target, raw, record

    def record(self, handle):
        path = self.resolve(handle)
        try:
            _target, _raw, record = self._load_record(handle, path)
            source_stat = path.stat()
        except FileNotFoundError:
            raise _source_error("source_missing") from None
        except OSError:
            raise _source_error("source_unreadable") from None
        if source_stat.st_size != record["size"]:
            raise _source_error("source_size_changed")
        if source_stat.st_mtime_ns == record["mtime_ns"]:
            return record["asset"]
        digest = record.get("source_sha256")
        if digest is None:
            raise _source_error("source_metadata_changed")
        # One process may normalize, preview and execute the same large source at
        # once.  Serialize only this rare mtime fallback and cache its exact stat;
        # normal records never enter this lock and shared registry state is not
        # rewritten.
        with self.integrity_lock:
            try:
                current_stat = path.stat()
            except FileNotFoundError:
                raise _source_error("source_missing") from None
            except OSError:
                raise _source_error("source_unreadable") from None
            if current_stat.st_size != record["size"]:
                self.verified_sources.pop(handle, None)
                raise _source_error("source_size_changed")
            if current_stat.st_mtime_ns == record["mtime_ns"]:
                return record["asset"]
            cache_key = (digest, _stat_signature(current_stat))
            if self.verified_sources.get(handle) == cache_key:
                self.verified_sources.move_to_end(handle)
                return record["asset"]
            verified_stat, verified_digest = _stable_sha256(path)
            if verified_stat.st_size != record["size"]:
                self.verified_sources.pop(handle, None)
                raise _source_error("source_size_changed")
            if verified_digest != digest:
                self.verified_sources.pop(handle, None)
                raise _source_error("source_content_changed")
            self.verified_sources[handle] = (digest, _stat_signature(verified_stat))
            self.verified_sources.move_to_end(handle)
            while len(self.verified_sources) > MAX_VERIFIED_SOURCES:
                self.verified_sources.popitem(last=False)
        return record["asset"]

    def canonical(self, project):
        # Validate shape before reading handles; hydrate facts only from our upload registry.
        result = normalize_project(project)
        unavailable = []
        for i, asset in enumerate(result["assets"]):
            asset.pop("capture", None)
            try:
                facts = self.record(asset["source_handle"])
                asset.update(kind=facts["kind"], probe=facts["probe"])
                if "capture" in facts:
                    asset["capture"] = facts["capture"]
            except MediaError as error:
                unavailable.append(problem(f"/assets/{i}", error.code, error.message))
        result = normalize_project(result)
        result["validation"]["errors"].extend(unavailable)
        return result

    def preview(self, handle, variant):
        asset = self.record(handle)
        source = self.resolve(handle)
        if variant == "original":
            return source
        if variant not in {"thumbnail", "proxy", "audio", "peaks"}:
            raise MediaError("variant", "Unknown preview variant")
        if variant in {"audio", "peaks"} and not asset["probe"]["has_audio"]:
            raise MediaError("no_audio", "Source has no audio stream")
        if variant == "proxy" and asset["kind"] != "video":
            raise MediaError("no_video", "Source has no video stream")
        if variant == "thumbnail" and asset["kind"] == "audio":
            raise MediaError("no_video", "Audio sources have no thumbnail")
        suffix = {"thumbnail": ".jpg", "proxy": ".mp4", "audio": ".m4a", "peaks": ".json"}[variant]
        # Proxy v2 keeps every source frame and its relative presentation time.
        # Do not reuse the old 12 fps cache for frame-accurate timeline playback.
        cache_version = "v2" if variant == "proxy" else "v1"
        key = hashlib.sha256((handle + variant + cache_version).encode()).hexdigest()
        target = self.safe(self.root / "cache" / (key + suffix))
        # Shared cache lock ensures two requests never expose a partially written preview.
        with self.cache_lock:
            if target.is_file():
                return target
            temporary = self.safe(target.with_name(key + ".partial" + suffix))
            try:
                if variant == "peaks":
                    temporary.write_text(json.dumps(self.worker("peaks", source)), encoding="utf-8")
                elif variant == "thumbnail":
                    self.worker("thumbnail", source, temporary)
                else:
                    # Full-frame previews can take materially longer than the
                    # former 12 fps previews on long sources. Keep a finite cap.
                    duration = float(asset["probe"].get("duration_seconds") or 0)
                    timeout = min(1800, max(90, math.ceil(duration * 2))) if variant == "proxy" else 90
                    self.encode(source, temporary, variant, timeout=timeout)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def encode(self, source, target, variant, timeout=90):
        executable = self.ffmpeg or shutil.which("ffmpeg")
        if not executable:
            try:
                import imageio_ffmpeg
                executable = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                raise MediaError("ffmpeg_missing", "FFmpeg is unavailable for preview generation") from None
        args = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-threads", "1", "-protocol_whitelist", "file,pipe", "-f", FORMATS[source.suffix[1:]], "-i", str(source)]
        if variant == "proxy":
            args += [
                "-map", "0:v:0", "-an",
                "-vf", "scale=480:480:force_original_aspect_ratio=decrease:force_divisible_by=2,setpts=PTS-STARTPTS",
                "-vsync", "0", "-enc_time_base:v", "-1",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p", "-g", "30", "-video_track_timescale", "1000000",
            ]
        else:
            args += ["-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "96k"]
        args += ["-threads", "1", "-movflags", "+faststart", str(target)]
        if not self.jobs.acquire(blocking=False):
            raise MediaError("busy", "Two media operations are already running; retry shortly")
        try:
            completed = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode:
                raise MediaError("preview_failed", "Could not encode the preview")
        except subprocess.TimeoutExpired:
            raise MediaError("preview_timeout", "Preview generation exceeded its time limit") from None
        except OSError:
            raise MediaError("ffmpeg_missing", "FFmpeg could not be started") from None
        finally:
            self.jobs.release()
