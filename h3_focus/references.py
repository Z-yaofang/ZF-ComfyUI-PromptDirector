"""Explicit H3 references: canonical tokens plus a stable runtime source."""

import copy
import re

LABEL_RE = re.compile(r"<(Picture|Video|Audio) ([0-9]+)>")
TOKEN_RE = re.compile(r"\{\{h3:(r[1-9][0-9]{0,2})\}\}")
ANY_TOKEN_RE = re.compile(r"\{\{h3:[^{}]*\}\}")
BANK_KIND = {"first_frame": "picture", "last_frame": "picture", "ref_images": "picture", "ref_videos": "video", "ref_video_audios": "video", "drive_audio": "audio", "ref_audios": "audio"}
ORIGIN_BANK = {("picture", "first_frame"): "first_frame", ("picture", "last_frame"): "last_frame", ("picture", "reference"): "ref_images", ("video", "reference"): "ref_videos", ("audio", "video_soundtrack"): "ref_video_audios", ("audio", "drive_audio"): "drive_audio", ("audio", "standalone"): "ref_audios"}
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,96}")


class ReferenceError(ValueError):
    pass


def typed_rows(inventory):
    result = {kind: [] for kind in ("picture", "video", "audio")}
    for row in inventory:
        if not row["linked_video_clip_id"]:
            result[row["kind"]].append(row)
    return result


def source_for_call(call, inventory):
    bank = ORIGIN_BANK.get((call["kind"], call["origin"]))
    if bank is None:
        raise ReferenceError("实际引用 origin 无法转换为可携带物理接口")
    kind = BANK_KIND[bank]
    rows = typed_rows(inventory)[kind]
    matches = [index + 1 for index, row in enumerate(rows) if row["item_id"] == call["item_id"]]
    if len(matches) != 1:
        raise ReferenceError("引用来源无法唯一反查素材台槽位")
    return {"kind": kind, "slot": matches[0], "bank": bank, "item_id": call["item_id"]}


def selector_errors(source, runtime=False):
    keys = {"kind", "slot", "bank"} | ({"item_id"} if runtime else set())
    if not isinstance(source, dict) or set(source) != keys:
        return ["引用 selector 字段不完整或包含未知字段"]
    errors = []
    if not isinstance(source["bank"], str) or source["bank"] not in BANK_KIND or source["kind"] != BANK_KIND.get(source["bank"]):
        errors.append("引用 selector 类型与物理 bank 不匹配")
    if type(source["slot"]) is not int or not 1 <= source["slot"] <= 512:
        errors.append("引用素材台同类槽位须为1–512整数")
    if runtime and source["item_id"] is not None and (not isinstance(source["item_id"], str) or not ID_RE.fullmatch(source["item_id"])):
        errors.append("实时引用 stable ID 无效")
    return errors


def entry_errors(entry, runtime=False):
    keys = {"text", "definitions"} | ({"rendered"} if runtime else set())
    if not isinstance(entry, dict) or set(entry) != keys:
        return ["引用文本结构包含未知字段"]
    if not isinstance(entry["text"], str) or len(entry["text"]) > 16000 or not isinstance(entry["definitions"], list) or len(entry["definitions"]) > 128:
        return ["引用文本或定义超过范围"]
    if not entry["definitions"] and len(entry["text"]) > 12000:
        return ["无引用的单项文本最多12000字符"]
    if runtime and (not isinstance(entry["rendered"], str) or len(entry["rendered"]) > 16000):
        return ["实时引用渲染文本无效"]
    errors, ids = [], []
    for definition in entry["definitions"]:
        keys = {"token", "source"} | ({"label"} if runtime else set())
        if not isinstance(definition, dict) or set(definition) != keys or not isinstance(definition.get("token"), str) or not re.fullmatch(r"r[1-9][0-9]{0,2}", definition["token"]) or int(definition["token"][1:]) > 128:
            errors.append("引用 token 定义无效")
            continue
        ids.append(definition["token"])
        errors.extend(selector_errors(definition["source"], runtime))
        if runtime and (not isinstance(definition["label"], str) or len(definition["label"]) > 96):
            errors.append("实时引用 label 无效")
    tokens = TOKEN_RE.findall(entry["text"])
    if len(set(ids)) != len(ids) or set(ids) != set(tokens):
        errors.append("引用 token 重复定义、缺定义或未使用")
    if entry["text"].count("{{h3:") != len(tokens) or ANY_TOKEN_RE.findall(entry["text"]) != [match.group() for match in TOKEN_RE.finditer(entry["text"])]:
        errors.append("存在非法或未知 H3 token")
    if LABEL_RE.search(entry["text"]):
        errors.append("可携带引用不能保留字面 H3 编号")
    return errors


