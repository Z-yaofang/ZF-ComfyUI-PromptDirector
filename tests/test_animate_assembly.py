"""Real CPU codecs: exact clocks survive assembly and native SaveVideo remux."""

from fractions import Fraction
import importlib
import io
from pathlib import Path
import sys
import types

import av
import numpy as np
import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
PACKAGE = "zf_animate_assembly_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
ASSEMBLY = importlib.import_module(PACKAGE + ".animate_video.assembly")
ENCODING = ASSEMBLY


def chunks(tmp_path, fps):
    paths, rows = [], []
    cursor = 0
    for index, length in enumerate([8, 5, 1]):
        path = tmp_path / f"chunk-{index}.mp4"
        samples = round((cursor + length) * 44100 / fps) - round(cursor * 44100 / fps)
        frames = torch.full((length, 24, 32, 3), .15 + index * .25)
        wave = torch.arange(samples, dtype=torch.float32) / 44100
        wave = (.1 * torch.sin(wave * (300 + index * 100) * 6.2831853)).reshape(1, 1, -1).repeat(1, 2, 1)
        ENCODING.encode_video_chunk(frames, {"waveform": wave, "sample_rate": 44100}, fps, path)
        paths.append(path)
        rows.append({"frames": length, "audio_samples": samples})
        cursor += length
    return paths, {"fps": fps, "shape": [24, 32, 3], "segments": rows}


def test_intermediate_video_preserves_rgb_pixels_without_lossy_recompression(tmp_path):
    pixels = np.random.default_rng(73).integers(0, 256, (5, 24, 32, 3), dtype=np.uint8)
    images = torch.from_numpy(pixels).float() / 255
    sound = {"waveform": torch.zeros(1, 2, 5 * 1470), "sample_rate": 44100}
    path = tmp_path / "lossless.mp4"
    ASSEMBLY.encode_video_chunk(images, sound, 30, path)
    with av.open(str(path)) as source:
        restored = np.stack([frame.to_ndarray(format="rgb24") for frame in source.decode(video=0)])
    assert np.array_equal(restored, pixels)


@pytest.mark.parametrize("quality,codec,pixel_format,bt709", [
    ("兼容 · H.264 8位", "h264", "yuv420p", False),
    ("高画质 · H.264 BT.709", "h264", "yuv420p", True),
    ("高画质 · H.265 10位 BT.709", "hevc", "yuv420p10le", True),
])
def test_output_quality_profiles_preserve_clock_and_save_without_reencoding(tmp_path, quality, codec, pixel_format, bt709):
    paths, manifest = chunks(tmp_path, 30)
    result = ASSEMBLY.assemble_video(paths, manifest, tmp_path / "assembled.mp4", 30, quality)
    saved = tmp_path / "saved.mp4"
    result.save_to(str(saved), metadata={"quality": quality})
    for path in (result._animate_path, saved):
        ASSEMBLY._probe(str(path), 14, Fraction(30), round(14 * 44100 / 30))
        with av.open(str(path)) as source:
            video = source.streams.video[0]
            assert video.codec_context.name == codec
            assert video.codec_context.format.name == pixel_format
            if bt709:
                assert all(int(getattr(video.codec_context, field)) == 1 for field in (
                    "colorspace", "color_primaries", "color_trc", "color_range"))
                frame = next(source.decode(video=0))
                assert all(int(getattr(frame, field)) == 1 for field in (
                    "colorspace", "color_primaries", "color_trc", "color_range"))
    with av.open(str(result._animate_path)) as source, av.open(str(saved)) as copy:
        assert [bytes(packet) for packet in source.demux(video=0) if packet.dts is not None] == [
            bytes(packet) for packet in copy.demux(video=0) if packet.dts is not None]
    if codec == "hevc":
        transcoded = tmp_path / "explicit-h264.mp4"
        result.save_to(str(transcoded), codec=ASSEMBLY.Types.VideoCodec.H264)
        with av.open(str(transcoded)) as video:
            assert video.streams.video[0].codec_context.name == "h264"


def test_invalid_output_quality_does_not_publish_file(tmp_path):
    paths, manifest = chunks(tmp_path, 30)
    target = tmp_path / "assembled.mp4"
    with pytest.raises(ValueError, match="输出质量档位无效"):
        ASSEMBLY.assemble_video(paths, manifest, target, 30, "unknown")
    assert not target.exists()


