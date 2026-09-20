import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_media_testcore", ROOT / "media_evidence" / "__init__.py", submodule_search_locations=[str(ROOT / "media_evidence")])
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
C = importlib.import_module(SPEC.name + ".contract")
S = importlib.import_module(SPEC.name + ".storage")
P = importlib.import_module(SPEC.name + ".presets")
O = importlib.import_module(SPEC.name + ".outlet")


def asset(kind="video", identifier="source"):
    return {"asset_id": identifier, "name": "Generated fixture", "kind": kind, "source_handle": "originals/" + "a"*32 + {"video": ".mp4", "audio": ".wav", "picture": ".png"}[kind],
            "probe": {"size_bytes": 500, "duration_seconds": None if kind == "picture" else 120, "width": None if kind == "audio" else 320, "height": None if kind == "audio" else 180, "fps": 30 if kind == "video" else None, "frame_count": 3600 if kind == "video" else None, "frame_count_exact": kind == "video", "vfr": False if kind == "video" else None, "has_audio": kind != "picture", "sample_rate": 48000 if kind != "picture" else None, "channels": 1 if kind != "picture" else None, "codec": "fixture"}}


def video(identifier="v1", at=0):
    return dict(clip_id=identifier, asset_id="source", timeline_in_seconds=at, source_in_seconds=1, source_out_seconds=11, source_audio_enabled=False, audio_link_id=None)


def project():
    p = C.empty_project()
    p["assets"] = [asset()]
    p["video_track"] = [video()]
    return p


def bound_project():
    p = project()
    p["video_track"][0].update(audio_link_id="a1", source_audio_enabled=True)
    p["audio_track"] = [dict(clip_id="a1", asset_id="source", timeline_in_seconds=0, source_in_seconds=1, source_out_seconds=11, origin="video_source", enabled=True, linked_video_clip_id="v1", source_video_clip_id="v1")]
    return p


def codes(p):
    return {e["code"] for e in C.normalize_project(p)["validation"]["errors"]}


def test_retired_slots_do_not_return_or_discard_media():
    p = bound_project()
    p["outlet_slots"] = {"version": 1, "items": [{"slot_id": "retired", "binding_id": "v1"}]}
    original = copy.deepcopy(p)
    result = C.normalize_project(p)
    assert "outlet_slots" not in result
    assert "outlet_slots" not in C.empty_project()
    assert result["assets"] == original["assets"]
    assert result["video_track"][0]["clip_id"] == "v1"
    assert result["audio_track"][0]["clip_id"] == "a1"
    assert not result["validation"]["errors"]
    assert p == original


def test_schema_round_trip_and_input_immutable():
    p = bound_project()
    original = copy.deepcopy(p)
    out = C.normalize_project(p)
    assert not out["validation"]["errors"]
    assert C.shape_errors(out) == []
    assert C.normalize_project(out) == out
    assert p == original
    assert C.parse_project(json.dumps(out)) == out
    assert out["video_track"][0]["source_in_frame"] == 30
    assert out["video_track"][0]["project_frame_count"] == 240


@pytest.mark.parametrize("frames,valid", [(0, False), (47, False), (48, True), (240, True), (360, True), (361, False), (480, False)])
def test_window_bounds_do_not_truncate(frames, valid):
    p = project()
    p["processing_preset"] = P.builtin("builtin.minimax-h3.single")
    p["processing_window"].update(start_seconds=100, end_seconds=100+frames/24)
    out = C.normalize_project(p)
    assert out["preset_compatibility"]["compatible"] == valid
    assert out["processing_window"]["end_seconds"] == p["processing_window"]["end_seconds"]
    assert out["processing_window"]["frame_count"] == frames


