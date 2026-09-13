"""Portable interview templates, never files, models, or project settings."""

import copy
import json
import math

from .references import ReferenceError, entry_errors, typed_rows, tokenize, field_text, source_for_call, render, ID_RE
from .routing import BANKS_BY_KIND, alignment_context, reusable_template

SCHEMA = "zv-h3-interview-preset-v1"
MAX_BYTES = 2 * 1024 * 1024


class PresetError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def strict_json(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise PresetError("preset_size", "请求最多2 MiB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        def depth(item, level=0):
            if level > 16:
                raise ValueError("depth")
            if isinstance(item, dict):
                for child in item.values(): depth(child, level + 1)
            elif isinstance(item, list):
                for child in item: depth(child, level + 1)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("nonfinite")
        depth(value)
        return value
    except (ValueError, TypeError, RecursionError):
        raise PresetError("preset_json", "JSON非法、重复字段、过深或包含非法数值") from None


def keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise PresetError("preset_fields", "预设字段缺失或包含未知字段")


def validate_slot(slot):
    entries = []
    if not isinstance(slot, dict) or not isinstance(slot.get("kind"), str) or slot.get("kind") not in BANKS_BY_KIND:
        raise PresetError("preset_slots", "模板素材类型无效")
    kind = slot["kind"]
    keys(slot, {"kind", "slot", "participates", "banks", "roles", "purpose"} | ({"soundtrack"} if kind == "video" else set()))
    if type(slot["slot"]) is not int or not 1 <= slot["slot"] <= 512 or type(slot["participates"]) is not bool:
        raise PresetError("preset_slots", "同类槽位重复、范围或参与值无效")
    banks = slot["banks"]
    if not isinstance(banks, list) or not banks or any(not isinstance(bank, str) or bank not in BANKS_BY_KIND[kind] for bank in banks) or len(set(banks)) != len(banks):
        raise PresetError("preset_bank", "槽位物理接口无效")
    roles = slot["roles"]
    if not isinstance(roles, list) or len(roles) > 64 or any(not isinstance(role, str) or not 1 <= len(role) <= 96 for role in roles) or len(set(roles)) != len(roles):
        raise PresetError("preset_roles", "语义标签需要受限且无重复的字符串列表")
    entries.append(slot["purpose"])
    if kind == "video":
        pair = slot["soundtrack"]
        keys(pair, {"expected", "roles", "purpose"})
        if type(pair["expected"]) is not bool or not isinstance(pair["roles"], list) or len(pair["roles"]) > 64 or any(not isinstance(role, str) or not 1 <= len(role) <= 96 for role in pair["roles"]) or len(set(pair["roles"])) != len(pair["roles"]):
            raise PresetError("preset_soundtrack", "原声期望或语义标签无效")
        entries.append(pair["purpose"])
    for entry in entries:
        errors = entry_errors(entry)
        if errors: raise PresetError("preset_reference", "；".join(errors))
    return entries


def validate_template(value):
    from .interview import TEXT_FIELDS, FOCUSES, RECIPES, MODES
    keys(value, {"schema_version", "fields", "director_focus", "slots", "notes"})
    if value["schema_version"] != SCHEMA or value["director_focus"] not in FOCUSES:
        raise PresetError("preset_version", "模板版本或导演侧重无效")
    keys(value["fields"], TEXT_FIELDS)
    keys(value["notes"], {"recipe", "mode"})
    if not isinstance(value["notes"]["recipe"], str) or value["notes"]["recipe"] not in RECIPES or value["notes"]["mode"] not in MODES:
        raise PresetError("preset_notes", "旧配方或模式备注无效")
    entries = list(value["fields"].values())
    slots, identities = value["slots"], set()
    if not isinstance(slots, list) or len(slots) > 1536:
        raise PresetError("preset_slots", "模板槽位最多1536项")
    for slot in slots:
        entries.extend(validate_slot(slot))
        identity = (slot["kind"], slot["slot"])
        if identity in identities: raise PresetError("preset_slots", "同类槽位重复")
        identities.add(identity)
    for entry in entries:
        errors = entry_errors(entry)
        if errors:
            raise PresetError("preset_reference", "；".join(errors))
        for definition in entry["definitions"]:
            source = definition["source"]
            if (source["kind"], source["slot"]) not in identities:
                raise PresetError("preset_reference", "引用 selector 未定义对应素材槽位")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
        raise PresetError("preset_size", "单模板超过2 MiB")
    return copy.deepcopy(value)


def bind_text(entry, inventory):
    rows = typed_rows(inventory)
    runtime = copy.deepcopy(entry)
    for definition in runtime["definitions"]:
        source = definition["source"]
        available = rows[source["kind"]]
        source["item_id"] = available[source["slot"] - 1]["item_id"] if len(available) >= source["slot"] else None
        definition["label"] = f"<H3待绑定:{definition['token']}>"
    runtime["rendered"] = runtime["text"]
    return runtime


def install_text(entry, state, key):
    runtime = copy.deepcopy(entry)
    if key.startswith("purpose:"): state["media_purposes"][key[8:]] = runtime["rendered"]
    else: state[key] = runtime["rendered"]
    state["reference_texts"][key] = runtime


def pending_slot(slot, item_id, soundtrack_only, inventory):
    entries = {"purpose": bind_text(slot["purpose"], inventory)}
    if slot["kind"] == "video": entries["soundtrack"] = bind_text(slot["soundtrack"]["purpose"], inventory)
    return {"slot": copy.deepcopy(slot), "item_id": item_id, "soundtrack_only": soundtrack_only, "reference_texts": entries, "existing_item_ids": [row["item_id"] for row in typed_rows(inventory)[slot["kind"]]]}


def validate_pending(pending):
    if not isinstance(pending, dict) or "existing_item_ids" not in pending:
        raise PresetError("preset_pending", "待补齐缺少初次来源记录，请重新载入原预设；不能按已重排旧槽位猜来源")
    keys(pending, {"slot", "item_id", "soundtrack_only", "reference_texts", "existing_item_ids"})
    slot = pending["slot"]
    validate_slot(slot)
    item_id = pending["item_id"]
    if type(pending["soundtrack_only"]) is not bool or item_id is not None and (not isinstance(item_id, str) or not ID_RE.fullmatch(item_id)) or pending["soundtrack_only"] and (slot["kind"] != "video" or item_id is None):
        raise PresetError("preset_pending", "待绑定原声须记录稳定视频来源")
    existing = pending["existing_item_ids"]
    if not isinstance(existing, list) or len(existing) > 512 or any(not isinstance(value, str) or not ID_RE.fullmatch(value) for value in existing) or len(set(existing)) != len(existing):
        raise PresetError("preset_pending", "初次已有素材须为受限且无重复的稳定ID列表")
    originals = {"purpose": slot["purpose"]}
    if slot["kind"] == "video": originals["soundtrack"] = slot["soundtrack"]["purpose"]
    keys(pending["reference_texts"], originals)
    for key, original in originals.items():
        entry = pending["reference_texts"][key]
        errors = entry_errors(entry, runtime=True)
        if errors: raise PresetError("preset_reference", "；".join(errors))
        portable = {"text": entry["text"], "definitions": [{"token": definition["token"], "source": {key: definition["source"][key] for key in ("kind", "slot", "bank")}} for definition in entry["definitions"]]}
        if portable != original: raise PresetError("preset_reference", "待绑定实时引用与保留用途定义不一致")


def resolve_pending_slots(state, inventory):
    rows, remaining, notices = typed_rows(inventory), [], []
    matched = {}
    ordered = sorted(state["preset_pending"], key=lambda pending: (pending["slot"]["kind"], pending["slot"]["slot"]))
    for pending in ordered:
        kind, ordinal = pending["slot"]["kind"], pending["slot"]["slot"]
        if pending["item_id"] is None:
            candidates = [row for row in rows[kind] if row["item_id"] not in pending["existing_item_ids"]]
            if candidates:
                pending["item_id"] = candidates[0]["item_id"]
                for peer in ordered:
                    if peer["slot"]["kind"] == kind and pending["item_id"] not in peer["existing_item_ids"]:
                        peer["existing_item_ids"].append(pending["item_id"])
        matched[(kind, ordinal)] = pending["item_id"]
    entries = [*state["reference_texts"].values(), *(entry for pending in ordered for entry in pending["reference_texts"].values())]
    for entry in entries:
        for definition in entry["definitions"]:
            source = definition["source"]
            if source["item_id"] is None and (source["kind"], source["slot"]) in matched:
                source["item_id"] = matched[(source["kind"], source["slot"])]
    for pending in ordered:
        slot, item_id = pending["slot"], pending["item_id"]
        # Capture each previously missing source once, even while its purpose waits for audio.
        for entry in pending["reference_texts"].values(): render(entry, [], inventory)
        candidates = rows[slot["kind"]]
        row = next((row for row in candidates if row["item_id"] == item_id), None)
        if row is None:
            remaining.append(pending); notices.append(f"{slot['kind']} 槽{slot['slot']} 待补齐；用途已保留")
            continue
        item_id = row["item_id"]
        if not pending["soundtrack_only"]:
            state["bindings"][item_id] = {"item_id": item_id, "participates": slot["participates"], "banks": list(slot["banks"])}
            state["media_roles"][item_id] = list(slot["roles"])
            install_text(pending["reference_texts"]["purpose"], state, "purpose:" + item_id)
        if slot["kind"] == "video":
            pair_id = row["audio_link_id"]
            if pair_id:
                state["media_roles"][pair_id] = list(slot["soundtrack"]["roles"])
                install_text(pending["reference_texts"]["soundtrack"], state, "purpose:" + pair_id)
            elif slot["soundtrack"]["expected"] or slot["soundtrack"]["roles"] or slot["soundtrack"]["purpose"]["text"]:
                pending["item_id"] = item_id; pending["soundtrack_only"] = True
                remaining.append(pending)
                notices.append(f"video 槽{slot['slot']} 原声待绑定；原声用途已保留，不暗开原声")
    state["preset_pending"] = remaining
    return notices


def capture_template(raw_state, project):
    from .interview import TEXT_FIELDS, compile_interview
    result = compile_interview(raw_state, project)
    if any(row["code"] == "json_size" for row in result["validation"]["errors"]):
        raise PresetError("preset_size", "含引用的当前采访状态超过256 KiB，减少文本后再保存")
    state, inventory, calls = result["state"], result["inventory"], result["call_references"]
    sent_purposes = {call["purpose_item_id"] for call in calls if call["resolved"]}
    confirmed = state["reference_detection"] is not None and state["alignment"] == alignment_context(state, project, inventory)
    def portable(key):
        text = field_text(state, key)
        entry = state["reference_texts"].get(key)
        if entry is not None and text != entry["rendered"]:
            raise PresetError("preset_reference", "编辑后的显式引用尚未解析；保留原文，请检测或修正来源")
        if entry is None:
            try:
                entry = tokenize(text, calls, inventory, confirmed=confirmed)
            except ReferenceError as error:
                raise PresetError("preset_reference", str(error)) from None
        definitions = []
        if entry["definitions"] and not confirmed:
            raise PresetError("preset_alignment", "保存显式引用前请检测，确认当前来源和编号")
        for definition in entry["definitions"]:
            source = definition["source"]
            candidates = [call for call in calls if call["item_id"] == source["item_id"] and source_for_call(call, inventory)["bank"] == source["bank"]]
            if len(candidates) != 1:
                inactive = key.startswith("purpose:") and key[8:] not in sent_purposes
                positions = [index + 1 for index, row in enumerate(typed_rows(inventory)[source["kind"]]) if row["item_id"] == source["item_id"]]
                if not inactive or len(positions) != 1:
                    raise PresetError("preset_reference", "引用来源或物理接口待绑定，不能保存为另一个合法编号")
                current = {**source, "slot": positions[0]}
            else:
                current = source_for_call(candidates[0], inventory)
            definitions.append({"token": definition["token"], "source": {key: current[key] for key in ("kind", "slot", "bank")}})
        return {"text": entry["text"], "definitions": definitions}
    template = {"schema_version": SCHEMA, "fields": {key: portable(key) for key in TEXT_FIELDS}, "director_focus": state["director_focus"], "notes": {"recipe": state["recipe"], "mode": state["mode"]}, "slots": []}
    rows = typed_rows(inventory)
    for base_slot in reusable_template(state, inventory)["slots"]:
        kind, ordinal = base_slot["kind"], base_slot["slot"]
        row = rows[kind][ordinal - 1]; item_id = row["item_id"]
        slot = {**base_slot, "purpose": portable("purpose:" + item_id)}
        if kind == "video":
            pair_id = row["audio_link_id"]
            slot["soundtrack"] = {"expected": any(call["origin"] == "video_soundtrack" and call["item_id"] == item_id for call in calls), "roles": list(state["media_roles"].get(pair_id, [])), "purpose": portable("purpose:" + pair_id) if pair_id else {"text": "", "definitions": []}}
        template["slots"].append(slot)
    for pending in state["preset_pending"]:
        slot = copy.deepcopy(pending["slot"])
        if pending["item_id"] is not None:
            positions = [index + 1 for index, row in enumerate(rows[slot["kind"]]) if row["item_id"] == pending["item_id"]]
            if len(positions) != 1: raise PresetError("preset_reference", "待补齐用途的稳定来源已不在素材台，不能导出为另一槽位")
            slot["slot"] = positions[0]
        def pending_text(entry):
            definitions = []
            for definition in entry["definitions"]:
                source = definition["source"]
                positions = [index + 1 for index, row in enumerate(rows[source["kind"]]) if row["item_id"] == source["item_id"]]
                if source["item_id"] is None and len(rows[source["kind"]]) < source["slot"]:
                    ordinal = source["slot"]
                elif len(positions) == 1:
                    ordinal = positions[0]
                else:
                    raise PresetError("preset_reference", "待补齐引用的稳定来源缺失，不能导出为另一个合法编号")
                definitions.append({"token": definition["token"], "source": {"kind": source["kind"], "slot": ordinal, "bank": source["bank"]}})
            return {"text": entry["text"], "definitions": definitions}
        if not pending["soundtrack_only"]: slot["purpose"] = pending_text(pending["reference_texts"]["purpose"])
        if slot["kind"] == "video": slot["soundtrack"]["purpose"] = pending_text(pending["reference_texts"]["soundtrack"])
        if pending["soundtrack_only"]:
            current = next((row for row in template["slots"] if row["kind"] == "video" and row["slot"] == slot["slot"]), None)
            if current: current["soundtrack"] = slot["soundtrack"]
        elif not any(row["kind"] == slot["kind"] and row["slot"] == slot["slot"] for row in template["slots"]):
            template["slots"].append(slot)
    return validate_template(template)


def apply_template(template, raw_state, project):
    from .interview import TEXT_FIELDS, compile_interview, normalize_interview, media_inventory
    template = validate_template(template)
    state = normalize_interview(raw_state)
    inventory = media_inventory(project)
    rows, notices = typed_rows(inventory), []
    old_context = alignment_context(state, project, inventory)
    def install(entry, key): install_text(bind_text(entry, inventory), state, key)
    state["preset_pending"] = []
    for key in TEXT_FIELDS: install(template["fields"][key], key)
    state["director_focus"] = template["director_focus"]
    state["recipe"], state["mode"] = template["notes"]["recipe"], template["notes"]["mode"]
    matched = set()
    for slot in template["slots"]:
        kind, ordinal = slot["kind"], slot["slot"]
        if len(rows[kind]) < ordinal:
            notices.append({"code": "missing_slot", "message": f"缺少 {kind} 槽{ordinal}；预期仅提醒，可继续补素材"})
            state["preset_pending"].append(pending_slot(slot, None, False, inventory))
            continue
        row = rows[kind][ordinal - 1]; item_id = row["item_id"]; matched.add(item_id)
        state["bindings"][item_id] = {"item_id": item_id, "participates": slot["participates"], "banks": list(slot["banks"])}
        state["media_roles"][item_id] = list(slot["roles"])
        install(slot["purpose"], "purpose:" + item_id)
        if kind == "video":
            pair_id = row["audio_link_id"]
            actual = bool(pair_id and row["source_audio_enabled"] and any(audio["item_id"] == pair_id and audio["enabled"] for audio in inventory))
            if actual != slot["soundtrack"]["expected"]:
                notices.append({"code": "soundtrack_difference", "message": f"video 槽{ordinal} 原声期望与当前状态不同；保持素材台开关"})
            if pair_id:
                pair = slot["soundtrack"]
                if pair["expected"] or pair["roles"] or pair["purpose"]["text"]:
                    state["media_roles"][pair_id] = list(pair["roles"])
                    install(pair["purpose"], "purpose:" + pair_id)
            elif slot["soundtrack"]["expected"] or slot["soundtrack"]["roles"] or slot["soundtrack"]["purpose"]["text"]:
                state["preset_pending"].append(pending_slot(slot, item_id, True, inventory))
    extra = [row for group in rows.values() for row in group if row["item_id"] not in matched]
    if extra:
        notices.append({"code": "extra_slots", "message": f"另有 {len(extra)} 项当前素材；保留其参与和用途，可自由扩展"})
    changed = old_context != alignment_context(state, project, inventory)
    if changed:
        state["reference_detection"] = None; state["alignment"] = None
    result = compile_interview(state, project)
    return {"state": result["state"], "validation": result["validation"], "notices": notices, "mechanical_changed": changed}
