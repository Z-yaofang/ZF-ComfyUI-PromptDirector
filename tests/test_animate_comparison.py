"""The optional comparison is a post-loop second save, never a segment output."""

from fractions import Fraction
import copy
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import types

import av
import numpy as np
import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
PACKAGE = "zf_animate_comparison_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
COMPARISON = importlib.import_module(PACKAGE + ".animate_video.comparison")
EXECUTION = importlib.import_module(PACKAGE + ".animate_video.execution")
PLAN = importlib.import_module(PACKAGE + ".animate_video.plan")
ASSEMBLY = importlib.import_module(PACKAGE + ".animate_video.assembly")

spec = importlib.util.spec_from_file_location("animate_comparison_plan_fixtures", ROOT / "tests" / "test_animate_plan.py")
FIXTURE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = FIXTURE
spec.loader.exec_module(FIXTURE)


def _source_movie(path, width, height, levels):
    with av.open(str(path), "w", format="mp4") as output:
        stream = output.add_stream("libx264rgb", rate=30)
        stream.width, stream.height, stream.pix_fmt = width, height, "rgb24"
        stream.options = {"crf": "0", "preset": "ultrafast"}
        for index, level in enumerate(levels):
            frame = av.VideoFrame.from_ndarray(np.full((height, width, 3), level, dtype=np.uint8), format="rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


def _prepared(tmp_path, width, height):
    # Two authored source cuts: 4+4 frames.  The generated flow instead yields
    # 3+5, so the comparison has to adjust only within each segment boundary.
    source = tmp_path / "original.mp4"
    _source_movie(source, width, height, [30, 50, 70, 90, 110, 130, 150, 170])
    media = FIXTURE.upstream_clips(FIXTURE.project(8, pictures=2, fps=30), [(0, 4), (4, 8)])
    media["assets"][0]["probe"].update(width=width, height=height)
    plan = PLAN.build_plan(media, FIXTURE.settings(), fps=30)
    assert plan["validation"]["ready"]
    run = None
    for index, (count, level) in enumerate(((3, .6), (5, .8))):
        context = EXECUTION.segment_context(plan, index)
        frames = torch.full((count, height, width, 3), level)
        run = EXECUTION.persist_segment(context, frames, None, run, tmp_path)
    paths, manifest = EXECUTION.complete_run(plan, run, tmp_path)
    finished = ASSEMBLY.assemble_video(paths, manifest, paths[0].parent / "complete.mp4", 30)
    return source, plan, run, paths, manifest, finished


@pytest.mark.parametrize("height,width,direction", [(32, 24, "左右"), (24, 32, "上下")])
def test_full_comparison_matches_actual_segments_once_and_keeps_one_audio(tmp_path, height, width, direction):
    source, plan, _run, paths, manifest, finished = _prepared(tmp_path, width, height)
    target = paths[0].parent / "comparison.mp4"
    comparison, report = COMPARISON.render_comparison(
        paths, manifest, plan, finished, target, lambda _handle: source)
    assert comparison._animate_frames == 8
    assert comparison._animate_fps == Fraction(30)
    assert direction in report
    assert "第 1 段原素材尾部少显示 1 帧" in report
    assert "第 2 段原素材尾帧重复 1 帧" in report
    assert "原声仅来自完整成片一次" in report
    assert target.is_file()
    with av.open(str(target)) as result:
        assert len(result.streams.video) == len(result.streams.audio) == 1
        frames = [frame.to_ndarray(format="rgb24") for frame in result.decode(video=0)]
        assert len(frames) == 8
        assert result.streams.video[0].duration * result.streams.video[0].time_base == Fraction(8, 30)
    assert frames[0].shape == ((height, width * 2, 3) if direction == "左右" else (height * 2, width, 3))
    source_levels = [30, 50, 70, 110, 130, 150, 170, 170]
    for index, frame in enumerate(frames):
        original = frame[:, :width] if direction == "左右" else frame[:height]
        generated = frame[:, width:] if direction == "左右" else frame[height:]
        assert abs(float(original.mean()) - source_levels[index]) < 6
        assert abs(float(generated.mean()) - (153 if index < 3 else 204)) < 6
    saved = tmp_path / "saved-comparison.mp4"
    comparison.save_to(str(saved))
    with av.open(str(saved)) as result:
        assert len(list(result.decode(video=0))) == 8
    assert finished._animate_path.is_file()  # The true film was not overwritten.


def test_wrong_film_is_rejected_before_second_save(tmp_path):
    source, plan, _run, paths, manifest, finished = _prepared(tmp_path, 24, 32)
    other = ASSEMBLY.AssembledVideo(tmp_path / "not-this-run.mp4", 8, 30, finished._animate_samples)
    with pytest.raises(ValueError, match="本次运行的完整成片"):
        COMPARISON.render_comparison(paths, manifest, plan, other,
                                     paths[0].parent / "comparison.mp4", lambda _handle: source)
    assert not (paths[0].parent / "comparison.mp4").exists()


def _comparison_node(monkeypatch, tmp_path, source):
    monkeypatch.setattr(COMPARISON.ZVAnimateFinalComparison, "_temp_root", staticmethod(lambda: tmp_path))
    store = types.SimpleNamespace(record=lambda _handle: None, resolve=lambda _handle: source)
    monkeypatch.setattr(COMPARISON, "get_store", lambda: store)
    return COMPARISON.ZVAnimateFinalComparison()


def test_comparison_node_recovers_manifest_from_final_video_without_run_result(tmp_path, monkeypatch):
    source, plan, _run, paths, _manifest, finished = _prepared(tmp_path, 24, 32)
    node = _comparison_node(monkeypatch, tmp_path, source)
    assert set(node.INPUT_TYPES()["required"]) == {"animate_plan", "video"}

    output = node.compare(plan, finished)

    comparison, report = output["result"]
    assert comparison._animate_path == paths[0].parent / "comparison.mp4"
    assert comparison._animate_frames == finished._animate_frames == 8
    assert output["ui"]["text"] == [report]
    assert "完整对照 8 帧" in report
    assert finished._animate_path.is_file()
    with av.open(str(comparison._animate_path)) as container:
        assert len(container.streams.video) == len(container.streams.audio) == 1
        assert len(list(container.decode(video=0))) == 8


def test_comparison_node_rejects_final_video_outside_its_run_directory(tmp_path, monkeypatch):
    source, plan, _run, paths, _manifest, finished = _prepared(tmp_path, 24, 32)
    node = _comparison_node(monkeypatch, tmp_path, source)
    foreign = tmp_path / "foreign" / paths[0].parent.name
    foreign.mkdir(parents=True)
    shutil.copy2(finished._animate_path, foreign / "complete.mp4")
    shutil.copy2(paths[0].parent / "manifest.json", foreign / "manifest.json")
    wrong = ASSEMBLY.AssembledVideo(foreign / "complete.mp4", finished._animate_frames,
                                    finished._animate_fps, finished._animate_samples)

    with pytest.raises(ValueError, match="不在本次运行目录"):
        node.compare(plan, wrong)
    assert not (foreign / "comparison.mp4").exists()


def test_comparison_node_rejects_incomplete_manifest_behind_apparent_final_video(tmp_path, monkeypatch):
    source, plan, _run, paths, _manifest, finished = _prepared(tmp_path, 24, 32)
    node = _comparison_node(monkeypatch, tmp_path, source)
    manifest_path = paths[0].parent / "manifest.json"
    partial = json.loads(manifest_path.read_text(encoding="utf-8"))
    partial["segments"].pop()
    manifest_path.write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="上一段结果与当前计划或循环顺序不一致"):
        node.compare(plan, finished)
    assert not (paths[0].parent / "comparison.mp4").exists()