def test_bt709_profile_converts_pixels_instead_of_only_adding_tags(tmp_path):
    frames = torch.zeros((2, 24, 32, 3))
    frames[..., 0] = 1
    path = tmp_path / "red.mp4"
    ASSEMBLY.encode_video_chunk(frames, {"waveform": torch.zeros(1, 2, 2940), "sample_rate": 44100}, 30, path)
    manifest = {"fps": 30, "shape": [24, 32, 3], "segments": [{"frames": 2, "audio_samples": 2940}]}
    luma = []
    for quality in ("兼容 · H.264 8位", "高画质 · H.264 BT.709"):
        result = ASSEMBLY.assemble_video([path], manifest, tmp_path / f"{len(luma)}.mp4", 30, quality)
        with av.open(str(result._animate_path)) as video:
            yuv = next(video.decode(video=0)).to_ndarray(format="yuv420p")
            luma.append(float(yuv[:24].mean()))
    assert luma[0] - luma[1] > 12


def inspect(path, fps, expected=14):
    fps = Fraction(str(fps)).limit_denominator(1_000_000)
    if isinstance(path, io.BytesIO):
        path.seek(0)
    with av.open(path) as source:
        stream = source.streams.video[0]
        assert stream.average_rate == fps
        assert stream.duration * stream.time_base == Fraction(expected, fps)
        frames = list(source.decode(video=0))
        assert len(frames) == expected
        assert [frame.pts * frame.time_base for frame in frames] == [Fraction(i, fps) for i in range(expected)]
        # Decoded picture order is preserved across the two joins.
        means = [float(frame.to_ndarray(format="rgb24").mean()) / 255 for frame in frames]
        assert means[7] < means[8] < means[13]
    if isinstance(path, io.BytesIO):
        path.seek(0)
    with av.open(path) as source:
        packet_ends = [Fraction(packet.pts + packet.duration) * packet.time_base
                       for packet in source.demux(video=0) if packet.pts is not None]
        assert max(packet_ends) == Fraction(expected, fps)


@pytest.mark.parametrize("fps", [12, 29, 59, 29.97, 30000 / 1001, 24000 / 1001, 60000 / 1001])
def test_streamed_assembly_and_default_native_save_preserve_clocks(tmp_path, fps):
    paths, manifest = chunks(tmp_path, fps)
    result = ASSEMBLY.assemble_video(paths, manifest, tmp_path / "assembled.mp4", fps)
    assert isinstance(result, ASSEMBLY.InputImpl.VideoFromFile)
    inspect(str(tmp_path / "assembled.mp4"), fps)
    components = result.get_components()
    assert components.images.shape == (14, 24, 32, 3)
    assert components.audio["waveform"].shape == (1, 2, round(14 * 44100 / fps))
    expected_audio = []
    for path, row in zip(paths, manifest["segments"]):
        with av.open(str(path)) as source:
            decoded = np.concatenate([frame.to_ndarray() for frame in source.decode(audio=0)], axis=1)
        expected_audio.append(decoded[:, :row["audio_samples"]])
    expected_audio = np.concatenate(expected_audio, axis=1)
    # Guard samples must not introduce silence/offset at a segment boundary.
    assert np.abs(components.audio["waveform"].numpy()[0] - expected_audio).mean() < .01
    for explicit in [False, True]:
        saved = tmp_path / f"saved-{explicit}.mp4"
        options = ({"format": ASSEMBLY.Types.VideoContainer.MP4,
                    "codec": ASSEMBLY.Types.VideoCodec.H264} if explicit else {})
        result.save_to(str(saved), metadata={"workflow": {"fixture": fps}}, **options)
        inspect(str(saved), fps)
        with av.open(str(saved)) as source:
            assert source.metadata["workflow"] == '{"fixture": ' + str(fps) + '}'
    memory = io.BytesIO()
    result.save_to(memory)
    inspect(memory, fps)


def test_invalid_chunk_is_not_published_over_existing_file(tmp_path):
    paths, manifest = chunks(tmp_path, 29)
    manifest["segments"][-1]["frames"] = 2
    target = tmp_path / "existing.mp4"
    target.write_bytes(b"keep-existing-result")
    with pytest.raises(ValueError, match="帧数"):
        ASSEMBLY.assemble_video(paths, manifest, target, 29)
    assert target.read_bytes() == b"keep-existing-result"
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_insufficient_audio_fails_instead_of_padding_or_using_next_segment(tmp_path):
    paths, manifest = chunks(tmp_path, 29)
    manifest["segments"][-1]["audio_samples"] += 10000
    with pytest.raises(ValueError, match="原声音轨短"):
        ASSEMBLY.assemble_video(paths, manifest, tmp_path / "invalid.mp4", 29)
    assert not (tmp_path / "invalid.mp4").exists()
