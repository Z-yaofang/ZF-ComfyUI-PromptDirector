"""Original-video, previous-PTS frame previews must never become project assets."""
import asyncio
import importlib
import importlib.util
from io import BytesIO
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "zf_media_exact_frame", ROOT / "media_evidence" / "__init__.py",
    submodule_search_locations=[str(ROOT / "media_evidence")],
)
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
STORAGE = importlib.import_module(SPEC.name + ".storage")
SERVER = importlib.import_module(SPEC.name + ".server")


def files(store):
    return {path.relative_to(store.root).as_posix(): path.read_bytes()
            for path in store.root.rglob("*") if path.is_file()}


@pytest.fixture
def source(tmp_path):
    import av
    from PIL import Image

    store = STORAGE.MediaStore(tmp_path / "input")
    fixture = tmp_path / "source.mkv"
    with av.open(str(fixture), "w") as container:
        stream = container.add_stream("ffv1", rate=30)
        stream.width, stream.height, stream.pix_fmt = 16, 12, "yuv444p"
        for number in range(12):
            picture = Image.new("RGB", (16, 12), (number * 20,) * 3)
            for packet in stream.encode(av.VideoFrame.from_image(picture)):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    path, handle, name = store.allocate(fixture.name)
    shutil.copyfile(fixture, path)
    return store, store.finish_import(path, handle, name)


def test_frame_is_from_original_with_previous_pts_and_no_persistence(source):
    from PIL import Image

    store, asset = source
    before = files(store)
    png, actual = store.frame_preview(asset["source_handle"], 0.15)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    # Matroska stores this fixture's timestamps in millisecond units.
    assert actual == pytest.approx(4 / 30, abs=0.001)
    with Image.open(BytesIO(png)) as image:
        assert image.size == (16, 12)
        assert 70 <= image.getpixel((0, 0))[0] <= 90
    assert files(store) == before


def test_rounded_up_pts_selects_nominal_frame_only_for_preview(source, tmp_path):
    from PIL import Image

    store, asset = source
    before = files(store)
    nominal_seconds = 5 / 30
    png, actual = store.frame_preview(asset["source_handle"], nominal_seconds)
    # The MKV time base is 1 ms: the fifth zero-based frame is at 0.167 s,
    # 0.000333 s after its nominal 5/30 request. It is still that frame.
    assert actual == pytest.approx(0.167, abs=1e-6)
    with Image.open(BytesIO(png)) as image:
        assert 90 <= image.getpixel((0, 0))[0] <= 110
    assert files(store) == before

    # The persistent screenshot contract deliberately retains its strict
    # previous-PTS behavior; this compatibility check must not be relaxed.
    strict = store.worker("screenshot", store.resolve(asset["source_handle"]),
                          tmp_path / "strict.png", source_seconds=nominal_seconds)
    assert strict["frame_seconds"] == pytest.approx(0.133, abs=1e-6)


@pytest.mark.parametrize("seconds", ["", "nan", "inf", "-1", "0.4", True])
def test_invalid_time_never_creates_frame_file(source, seconds):
    store, asset = source
    before = files(store)
    with pytest.raises(STORAGE.MediaError) as error:
        store.frame_preview(asset["source_handle"], seconds)
    assert error.value.code == "frame_time"
    assert files(store) == before


def test_unregistered_handle_and_failed_decode_leave_no_frame_file(source, monkeypatch):
    store, asset = source
    before = files(store)
    with pytest.raises(STORAGE.MediaError) as error:
        store.frame_preview("../../outside.mkv", 0.1)
    assert error.value.code == "unsafe_handle"

    def failed_worker(*_args, **_kwargs):
        raise STORAGE.MediaError("invalid_media", "decode failed")

    monkeypatch.setattr(store, "worker", failed_worker)
    with pytest.raises(STORAGE.MediaError) as error:
        store.frame_preview(asset["source_handle"], 0.1)
    assert error.value.code == "invalid_media"
    assert files(store) == before


def test_frame_response_is_bounded_and_cleaned(source, monkeypatch):
    store, asset = source
    before = files(store)
    monkeypatch.setattr(STORAGE, "MAX_FRAME_PREVIEW_BYTES", 16)

    def oversized(_operation, _source, output, *, source_seconds):
        Path(output).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
        return {"frame_seconds": 0.0}

    monkeypatch.setattr(store, "worker", oversized)
    with pytest.raises(STORAGE.MediaError) as error:
        store.frame_preview(asset["source_handle"], 0.1)
    assert error.value.code == "frame_limit"
    assert files(store) == before


def test_http_frame_png_pts_header_and_strict_query(source):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    store, asset = source
    before = files(store)

    async def exercise():
        routes = web.RouteTableDef()
        SERVER.register_media_routes(routes, lambda: store, lambda _request: None)
        app = web.Application()
        app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            params = {"source": asset["source_handle"], "seconds": "0.15"}
            response = await client.get("/zf-media-evidence/frame", params=params)
            assert response.status == 200
            assert response.content_type == "image/png"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert float(response.headers["X-ZF-Frame-Seconds"]) == pytest.approx(4 / 30, abs=0.001)
            assert (await response.read()).startswith(b"\x89PNG\r\n\x1a\n")

            response = await client.get("/zf-media-evidence/frame", params={**params, "variant": "proxy"})
            assert response.status == 400
            assert (await response.json())["error"]["code"] == "frame_fields"
            response = await client.get("/zf-media-evidence/frame", params=params,
                                        headers={"Origin": "https://different.example"})
            assert response.status == 400
            assert (await response.json())["error"]["code"] == "origin"

    asyncio.run(exercise())
    assert files(store) == before
