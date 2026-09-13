"""Local current-user preset CRUD and portable template application."""

import asyncio
import functools
from urllib.parse import urlsplit
from aiohttp import web

from .interview import InterviewError
from .presets import PresetError, MAX_BYTES, strict_json, keys, capture_template, apply_template
from .preset_store import get_interview_library
from ..media_evidence.contract import ProjectError
from ..media_evidence.runtime import get_store

PREFIX = "/zf-prompt-director/h3-interview/presets"


def register_preset_routes(routes):
    def endpoint(function):
        @functools.wraps(function)
        async def guarded(request):
            try:
                origin = request.headers.get("Origin")
                if origin and urlsplit(origin).netloc != request.host:
                    raise PresetError("preset_origin", "预设仅允许同源请求", 403)
                return await function(request)
            except PresetError as error:
                return web.json_response({"error": {"code": error.code, "message": error.message}}, status=error.status)
            except (InterviewError, ProjectError) as error:
                rows = getattr(error, "issues", getattr(error, "errors", []))
                return web.json_response({"error": {"code": "preset_state", "message": "；".join(row["message"] for row in rows[:6])}}, status=400)
            except (ValueError, TypeError, KeyError, UnicodeError, web.HTTPException):
                return web.json_response({"error": {"code": "preset_request", "message": "预设请求字段或JSON无效"}}, status=400)
            except OSError:
                return web.json_response({"error": {"code": "preset_library", "message": "预设库访问失败，当前表格与既存库保留"}}, status=503)
        return guarded

    async def body(request, required):
        data = bytearray()
        async for chunk in request.content.iter_chunked(8192):
            data.extend(chunk)
            if len(data) > MAX_BYTES: raise PresetError("preset_size", "请求最多2 MiB")
        value = strict_json(data.decode("utf-8"))
        keys(value, required)
        return value

    def project(value):
        return get_store().canonical(value["media_project"])

    @routes.get(PREFIX)
    @endpoint
    async def listing(request):
        if set(request.query) - {"cursor", "limit"}: raise PresetError("preset_page", "未知分页参数")
        result = await asyncio.to_thread(get_interview_library(request).listing, int(request.query.get("cursor", 0)), int(request.query.get("limit", 50)))
        return web.json_response(result)

    @routes.post(PREFIX)
    @endpoint
    async def create(request):
        value = await body(request, {"name", "state", "media_project"})
        template = capture_template(value["state"], project(value))
        saved = await asyncio.to_thread(get_interview_library(request).create, value["name"], template)
        return web.json_response(saved, status=201)

    @routes.post(PREFIX + "/import")
    @endpoint
    async def importing(request):
        value = await body(request, {"schema_version", "presets"})
        result = await asyncio.to_thread(get_interview_library(request).import_collection, value)
        return web.json_response({"presets": result}, status=201)

    @routes.post(PREFIX + "/export")
    @endpoint
    async def exporting(request):
        value = await body(request, {"preset_ids"})
        result = await asyncio.to_thread(get_interview_library(request).export, value["preset_ids"])
        return web.json_response(result)

    @routes.get(PREFIX + "/{preset_id}")
    @endpoint
    async def get(request):
        result = await asyncio.to_thread(get_interview_library(request).get, request.match_info["preset_id"])
        return web.json_response(result)

    @routes.put(PREFIX + "/{preset_id}")
    @endpoint
    async def update(request):
        value = await body(request, {"name", "preset_version", "state", "media_project"})
        template = capture_template(value["state"], project(value))
        saved = await asyncio.to_thread(get_interview_library(request).update, request.match_info["preset_id"], value["preset_version"], value["name"], template)
        return web.json_response(saved)

    @routes.patch(PREFIX + "/{preset_id}")
    @endpoint
    async def rename(request):
        value = await body(request, {"name", "preset_version"})
        saved = await asyncio.to_thread(get_interview_library(request).update, request.match_info["preset_id"], value["preset_version"], value["name"])
        return web.json_response(saved)

    @routes.delete(PREFIX + "/{preset_id}")
    @endpoint
    async def delete(request):
        value = await body(request, {"preset_version"})
        await asyncio.to_thread(get_interview_library(request).delete, request.match_info["preset_id"], value["preset_version"])
        return web.json_response({"deleted": True})

    @routes.post(PREFIX + "/{preset_id}/apply")
    @endpoint
    async def apply(request):
        value = await body(request, {"state", "media_project"})
        saved = await asyncio.to_thread(get_interview_library(request).get, request.match_info["preset_id"])
        result = apply_template(saved["template"], value["state"], project(value))
        return web.json_response({**result, "preset": {key: saved[key] for key in ("preset_id", "preset_version", "name")}})
