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