@pytest.mark.parametrize("fps,end,code", [(30, 10, "preset_fps"), (24, 15.000001, "preset_seconds"), (24, 2.01, "preset_grid"), (24, 0, "preset_min_frames")])
def test_window_seconds_and_clock_constraints(fps, end, code):
    p = project()
    p["processing_preset"] = P.builtin("builtin.minimax-h3.single")
    p["processing_window"].update(fps=fps, end_seconds=end)
    out = C.normalize_project(p)
    assert code in {e["code"] for e in out["preset_compatibility"]["issues"]}
    assert ("window_range" in codes(p)) == (end == 0)


def test_long_project_not_limited_by_processing_window():
    p = project(); p["video_track"][0].update(timeline_in_seconds=1000, source_in_seconds=0, source_out_seconds=120)
    assert not codes(p)


def test_labels_follow_order_and_delete_with_stable_ids():
    p = project(); p["video_track"] = [video("left", 4), video("right", 20)]
    assert [(r["item_id"], r["label"]) for r in C.normalize_project(p)["label_map"]] == [("left", "Video 1"), ("right", "Video 2")]
    p["video_track"][1]["timeline_in_seconds"] = 0
    assert [(r["item_id"], r["label"]) for r in C.normalize_project(p)["label_map"]] == [("right", "Video 1"), ("left", "Video 2")]
    p["video_track"].pop(1)
    assert C.normalize_project(p)["label_map"][0]["label"] == "Video 1"


def test_pictures_have_no_duration_and_labels_are_recomputed():
    p = C.empty_project(); p["assets"] = [asset("picture")]
    p["picture_track"] = [dict(item_id="b", asset_id="source", order=9), dict(item_id="a", asset_id="source", order=2)]
    p["label_map"] = [{"arbitrary": "untrusted derived state"}]
    out = C.normalize_project(p)
    assert [r["item_id"] for r in out["label_map"]] == ["a", "b"]
    assert out["label_map"][1]["label"] == "Picture 2"
    assert "duration_seconds" not in out["picture_track"][0]


def test_bound_audio_follows_and_detached_gets_independent_label():
    p = bound_project(); p["video_track"][0]["timeline_in_seconds"] = 12
    out = C.normalize_project(p)
    assert out["audio_track"][0]["timeline_in_seconds"] == 12
    assert out["label_map"][1]["label"] == "Video 1 原声"
    p["video_track"][0].update(audio_link_id=None, source_audio_enabled=False)
    p["audio_track"][0]["linked_video_clip_id"] = None
    assert C.normalize_project(p)["label_map"][1]["label"] == "Audio 1"


@pytest.mark.parametrize("mutation,code", [(lambda p: p["video_track"][0].update(audio_link_id="missing"), "audio_link"), (lambda p: p["audio_track"][0].update(linked_video_clip_id="bad"), "audio_link"), (lambda p: p["assets"][0]["probe"].update(has_audio=False), "no_source_audio"), (lambda p: p["video_track"][0].update(audio_link_id=None), "missing_audio_link")])
def test_broken_bindings(mutation, code):
    p = bound_project(); mutation(p); assert code in codes(p)


