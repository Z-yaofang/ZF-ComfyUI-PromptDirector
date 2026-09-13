"""Structural and cross-field validation of the selected model inputs."""

import math
import re

from .contract import (
    ContractError, KINDS, LABEL_RE, issue, normalize_labels, normalize_plan,
    paths_overlap, pointer_get, pointer_owner, referenced_labels, selected_asset_ids, PROTECTED_RE,
)


VISUAL_RELATIONS = {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"}
AUDIO_RELATIONS = {"fully_copy", "partially_copy", "reference", "weak_reference"}
CONTENT_PATH = re.compile(
    r"^/(?:style|overall_soundscape|non_diegetic_music|ref2va/summary|"
    r"(?:media_assets|subjects)/[0-9]+/(?:definition|retention/(?:details|placement))|"
    r"shots/[0-9]+/(?:composition|subject_description|environment|action|camera|sound|"
    r"dialogue/[0-9]+/(?:source|delivery|text|after)|visible_text/[0-9]+/(?:description|text)|"
    r"reference_placements/[0-9]+/text)|segmentation/(?:global_prompt|segments/[0-9]+/local_prompt))$"
)


def empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def editable_gap_path(path):
    return bool(CONTENT_PATH.fullmatch(path))


def check_window(window, probe, path, errors, kind=None):
    if window is None:
        return
    start, end = window["in_seconds"], window["out_seconds"]
    if end <= start:
        errors.append(issue(path, "window_order", "Window out must be greater than in; end is exclusive"))
    if probe.get("duration_seconds") is not None and end > probe["duration_seconds"] + 1e-6:
        errors.append(issue(path, "window_bounds", "Selected window exceeds the source duration"))
    for unit, rate_key, count_key in (("frame", "fps", "frame_count"), ("sample", "sample_rate", "sample_count")):
        left, right = f"in_{unit}", f"out_{unit}"
        if (left in window) != (right in window):
            errors.append(issue(path, "boundary_pair", f"Both {unit} boundaries are required together"))
            continue
        if left not in window:
            continue
        rate = probe.get(rate_key)
        if not rate:
            errors.append(issue(path, "boundary_rate", f"Source {rate_key} is required for {unit} boundaries"))
            continue
        if window[right] <= window[left]:
            errors.append(issue(path, "boundary_order", f"Invalid {unit} boundary order"))
        if probe.get(count_key) is not None and window[right] > probe[count_key]:
            errors.append(issue(path, "boundary_bounds", f"Selected {unit} boundary exceeds source count"))
        if not math.isclose(window[left] / rate, start, abs_tol=1e-6) or not math.isclose(window[right] / rate, end, abs_tol=1e-6):
            errors.append(issue(path, "boundary_clock", f"Seconds and {unit} boundaries disagree on the source clock"))
    if kind == "picture":
        errors.append(issue(path, "picture_window", "Picture assets are prepared stills; keep video extraction in a future preparation plan"))


def check_inputs(plan, selections, assets, path, errors):
    counts = {"picture": 0, "video": 0, "audio": 0}
    totals = {"video": 0, "audio": 0}
    by_id = {}
    for i, selection in enumerate(selections):
        p = f"{path}/{i}"
        asset_id = selection["asset_id"]
        if asset_id in by_id:
            errors.append(issue(p, "duplicate_selection", "A physical asset can only have one window per model invocation"))
        by_id[asset_id] = selection
        if asset_id not in assets:
            errors.append(issue(p, "unknown_asset", "Selection references an unknown asset_id"))
            continue
        asset = assets[asset_id]
        kind = asset["kind"]
        if kind != "audio" or not asset.get("source_video_asset_id"):
            counts[kind] += 1
        window = selection.get("window")
        check_window(window, asset["probe"], p + "/window", errors, kind)
        if kind in totals:
            if asset["probe"].get("duration_seconds") is None:
                errors.append(issue(p, "probe_required", "Selected timed media requires probed source duration"))
            if window is None:
                errors.append(issue(p, "selected_window_required", "Selected timed media needs explicit in/out seconds"))
            else:
                totals[kind] += window["out_seconds"] - window["in_seconds"]
                if plan["profile"] == "local_t8" and kind == "video":
                    model = selection.get("model_input")
                    if not model or model["fps"] != 24 or not 48 <= model["frame_count"] <= 360:
                        errors.append(issue(p + "/model_input", "local_video_frames", "local_t8 requires actual input at 24 fps with 48–360 frames"))
                    elif not math.isclose(model["frame_count"] / 24, window["out_seconds"] - window["in_seconds"], abs_tol=1e-6):
                        errors.append(issue(p + "/model_input", "model_window_mismatch", "Actual input frames must describe the selected window duration"))
    if plan["profile"] == "local_t8":
        for kind, limit in (("picture", 9), ("video", 3), ("audio", 3)):
            if counts[kind] > limit:
                errors.append(issue(path, "local_asset_limit", f"local_t8 allows at most {limit} selected {kind} assets per invocation"))
    else:
        limits = plan.get("profile_limits", {})
        for kind in totals:
            if totals[kind] > limits.get(kind + "_total_seconds", 15) + 1e-6:
                errors.append(issue(path, "cloud_duration_limit", f"Selected {kind} duration exceeds the cloud_strict deployment policy"))
    for asset_id, selection in by_id.items():
        asset = assets.get(asset_id)
        if not asset:
            continue
        if asset["kind"] == "video" and asset.get("audio_enabled"):
            paired = by_id.get(asset.get("paired_audio_asset_id"))
            if paired is None:
                errors.append(issue(path, "missing_paired_audio", "Enabled video audio must be selected in the same invocation"))
            elif selection.get("window") != paired.get("window"):
                # Frame and sample representations may differ; compare seconds below.
                a, b = selection.get("window"), paired.get("window")
                if a is None or b is None or any(a[key] != b[key] for key in ("in_seconds", "out_seconds")):
                    errors.append(issue(path, "paired_window", "Video and its enabled audio must use the same source window"))
        if asset.get("source_video_asset_id") and asset["source_video_asset_id"] not in by_id:
            errors.append(issue(path, "orphan_audio", "A paired audio track requires its video in this invocation"))


def validate_plan(plan):
    try:
        plan = normalize_plan(plan)
    except ContractError as exc:
        return {"ready": False, "errors": exc.issues, "warnings": []}
    errors, warnings = [], []
    duration = plan["duration_seconds"]
    assets = {a["asset_id"]: a for a in plan["media_assets"]}
    subjects = {s["subject_id"]: s for s in plan["subjects"]}
    active_ids = selected_asset_ids(plan)
    active = [a for a in plan["media_assets"] if a["asset_id"] in active_ids]
    known_labels = {a["official_label"] for a in active} | {s["official_label"] for s in plan["subjects"]}
    label_owners = set()
    for collection, id_key in (("media_assets", "asset_id"), ("subjects", "subject_id"), ("shots", "id"), ("gaps", "id")):
        ids = [row[id_key] for row in plan[collection]]
        if len(ids) != len(set(ids)):
            errors.append(issue("/" + collection, "duplicate_id", "Stable IDs must be unique within this collection"))
    for collection, items in (("media_assets", plan["media_assets"]), ("subjects", plan["subjects"])):
        for i, item in enumerate(items):
            p = f"/{collection}/{i}"
            kind = "Subject" if collection == "subjects" else KINDS[item["kind"]]
            label = item["official_label"]
            if label != f"<{kind} {item['ordinal']}>":
                errors.append(issue(p + "/official_label", "label_ordinal", "Label must match its independent kind and persisted ordinal"))
            if label in label_owners:
                errors.append(issue(p + "/official_label", "duplicate_label", "Reference labels must be unique"))
            label_owners.add(label)
    for i, a in enumerate(plan["media_assets"]):
        p = f"/media_assets/{i}"
        handle = a["source"]["handle"]
        if handle.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", handle) or "://" in handle or ".." in re.split(r"[/\\]", handle):
            errors.append(issue(p + "/source/handle", "source_handle", "Use an opaque handle or upload-relative identifier, without absolute paths or traversal"))
        check_window(a["selected_window"], a["probe"], p + "/selected_window", errors, a["kind"])
        allowed = {
            "picture": {"subject_source", "first_frame", "last_frame", "keyframe", "storyboard"},
            "video": {"subject_source", "video_edit", "video_continue", "structure_reference"},
            "audio": {"audio_reuse", "audio_reference"},
        }[a["kind"]]
        if a["role"] not in allowed:
            errors.append(issue(p + "/role", "asset_role", "Role does not belong to this physical media kind"))
        if a.get("audio_enabled"):
            paired = assets.get(a.get("paired_audio_asset_id"))
            if a["kind"] != "video" or a["probe"].get("has_audio") is not True or not paired or paired["kind"] != "audio" or paired.get("source_video_asset_id") != a["asset_id"]:
                errors.append(issue(p, "audio_pair", "Enabled source audio needs a probed video and reciprocal audio asset link"))
        elif a.get("paired_audio_asset_id"):
            errors.append(issue(p, "disabled_audio_pair", "Remove the active pair link when video audio is disabled"))
        if a.get("source_video_asset_id"):
            video = assets.get(a["source_video_asset_id"])
            if a["kind"] != "audio" or not video or video["kind"] != "video" or not video.get("audio_enabled") or video.get("paired_audio_asset_id") != a["asset_id"]:
                errors.append(issue(p, "audio_pair", "Paired audio needs an enabled reciprocal video link"))
            elif a["source"] != video["source"]:
                errors.append(issue(p + "/source", "paired_clock", "Paired video and audio share one source handle and clock"))
    for i, s in enumerate(plan["subjects"]):
        p = f"/subjects/{i}"
        for asset_id in s["source_asset_ids"]:
            if asset_id not in active_ids or asset_id not in assets or assets[asset_id]["kind"] == "audio":
                errors.append(issue(p + "/source_asset_ids", "subject_source", "Visible subjects require selected picture/video source assets"))
    ordered_shots = sorted(plan["shots"], key=lambda s: s["order"])
    if [s["order"] for s in ordered_shots] != list(range(1, len(ordered_shots) + 1)):
        errors.append(issue("/shots", "shot_order", "Shot orders must be unique and consecutive from 1"))
    previous = -1
    speakers = {}
    for shot in ordered_shots:
        i = plan["shots"].index(shot)
        p = f"/shots/{i}"
        cut = shot["cut_seconds"]
        if (shot["order"] == 1 and cut != 0) or cut <= previous or cut >= duration:
            errors.append(issue(p + "/cut_seconds", "shot_time", "Shot 1 starts at zero; later cuts strictly increase within target duration"))
        if not math.isclose(cut * 1000, round(cut * 1000), abs_tol=1e-6):
            errors.append(issue(p + "/cut_seconds", "shot_precision", "Cut times must be representable in whole milliseconds"))
        previous = cut
        for key in ("composition", "action"):
            if empty(shot[key]):
                errors.append(issue(p + "/" + key, "required_content", "Required shot content is unresolved"))
        for sid in shot["subject_ids"]:
            if sid not in subjects:
                errors.append(issue(p + "/subject_ids", "unknown_subject", "Unknown semantic subject_id"))
        for j, placement in enumerate(shot["reference_placements"]):
            if normalize_labels(placement["label"]) not in known_labels:
                errors.append(issue(f"{p}/reference_placements/{j}/label", "unknown_label", "Reference placement needs a selected, defined label"))
            target = placement["target_seconds"]
            next_cut = ordered_shots[shot["order"]]["cut_seconds"] if shot["order"] < len(ordered_shots) and shot["order"] > 0 else duration
            if target is not None and not cut <= target <= next_cut:
                errors.append(issue(f"{p}/reference_placements/{j}/target_seconds", "placement_time", "Placement must fall within its shot"))
            if normalize_labels(placement["label"]) not in referenced_labels(placement["text"]):
                errors.append(issue(f"{p}/reference_placements/{j}/text", "placement_label", "Placement prose must include its declared reference label"))
        for j, visible in enumerate(shot["visible_text"]):
            if empty(visible["text"]) or empty(visible["description"]):
                errors.append(issue(f"{p}/visible_text/{j}", "visible_text_gap", "Visible text needs its literal words and placement description"))
        for j, d in enumerate(shot["dialogue"]):
            dp = f"{p}/dialogue/{j}"
            for key in ("source", "delivery", "text"):
                if empty(d[key]):
                    errors.append(issue(dp + "/" + key, "dialogue_gap", "Vocal event content is unresolved"))
            if d["text"] and ("<d>" in d["text"] or "</d>" in d["text"]):
                errors.append(issue(dp + "/text", "dialogue_markup", "Provide literal words without nested dialogue tags"))
            speaker_id = d["speaker_id"]
            source = normalize_labels(d["source"])
            if speaker_id:
                if speaker_id not in speakers:
                    if speaker_id != f"S{len(speakers) + 1}":
                        errors.append(issue(dp, "speaker_order", "Assign speaker IDs in first actual vocal-event order"))
                    speakers[speaker_id] = source
                elif speakers[speaker_id] != source:
                    errors.append(issue(dp, "speaker_identity", "One speaker ID must keep the same source identity"))
            elif not (LABEL_RE.fullmatch(source) and source.startswith("<Audio ") and source in known_labels):
                errors.append(issue(dp, "vocal_source", "Vocal events need a stable speaker ID or a directly reused Audio label"))
            if "voiceover" in (d["delivery"] or "") and ("says in an off-screen voiceover" not in d["delivery"] or not re.search(r"lips.*closed", d["after"] or "", re.I)):
                errors.append(issue(dp, "voiceover_format", "Voiceover requires the fixed delivery phrase and an explicit lips-closed continuation"))
    for key in ("style", "overall_soundscape", "non_diegetic_music"):
        if empty(plan[key]):
            errors.append(issue("/" + key, "required_content", "Required content is unresolved; silence must be explicitly supplied"))
    lock_paths = []
    for i, lock in enumerate(plan["locks"]):
        try:
            current = pointer_get(plan, lock["path"])
            if pointer_owner(plan, lock["path"]) != lock.get("target_id"):
                errors.append(issue(f"/locks/{i}", "stale_binding", "Lock pointer now addresses a different stable ID; explicitly rebind before applying patches"))
            if current != lock["value"]:
                errors.append(issue(f"/locks/{i}", "lock_changed", "Locked field no longer matches its snapshot; rebind after explicit user edits or reordering"))
            lock_paths.append(lock["path"])
        except (ValueError, KeyError, IndexError):
            errors.append(issue(f"/locks/{i}/path", "unknown_path", "Lock path does not resolve"))
    gap_paths = set()
    for i, gap in enumerate(plan["gaps"]):
        p = f"/gaps/{i}"
        try:
            value = pointer_get(plan, gap["path"])
            if pointer_owner(plan, gap["path"]) != gap.get("target_id"):
                errors.append(issue(p, "stale_binding", "Gap pointer now addresses a different stable ID"))
            if not editable_gap_path(gap["path"]) or gap["value_type"] != "string":
                errors.append(issue(p, "gap_scope", "Stage 1 gaps authorize exact existing prose fields of type string only"))
            if gap["path"] in gap_paths:
                errors.append(issue(p, "duplicate_gap", "Only one task may own an exact field path"))
            gap_paths.add(gap["path"])
            if gap["status"] == "pending" and not empty(value):
                errors.append(issue(p, "gap_not_empty", "A pending gap cannot authorize rewriting existing content"))
            if gap["status"] == "resolved" and empty(value):
                errors.append(issue(p, "gap_false_resolution", "Resolved gap still has no value"))
            if gap["required"] and (gap["status"] != "resolved" or empty(value)):
                errors.append(issue(p, "required_gap", "Required gap is unresolved"))
            if gap["status"] == "pending" and any(paths_overlap(gap["path"], lock) for lock in lock_paths):
                errors.append(issue(p, "gap_locked", "Pending gap overlaps a user lock"))
        except (ValueError, KeyError, IndexError):
            errors.append(issue(p + "/path", "unknown_path", "Gap path does not resolve"))
    seg = plan["segmentation"]
    if seg["strategy"] == "none":
        if seg["segments"] or not empty(seg["global_prompt"]) or seg["shared_lock_paths"]:
            errors.append(issue("/segmentation", "inactive_segmentation", "Inactive segmentation cannot carry hidden execution prompts or segments"))
        selections = [{"asset_id": a["asset_id"], "window": a["selected_window"], "model_input": a.get("model_input")} for a in active]
        check_inputs(plan, selections, assets, "/selected_inputs", errors)
    else:
        if not seg["segments"]:
            errors.append(issue("/segmentation/segments", "segments_empty", "Active segmentation needs explicit segments"))
        if seg["strategy"] == "uniform_edit" and empty(seg["global_prompt"]):
            errors.append(issue("/segmentation/global_prompt", "shared_prompt", "Uniform editing needs one shared prompt"))
        for path in seg["shared_lock_paths"]:
            if path not in lock_paths:
                errors.append(issue("/segmentation/shared_lock_paths", "shared_lock", "Shared lock paths must resolve to actual plan locks"))
        segments = sorted(seg["segments"], key=lambda s: s["order"])
        if [s["order"] for s in segments] != list(range(1, len(segments) + 1)) or len({s["id"] for s in segments}) != len(segments):
            errors.append(issue("/segmentation/segments", "segment_order", "Segments need unique IDs and consecutive order"))
        prior_start, prior_end = -1, -1
        for i, segment in enumerate(segments):
            p = f"/segmentation/segments/{seg['segments'].index(segment)}"
            win = segment["source_window"]
            check_window(win, {}, p + "/source_window", errors)
            if win["in_seconds"] <= prior_start or win["out_seconds"] <= prior_end:
                errors.append(issue(p, "segment_clock", "Segment starts and ends must advance; overlap is allowed"))
            if prior_end >= 0 and win["in_seconds"] > prior_end:
                errors.append(issue(p, "segment_hole", "Source-clock segments must cover a continuous range"))
            prior_start, prior_end = win["in_seconds"], win["out_seconds"]
            if seg["strategy"] == "narrative" and empty(segment["local_prompt"]):
                errors.append(issue(p + "/local_prompt", "local_prompt", "Narrative segments each require their own local prompt"))
            check_inputs(plan, segment["selections"], assets, p + "/selections", errors)
            for j, selection in enumerate(segment["selections"]):
                asset = assets.get(selection["asset_id"])
                if not asset or asset["kind"] == "picture" or selection["timing"] != "synchronized":
                    continue
                sw = selection["window"]
                source = asset["source"]
                if source.get("clock_id") != seg["clock_id"] or sw is None or any(not math.isclose(sw[key] + source.get("clock_offset_seconds", 0), win[key], abs_tol=1e-6) for key in ("in_seconds", "out_seconds")):
                    errors.append(issue(f"{p}/selections/{j}", "synchronized_clock", "Synchronized selections must map onto the same segment source clock"))
        if segments and not math.isclose(segments[-1]["source_window"]["out_seconds"] - segments[0]["source_window"]["in_seconds"], duration, abs_tol=1e-6):
            errors.append(issue("/segmentation", "segment_duration", "The covered source-clock span must equal target duration; retiming is outside stage 1"))
    mode = plan["effective_mode"]
    if mode != "Ref2VA":
        expected = {"T2VA": [], "I2VA": [("<Picture 1>", "first_frame")], "L2VA": [("<Picture 1>", "last_frame")], "FL2VA": [("<Picture 1>", "first_frame"), ("<Picture 2>", "last_frame")]}[mode]
        actual = sorted((a["official_label"], a["role"]) for a in active)
        if actual != expected or subjects:
            errors.append(issue("/mode", "mode_assets", "Base-mode inputs must match their fixed physical frame contract; choose Ref2VA or explicitly renumber"))
    else:
        validate_references(plan, active, assets, known_labels, errors)
    # Labels in literal dialogue and visible text are deliberately excluded.
    for path, text in prompt_fields(plan):
        check_prose(text, path, len(plan["shots"]), errors)
        for label in referenced_labels(text):
            if label not in known_labels:
                errors.append(issue(path, "undefined_label", "Prompt refers to an unselected or undefined reference label"))
        if re.search(r"\[Shot\s+\d+\]|^\s*At\s+\d+:\d", text or "") and path.startswith("/shots/"):
            errors.append(issue(path, "embedded_shot", "Shot headings and cut timestamps belong to structured shot fields"))
        if re.search(r"SLOT:|【反推[:：]", text or ""):
            errors.append(issue(path, "placeholder", "Replace prototype placeholders with explicit gaps"))
        if re.search(r"(?m)^\s*(?:subject_definitions|summary|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music)\s*:", text or ""):
            errors.append(issue(path, "embedded_heading", "Core headings are assembled by the compiler, not embedded in prose fields"))
    return {"ready": not errors, "effective_mode": mode, "errors": errors, "warnings": warnings}


def check_prose(text, path, shot_count, errors):
    normalized = normalize_labels(text)
    prose = "".join(part for index, part in enumerate(PROTECTED_RE.split(normalized)) if not index % 2)
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", prose):
        errors.append(issue(path, "prose_language", "Supply approved English prose; this compiler does not translate. Literal dialogue and visible text keep their language"))
    for match in re.finditer(r"<(?:Subject|Picture|Video|Audio)\b[^>]*>", prose):
        if not LABEL_RE.fullmatch(match[0]):
            errors.append(issue(path, "label_format", "Reference labels need a positive canonical ordinal"))
    for match in re.finditer(r"\[Shot (\d+)\]", prose):
        if not 1 <= int(match[1]) <= shot_count:
            errors.append(issue(path, "unknown_shot", "Referenced Shot does not exist"))


def prompt_fields(plan):
    for key in ("style", "overall_soundscape", "non_diegetic_music"):
        yield "/" + key, plan[key]
    yield "/ref2va/summary", plan["ref2va"]["summary"]
    for i, shot in enumerate(plan["shots"]):
        for key in ("composition", "subject_description", "environment", "action", "camera", "sound"):
            yield f"/shots/{i}/{key}", shot[key]
        for j, dialogue in enumerate(shot["dialogue"]):
            for key in ("source", "delivery", "after"):
                yield f"/shots/{i}/dialogue/{j}/{key}", dialogue[key]
        for j, placement in enumerate(shot["reference_placements"]):
            yield f"/shots/{i}/reference_placements/{j}/text", placement["text"]
        for j, visible in enumerate(shot["visible_text"]):
            yield f"/shots/{i}/visible_text/{j}/description", visible["description"]
    yield "/segmentation/global_prompt", plan["segmentation"]["global_prompt"]
    for i, segment in enumerate(plan["segmentation"]["segments"]):
        yield f"/segmentation/segments/{i}/local_prompt", segment["local_prompt"]


def validate_references(plan, active, assets, known_labels, errors):
    entries = [(f"/subjects/{i}", s, "Subject") for i, s in enumerate(plan["subjects"])]
    entries += [(f"/media_assets/{plan['media_assets'].index(a)}", a, KINDS[a["kind"]]) for a in active if a["role"] != "subject_source"]
    if not entries:
        errors.append(issue("/subjects", "reference_definitions", "Ref2VA needs at least one tracked reference definition"))
    used = set().union(*(referenced_labels(text) for _, text in prompt_fields(plan)))
    defined = {item["official_label"] for _, item, _ in entries}
    for path, item, kind in entries:
        definition = item.get("definition")
        check_prose(definition, path + "/definition", len(plan["shots"]), errors)
        if empty(definition):
            errors.append(issue(path + "/definition", "definition_gap", "Tracked references require a definition"))
        for label in referenced_labels(definition):
            if label not in known_labels:
                errors.append(issue(path + "/definition", "undefined_label", "Definition refers to an unknown or unselected label"))
        retention = item.get("retention")
        if not retention or empty(retention["details"]):
            errors.append(issue(path + "/retention", "retention_gap", "Each tracked definition needs retention analysis"))
        else:
            allowed = AUDIO_RELATIONS if kind == "Audio" else VISUAL_RELATIONS
            check_prose(retention["details"], path + "/retention/details", len(plan["shots"]), errors)
            check_prose(retention["placement"], path + "/retention/placement", len(plan["shots"]), errors)
            if retention["relationship"] not in allowed:
                errors.append(issue(path + "/retention/relationship", "retention_kind", "Retention marker does not match the label kind"))
            if re.search(r"\(S\d", (retention["placement"] or "") + (retention["details"] or "")):
                errors.append(issue(path + "/retention", "retention_speaker", "Speaker IDs do not belong in retention analysis"))
            if referenced_labels((retention["details"] or "") + " " + (retention["placement"] or "")) - known_labels:
                errors.append(issue(path + "/retention", "undefined_label", "Retention analysis refers to an unknown label"))
        if item["official_label"] not in used:
            errors.append(issue(path, "unused_definition", "Tracked reference must be used in the target prompt"))
        if kind == "Subject":
            source_labels = {assets[a]["official_label"] for a in item["source_asset_ids"] if a in assets}
            if not source_labels <= referenced_labels(definition):
                errors.append(issue(path + "/definition", "subject_provenance", "Subject definition must identify its physical source labels"))
    if used - defined:
        errors.append(issue("/ref2va", "untracked_usage", "Labels used outside definitions need their own definition and retention entry"))
    for a in active:
        if a["role"] == "subject_source" and not any(a["asset_id"] in s["source_asset_ids"] for s in plan["subjects"]):
            errors.append(issue("/media_assets", "unused_source", "A source-only asset must supply a semantic subject"))
    tasks = plan["ref2va"]["task_types"]
    if not tasks or empty(plan["ref2va"]["summary"]):
        errors.append(issue("/ref2va", "summary_gap", "Ref2VA requires explicit task types and summary"))
    roles = {a["role"] for a in active}
    needed = set()
    for role, task in (("video_edit", "video editing"), ("video_continue", "video continuation"), ("audio_reuse", "audio reuse"), ("audio_reference", "audio reference"), ("subject_source", "reference generation"), ("structure_reference", "reference generation"), ("storyboard", "reference generation")):
        if role in roles:
            needed.add(task)
    if roles & {"first_frame", "last_frame", "keyframe"}:
        needed.add("keyframe completion")
    if set(tasks) != needed:
        errors.append(issue("/ref2va/task_types", "task_roles", "Explicit task types must agree with the selected reference roles"))
    edits = [a for a in active if a["role"] == "video_edit"]
    if edits:
        expected = f"The target video is an edited version of {sorted(edits, key=lambda a: a['ordinal'])[0]['official_label']}."
        if not normalize_labels(plan["ref2va"]["summary"]).startswith(expected):
            errors.append(issue("/ref2va/summary", "editing_summary", "Video-editing summary must begin with the exact edited-version sentence for the primary source"))
