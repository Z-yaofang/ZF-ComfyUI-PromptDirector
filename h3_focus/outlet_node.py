"""One normal backend node exposing the complete official H3 media surface."""

from __future__ import annotations

import json
import copy

from .reference_plan import ReferencePlanError, normalize_reference_plan


def _target_canvas(project):
    """Read the one canonical canvas owned by the material desk."""
    value = project.get("output_canvas")
    if isinstance(value, dict):
        width, height = value.get("width"), value.get("height")
        if type(width) is int and type(height) is int:
            return width, height
    return None, None


def _error_summary(plan):
    messages = []
    for row in plan.get("errors", []):
        if isinstance(row, dict):
            messages.append(str(row.get("message") or row.get("code") or "素材计划未就绪"))
        elif row:
            messages.append(str(row))
    return "；".join(dict.fromkeys(messages)) or "采访内容或素材用途尚未通过检查"


def _recovery_hint(plan):
    """Give a remedy that matches the actual validation failure.

    A detection snapshot can be perfectly current while the selected recipe,
    roles, or processing window is invalid.  Telling users to run detection in
    every case hides the useful error and creates a retry loop.
    """
    codes = {
        str(row.get("code", ""))
        for row in plan.get("errors", [])
        if isinstance(row, dict)
    }
    detection_codes = {
        "detection_missing",
        "detection_source_missing",
        "alignment_stale",
        "stage1_mapping",
    }
    if codes and codes <= detection_codes:
        return "请在采访表点击“检测并对齐素材”"
    return "请回到采访表修正上述机械错误；语义用途可留空，检测不能代替接口和时长校验"