@pytest.mark.parametrize("mutation,code", [(lambda p: p["video_track"].append(video()), "duplicate_id"), (lambda p: p["assets"].append(asset()), "duplicate_id"), (lambda p: p["video_track"][0].update(asset_id="unknown"), "missing_asset"), (lambda p: p["assets"][0].update(kind="picture"), "track_kind"), (lambda p: p["video_track"][0].update(source_out_seconds=121), "source_window"), (lambda p: p["video_track"][0].update(source_out_seconds=0), "source_window")])
def test_invalid_mechanical_edits(mutation, code):
    p = project(); mutation(p); assert code in codes(p)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', 'invalid', '{', '['*2000])
def test_malformed_json(text):
    with pytest.raises(C.ProjectError): C.parse_project(text)


def test_json_size():
    with pytest.raises(C.ProjectError): C.parse_project(' '*(2*1024*1024+1))


@pytest.mark.parametrize("handle", ["C:/private/secret.mp4", "../secret.mp4", "originals/../secret.mp4", "originals/"+"a"*32+".mp4/../../x", "file:///secret", "https://example.com/a.mp4", "originals/"+"a"*32+".m3u8", "originals\\"+"a"*32+".mp4"])
def test_path_rejection(tmp_path, handle):
    store = S.MediaStore(tmp_path)
    with pytest.raises(S.MediaError): store.resolve(handle)
    p = project(); p["assets"][0]["source_handle"] = handle
    with pytest.raises(C.ProjectError): C.normalize_project(p)


def test_safe_path_and_display_name(tmp_path):
    store = S.MediaStore(tmp_path)
    path, handle, name = store.allocate(r"C:\private\new\clip.mp4")
    assert name == "clip.mp4" and path.is_relative_to(tmp_path / "zf_media_evidence")
    assert store.resolve(handle) == path
    with pytest.raises(S.MediaError): store.safe(tmp_path / "outside")


def test_missing_file_and_forged_probe_flagged(tmp_path):
    store = S.MediaStore(tmp_path)
    p = project(); out = store.canonical(p)
    assert "source_unavailable" in {e["code"] for e in out["validation"]["errors"]}
    source = store.resolve(p["assets"][0]["source_handle"]); source.write_bytes(b"fixture")
    trusted = copy.deepcopy(p["assets"][0]); trusted["probe"]["fps"] = 25
    (store.root / "cache" / (source.stem+".json")).write_text(json.dumps({"asset": trusted, "size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}))
    assert store.canonical(p)["assets"][0]["probe"]["fps"] == 25
    source.write_bytes(b"changed length")  # Different size avoids same-tick Windows mtime resolution.
    assert "source_unavailable" in {e["code"] for e in store.canonical(p)["validation"]["errors"]}


def registered_source(store, content=b"fixture", *, with_hash=True):
    handle = "originals/" + "b"*32 + ".png"
    source = store.resolve(handle); source.write_bytes(content)
    trusted = asset("picture", "registered"); trusted["source_handle"] = handle
    info = source.stat()
    record = {"asset": trusted, "size": info.st_size, "mtime_ns": info.st_mtime_ns}
    if with_hash:
        record["source_sha256"] = hashlib.sha256(content).hexdigest()
    registry = store.root / "cache" / (source.stem + ".json")
    registry.write_text(json.dumps(record), encoding="utf-8")
    return source, handle, trusted, registry


def test_finish_import_records_verified_source_sha256(tmp_path, monkeypatch):
    store = S.MediaStore(tmp_path)
    path, handle, name = store.allocate("still.png"); content = b"stable-picture-bytes"; path.write_bytes(content)
    probe = copy.deepcopy(asset("picture")["probe"])
    monkeypatch.setattr(store, "worker", lambda *_args, **_kwargs: {"kind": "picture", "probe": probe})
    imported = store.finish_import(path, handle, name, source_sha256=hashlib.sha256(content).hexdigest())
    record = json.loads((store.root / "cache" / (path.stem + ".json")).read_text(encoding="utf-8"))
    assert record["source_sha256"] == hashlib.sha256(content).hexdigest()
    assert store.record(handle) == imported
    path.write_bytes(b"changed-picture-byte")
    os.utime(path, ns=(path.stat().st_atime_ns, record["mtime_ns"] + 1000000))
    with pytest.raises(S.MediaError) as error:
        store.record(handle)
    assert error.value.code == "source_unavailable" and error.value.reason == "source_content_changed"


@pytest.mark.parametrize("case,reason", [
    ("registry_missing", "registry_missing"),
    ("registry_invalid", "registry_invalid"),
    ("source_missing", "source_missing"),
    ("source_size_changed", "source_size_changed"),
    ("source_content_changed", "source_content_changed"),
    ("legacy_mtime", "source_metadata_changed"),
])
def test_source_unavailable_reason_is_precise_and_path_free(tmp_path, case, reason):
    store = S.MediaStore(tmp_path); source, handle, _trusted, registry = registered_source(store, with_hash=case != "legacy_mtime")
    if case == "registry_missing": registry.unlink()
    if case == "registry_invalid": registry.write_text("{broken", encoding="utf-8")
    if case == "source_missing": source.unlink()
    if case == "source_size_changed": source.write_bytes(b"longer fixture")
    if case == "source_content_changed":
        source.write_bytes(b"changed")
        os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1000000))
    if case == "legacy_mtime": os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1000000))
    with pytest.raises(S.MediaError) as error:
        store.record(handle)
    assert error.value.code == "source_unavailable" and error.value.reason == reason
    assert str(tmp_path) not in error.value.message


def test_canonical_outlet_keeps_safe_registry_diagnostic(tmp_path):
    store = S.MediaStore(tmp_path); _source, _handle, trusted, registry = registered_source(store)
    registry.unlink(); value = C.empty_project(); value["assets"] = [trusted]
    canonical = store.canonical(value)
    assert canonical["validation"]["errors"][-1]["code"] == "source_unavailable"
    with pytest.raises(O.OutletError) as error:
        O.require_valid_project(canonical)
    assert "素材登记文件不可见" in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_mtime_only_change_repeats_across_store_instances_without_registry_write(tmp_path, monkeypatch):
    store = S.MediaStore(tmp_path); source, handle, trusted, registry = registered_source(store)
    before = registry.read_bytes(); info = source.stat(); stable = S._stable_sha256; calls = 0; calls_lock = threading.Lock()
    def counted(path):
        nonlocal calls
        with calls_lock: calls += 1
        return stable(path)
    monkeypatch.setattr(S, "_stable_sha256", counted)
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    stores = [S.MediaStore(tmp_path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda index: stores[index % len(stores)].record(handle), range(24)))
    assert results == [trusted] * 24
    assert calls == 4
    changed = source.stat(); os.utime(source, ns=(changed.st_atime_ns, changed.st_mtime_ns + 1000000))
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda index: stores[index % len(stores)].record(handle), range(24))) == [trusted] * 24
    assert calls == 8
    assert registry.read_bytes() == before