def field_text(state, key):
    return state["media_purposes"].get(key[8:], "") if key.startswith("purpose:") else state[key]


def set_field_text(state, key, text):
    if key.startswith("purpose:"):
        state["media_purposes"][key[8:]] = text
    else:
        state[key] = text


def tokenize(text, calls, inventory, prior=None, confirmed=False):
    """Keep prior sources by their displayed label when prose is edited."""
    definitions = []
    prior_by_label = {}
    for definition in (prior or {}).get("definitions", []):
        prior_by_label.setdefault(definition["label"], []).append(definition["source"])
    by_label = {}
    if confirmed:
        for call in calls:
            by_label.setdefault(call["call_label"], []).append(call)
    def replace(match):
        label = match.group()
        old = prior_by_label.get(label, [])
        unique = {repr(source): source for source in old}
        if len(unique) == 1:
            source = copy.deepcopy(next(iter(unique.values())))
        else:
            matches = by_label.get(label, [])
            if len(matches) != 1:
                raise ReferenceError(f"{label[:96]} 未确认或无法唯一反查；请检测并选择实际来源")
            source = source_for_call(matches[0], inventory)
        token = f"r{len(definitions) + 1}"
        definitions.append({"token": token, "source": source, "label": label})
        return "{{h3:" + token + "}}"
    # Pending markers can be retained or explicitly removed during text edits.
    pending_re = re.compile(r"<H3待绑定:(r[1-9][0-9]*)>")
    def restore_pending(match):
        old = next((row for row in (prior or {}).get("definitions", []) if row["token"] == match.group(1)), None)
        if old is None:
            raise ReferenceError("待绑定引用没有来源定义")
        token = f"r{len(definitions) + 1}"
        definitions.append({"token": token, "source": copy.deepcopy(old["source"]), "label": match.group()})
        return "{{h3:" + token + "}}"
    canonical = LABEL_RE.sub(replace, text)
    canonical = pending_re.sub(restore_pending, canonical)
    if ANY_TOKEN_RE.search(text):
        raise ReferenceError("请从当前有效标签插入引用，不接受手写内部 token")
    if len(definitions) > 128:
        raise ReferenceError("每项文本最多128个显式引用")
    return {"text": canonical, "definitions": definitions, "rendered": text}


def render(entry, calls, inventory):
    rows = typed_rows(inventory)
    missing = []
    for definition in entry["definitions"]:
        source = definition["source"]
        if source["item_id"] is None and len(rows[source["kind"]]) >= source["slot"]:
            source["item_id"] = rows[source["kind"]][source["slot"] - 1]["item_id"]
        matches = [call for call in calls if call["item_id"] == source["item_id"] and ORIGIN_BANK.get((call["kind"], call["origin"])) == source["bank"]]
        definition["label"] = matches[0]["call_label"] if len(matches) == 1 else f"<H3待绑定:{definition['token']}>"
        if len(matches) != 1:
            missing.append(f"{source['kind']} 槽{source['slot']} / {source['bank']} 待绑定")
    labels = {row["token"]: row["label"] for row in entry["definitions"]}
    entry["rendered"] = TOKEN_RE.sub(lambda match: labels[match.group(1)], entry["text"])
    return entry["rendered"], missing


def sync_references(state, calls, inventory, fields, confirmed=False):
    issues = []
    refs = state["reference_texts"]
    for key in [*fields, *("purpose:" + item_id for item_id in state["media_purposes"])]:
        text, prior = field_text(state, key), refs.get(key)
        if prior is None and ("{{h3:" in text or "<H3待绑定:" in text):
            issues.append((key, "引用标记缺少来源定义，请选择实际有效标签"))
            continue
        if prior is not None and text != prior["rendered"] or prior is None and confirmed and LABEL_RE.search(text):
            try:
                prior = refs[key] = tokenize(text, calls, inventory, prior, confirmed)
            except ReferenceError as error:
                issues.append((key, str(error)))
                continue
        if prior is not None:
            rendered, missing = render(prior, calls, inventory)
            set_field_text(state, key, rendered)
            issues.extend((key, message) for message in missing)
    return issues