class ZVH3ReferenceOutlet:
    """Decode stable interview routes into fixed H3 sockets.

    The output order is an API contract.  New outputs may only be appended so
    saved workflows keep their existing links.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"reference_plan": ("ZV_H3_REFERENCE_PLAN",)}}

    RETURN_TYPES = (
        # Official keyframe sockets.
        "IMAGE", "IMAGE",
        # Official ref_images max=9.
        *("IMAGE",) * 9,
        # Official ref_videos max=3.
        *("IMAGE",) * 3,
        # Same-numbered optional video soundtracks max=3.
        *("AUDIO",) * 3,
        # Source/drive audio is separate from standalone references.
        "AUDIO", "AUDIO",
        # Official ref_audios max=3.
        *("AUDIO",) * 3,
        "STRING", "STRING",
    )
    RETURN_NAMES = (
        "first_frame", "last_frame",
        *(f"ref_image_{index}" for index in range(1, 10)),
        *(f"ref_video_{index}" for index in range(1, 4)),
        *(f"ref_video_audio_{index}" for index in range(1, 4)),
        "drive_audio", "final_audio",
        *(f"ref_audio_{index}" for index in range(1, 4)),
        "reference_plan_json", "report",
    )
    FUNCTION = "export_references"
    CATEGORY = "ZV/视频创作/H3"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        # Stable IDs still point at private source files that can change outside
        # ComfyUI, so the store registry must be checked on every execution.
        return float("nan")

    def export_references(self, reference_plan):
        from ..media_evidence.contract import ProjectError
        from ..media_evidence.outlet import (
            OutletError,
            build_outlet_plan,
            require_combined_output_budget,
            require_valid_project,
        )
        from ..media_evidence.outlet_decode import execute_outlet
        from ..media_evidence.runtime import get_store
        from ..media_evidence.storage import MediaError

        plan = normalize_reference_plan(reference_plan)
        if not plan["ready"]:
            raise ReferencePlanError(
                "H3 素材计划未就绪：" + _error_summary(plan) + "。" + _recovery_hint(plan) + "。"
            )
        if plan.get("media_project") is None:
            raise ReferencePlanError("H3 素材计划没有素材工程，请重新检测并对齐素材")

        store = get_store()
        try:
            project = store.canonical(plan["media_project"])
            require_valid_project(project)
        except ProjectError:
            raise ReferencePlanError("素材工程结构或处理窗口无效，请先在素材台修正") from None
        except MediaError:
            raise ReferencePlanError("素材来源失效或已改变，请在素材台重新导入") from None

        width, height = _target_canvas(project)
        routes = plan["routes"]
        prepared = {}

        def prepare(kind, item_id):
            if item_id is None:
                return
            key = (kind, item_id)
            if key in prepared:
                return
            try:
                reference_project = project
                if kind in ("video", "audio") and plan.get("reference_selection") == "desk_selected_source_segment":
                    item = next((row for row in project.get(kind + "_track", []) if row["clip_id"] == item_id), None)
                    if item is None:
                        raise ReferencePlanError(f"参考段 {item_id} 已不存在")
                    # H3 reference context can precede/follow GEN. Adapt only
                    # this call's window; ordinary/mix outlets retain intersection.
                    reference_project = copy.deepcopy(project)
                    reference_project["processing_window"] = {
                        "start_seconds": item["timeline_in_seconds"],
                        "end_seconds": item["timeline_in_seconds"] + item["source_out_seconds"] - item["source_in_seconds"],
                        "fps": 24,
                    }
                prepared[key] = build_outlet_plan(reference_project, kind, item_id)
            except (OutletError, MediaError) as exc:
                labels = {"picture": "图片", "video": "视频", "audio": "音频"}
                raise ReferencePlanError(f"{labels[kind]} {item_id} 导出计划失败：{exc}") from None

        for item_id in dict.fromkeys(
            [routes["first_frame"], routes["last_frame"], *routes["ref_images"]]
        ):
            prepare("picture", item_id)
        for item_id in dict.fromkeys(routes["ref_videos"]):
            prepare("video", item_id)
        for item_id in dict.fromkeys([routes["drive_audio"], *routes["ref_audios"]]):
            prepare("audio", item_id)
        try:
            require_combined_output_budget(
                prepared.values(), label="H3 固定素材出口本次全部素材"
            )
        except OutletError as exc:
            raise ReferencePlanError(str(exc)) from None

        decoded = {}
        manifests = {}
        reports = []

        def picture(item_id):
            if item_id is None:
                return None
            key = ("picture", item_id)
            if key not in decoded:
                try:
                    media, _original_audio, manifest, report = execute_outlet(
                        store, prepared[key]
                    )
                except (OutletError, MediaError) as exc:
                    raise ReferencePlanError(f"图片 {item_id} 导出失败：{exc}") from None
                decoded[key] = media
                manifests[f"picture:{item_id}"] = manifest
                reports.append(report)
            return decoded[key]

        def video(item_id):
            key = ("video", item_id)
            if key not in decoded:
                try:
                    # The material desk owns output_canvas; the ordinary video
                    # plan inherits it when no per-outlet override is supplied.
                    media, original_audio, manifest, report = execute_outlet(
                        store, prepared[key]
                    )
                except (OutletError, MediaError) as exc:
                    raise ReferencePlanError(f"视频 {item_id} 导出失败：{exc}") from None
                decoded[key] = (media, original_audio)
                manifests[f"video:{item_id}"] = manifest
                reports.append(report)
            return decoded[key]

        def audio(item_id):
            if item_id is None:
                return None
            key = ("audio", item_id)
            if key not in decoded:
                try:
                    media, _original_audio, manifest, report = execute_outlet(
                        store, prepared[key]
                    )
                except (OutletError, MediaError) as exc:
                    raise ReferencePlanError(f"音频 {item_id} 导出失败：{exc}") from None
                decoded[key] = media
                manifests[f"audio:{item_id}"] = manifest
                reports.append(report)
            return decoded[key]

        first_frame = picture(routes["first_frame"])
        last_frame = picture(routes["last_frame"])
        ref_images = [picture(item_id) for item_id in routes["ref_images"]]
        ref_images.extend([None] * (9 - len(ref_images)))

        video_pairs = [video(item_id) for item_id in routes["ref_videos"]]
        video_frames = [pair[0] for pair in video_pairs]
        video_frames.extend([None] * (3 - len(video_frames)))
        soundtrack_ids = set(routes["ref_video_audios"])
        video_audios = [
            pair[1] if item_id in soundtrack_ids else None
            for item_id, pair in zip(routes["ref_videos"], video_pairs)
        ]
        video_audios.extend([None] * (3 - len(video_audios)))

        drive_audio = audio(routes["drive_audio"])
        # T8 defaults final_audio to drive_audio when omitted. Expose the alias
        # explicitly so a completely prewired template also covers this socket.
        final_audio = drive_audio
        ref_audios = [audio(item_id) for item_id in routes["ref_audios"]]
        ref_audios.extend([None] * (3 - len(ref_audios)))

        public_plan = {key: value for key, value in plan.items() if key != "media_project"}
        public_plan["canvas"] = {"width": width, "height": height}
        public_plan["decoded_manifests"] = manifests
        plan_json = json.dumps(public_plan, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        used = (
            f"首帧 {int(first_frame is not None)} / 尾帧 {int(last_frame is not None)} / "
            f"参考图 {len(routes['ref_images'])}/9 / 视频 {len(routes['ref_videos'])}/3 / "
            f"视频原声 {len(routes['ref_video_audios'])}/3 / "
            f"驱动/成片音频 {int(drive_audio is not None)} / 独立音频 {len(routes['ref_audios'])}/3"
        )
        canvas = f"；视频解码画布 {width}×{height}" if width is not None else "；视频保持源尺寸"
        report = "H3 固定素材出口已对齐：" + used + canvas
        if reports:
            report += "\n" + "\n".join(dict.fromkeys(str(row) for row in reports if row))
        if plan.get("reference_selection") == "desk_selected_source_segment":
            report += "\nH3 参考段使用素材台源入/出点，独立于目标 GEN 窗口；普通出口交集规则保持。"
        for row in plan.get("model_visibility", []):
            proof = "已核实" if row.get("model_length_verified") else "假设，实际 length 未核实"
            report += f"\n{row['call_label']} 请求参考 {row['requested_seconds']:.3f} 秒 / 出口 {row['export_frames']} 帧；length={row.get('assumed_model_length')}（{proof}）时预测模型可见 {row['model_frames']} 帧；未做 GPU 成片验证。"
        return (
            first_frame, last_frame,
            *ref_images,
            *video_frames,
            *video_audios,
            drive_audio, final_audio,
            *ref_audios,
            plan_json, report,
        )


__all__ = ["ZVH3ReferenceOutlet"]