def test_hash_validation_interruption_leaves_next_retry_available(tmp_path, monkeypatch):
    store = S.MediaStore(tmp_path); source, handle, trusted, _registry = registered_source(store)
    info = source.stat(); os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    stable = S._stable_sha256; calls = 0
    def interrupted(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise S._source_error("source_unstable")
        return stable(path)
    monkeypatch.setattr(S, "_stable_sha256", interrupted)
    with pytest.raises(S.MediaError) as error:
        store.record(handle)
    assert error.value.reason == "source_unstable"
    assert handle not in store.verified_sources
    assert store.record(handle) == trusted


def test_second_stat_invalidates_first_observation_before_hash(tmp_path, monkeypatch):
    store = S.MediaStore(tmp_path); source, handle, _trusted, _registry = registered_source(store)
    info = source.stat(); os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    original_stat = Path.stat; observed = threading.Event(); count = 0; count_lock = threading.Lock()
    def watched(path, *args, **kwargs):
        nonlocal count
        result = original_stat(path, *args, **kwargs)
        if path == source:
            with count_lock:
                count += 1
                if count == 1: observed.set()
        return result
    monkeypatch.setattr(Path, "stat", watched)
    store.integrity_lock.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.record, handle)
            assert observed.wait(2)
            source.write_bytes(b"changed")
            os.utime(source, ns=(source.stat().st_atime_ns, info.st_mtime_ns + 2000000))
            store.integrity_lock.release()
            with pytest.raises(S.MediaError) as error:
                future.result()
    finally:
        if store.integrity_lock.locked(): store.integrity_lock.release()
    assert count >= 2 and error.value.reason == "source_content_changed"
    assert handle not in store.verified_sources


