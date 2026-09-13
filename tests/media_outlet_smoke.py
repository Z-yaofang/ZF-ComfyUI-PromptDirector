"""Exercise real outlet nodes with generated media, without a running ComfyUI server."""
import copy
from fractions import Fraction
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_outlet_smoke", ROOT / "media_evidence" / "__init__.py", submodule_search_locations=[str(ROOT / "media_evidence")])
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
C = importlib.import_module(SPEC.name + ".contract")
S = importlib.import_module(SPEC.name + ".storage")


def make_fixtures(directory):
    import av
    import numpy as np
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    red, green = directory / "red-rgb.png", directory / "green-rgba.png"
    Image.new("RGB", (32, 24), (255, 0, 0)).save(red)
    Image.new("RGBA", (17, 11), (0, 255, 0, 100)).save(green)
    standalone = directory / "stepped-mono.wav"
    samples = np.full(3 * 44100, 8192, dtype="<i2")
    samples[44100:88200] = 16384
    samples[88200:] = -4096
    with wave.open(str(standalone), "wb") as sound:
        sound.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        sound.writeframes(samples.tobytes())

    def encode(name, voiced):
        path = directory / name
        with av.open(str(path), "w") as container:
            video = container.add_stream("ffv1", rate=12)
            video.width, video.height, video.pix_fmt = 32, 24, "yuv444p"
            audio = container.add_stream("pcm_s16le", rate=48000) if voiced else None
            if audio:
                audio.layout = "mono"
            for index in range(36):
                pixels = np.empty((24, 32, 3), dtype=np.uint8)
                pixels[:] = (index * 6, 50, 100)
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                frame.pts, frame.time_base = index, Fraction(1, 12)
                for packet in video.encode(frame):
                    container.mux(packet)
                if audio:
                    sound = av.AudioFrame.from_ndarray(np.full((1, 4000), 6554, dtype=np.int16), format="s16", layout="mono")
                    sound.sample_rate, sound.pts, sound.time_base = 48000, index * 4000, Fraction(1, 48000)
                    for packet in audio.encode(sound):
                        container.mux(packet)
            for packet in video.encode(None):
                container.mux(packet)
            if audio:
                for packet in audio.encode(None):
                    container.mux(packet)
        return path

    return [red, green, encode("silent.mkv", False), encode("voiced.mkv", True), standalone]


def imported_project(directory):
    store = S.MediaStore(directory / "input")
    assets = []
    for source in make_fixtures(directory / "fixtures"):
        path, handle, name = store.allocate(source.name)
        shutil.copyfile(source, path)
        assets.append(store.finish_import(path, handle, name))
    p = C.empty_project()
    p["assets"] = assets
    p["processing_window"].update(start_seconds=10.5, end_seconds=13.5, fps=10)
    p["picture_track"] = [dict(item_id="green", asset_id=assets[1]["asset_id"], order=1), dict(item_id="red", asset_id=assets[0]["asset_id"], order=2)]
    p["video_track"] = [dict(clip_id="silent", asset_id=assets[2]["asset_id"], timeline_in_seconds=12.75, source_in_seconds=.5, source_out_seconds=1.5, source_audio_enabled=False, audio_link_id=None), dict(clip_id="voiced", asset_id=assets[3]["asset_id"], timeline_in_seconds=11, source_in_seconds=.25, source_out_seconds=1.75, source_audio_enabled=True, audio_link_id="original")]
    p["audio_track"] = [dict(clip_id="original", asset_id=assets[3]["asset_id"], timeline_in_seconds=11, source_in_seconds=.25, source_out_seconds=1.75, origin="video_source", enabled=True, linked_video_clip_id="voiced", source_video_clip_id="voiced"), dict(clip_id="independent", asset_id=assets[4]["asset_id"], timeline_in_seconds=11.75, source_in_seconds=.25, source_out_seconds=1.75, origin="standalone", enabled=True, linked_video_clip_id=None, source_video_clip_id=None)]
    assert not store.canonical(p)["validation"]["errors"]
    return store, p


def assert_private_manifest(text, directory):
    manifest = json.loads(text)
    assert str(directory).lower() not in text.lower()
    for token in ("file://", "http://", "https://", "E:\\", "C:\\", "E:/", "C:/"):
        assert token not in text
    return manifest


