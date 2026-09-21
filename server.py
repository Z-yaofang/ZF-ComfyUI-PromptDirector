import json
from pathlib import Path

from aiohttp import web
from server import PromptServer
from .media_evidence.runtime import get_store as get_media_store
from .media_evidence.runtime import get_preset_library
from .media_evidence.server import register_media_routes
from .h3_focus.server import register_interview_routes
from .long_video.server import register_long_video_routes
from .animate_video.server import register_animate_routes

register_media_routes(PromptServer.instance.routes, get_media_store, get_preset_library)
register_interview_routes(PromptServer.instance.routes)
register_long_video_routes(PromptServer.instance.routes)
register_animate_routes(PromptServer.instance.routes)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
THUMB_DIR = ROOT / "web" / "thumbnails"


def _read(name):
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@PromptServer.instance.routes.get("/zf-prompt-director/catalog")
async def catalog(_request):
    return web.json_response(
        {
            "purposes": _read("purposes.json"),
            "visual_methods": _read("visual_methods.json"),
            "purpose_visual_recommendations": _read("purpose_visual_recommendations.json"),
            "default_combinations": _read("default_combinations.json"),
        }
    )


@PromptServer.instance.routes.get("/zf-prompt-director/portrait-catalog")
async def portrait_catalog(_request):
    return web.json_response(_read("portrait_generator_v12.json"))


@PromptServer.instance.routes.get("/zf-prompt-director/thumbnail/{name}")
async def thumbnail(request):
    name = Path(request.match_info["name"]).name
    path = (THUMB_DIR / name).resolve()
    if path.parent != THUMB_DIR.resolve() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)
