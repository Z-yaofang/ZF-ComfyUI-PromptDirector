"""CPU regressions for annotated SAM3 VIDEO export; no model, GPU or cloud calls."""
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys
import types

import numpy as np
import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_sam3_tracking_test", ROOT / "sam3_tracking.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def packed_tracks(masks, original_size=None):
    pixels = np.asarray(masks, dtype=np.uint8)
    return {
        "packed_masks": torch.from_numpy(np.packbits(pixels, axis=-1, bitorder="little")),
        "n_frames": pixels.shape[0],
        "scores": [0.9] * pixels.shape[1],
        "orig_size": original_size or tuple(pixels.shape[-2:]),
    }


def tracks_fixture():
    masks = np.zeros((3, 2, 96, 160), dtype=np.uint8)
    masks[[0, 2], 0, 10:70, 8:64] = 1
    masks[:, 1, 20:84, 88:152] = 1
    return packed_tracks(masks), torch.full((3, 96, 160, 3), 0.2)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "folder_paths", types.SimpleNamespace(get_temp_directory=lambda: str(tmp_path)))
    monkeypatch.setattr(M, "_check_interruption", lambda: None)
    monkeypatch.setattr(M, "_native_video", lambda path: Path(path))
    return tmp_path


def test_stable_slot_colors_and_numbers_when_first_object_disappears(monkeypatch):
    tracks, images = tracks_fixture()
    before_masks, before_images = tracks["packed_masks"].clone(), images.clone()
    numbers = []
    draw = M._draw_number

    def record(frame, number, cx, cy, scale):
        numbers.append(number)
        draw(frame, number, cx, cy, scale)

    monkeypatch.setattr(M, "_draw_number", record)
    rendered = []
    for index, expected in enumerate(([0, 1], [1], [0, 1])):
        numbers.clear()
        rendered.append(M._render_frame(images[index], tracks["packed_masks"][index], 0.5, 2, False, []))
        assert numbers == expected
    color = np.rint((0.2 * 0.5 + np.asarray(M._color(1)) * 0.5) * 255).astype(np.uint8)
    for frame in rendered:
        np.testing.assert_array_equal(frame[22, 90], color)
    assert torch.equal(before_masks, tracks["packed_masks"])
    assert torch.equal(before_images, images)
    assert np.any(np.all(rendered[1] == 255, axis=-1)), "Readable white number is missing"
    assert np.any(np.all(rendered[1] == 0, axis=-1)), "Black number edge is missing"


def test_low_bit_first_masks_and_lower_slot_owns_overlaps(monkeypatch):
    monkeypatch.setattr(M, "_draw_number", lambda *args: None)
    masks = np.zeros((1, 2, 8, 16), dtype=np.uint8)
    masks[0, 0, 2:6, 0:8] = 1
    masks[0, 1, 2:6, 4:16] = 1
    tracks = packed_tracks(masks)
    result = M._render_frame(torch.zeros((8, 16, 3)), tracks["packed_masks"][0], 1.0, 1, False, [])
    np.testing.assert_array_equal(result[2, 0], np.rint(np.asarray(M._color(0)) * 255).astype(np.uint8))
    np.testing.assert_array_equal(result[2, 6], result[2, 0])
    np.testing.assert_array_equal(result[2, 15], np.rint(np.asarray(M._color(1)) * 255).astype(np.uint8))
    np.testing.assert_array_equal(result[1, 0], [0, 0, 0])


def test_non_symmetric_byte_uses_official_little_endian_mask_bits(monkeypatch):
    monkeypatch.setattr(M, "_draw_number", lambda *args: None)
    packed_frame = torch.zeros((1, 4, 1), dtype=torch.uint8)
    packed_frame[0, 1, 0] = 0b01000001
    result = M._render_frame(torch.zeros((4, 8, 3)), packed_frame, 1.0, 1, False, [])
    assert np.any(result[1, 0]) and np.any(result[1, 6])
    for column in (1, 2, 3, 4, 5, 7):
        np.testing.assert_array_equal(result[1, column], [0, 0, 0])


def test_more_than_twelve_objects_get_distinct_deterministic_colors():
    colors = [tuple(np.rint(np.asarray(M._color(i)) * 255).astype(int)) for i in range(32)]
    assert len(set(colors)) == len(colors)
    assert colors[:12] == [tuple(np.rint(np.asarray(c) * 255).astype(int)) for c in M._COLORS]
    assert M._color(17) == M._color(17)
    assert M._color(0) != M._color(12)


def test_resize_and_opacity_do_not_paint_background(monkeypatch):
    monkeypatch.setattr(M, "_draw_number", lambda *args: None)
    masks = np.zeros((1, 1, 4, 8), dtype=np.uint8)
    masks[0, 0, 1:3, 2:6] = 1
    tracks = packed_tracks(masks, original_size=(16, 32))
    source = torch.full((16, 32, 3), 0.4)
    clear = M._render_frame(source, tracks["packed_masks"][0], 0.0, 1, False, [])
    full = M._render_frame(source, tracks["packed_masks"][0], 1.0, 1, False, [])
    np.testing.assert_array_equal(clear, np.full((16, 32, 3), 102, dtype=np.uint8))
    np.testing.assert_array_equal(full[0, 0], clear[0, 0])
    np.testing.assert_array_equal(full[4, 8], np.rint(np.asarray(M._color(0)) * 255).astype(np.uint8))