def run_real_checks(directory):
    import numpy as np
    import torch

    nodes = importlib.import_module(SPEC.name + ".outlet_nodes")
    runtime = importlib.import_module(SPEC.name + ".runtime")
    store, project = imported_project(directory)
    previous_store = runtime._store
    runtime._store = store
    count = 0

    def check(condition):
        nonlocal count
        assert condition
        count += 1

    try:
        original = copy.deepcopy(project)
        green, text, report = nodes.ZVPictureOutlet().export_media(project, "green")
        manifest = assert_private_manifest(text, directory)
        check(tuple(green.shape) == (1, 11, 17, 3) and green.dtype == torch.float32)
        check(torch.all(green[0, :, :, 1] == 1).item() and torch.all(green[0, :, :, 0] == 0).item())
        check(manifest["items"][0]["label"] == "Picture 1" and manifest["items"][0]["item_id"] == "green")
        red, _, _ = nodes.ZVPictureOutlet().export_media(project, "red")
        check(tuple(red.shape) == (1, 24, 32, 3) and torch.all(red[0, :, :, 0] == 1).item())
        frames, sound, text, report = nodes.ZVVideoOutlet().export_media(project, "voiced")
        manifest = assert_private_manifest(text, directory)
        check(tuple(frames.shape) == (15, 24, 32, 3) and frames.dtype == torch.float32)
        check(0 <= frames.min().item() <= frames.max().item() <= 1)
        check(sound["sample_rate"] == 44100 and tuple(sound["waveform"].shape) == (1, 2, 66150))
        check(sound["waveform"].dtype == torch.float32)
        check(manifest["items"][0]["source_window"] == {"start_seconds": .25, "end_seconds": 1.75})
        check(manifest["original_audio"]["sample_count"] == frames.shape[0] / 10 * 44100)
        fitted, fitted_sound, text, report = nodes.ZVVideoOutlet().export_media(
            project, "voiced", target_width=64, target_height=96,
        )
        manifest = assert_private_manifest(text, directory)
        check(tuple(fitted.shape) == (15, 96, 64, 3) and fitted.dtype == torch.float32)
        check(torch.equal(sound["waveform"], fitted_sound["waveform"]))
        check(manifest["items"][0]["source_width"] == 32 and manifest["items"][0]["source_height"] == 24)
        check(manifest["items"][0]["output_width"] == 64 and manifest["items"][0]["output_height"] == 96)
        check(manifest["items"][0]["fit_mode"] == "center_crop_fill" and "未先构造原尺寸批次" in report)
        silent, sound, text, _ = nodes.ZVVideoOutlet().export_media(project, "silent")
        manifest = assert_private_manifest(text, directory)
        check(tuple(silent.shape) == (8, 24, 32, 3) and sound is None)
        check(abs(manifest["items"][0]["source_window"]["end_seconds"] - 1.3) < 1e-9)
        check(manifest["items"][0]["requested_source_window"]["end_seconds"] == 1.25)
        audio, text, _ = nodes.ZVAudioOutlet().export_media(project, "independent")
        manifest = assert_private_manifest(text, directory)
        check(tuple(audio["waveform"].shape) == (1, 2, 66150) and audio["sample_rate"] == 44100)
        check(manifest["items"][0]["clip_id"] == "independent" and manifest["items"][0]["label"] == "Audio 1")
        signal = audio["waveform"][0].numpy()
        check(np.allclose(signal[0], signal[1]))
        check(abs(float(signal[0, 10000]) - .25) < 1e-4 and abs(float(signal[0, 50000]) - .5) < 1e-4)
        mixed, text, report = nodes.ZVTimelineAudioOutlet().export_media(project)
        manifest = assert_private_manifest(text, directory)
        check(tuple(mixed["waveform"].shape) == (1, 2, 132300) and mixed["sample_rate"] == 44100)
        values = mixed["waveform"][0, 0].numpy()
        check(np.count_nonzero(values[:22050]) == 0)
        check(np.count_nonzero(values[121275:]) == 0)
        check(abs(float(values[33075]) - 6554 / 32768) < 1e-4)
        check(abs(float(values[66150]) - (6554 / 32768 + .25)) < 1e-4)
        check(abs(float(values[99225]) - .5) < 1e-4)
        check({item["clip_id"] for item in manifest["items"]} == {"original", "independent"})
        check(manifest["mix"]["strategy"] == "peak_limit" and manifest["mix"]["gain"] == 1)
        crowded = copy.deepcopy(project)
        crowded["audio_track"] += [dict(crowded["audio_track"][1], clip_id="second"), dict(crowded["audio_track"][1], clip_id="third")]
        loud, text, _ = nodes.ZVTimelineAudioOutlet().export_media(crowded)
        manifest = assert_private_manifest(text, directory)
        check(abs(loud["waveform"].abs().max().item() - .98) < 1e-5)
        check(0 < manifest["mix"]["gain"] < 1 and abs(manifest["mix"]["peak_before_gain"] - 1.5) < 1e-4)
        empty = C.empty_project()
        empty["processing_window"].update(start_seconds=3, end_seconds=3.125)
        quiet, text, _ = nodes.ZVTimelineAudioOutlet().export_media(empty)
        manifest = assert_private_manifest(text, directory)
        check(tuple(quiet["waveform"].shape) == (1, 2, 5513) and not torch.count_nonzero(quiet["waveform"]).item())
        check(manifest["items"] == [])
        check(project == original)
        return count
    finally:
        runtime._store = previous_store


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zf-outlet-smoke-") as temporary:
        result = run_real_checks(Path(temporary))
    print(f"OUTLET_MEDIA_OK {result}")
