"""Deterministic assembly. Supplied prose is never inferred or translated."""

from .contract import normalize_labels, normalize_plan, selected_asset_ids
from .patching import apply_llm_patch
from .validation import validate_plan


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    minutes, rest = divmod(milliseconds, 60000)
    return f"{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def join_text(parts):
    return " ".join(normalize_labels(part) for part in parts if part)


def shot_text(shot):
    parts = [shot[key] for key in ("composition", "subject_description", "environment", "action", "camera", "sound")]
    body = join_text(parts)
    for d in shot["dialogue"]:
        speaker = f" ({d['speaker_id']})" if d["speaker_id"] else ""
        # Literal dialogue/lyrics and visible text bypass alias normalization.
        event = f"{normalize_labels(d['source'])}{speaker} {normalize_labels(d['delivery'])} <d>[{d['language']}] {d['text']}</d>"
        if d["after"]:
            event += " " + normalize_labels(d["after"])
        body += " " + event
    for visible in shot["visible_text"]:
        body += f" {normalize_labels(visible['description'])} \"{visible['text']}\""
    for placement in shot["reference_placements"]:
        if placement["text"]:
            body += " " + normalize_labels(placement["text"])
    prefix = f"[Shot {shot['order']}]"
    if shot["order"] > 1:
        prefix += f" At {timestamp(shot['cut_seconds'])},"
    return prefix + " " + body


def assemble_prompt(plan):
    mode = plan["effective_mode"]
    shots = sorted(plan["shots"], key=lambda shot: shot["order"])
    body = "\n".join(shot_text(shot) for shot in shots)
    if mode == "Ref2VA":
        active = selected_asset_ids(plan)
        entries = sorted(plan["subjects"], key=lambda s: s["ordinal"])
        entries += sorted((a for a in plan["media_assets"] if a["asset_id"] in active and a["role"] != "subject_source"), key=lambda a: ({"picture": 0, "video": 1, "audio": 2}[a["kind"]], a["ordinal"]))
        definitions, retention = [], []
        for item in entries:
            label = item["official_label"]
            definitions.append(f"{label} {normalize_labels(item['definition'])}")
            r = item["retention"]
            placement = f" ({normalize_labels(r['placement'])})" if r["placement"] else ""
            retention.append(f"{label}{placement}: {r['relationship']} - {normalize_labels(r['details'])}")
        sections = [
            ("subject_definitions", "\n".join(definitions)),
            ("summary", "[" + " + ".join(plan["ref2va"]["task_types"]) + "] " + normalize_labels(plan["ref2va"]["summary"])),
            ("retention_analysis", "\n".join(retention)),
            ("detailed_description", normalize_labels(plan["style"]) + "\n" + body),
        ]
    else:
        body = body.replace("[Shot 1] ", "[Shot 1] " + normalize_labels(plan["style"]) + " ", 1)
        sections = [("integrated_multimodal_description", body)]
    sections += [("overall_soundscape", normalize_labels(plan["overall_soundscape"])), ("non_diegetic_music", normalize_labels(plan["non_diegetic_music"]))]
    field_separator = "\n" if mode == "Ref2VA" else " "
    prompt = "\n\n".join(f"{heading}:{field_separator}{text}" for heading, text in sections)
    n, seconds = len(shots), f"{plan['duration_seconds']:.2f}"
    if mode == "I2VA":
        first_line = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    elif mode == "FL2VA":
        first_line = f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot {n}) aligns with the {seconds}-second mark of the target video."
    elif mode == "L2VA":
        first_line = f"How the reference pictures align with the target video — <Picture 1> (from [Shot {n}]) aligns with the {seconds}-second mark of the target video."
    else:
        first_line = ""
    return first_line + "\n\n" + prompt if first_line else prompt


def compile_plan(plan, llm_patch=None):
    normalized = normalize_plan(plan)
    patches = {"accepted": [], "rejected": []}
    if llm_patch is not None:
        normalized, patches = apply_llm_patch(normalized, llm_patch)
    validation = validate_plan(normalized)
    normalized["ready"] = validation["ready"]
    prompt = assemble_prompt(normalized) if validation["ready"] else ""
    reverse_tasks = {
        "schema_version": normalized["schema_version"],
        "allowed_operation": "replace",
        "gaps": normalized["gaps"],
        "locks": normalized["locks"],
        "patch_report": patches,
    }
    seg = normalized["segmentation"]
    validation["segment_prompt_layers"] = [
        {"segment_id": segment["id"], "shared_prompt": normalize_labels(seg["global_prompt"]), "local_prompt": normalize_labels(segment["local_prompt"])}
        for segment in sorted(seg["segments"], key=lambda s: s["order"])
    ]
    report = [f"H3 采访编译：{'就绪' if validation['ready'] else '待处理'}", f"模式：{normalized['effective_mode']}；策略：{normalized['profile']}；目标时长：{normalized['duration_seconds']} 秒"]
    for asset in normalized["media_assets"]:
        report.append(f"素材 {asset['asset_id']} → {asset['official_label']}；用途 {asset['role']}；{'已选择' if asset['asset_id'] in selected_asset_ids(normalized) else '资产库'}")
    for shot in sorted(normalized["shots"], key=lambda s: s["order"]):
        report.append(f"镜头 {shot['order']}（{shot['id']}，{shot['cut_seconds']} 秒）：{shot['composition'] or '待填写'} {shot['action'] or '待填写'}")
    report.extend(f"待处理 {e['path']}：{e['message']}" for e in validation["errors"])
    report.append(f"补槽接受 {len(patches['accepted'])} 项，拒绝 {len(patches['rejected'])} 项。")
    report.extend(f"拒绝 {item['path']}：{item['reason']}" for item in patches["rejected"])
    if seg["strategy"] != "none":
        report.append(f"分段：{seg['strategy']}，共 {len(seg['segments'])} 段；共享与局部提示见 validation_report_json.segment_prompt_layers。本阶段只输出计划。")
    return {"plan": normalized, "final_prompt": prompt, "reverse_tasks": reverse_tasks, "human_report": "\n".join(report), "validation": validation, "ready": validation["ready"]}
