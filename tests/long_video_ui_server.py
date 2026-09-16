"""Isolated UI harness with synthetic metadata; no user's ComfyUI is touched."""

import asyncio
import importlib.util
import json
from pathlib import Path

from aiohttp import web


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("zv_long_fixture", ROOT / "tests" / "test_long_video_interview.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
S = __import__(fixture.PACKAGE + ".long_video.server", fromlist=["server"])


async def main():
    class Registry:
        canonical = staticmethod(fixture.C.normalize_project)
    S.get_store = lambda: Registry()
    routes = web.RouteTableDef()
    S.register_long_video_routes(routes)

    @routes.get("/scripts/app.js")
    async def app_stub(_request):
        return web.Response(text="export const app={registerExtension(){}};", content_type="text/javascript")

    @routes.get("/web/{file}")
    async def file(request):
        path = (ROOT / "web" / request.match_info["file"]).resolve()
        if path.parent != (ROOT / "web").resolve():
            raise web.HTTPForbidden()
        return web.FileResponse(path)

    @routes.get("/zf-media-evidence/preview")
    async def thumbnail(_request):
        return web.Response(text='<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#2d5b69"/><circle cx="80" cy="40" r="20" fill="#77cbbb"/></svg>', content_type="image/svg+xml")

    @routes.get("/")
    async def index(_request):
        source = json.dumps(fixture.source(), ensure_ascii=False)
        return web.Response(content_type="text/html", text="""<!doctype html><html><meta charset="UTF-8"><body style="margin:0;background:#081017;padding:16px"><main id="desk" style="height:760px"></main><main id="interview" style="height:850px;margin-top:18px"></main><script type="module">
import {attachDesk,attachInterview} from '/web/long_video.js';
import {defaultSettings,emptyInterview} from '/web/long_video_core.mjs';
window.sourceNode={id:1,widgets:[{name:'project_data',value:JSON.stringify(SOURCE)}],inputs:[]};
function node(id,key,value,host,inputs){return {id,widgets:[{name:key,value:JSON.stringify(value)}],properties:{},inputs:inputs.map(name=>({name})),size:[1100,750],setSize(){},graph:{setDirtyCanvas(){}},addDOMWidget(name,type,element){document.getElementById(host).append(element);return {};}};}
window.desk=node(2,'segment_data',defaultSettings(),'desk',['media_project']);desk.getInputNode=()=>sourceNode;attachDesk(desk);
window.interview=node(3,'interview_data',emptyInterview(),'interview',['segment_plan']);interview.getInputNode=()=>desk;attachInterview(interview);
</script></body></html>""".replace("SOURCE", source))

    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