def test_real_file_change_during_hash_is_unstable(tmp_path, monkeypatch):
    source = tmp_path / "changing.bin"; source.write_bytes(b"a" * (2 * 1024 * 1024))
    real_sha256 = hashlib.sha256; hashing = threading.Event(); changed = threading.Event()
    class BlockingHash:
        def __init__(self): self.inner = real_sha256()
        def update(self, chunk):
            self.inner.update(chunk); hashing.set(); assert changed.wait(2)
        def hexdigest(self): return self.inner.hexdigest()
    monkeypatch.setattr(S.hashlib, "sha256", BlockingHash)
    def mutate():
        assert hashing.wait(2)
        with source.open("r+b") as output:
            output.seek(0); output.write(b"b")
        changed.set()
    thread = threading.Thread(target=mutate); thread.start()
    try:
        with pytest.raises(S.MediaError) as error:
            S._stable_sha256(source)
    finally:
        changed.set(); thread.join(2)
    assert not thread.is_alive() and error.value.reason == "source_unstable"


def test_verified_source_cache_is_bounded_lru(tmp_path):
    store = S.MediaStore(tmp_path); first_handle = None
    for index in range(S.MAX_VERIFIED_SOURCES + 1):
        handle = f"originals/{index:032x}.png"; first_handle = first_handle or handle
        source = store.resolve(handle); content = f"media-{index}".encode(); source.write_bytes(content); info = source.stat()
        trusted = asset("picture", f"asset-{index}"); trusted["source_handle"] = handle
        record = {"asset": trusted, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                  "source_sha256": hashlib.sha256(content).hexdigest()}
        (store.root / "cache" / (source.stem + ".json")).write_text(json.dumps(record), encoding="utf-8")
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        assert store.record(handle) == trusted
    assert len(store.verified_sources) == S.MAX_VERIFIED_SOURCES
    assert first_handle not in store.verified_sources


def test_vfr_is_explicit_estimate():
    p = project(); p["assets"][0]["probe"].update(vfr=True, frame_count_exact=False)
    out = C.normalize_project(p)
    assert out["video_track"][0]["frame_estimated"] is True
    assert any(e["code"] == "estimated_frames" for e in out["validation"]["warnings"])


def test_worker_concurrency_limit(tmp_path):
    store = S.MediaStore(tmp_path)
    store.jobs.acquire(); store.jobs.acquire()
    with pytest.raises(S.MediaError, match="Two media") as error: store.worker("probe", tmp_path / "none")
    assert error.value.code == "busy"


def test_asset_count_limit():
    p = C.empty_project(); p["assets"] = [asset("picture", f"a{i}") for i in range(129)]
    with pytest.raises(C.ProjectError): C.normalize_project(p)


@pytest.mark.parametrize("field,value", [("kind", ["video"]), ("kind", {"x": "video"}), ("schema_version", True), ("schema_version", [1])])
def test_enum_types_are_structured_errors(field, value):
    p = project()
    if field == "kind": p["assets"][0][field] = value
    else: p[field] = value
    with pytest.raises(C.ProjectError): C.normalize_project(p)


def test_valid_but_deep_json_is_rejected():
    with pytest.raises(C.ProjectError): C.parse_project('['*40+'0'+']'*40)


def test_storage_quota(tmp_path, monkeypatch):
    store = S.MediaStore(tmp_path)
    monkeypatch.setattr(S, "MAX_FILES_BYTES", 10)
    path, _, _ = store.allocate("fixture.png"); path.write_bytes(b"x"*10)
    with pytest.raises(S.MediaError) as error: store.quota()
    assert error.value.code == "storage_limit"


def test_symlink_escape(tmp_path):
    store = S.MediaStore(tmp_path / "input")
    external = tmp_path / "external.png"; external.write_bytes(b"fixture")
    path, handle, _ = store.allocate("fixture.png")
    try: path.symlink_to(external)
    except OSError:
        # Windows permits directory junctions without the file-symlink privilege.
        import os
        import subprocess
        if os.name != "nt": pytest.skip("Creating symbolic links is not permitted on this host")
        outside_directory = tmp_path / "outside-directory"; outside_directory.mkdir()
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = f"$null = New-Item -ItemType Junction -Path {quote(path)} -Target {quote(outside_directory)} -ErrorAction Stop"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: pytest.skip("Creating symlinks and junctions is not permitted on this host")
    with pytest.raises(S.MediaError): store.resolve(handle)


