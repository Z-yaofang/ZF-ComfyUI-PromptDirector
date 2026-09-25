"""Timeline proxies preserve source frame order and presentation times."""
from fractions import Fraction
import hashlib
import importlib
import importlib.util
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "zf_media_preview_proxy", ROOT / "media_evidence" / "__init__.py",
    submodule_search_locations=[str(ROOT / "media_evidence")],
)
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
STORAGE = importlib.import_module(SPEC.name + ".storage")


def make_source(tmp_path, times):
    import av
    from PIL import Image

    source = tmp_path / "source.mkv"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("ffv1", rate=30)
        stream.width, stream.height, stream.pix_fmt = 600, 900, "yuv444p"
        stream.time_base = Fraction(1, 1000)
        for index, milliseconds in enumerate(times):
            frame = av.VideoFrame.from_image(Image.new("RGB", (600, 900), (index * 28, 35, 65)))
            frame.pts, frame.time_base = milliseconds, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    store = STORAGE.MediaStore(tmp_path / "input")
    path, handle, name = store.allocate(source.name)
    shutil.copyfile(source, path)
    return store, store.finish_import(path, handle, name)


def decoded(path):
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frames = list(container.decode(stream))
        return ([(float(frame.time), float(frame.to_rgb().to_ndarray()[0, 0, 0]))
                 for frame in frames], frames[0].width, frames[0].height)


@pytest.mark.parametrize("times", [
    [index * 33 for index in range(12)],
    [0, 33, 67, 133, 167, 233, 267, 333],
    [1000, 1033, 1100, 1133, 1200, 1233, 1300, 1333],
])
def test_proxy_retains_every_frame_and_source_pts_at_480p(tmp_path, times):
    store, asset = make_source(tmp_path, times)
    original = store.resolve(asset["source_handle"])
    source_frames, source_width, source_height = decoded(original)
    assert (source_width, source_height) == (600, 900)
    assert len(source_frames) == len(times)
    if len(times) == 8:
        intervals = [round(source_frames[i + 1][0] - source_frames[i][0], 3)
                     for i in range(len(times) - 1)]
        assert len(set(intervals)) > 1

    proxy = store.preview(asset["source_handle"], "proxy")
    proxy_frames, width, height = decoded(proxy)
    assert (width, height) == (320, 480)
    assert len(proxy_frames) == len(source_frames)
    for (source_time, source_red), (proxy_time, proxy_red) in zip(source_frames, proxy_frames):
        assert proxy_time == pytest.approx(source_time - source_frames[0][0], abs=0.001)
        assert proxy_red == pytest.approx(source_red, abs=5)


def test_existing_12fps_cache_is_not_reused(tmp_path):
    store, asset = make_source(tmp_path, [index * 33 for index in range(8)])
    handle = asset["source_handle"]
    old_key = hashlib.sha256((handle + "proxy" + "v1").encode()).hexdigest()
    old_cache = store.root / "cache" / (old_key + ".mp4")
    old_cache.write_bytes(b"old-12-fps-preview")
    proxy = store.preview(handle, "proxy")
    assert proxy != old_cache
    assert old_cache.read_bytes() == b"old-12-fps-preview"
    assert len(decoded(proxy)[0]) == 8
