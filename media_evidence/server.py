"""Local-only media endpoints, with stable public errors and bounded payloads."""
import asyncio
import functools
import hashlib
from urllib.parse import urlsplit
from aiohttp import web
from .contract import ProjectError, parse_project
from .storage import MAX_UPLOAD, MediaError, remove_owned_files
from .preset_store import PresetError


def register_media_routes(routes, get_store, get_preset_library):
    def endpoint(function):
        @functools.wraps(function)
        async def guarded(request):
            try:
                origin = request.headers.get("Origin")
                if origin and urlsplit(origin).netloc != request.host:
                    raise MediaError("origin", "Cross-origin media access is not supported")
                return await function(request, get_store())
            except ProjectError as error:
                return web.json_response({"ok": False, "error": {"code": "invalid_project", "message": "项目结构或规则无效：" + "；".join(item["message"] for item in error.errors[:6]), "details": error.errors}}, status=400)
            except PresetError as error:
                return web.json_response({"ok": False, "error": {"code": error.code, "message": error.message}}, status=409 if error.code == "preset_conflict" else 400)
            except MediaError as error:
                return web.json_response({"ok": False, "error": {"code": error.code, "message": error.message}}, status=429 if error.code == "busy" else 400)
            except (ValueError, OSError, KeyError, AssertionError, web.HTTPException):
                return web.json_response({"ok": False, "error": {"code": "request_failed", "message": "Media request could not be completed"}}, status=400)
        return guarded

    async def preset_body(request, keys):
        data = bytearray()
        async for chunk in request.content.iter_chunked(8192):
            data.extend(chunk)
            if len(data) > 16384:
                raise PresetError("preset_size", "单个预设请求最多 16 KiB")
        body = parse_project(data.decode("utf-8"))
        if not isinstance(body, dict) or set(body) != keys:
            raise PresetError("preset_fields", "预设请求字段不完整或包含未知字段")
        return body

    @routes.get("/zf-media-evidence/presets")
    @endpoint
    async def presets(request, store):
        data = await asyncio.to_thread(get_preset_library(request).listing)
        return web.json_response({"ok": True, **data})

    @routes.post("/zf-media-evidence/presets")
    @endpoint
    async def create_preset(request, store):
        body = await preset_body(request, {"snapshot"})
        preset = await asyncio.to_thread(get_preset_library(request).save, body["snapshot"])
        return web.json_response({"ok": True, "preset": preset})

    @routes.put("/zf-media-evidence/presets/{preset_id}")
    @endpoint
    async def update_preset(request, store):
        body = await preset_body(request, {"snapshot", "preset_version"})
        preset = await asyncio.to_thread(get_preset_library(request).save, body["snapshot"], request.match_info["preset_id"], body["preset_version"])
        return web.json_response({"ok": True, "preset": preset})

    @routes.delete("/zf-media-evidence/presets/{preset_id}")
    @endpoint
    async def delete_preset(request, store):
        body = await preset_body(request, {"preset_version"})
        await asyncio.to_thread(get_preset_library(request).delete, request.match_info["preset_id"], body["preset_version"])
        return web.json_response({"ok": True})

    @routes.post("/zf-media-evidence/upload")
    @endpoint
    async def upload(request, store):
        if request.content_length and request.content_length > MAX_UPLOAD + 65536:
            raise MediaError("upload_limit", "Each file is limited to 512 MiB")
        if not store.import_lock.acquire(blocking=False):
            raise MediaError("busy", "A media upload is in progress; retry shortly")
        path, owned, complete = None, False, False
        try:
            available = store.quota()
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file" or not field.filename:
                raise MediaError("file_required", "Upload one file in the file field")
            path, handle, name = store.allocate(field.filename)
            count = 0
            digest = hashlib.sha256()
            with path.open("xb") as output:
                owned = True
                while True:
                    chunk = await field.read_chunk(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > min(MAX_UPLOAD, available):
                        raise MediaError("upload_limit", "Upload exceeds the file or storage limit")
                    output.write(chunk)
                    digest.update(chunk)
            if count == 0 or await reader.next() is not None:
                raise MediaError("file_required", "Upload exactly one nonempty file per request")
            asset = await asyncio.to_thread(store.finish_import, path, handle, name, source_sha256=digest.hexdigest())
            complete = True
            return web.json_response({"ok": True, "asset": asset})
        except MediaError as error:
            complete = error.asset_committed
            raise
        finally:
            try:
                if owned and not complete and remove_owned_files([path]):
                    raise MediaError("cleanup_failed", "本次上传文件未能清理，请稍后检查本地素材目录")
            finally:
                store.import_lock.release()

    @routes.post("/zf-media-evidence/normalize")
    @endpoint
    async def normalize(request, store):
        data = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            data.extend(chunk)
            if len(data) > 2*1024*1024:
                raise MediaError("json_size", "Project JSON is limited to 2 MiB")
        project = await asyncio.to_thread(store.canonical, parse_project(data.decode("utf-8")))
        return web.json_response({"ok": True, "project": project})

    @routes.post("/zf-media-evidence/screenshot")
    @endpoint
    async def screenshot(request, store):
        data = bytearray()
        async for chunk in request.content.iter_chunked(2048):
            data.extend(chunk)
            if len(data) > 2048:
                raise MediaError("capture_size", "截图请求最多 2 KiB")
        body = parse_project(data.decode("utf-8"))
        keys = {"source_handle", "timeline_in_seconds", "source_in_seconds", "source_out_seconds", "playhead_seconds"}
        if not isinstance(body, dict) or set(body) != keys:
            raise MediaError("capture_fields", "截图请求字段不完整或包含未知字段")
        try:
            asset = await asyncio.to_thread(store.capture_frame, **body)
        except OSError:
            raise MediaError("capture_storage", "截图保存或注册失败，本次新文件已清理") from None
        return web.json_response({"ok": True, "asset": asset})

    @routes.get("/zf-media-evidence/preview")
    @endpoint
    async def preview(request, store):
        variant = request.query.get("variant", "original")
        path = await asyncio.to_thread(store.preview, request.query.get("source", ""), variant)
        return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})

    @routes.get("/zf-media-evidence/frame")
    @endpoint
    async def frame(request, store):
        if len(request.query) != 2 or set(request.query) != {"source", "seconds"}:
            raise MediaError("frame_fields", "预览帧请求需要 source 和 seconds")
        data, frame_seconds = await asyncio.to_thread(
            store.frame_preview, request.query["source"], request.query["seconds"]
        )
        return web.Response(
            body=data,
            content_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-ZF-Frame-Seconds": f"{frame_seconds:.9f}",
            },
        )
