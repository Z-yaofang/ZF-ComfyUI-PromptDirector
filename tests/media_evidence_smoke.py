"""Run with ComfyUI's Python; generates all media in an isolated temporary input.

No pytest dependency. Exit 77 means a required decoder/encoder is unavailable.
--serve starts an isolated UI harness on an OS-selected localhost port.
"""
import asyncio
import hashlib
import importlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_media_smoke", ROOT / "media_evidence" / "__init__.py", submodule_search_locations=[str(ROOT / "media_evidence")])
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
STORAGE = importlib.import_module(SPEC.name + ".storage")
C = importlib.import_module(SPEC.name + ".contract")


def fixtures(directory):
    from PIL import Image, ImageDraw
    import av  # noqa: F401 -- explicit capability check
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    picture = directory / "generated-picture.png"
    image = Image.new("RGB", (320, 180), "#16324f")
    draw = ImageDraw.Draw(image); draw.rectangle((30, 40, 140, 145), fill="#54dce6"); draw.ellipse((180, 45, 275, 140), fill="#ffd166")
    image.save(picture)
    sound = directory / "generated-audio.wav"
    with wave.open(str(sound), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"".join(struct.pack("<h", int((3000+9000*i/32000) * math.sin(i*2*math.pi*440/16000))) for i in range(32000)))
    video = directory / "generated-video.mp4"
    result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-loop", "1", "-framerate", "24", "-i", str(picture), "-i", str(sound), "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-shortest", str(video)], capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode: raise ImportError("FFmpeg test encoder unavailable")
    return [picture, video, sound]


async def application(directory, fixture_paths):
    from aiohttp import web
    server = importlib.import_module(SPEC.name + ".server")
    store = STORAGE.MediaStore(directory / "input")
    presets = importlib.import_module(SPEC.name + ".preset_store")
    routes = web.RouteTableDef(); server.register_media_routes(routes, lambda: store, lambda request: presets.PresetLibrary(directory / "user" / "default"))
    app = web.Application(client_max_size=2*1024*1024)
    app.add_routes(routes)

    async def index(_request):
        html = '''<!doctype html><meta charset="utf-8"><title>ZF media isolated harness</title><style>body{margin:20px;background:#10151d}.mount{width:1180px;height:1000px}#outside-canvas{width:1180px;height:70px;background:#293342;color:#aabbcc;margin-top:10px}</style><div id="mount" class="mount"></div><div id="outside-canvas">Independent canvas drop test area</div><script type="module">
import '/extensions/media_evidence_desk.js';
import {app} from '/scripts/app.js';
import {freshProject} from '/extensions/media_evidence_core.mjs';
window.deskNode={comfyClass:'ZVUniversalMediaEvidenceDesk',type:'ZVUniversalMediaEvidenceDesk',widgets:[{name:'project_data',value:localStorage.getItem('project')||JSON.stringify(freshProject())}],properties:JSON.parse(localStorage.getItem('view')||'{}'),size:[1180,860],setSize(){},setDirtyCanvas(){},addDOMWidget(name,type,root){document.getElementById('mount').append(root);return {};}};
app.extensions.find(extension=>extension.name==='ZV.UniversalMediaEvidenceDesk').nodeCreated(window.deskNode);
window.saveWorkflow=()=>{localStorage.setItem('project',deskNode.widgets[0].value);localStorage.setItem('view',JSON.stringify(deskNode.properties));};
window.canvasDropLog=[];window.loadImageNodes=0;window.lastMediaDragTypes=[];
document.getElementById('outside-canvas').addEventListener('dragover',event=>event.preventDefault());
document.getElementById('outside-canvas').addEventListener('drop',event=>{event.preventDefault();canvasDropLog.push([...event.dataTransfer.types]);if(event.dataTransfer.types.some(t=>['text/uri-list','text/plain','Files'].includes(t)))loadImageNodes++;});
document.addEventListener('dragover',event=>{window.lastMediaDragTypes=[...event.dataTransfer.types];},{capture:true});
</script>'''
        return web.Response(text=html, content_type="text/html")

    async def script(request):
        name = request.match_info["name"]
        if name == "app.js": return web.Response(text="export const app={extensions:[],registerExtension(extension){this.extensions.push(extension);}};", content_type="application/javascript")
        if name == "api.js": return web.Response(text="export const api={apiURL:p=>p,fetchApi:(p,o)=>fetch(p,o)};", content_type="application/javascript")
        raise web.HTTPNotFound()

    async def extension(request):
        name = request.match_info["name"]
        if name not in {"media_evidence_desk.js", "media_evidence_core.mjs", "media_evidence_presets.mjs", "media_evidence_outlets.mjs", "media_processing_presets.json", "media_evidence_desk.css", "dom_widget_layout.mjs"}: raise web.HTTPNotFound()
        return web.FileResponse(ROOT / "web" / name)

    async def fixture_list(_request):
        return web.json_response([str(p) for p in fixture_paths])

    app.router.add_get("/", index); app.router.add_get("/scripts/{name}", script); app.router.add_get("/extensions/{name}", extension); app.router.add_get("/fixtures", fixture_list)
    return app, store


