"""Isolated Animate UI harness; synthetic sources, no Comfy process or GPU."""
import asyncio
import importlib
import json
import sys
import tempfile
import types
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("animate_ui_fixture")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
C = importlib.import_module(package.__name__ + ".media_evidence.contract")
S = importlib.import_module(package.__name__ + ".animate_video.server")
STORAGE = importlib.import_module(package.__name__ + ".media_evidence.storage")


def fixture():
    project = C.empty_project()
    project["assets"] = [
        {"asset_id": "v1", "name": "motion.mp4", "kind": "video", "source_handle": "originals/" + "a" * 32 + ".mp4", "probe": {"size_bytes": 100, "duration_seconds": 24, "width": 640, "height": 360, "fps": 30, "frame_count": 720, "frame_count_exact": True, "vfr": False, "has_audio": True, "sample_rate": 48000, "channels": 2, "codec": "h264"}},
        {"asset_id": "p1", "name": "character.png", "kind": "picture", "source_handle": "originals/" + "b" * 32 + ".png", "probe": {"size_bytes": 100, "duration_seconds": None, "width": 640, "height": 360, "fps": None, "frame_count": None, "frame_count_exact": False, "vfr": None, "has_audio": False, "sample_rate": None, "channels": None, "codec": "png"}},
    ]
    project["video_track"] = [{"clip_id": f"clip{index}", "asset_id": "v1", "timeline_in_seconds": start / 30,
        "source_in_seconds": start / 30, "source_out_seconds": end / 30, "source_audio_enabled": True,
        "audio_link_id": f"a{index}"} for index, (start, end) in enumerate([(0, 200), (200, 400), (400, 610)], 1)]
    project["picture_track"] = [{"item_id": f"picture{index}", "asset_id": "p1", "order": index} for index in range(1, 4)]
    project["audio_track"] = [{"clip_id": clip["audio_link_id"], "asset_id": "v1", "origin": "video_source",
        "linked_video_clip_id": clip["clip_id"], "source_video_clip_id": clip["clip_id"],
        "timeline_in_seconds": clip["timeline_in_seconds"], "source_in_seconds": clip["source_in_seconds"],
        "source_out_seconds": clip["source_out_seconds"], "enabled": True} for clip in project["video_track"]]
    return C.normalize_project(project)


async def main():
    routes = web.RouteTableDef()
    source = fixture()
    temporary = tempfile.TemporaryDirectory(prefix="animate-ui-")
    store = STORAGE.MediaStore(temporary.name)
    records = {row["source_handle"]: row for row in source["assets"]}

    def record(handle):
        if handle not in records:
            raise STORAGE.MediaError("source_unavailable", "测试素材不存在")
        return records[handle]

    store.record = record
    S.get_store = lambda: store
    S.register_animate_routes(routes)

    @routes.get("/scripts/app.js")
    async def app_stub(_request):
        return web.Response(text="export const app={extensions:[],registerExtension(value){this.extensions.push(value)}};", content_type="text/javascript")

    @routes.get("/web/{file}")
    async def file(request):
        path = (ROOT / "web" / request.match_info["file"]).resolve()
        if path.parent != (ROOT / "web").resolve():
            raise web.HTTPForbidden()
        return web.FileResponse(path)

    @routes.get("/zf-media-evidence/preview")
    async def thumbnail(_request):
        return web.Response(text='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="100"><rect width="80" height="100" fill="#214a44"/><circle cx="40" cy="30" r="15" fill="#94d9c8"/><path d="M15 90L25 50H55L65 90" fill="#94d9c8"/></svg>', content_type="image/svg+xml")

    @routes.get("/")
    async def index(_request):
        return web.Response(content_type="text/html", text="""<!doctype html><meta charset="utf-8"><body style="margin:0;padding:15px;background:#0a121b"><main id="host" style="height:760px;width:1150px"></main><div id="preview-host"></div><script type="module">
import {attachAnimateDesk} from '/web/animate_video.js';
import {defaultSettings} from '/web/animate_video_core.mjs';
import {app} from '/scripts/app.js';
window.sourceNode={id:1,widgets:[{name:'project_data',value:JSON.stringify(SOURCE)}],inputs:[]};
window.fpsNode={id:3,type:'FloatConstant',widgets:[{name:'value',value:30}],inputs:[]};
window.desk={id:2,widgets:[{name:'segment_data',value:JSON.stringify(defaultSettings())}],inputs:[{name:'media_project'},{name:'fps',link:1}],size:[1100,720],setSize(){},graph:{setDirtyCanvas(){}},getInputNode(index){return index===1?fpsNode:sourceNode;},addDOMWidget(name,type,element){document.getElementById('host').append(element);return {};}};
attachAnimateDesk(desk);
const previews=app.extensions.find(row=>row.name==='ZV.AnimateRunPreviews');
class GateNode{constructor(){this.size=[410,180]}addDOMWidget(name,type,element){document.getElementById('preview-host').append(element);return {}}setSize(value){this.size=value}}
class EndNode{constructor(){this.size=[380,240]}addDOMWidget(name,type,element){document.getElementById('preview-host').append(element);return {}}setSize(value){this.size=value}}
await previews.beforeRegisterNodeDef(GateNode,{name:'ZVAnimateMaskGate'});
await previews.beforeRegisterNodeDef(EndNode,{name:'ZVAnimateExecutionEnd'});
window.gateNode=new GateNode();gateNode.onNodeCreated();
window.endNode=new EndNode();endNode.onNodeCreated();
</script>""".replace("SOURCE", json.dumps(source, ensure_ascii=False)))

    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        temporary.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