def test_worker_timeout_is_stable_and_releases_slot(tmp_path, monkeypatch):
    import subprocess
    store = S.MediaStore(tmp_path)
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("private-command", 30)
    monkeypatch.setattr(S.subprocess, "run", timeout)
    with pytest.raises(S.MediaError) as error: store.worker("probe", tmp_path / "private-file")
    assert error.value.code == "probe_timeout" and str(tmp_path) not in str(error.value)
    assert store.jobs.acquire(blocking=False) and store.jobs.acquire(blocking=False)


def test_node_exports_the_same_canonical_dictionary_and_json(tmp_path, monkeypatch):
    runtime = importlib.import_module(SPEC.name + ".runtime")
    node = importlib.import_module(SPEC.name + ".node").ZVUniversalMediaEvidenceDesk
    monkeypatch.setattr(runtime, "_store", S.MediaStore(tmp_path))
    output, text, catalog = node().export_project(json.dumps(C.empty_project()))
    assert output == json.loads(text) == C.normalize_project(C.empty_project())
    assert node.RETURN_TYPES == ("ZV_MEDIA_PROJECT", "STRING", "ZV_ORIGINAL_SOURCES")
    assert catalog.entries == ()


def test_desk_injects_optional_output_canvas_without_changing_saved_project(tmp_path, monkeypatch):
    runtime = importlib.import_module(SPEC.name + ".runtime")
    node = importlib.import_module(SPEC.name + ".node").ZVUniversalMediaEvidenceDesk
    monkeypatch.setattr(runtime, "_store", S.MediaStore(tmp_path))
    source = C.empty_project()
    output, text, _ = node().export_project(json.dumps(source), width=640, height=1152)
    assert output == json.loads(text)
    assert output["output_canvas"] == {"width": 640, "height": 1152}
    assert "output_canvas" not in source
    optional = node.INPUT_TYPES()["optional"]
    assert list(optional) == ["width", "height"]
    assert all(spec[1]["forceInput"] for spec in optional.values())


@pytest.mark.parametrize("width,height", [(640, None), (None, 1152), (641, 1152)])
def test_desk_rejects_partial_or_unaligned_output_canvas(tmp_path, monkeypatch, width, height):
    runtime = importlib.import_module(SPEC.name + ".runtime")
    node = importlib.import_module(SPEC.name + ".node").ZVUniversalMediaEvidenceDesk
    monkeypatch.setattr(runtime, "_store", S.MediaStore(tmp_path))
    spec=importlib.util.spec_from_file_location('comfy_execution.graph_utils',ROOT.parents[1]/'comfy_execution/graph_utils.py')
    core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
    monkeypatch.setitem(sys.modules,'comfy_execution.graph_utils',core)
    project, text, raw = node().export_project(json.dumps(C.empty_project()), width=width, height=height)
    assert isinstance(project,core.ExecutionBlocker) and isinstance(text,core.ExecutionBlocker)
    assert '目标' in project.message or 'H3' in project.message
    assert raw.entries == ()


@pytest.mark.parametrize("canvas", [
    {"width": 640},
    {"width": 640, "height": 1152, "extra": 1},
    {"width": 641, "height": 1152},
    {"width": True, "height": 1152},
])
def test_output_canvas_contract_is_strict(canvas):
    p = C.empty_project()
    p["output_canvas"] = canvas
    with pytest.raises(C.ProjectError):
        C.normalize_project(p)


def test_published_schema_accepts_canonical_output():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(C.SCHEMA)
    for p in [C.empty_project(), project(), bound_project()]:
        jsonschema.validate(C.normalize_project(p), C.SCHEMA)