async def smoke(directory, paths):
    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer
    app, store = await application(directory, paths)
    count = 0
    async with TestClient(TestServer(app)) as client:
        assets = []
        for path in paths:
            form = aiohttp.FormData(); form.add_field("file", path.read_bytes(), filename=path.name)
            response = await client.post("/zf-media-evidence/upload", data=form)
            data = await response.json(); assert response.status == 200, data
            assets.append(data["asset"]); count += 1
        assert [a["kind"] for a in assets] == ["picture", "video", "audio"]
        assert assets[1]["probe"]["has_audio"] and assets[1]["probe"]["frame_count"] == 48
        assert assets[1]["probe"]["fps"] == 24 and assets[1]["probe"]["frame_count_exact"]
        for asset, variants in [(assets[0], ["original", "thumbnail"]), (assets[1], ["proxy", "audio", "peaks", "thumbnail"]), (assets[2], ["audio", "peaks"])]:
            source = store.resolve(asset["source_handle"]); original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            for variant in variants:
                response = await client.get("/zf-media-evidence/preview", params={"source": asset["source_handle"], "variant": variant})
                assert response.status == 200, await response.text()
                body = await response.read(); assert body
                if variant == "peaks":
                    peaks = json.loads(body)["peaks"]; assert len(peaks) == 1024 and .1 < max(peaks) <= 1
                if variant == "proxy":
                    proxy = await asyncio.to_thread(store.preview, asset["source_handle"], variant)
                    facts = await asyncio.to_thread(store.worker, "probe", proxy)
                    assert not facts["probe"]["has_audio"] and facts["probe"]["fps"] == 24
                count += 1
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
        p = C.empty_project(); p["assets"] = assets
        response = await client.post("/zf-media-evidence/normalize", json=p)
        assert response.status == 200 and not (await response.json())["project"]["validation"]["errors"]; count += 1
        response = await client.get("/zf-media-evidence/preview", params={"source": "../../secret"})
        data = await response.json(); assert response.status == 400 and str(directory) not in json.dumps(data); count += 1
        response = await client.post("/zf-media-evidence/normalize", json=p, headers={"Origin": "https://unrelated.example"})
        assert response.status == 400 and (await response.json())["error"]["code"] == "origin"; count += 1
        response = await client.post("/zf-media-evidence/normalize", data='{"x":1,"x":2}')
        assert response.status == 400; count += 1
        form = aiohttp.FormData(); form.add_field("file", b"not media", filename="bad.mp4")
        before = len(list((store.root / "originals").iterdir()))
        response = await client.post("/zf-media-evidence/upload", data=form)
        assert response.status == 400 and len(list((store.root / "originals").iterdir())) == before; count += 1
        from PIL import Image
        oversized = io.BytesIO(); Image.new("RGB", (17000, 1)).save(oversized, "PNG")
        form = aiohttp.FormData(); form.add_field("file", oversized.getvalue(), filename="wide.png")
        response = await client.post("/zf-media-evidence/upload", data=form)
        assert response.status == 400 and (await response.json())["error"]["code"] == "image_limit"; count += 1
        server = importlib.import_module(SPEC.name + ".server")
        original_limit = server.MAX_UPLOAD; server.MAX_UPLOAD = 10
        try:
            form = aiohttp.FormData(); form.add_field("file", paths[0].read_bytes(), filename="large.png")
            response = await client.post("/zf-media-evidence/upload", data=form)
            assert response.status == 400 and (await response.json())["error"]["code"] == "upload_limit"; count += 1
        finally: server.MAX_UPLOAD = original_limit
        # Presets use a separate temporary user directory and the real same-origin endpoints.
        response = await client.get("/zf-media-evidence/presets")
        library = await response.json(); assert response.status == 200 and len(library["builtins"]) == 3 and library["users"] == []; count += 1
        snapshot = library["builtins"][1]["snapshot"]
        response = await client.post("/zf-media-evidence/presets", json={"snapshot": snapshot})
        first = (await response.json())["preset"]; assert response.status == 200 and first["preset_id"].startswith("user."); count += 1
        response = await client.get("/zf-media-evidence/presets")
        assert (await response.json())["users"] == [first]; count += 1
        edited = json.loads(json.dumps(snapshot)); edited["name"] = "Endpoint fixture"; edited["rules"].update(max_frames=720, max_seconds=30)
        response = await client.put("/zf-media-evidence/presets/" + first["preset_id"], json={"snapshot": edited, "preset_version": 1})
        second = (await response.json())["preset"]; assert response.status == 200 and second["preset_version"] == 2; count += 1
        frozen = C.empty_project(); frozen["processing_preset"] = first; frozen["processing_window"]["end_seconds"] = 17
        response = await client.post("/zf-media-evidence/normalize", json=frozen)
        normalized = (await response.json())["project"]; assert normalized["processing_preset"] == first and not normalized["validation"]["errors"] and not normalized["preset_compatibility"]["compatible"]; count += 1
        response = await client.put("/zf-media-evidence/presets/" + first["preset_id"], json={"snapshot": edited, "preset_version": 1})
        assert response.status == 409 and (await response.json())["error"]["code"] == "preset_conflict"; count += 1
        response = await client.delete("/zf-media-evidence/presets/" + first["preset_id"], json={"preset_version": 1})
        assert response.status == 409; count += 1
        response = await client.delete("/zf-media-evidence/presets/builtin.generic", json={"preset_version": 1})
        assert response.status == 400 and (await response.json())["error"]["code"] == "preset_builtin"; count += 1
        response = await client.put("/zf-media-evidence/presets/builtin.generic", json={"snapshot": edited, "preset_version": 1})
        assert response.status == 400; count += 1
        response = await client.post("/zf-media-evidence/presets", json={"snapshot": edited, "path": "../../outside.json"})
        assert response.status == 400 and (await response.json())["error"]["code"] == "preset_fields"; count += 1
        response = await client.post("/zf-media-evidence/presets", json={"snapshot": edited}, headers={"Origin": "https://unrelated.example"})
        assert response.status == 400 and (await response.json())["error"]["code"] == "origin"; count += 1
        invalid = json.loads(json.dumps(edited)); invalid["rules"]["min_frames"] = 1000
        response = await client.post("/zf-media-evidence/presets", json={"snapshot": invalid})
        assert response.status == 400 and "规则冲突" in (await response.json())["error"]["message"]; count += 1
        response = await client.post("/zf-media-evidence/presets", data='{"snapshot":' + ' '*17000 + 'null}')
        assert response.status == 400 and (await response.json())["error"]["code"] == "preset_size"; count += 1
        response = await client.get("/zf-media-evidence/presets")
        assert (await response.json())["users"] == [second]; count += 1
        response = await client.delete("/zf-media-evidence/presets/" + first["preset_id"], json={"preset_version": 2})
        assert response.status == 200; response = await client.get("/zf-media-evidence/presets"); assert (await response.json())["users"] == []; count += 1
    print(f"MEDIA_SMOKE_OK {count} real upload/probe/preview/security checks", flush=True)


async def main():
    with tempfile.TemporaryDirectory(prefix="zf-media-evidence-test-") as temporary:
        directory = Path(temporary)
        try: paths = fixtures(directory)
        except (ImportError, FileNotFoundError) as error:
            print("SKIP: media dependency/encoder unavailable: " + str(error)); return 77
        if "--serve" in sys.argv:
            from aiohttp import web
            app, _store = await application(directory, paths)
            runner = web.AppRunner(app); await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
            print("HARNESS_URL http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]), flush=True)
            try: await asyncio.Event().wait()
            finally: await runner.cleanup()
        else: await smoke(directory, paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