@pytest.mark.parametrize("field,value", [
    ("fps", float("nan")), ("fps", 0), ("fps", True), ("opacity", 1.1),
    ("opacity", float("inf")), ("label_scale", -1), ("label_scale", True), ("show_scores", 1),
])
def test_bad_controls_fail_before_writing(runtime, field, value):
    tracks, images = tracks_fixture()
    kwargs = {field: value}
    with pytest.raises(ValueError):
        M.ZVSAM3TrackVideo().render_video(tracks, images, **kwargs)
    assert not list(runtime.iterdir())


def test_mismatched_or_noncanonical_track_data_is_rejected(runtime):
    tracks, images = tracks_fixture()
    for bad in (
        {**tracks, "n_frames": 2},
        {**tracks, "orig_size": (True, 160)},
        {**tracks, "packed_masks": tracks["packed_masks"].float()},
        {**tracks, "packed_masks": tracks["packed_masks"][:1]},
        {key: value for key, value in tracks.items() if key != "packed_masks"},
    ):
        with pytest.raises(ValueError):
            M.ZVSAM3TrackVideo().render_video(bad, images)
    with pytest.raises(ValueError):
        M.ZVSAM3TrackVideo().render_video(tracks, images[..., :2])
    with pytest.raises(ValueError):
        M.ZVSAM3TrackVideo().render_video(tracks, images.to(torch.uint8))
    assert not list(runtime.iterdir())


def test_confidence_controls_and_multidigit_label_are_visible(monkeypatch):
    tracks, images = tracks_fixture()
    calls = []
    draw = M._draw_number
    monkeypatch.setattr(M, "_draw_number", lambda frame, number, *args: (calls.append(number), draw(frame, number, *args)))
    M._render_frame(images[0], tracks["packed_masks"][0], 0.5, 2, True, [0.9, 0.84])
    assert calls == [0, 90, 1, 84]
    frame = np.full((12, 24, 3), 0.5, dtype=np.float32)
    draw(frame, 123, 23, 11, 6)
    assert frame.shape == (12, 24, 3)
    assert np.all(np.isfinite(frame))
    assert np.any(frame == 1)


def test_real_h264_encode_has_exact_timeline_and_odd_edge_padding(runtime):
    import av

    images = torch.full((5, 47, 79, 3), 0.4)
    images[:, :, -1] = torch.tensor([0.8, 0.1, 0.1])
    images[:, -1] = torch.tensor([0.1, 0.8, 0.1])
    tracks = {"packed_masks": None, "n_frames": 5, "orig_size": (47, 79), "scores": []}
    video, report = M.ZVSAM3TrackVideo().render_video(tracks, images, fps=29.97)
    assert video.is_file() and video.suffix == ".mp4"
    assert "80×48" in report and "无音轨" in report
    assert not list(runtime.glob("*.partial.mp4"))
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "h264"
        assert stream.average_rate == Fraction(2997, 100)
        frames = list(container.decode(video=0))
        assert len(frames) == 5
        assert (frames[0].width, frames[0].height) == (80, 48)
        assert float(frames[-1].time) == pytest.approx(4 / 29.97, abs=1e-4)
        pixels = frames[0].to_ndarray(format="rgb24").astype(int)
        assert np.max(abs(pixels[-1] - pixels[-2])) < 20
        assert np.max(abs(pixels[:, -1] - pixels[:, -2])) < 20


def test_repeated_exports_do_not_overwrite_and_input_is_unchanged(runtime):
    tracks, images = tracks_fixture()
    before = images.clone()
    first, _ = M.ZVSAM3TrackVideo().render_video(tracks, images, fps=12)
    first_bytes = first.read_bytes()
    second, _ = M.ZVSAM3TrackVideo().render_video(tracks, images, fps=12)
    assert first != second and first.read_bytes() == first_bytes
    assert second.is_file()
    assert torch.equal(before, images)


def test_interruption_and_invalid_pixels_remove_only_owned_files(runtime, monkeypatch):
    tracks, images = tracks_fixture()
    unrelated = runtime / "keep.txt"
    unrelated.write_text("keep")

    def interrupt():
        raise RuntimeError("cancelled")

    monkeypatch.setattr(M, "_check_interruption", interrupt)
    with pytest.raises(RuntimeError, match="cancelled"):
        M.ZVSAM3TrackVideo().render_video(tracks, images)
    monkeypatch.setattr(M, "_check_interruption", lambda: None)
    images[1, 0, 0, 0] = float("nan")
    with pytest.raises(ValueError, match="非有限"):
        M.ZVSAM3TrackVideo().render_video(tracks, images)
    assert list(runtime.iterdir()) == [unrelated]


def test_video_adapter_failure_removes_completed_temporary_file(runtime, monkeypatch):
    tracks, images = tracks_fixture()

    def broken_adapter(path):
        raise RuntimeError("native VIDEO unavailable")

    monkeypatch.setattr(M, "_native_video", broken_adapter)
    with pytest.raises(RuntimeError, match="native VIDEO"):
        M.ZVSAM3TrackVideo().render_video(tracks, images)
    assert not list(runtime.iterdir())
