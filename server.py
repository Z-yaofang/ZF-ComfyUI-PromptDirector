import json
from pathlib import Path

from aiohttp import web
from server import PromptServer


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
            "default_combinations": _read("default_combinations.json"),
            "worldviews": _read("worldviews.json"),
        }
    )


@PromptServer.instance.routes.get("/zf-prompt-director/thumbnail/{name}")
async def thumbnail(request):
    name = Path(request.match_info["name"]).name
    path = (THUMB_DIR / name).resolve()
    if path.parent != THUMB_DIR.resolve() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)