def test_four_segments_from_two_different_videos_restart_source_index_at_each_cut(tmp_path):
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    _source_movie(first, 24, 32, [20, 40, 60, 80])
    _source_movie(second, 24, 32, [100, 120, 140, 160])
    media = FIXTURE.upstream_clips(FIXTURE.project(4, pictures=4, fps=30),
                                   [(0, 2), (2, 4), (4, 6), (6, 8)])
    other = copy.deepcopy(media["assets"][0])
    other["asset_id"] = "video-2"
    other["source_handle"] = "originals/" + "c" * 32 + ".mp4"
    media["assets"].append(other)
    for index in (2, 3):
        clip = media["video_track"][index]
        clip["asset_id"] = "video-2"
        clip["source_in_seconds"] = (index - 2) * 2 / 30
        clip["source_out_seconds"] = (index - 1) * 2 / 30
    value = PLAN.build_plan(media, FIXTURE.settings(), fps=30)
    assert value["validation"]["ready"]
    run = None
    for index in range(4):
        context = EXECUTION.segment_context(value, index)
        run = EXECUTION.persist_segment(context, torch.full((2, 32, 24, 3), .3 + .1 * index),
                                        None, run, tmp_path)
    paths, manifest = EXECUTION.complete_run(value, run, tmp_path)
    finished = ASSEMBLY.assemble_video(paths, manifest, paths[0].parent / "complete.mp4", 30)
    result, report = COMPARISON.render_comparison(
        paths, manifest, value, finished, paths[0].parent / "comparison.mp4",
        lambda handle: second if handle == other["source_handle"] else first)
    assert "各段原素材帧数与成片一致" in report
    with av.open(str(result._animate_path)) as comparison:
        means = [float(frame.to_ndarray(format="rgb24")[:, :24].mean())
                 for frame in comparison.decode(video=0)]
    assert len(means) == 8
    assert all(abs(observed - wanted) < 6 for observed, wanted in zip(
        means, [20, 40, 60, 80, 100, 120, 140, 160]))


def test_near_integer_probe_fps_does_not_insert_or_drop_source_frames(tmp_path):
    source = tmp_path / "near-30.mp4"
    _source_movie(source, 24, 32, [20, 40, 60, 80, 100, 120, 140, 160])
    frames = list(COMPARISON._source_frames(source, 3, 5, 30.000000845070446, Fraction(30)))
    assert len(frames) == 5
    assert [round(float(frame.mean())) for frame in frames] == [80, 100, 120, 140, 160]
