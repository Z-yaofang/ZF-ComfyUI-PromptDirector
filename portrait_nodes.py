import copy
import json
import random
import re
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "portrait_generator_v12.json"


def _load_catalog():
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


PORTRAIT_CATALOG = _load_catalog()
PORTRAIT_FIELDS = [
    (section, field)
    for section in PORTRAIT_CATALOG.get("sections", [])
    for field in section.get("fields", [])
]
PORTRAIT_FIELD_BY_ID = {field["id"]: (section, field) for section, field in PORTRAIT_FIELDS}
DEFAULT_PORTRAIT_STATE = json.dumps(
    {
        "version": 6,
        "adult_content": False,
        "auto_random": False,
        "selected": {},
        "enabled": {},
        "overrides": {},
        "pinned": {},
        "locked": {},
        "section_locked": {},
        "section_lock_items": {},
        "section_enabled": {},
        "option_overrides": {},
    },
    ensure_ascii=False,
    separators=(",", ":"),
)


PROMPT_SECTION_ORDER = (
    "shooting_light",
    "subject",
    "person_detail",
    "hair",
    "styling_expression",
    "wear_state",
    "clothing",
    "accessories",
    "clothing_expression",
    "posture",
    "action",
    "bg",
    "comp",
    "extra",
)

CORE_RANDOM_FIELDS = {
    "lens", "viewpoint", "shotSize", "dof", "device", "mainLight", "ambient", "colorTone",
    "temperament", "age", "race", "face", "skin", "texture", "body", "leg", "firstImp",
    "nsfwLowerBody", "nsfwBreastDetail",
    "hairLen", "hairColor", "hairCurl", "hairTie", "hairBangs", "hairState",
    "makeup", "makeupDetail", "emotion", "eye", "mouth",
    "scene", "prop", "weather", "comp", "compPos",
}
ALWAYS_RANDOM_FIELDS = {
    "lens", "viewpoint", "shotSize", "mainLight", "colorTone", "temperament", "age",
    "race", "face", "skin", "body", "leg", "firstImp", "hairLen", "hairColor",
    "emotion", "eye", "mouth", "scene", "comp", "compPos",
}
POSTURE_FIELD_IDS = {
    "postureSupine", "postureProne", "postureSide", "postureKneeling", "postureSitting",
    "postureStanding", "postureSquatting", "postureSuspended", "postureSpecial",
    "adultPostureSupine", "adultPostureProne", "adultPostureSide", "adultPostureKneeling",
    "adultPostureSitting", "adultPostureStanding", "adultPostureSquatting",
    "adultPostureSuspended", "adultPostureSpecial",
}
ACTION_FIELD_IDS = {
    "actionTransition", "actionWalking", "actionJumping", "actionSpinning",
    "adultActionTransition", "adultActionWalking", "adultActionJumping", "adultActionSpinning",
}
MOVEMENT_FIELD_IDS = POSTURE_FIELD_IDS | ACTION_FIELD_IDS
ADULT_MOVEMENT_FIELD_IDS = {
    field_id for field_id in MOVEMENT_FIELD_IDS
    if PORTRAIT_FIELD_BY_ID.get(field_id, ({}, {}))[1].get("adult")
}
REGULAR_MOVEMENT_FIELD_IDS = MOVEMENT_FIELD_IDS - ADULT_MOVEMENT_FIELD_IDS
STANDARD_CLOTHING_FIELD_IDS = {
    "stylePreset", "clothCat", "clothItem", "outerwear", "collarStyle", "topLength",
    "bottomStyle", "splitColor", "bottomLength",
}
LINGERIE_FIELD_IDS = {
    "lingerieCat", "lingerieItem", "lingerieColor1", "lingerieColor2", "pantyColor", "pantyStyle",
}
ACCESSORY_FIELD_IDS = {"shoes", "sockType", "sockLen", "sockColor", "sockOpacity", "accessory"}
CLOTHING_EXPRESSION_FIELD_IDS = {
    "clothMat", "clothPattern", "clothDeco", "clothLayer", "sfwExposure",
    "clothTransparency", "nsfwExposure",
}
CLOTHING_DEGREE_FIELD_IDS = {"sfwExposure", "clothTransparency", "nsfwExposure"}
CLOTHING_MANAGED_FIELD_IDS = (
    {"nsfwState"} | STANDARD_CLOTHING_FIELD_IDS | LINGERIE_FIELD_IDS
    | ACCESSORY_FIELD_IDS | CLOTHING_EXPRESSION_FIELD_IDS
)
NO_CLOTHING_STATES = {"仅剩配饰", "裸露加配饰"}
ADULT_DETAIL_FIELD_IDS = {"nsfwLowerBody", "nsfwBreastDetail"}


def _legacy_movement_field(field_id, value):
    adult = field_id == "simPick"
    code = str(value or "").upper()
    prefix = "adultPosture" if adult else "posture"
    posture_names = {
        "A": "Supine",
        "B": "Prone",
        "C": "Side",
        "D": "Kneeling",
        "E": "Sitting",
        "F": "Standing",
        "G": "Squatting",
        "H": "Suspended",
        "J": "Special",
    }
    if code[:1] in posture_names:
        return prefix + posture_names[code[0]]
    if not code.startswith("I"):
        return ""
    try:
        number = int(code[1:])
    except ValueError:
        return ""
    if adult:
        if number <= 20 or number >= 81:
            return "adultActionTransition"
        if number <= 40:
            return "adultActionWalking"
        if number <= 60:
            return "adultActionJumping"
        return "adultActionSpinning"
    if number <= 10 or number >= 26:
        return "actionTransition"
    if number <= 18:
        return "actionWalking"
    if number <= 22:
        return "actionJumping"
    return "actionSpinning"


def _migrate_legacy_movement(state):
    for legacy_id in ("sfwSimPick", "simPick"):
        target_id = _legacy_movement_field(legacy_id, state["selected"].get(legacy_id))
        if target_id:
            state["selected"].setdefault(target_id, state["selected"][legacy_id])
            if state["overrides"].get(legacy_id):
                state["overrides"].setdefault(target_id, state["overrides"][legacy_id])
            if state["pinned"].get(legacy_id):
                state["pinned"][target_id] = True
            if state["locked"].get(legacy_id):
                state["locked"][target_id] = True
            if state["section_lock_items"].get(legacy_id):
                state["section_lock_items"][target_id] = True
            if state["enabled"].get(legacy_id) is False:
                state["enabled"][target_id] = False
        legacy_prefix = f"{legacy_id}::"
        for key, text in list(state["option_overrides"].items()):
            if not key.startswith(legacy_prefix):
                continue
            value = key[len(legacy_prefix):]
            option_target = _legacy_movement_field(legacy_id, value)
            if option_target:
                state["option_overrides"].setdefault(f"{option_target}::{value}", text)
            del state["option_overrides"][key]
        for name in ("selected", "overrides", "pinned", "locked", "section_lock_items", "enabled"):
            state[name].pop(legacy_id, None)
    for legacy_id in (
        "sfwSimMode", "sfwSimCoreCat", "sfwSimCat",
        "simMode", "simCoreCat", "simCat",
    ):
        for name in ("selected", "overrides", "pinned", "locked", "section_lock_items", "enabled"):
            state[name].pop(legacy_id, None)
    if "pose" in state["section_locked"]:
        value = state["section_locked"].pop("pose")
        state["section_locked"].setdefault("posture", value)
        state["section_locked"].setdefault("action", value)
    if "pose" in state["section_enabled"]:
        value = state["section_enabled"].pop("pose")
        state["section_enabled"].setdefault("posture", value)
        state["section_enabled"].setdefault("action", value)
    return state


def _migrate_legacy_sections(state, previous_version):
    if previous_version >= 6:
        return state
    targets = {
        "camera": ("shooting_light",),
        "light": ("shooting_light",),
        "person": ("subject", "person_detail"),
        "makeup": ("styling_expression",),
        "expression": ("styling_expression",),
        "cloth": ("wear_state", "clothing", "accessories", "clothing_expression"),
    }
    for collection_name in ("section_locked", "section_enabled"):
        collection = state[collection_name]
        for legacy_id, next_ids in targets.items():
            if legacy_id not in collection:
                continue
            value = collection.pop(legacy_id)
            for next_id in next_ids:
                if collection_name == "section_locked":
                    collection[next_id] = bool(collection.get(next_id) or value)
                elif next_id not in collection or value is False:
                    collection[next_id] = value
    return state


def _parse_state(value):
    try:
        state = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    try:
        previous_version = int(state.get("version", 0) or 0)
    except (TypeError, ValueError):
        previous_version = 0
    for key in (
        "selected",
        "enabled",
        "overrides",
        "pinned",
        "locked",
        "section_locked",
        "section_lock_items",
        "section_enabled",
        "option_overrides",
    ):
        if not isinstance(state.get(key), dict):
            state[key] = {}
    state = _migrate_legacy_movement(state)
    state = _migrate_legacy_sections(state, previous_version)
    if previous_version < 5:
        for section, field in PORTRAIT_FIELDS:
            if not state["section_locked"].get(section["id"]):
                continue
            field_id = field["id"]
            if state["selected"].get(field_id) or state["overrides"].get(field_id):
                state["section_lock_items"][field_id] = True
    state["auto_random"] = bool(state.get("auto_random", False))
    state["adult_content"] = bool(state.get("adult_content", False))
    state["version"] = 6
    return state


def _clean_text(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ，,;；")
    if text in ("", "不启用"):
        return ""
    return text


def _option_text(field, selected_value, option_overrides=None):
    selected = str(selected_value or "")
    for option in field.get("options", []):
        if str(option.get("value", "")) == selected:
            key = f"{field['id']}::{selected}"
            customized = _clean_text((option_overrides or {}).get(key))
            return customized or _clean_text(option.get("text") or option.get("value")), bool(option.get("adult"))
    return "", False


def _minor_marker(text):
    source = str(text or "")
    return None

def _is_locked(state, field_id):
    return bool(state["locked"].get(field_id) or state["section_lock_items"].get(field_id))


def _is_locked(state, field_id):
    return bool(state["locked"].get(field_id) or state["section_lock_items"].get(field_id))


def _has_value(state, field_id):
    return bool(_clean_text(state["selected"].get(field_id)) or _clean_text(state["overrides"].get(field_id)))


def _clear_unlocked(state, field_ids):
    for field_id in field_ids:
        if _is_locked(state, field_id):
            continue
        state["selected"].pop(field_id, None)
        state["overrides"].pop(field_id, None)


def _usable_options(field, state, adult_requested):
    if field.get("adult") and not adult_requested:
        return []
    options = [
        option for option in field.get("options", [])
        if _clean_text(option.get("value"))
        and _clean_text(option.get("value")) != "不启用"
        and (adult_requested or not option.get("adult"))
    ]
    if field["id"] == "clothItem" and state["selected"].get("clothCat"):
        matched = [option for option in options if option.get("group") == state["selected"]["clothCat"]]
        if matched:
            options = matched
    if field["id"] == "lingerieItem" and state["selected"].get("lingerieCat"):
        category = str(state["selected"]["lingerieCat"]).split("·")[-1]
        matched = [option for option in options if option.get("group") == category]
        if matched:
            options = matched
    return options


def _choose_random(state, field_id, rng, adult_requested):
    target = PORTRAIT_FIELD_BY_ID.get(field_id)
    if not target or _is_locked(state, field_id):
        return None
    _, field = target
    options = _usable_options(field, state, adult_requested)
    if not options:
        return None
    picked = rng.choice(options)
    state["selected"][field_id] = picked["value"]
    state["overrides"].pop(field_id, None)
    return picked


def _locked_value_in(state, field_ids):
    return any(_is_locked(state, field_id) and _has_value(state, field_id) for field_id in field_ids)


def _selected_clothing_family(state):
    standard = any(_has_value(state, field_id) for field_id in STANDARD_CLOTHING_FIELD_IDS)
    lingerie = any(_has_value(state, field_id) for field_id in LINGERIE_FIELD_IDS)
    if standard and not lingerie:
        return "standard"
    if lingerie and not standard:
        return "lingerie"
    if standard and lingerie:
        return "lingerie" if _locked_value_in(state, LINGERIE_FIELD_IDS) else "standard"
    return ""


def _option_for(field_id, value):
    target = PORTRAIT_FIELD_BY_ID.get(field_id)
    if not target:
        return None
    return next(
        (option for option in target[1].get("options", []) if str(option.get("value")) == str(value)),
        None,
    )


def _lingerie_category_for_group(group):
    target = PORTRAIT_FIELD_BY_ID.get("lingerieCat")
    if not target:
        return ""
    return next(
        (
            str(option.get("value")) for option in target[1].get("options", [])
            if str(option.get("value", "")).split("·")[-1] == str(group)
        ),
        "",
    )


def _resolve_clothing_conflicts(state, adult_requested):
    if not adult_requested:
        _clear_unlocked(state, {field_id for field_id in CLOTHING_MANAGED_FIELD_IDS if PORTRAIT_FIELD_BY_ID.get(field_id, ({}, {}))[1].get("adult")})

    if str(state["selected"].get("nsfwState", "")) in NO_CLOTHING_STATES:
        _clear_unlocked(state, STANDARD_CLOTHING_FIELD_IDS)
        _clear_unlocked(state, LINGERIE_FIELD_IDS)
        _clear_unlocked(state, CLOTHING_EXPRESSION_FIELD_IDS)
        return

    standard = any(_has_value(state, field_id) for field_id in STANDARD_CLOTHING_FIELD_IDS)
    lingerie = any(_has_value(state, field_id) for field_id in LINGERIE_FIELD_IDS)
    if standard and lingerie:
        standard_locked = _locked_value_in(state, STANDARD_CLOTHING_FIELD_IDS)
        lingerie_locked = _locked_value_in(state, LINGERIE_FIELD_IDS)
        if lingerie_locked and not standard_locked:
            _clear_unlocked(state, STANDARD_CLOTHING_FIELD_IDS)
        else:
            _clear_unlocked(state, LINGERIE_FIELD_IDS)

    cloth_item = _option_for("clothItem", state["selected"].get("clothItem"))
    if cloth_item and cloth_item.get("group"):
        if _is_locked(state, "clothCat") and state["selected"].get("clothCat") != cloth_item["group"]:
            _clear_unlocked(state, {"clothItem"})
        elif not _is_locked(state, "clothCat"):
            state["selected"]["clothCat"] = cloth_item["group"]

    lingerie_item = _option_for("lingerieItem", state["selected"].get("lingerieItem"))
    if lingerie_item and lingerie_item.get("group"):
        category = _lingerie_category_for_group(lingerie_item["group"])
        if _is_locked(state, "lingerieCat") and state["selected"].get("lingerieCat") != category:
            _clear_unlocked(state, {"lingerieItem"})
        elif category and not _is_locked(state, "lingerieCat"):
            state["selected"]["lingerieCat"] = category

    selected_degrees = [field_id for field_id in CLOTHING_DEGREE_FIELD_IDS if _has_value(state, field_id)]
    if len(selected_degrees) > 1:
        keep = next((field_id for field_id in selected_degrees if _is_locked(state, field_id)), selected_degrees[0])
        _clear_unlocked(state, set(selected_degrees) - {keep})


def _resolve_movement_conflicts(state):
    selected = [field_id for field_id in MOVEMENT_FIELD_IDS if _has_value(state, field_id)]
    if len(selected) <= 1:
        return
    keep = next((field_id for field_id in selected if _is_locked(state, field_id)), selected[0])
    _clear_unlocked(state, set(selected) - {keep})


def _randomize_clothing(state, rng, adult_requested):
    selected = state["selected"]

    def field_enabled(field_id):
        target = PORTRAIT_FIELD_BY_ID.get(field_id)
        if not target:
            return False
        section, field = target
        return (
            state["section_enabled"].get(section["id"], True) is not False
            and state["enabled"].get(field_id, True) is not False
            and (adult_requested or not field.get("adult"))
        )

    def random_field(field_id, probability=1.0):
        if not field_enabled(field_id) or _is_locked(state, field_id):
            return None
        if rng.random() > probability:
            _clear_unlocked(state, {field_id})
            return None
        return _choose_random(state, field_id, rng, adult_requested)

    if adult_requested and state["section_enabled"].get("wear_state", True) is not False:
        if field_enabled("nsfwState") and not _is_locked(state, "nsfwState"):
            wear_field = PORTRAIT_FIELD_BY_ID["nsfwState"][1]
            wear_options = _usable_options(wear_field, state, True)
            if _locked_value_in(state, STANDARD_CLOTHING_FIELD_IDS | LINGERIE_FIELD_IDS):
                wear_options = [
                    option for option in wear_options
                    if str(option.get("value")) not in NO_CLOTHING_STATES
                ]
            if wear_options:
                picked = rng.choice(wear_options)
                selected["nsfwState"] = picked["value"]
                state["overrides"].pop("nsfwState", None)
    else:
        _clear_unlocked(state, {"nsfwState"})

    no_clothing = str(selected.get("nsfwState", "")) in NO_CLOTHING_STATES
    if no_clothing:
        _clear_unlocked(state, STANDARD_CLOTHING_FIELD_IDS)
        _clear_unlocked(state, LINGERIE_FIELD_IDS)
        _clear_unlocked(state, CLOTHING_EXPRESSION_FIELD_IDS)
    elif state["section_enabled"].get("clothing", True) is not False:
        standard_locked = _locked_value_in(state, STANDARD_CLOTHING_FIELD_IDS)
        lingerie_locked = _locked_value_in(state, LINGERIE_FIELD_IDS)
        if lingerie_locked and not standard_locked:
            family = "lingerie"
        elif standard_locked:
            family = "standard"
        else:
            # The source HTML keeps ordinary clothing as the main outfit when
            # NSFW enhancement is enabled. Lingerie is a separate, explicit
            # replacement mode rather than the default adult random family.
            family = "standard"

        if family == "lingerie":
            _clear_unlocked(state, STANDARD_CLOTHING_FIELD_IDS)
            locked_item = _option_for("lingerieItem", selected.get("lingerieItem")) if _is_locked(state, "lingerieItem") else None
            if locked_item and locked_item.get("group") and not _is_locked(state, "lingerieCat"):
                selected["lingerieCat"] = _lingerie_category_for_group(locked_item["group"])
            elif not _is_locked(state, "lingerieCat"):
                random_field("lingerieCat")
            if not _is_locked(state, "lingerieItem"):
                random_field("lingerieItem")
            random_field("lingerieColor1", 0.42)
            random_field("lingerieColor2", 0.42)
            _clear_unlocked(state, {"pantyColor", "pantyStyle"})
        else:
            _clear_unlocked(state, LINGERIE_FIELD_IDS)
            if not _is_locked(state, "stylePreset"):
                _clear_unlocked(state, {"stylePreset"})
            locked_item = _option_for("clothItem", selected.get("clothItem")) if _is_locked(state, "clothItem") else None
            if locked_item and locked_item.get("group") and not _is_locked(state, "clothCat"):
                selected["clothCat"] = locked_item["group"]
            elif not _is_locked(state, "clothCat"):
                random_field("clothCat")
            if not _is_locked(state, "clothItem"):
                random_field("clothItem")
            random_field("outerwear", 0.42)
            random_field("bottomLength", 0.42)
            if selected.get("clothCat") == "上下装":
                for field_id in ("collarStyle", "topLength", "bottomStyle", "splitColor"):
                    random_field(field_id, 0.42)
            else:
                _clear_unlocked(state, {"collarStyle", "topLength", "bottomStyle", "splitColor"})

    if state["section_enabled"].get("accessories", True) is not False:
        for field_id in ACCESSORY_FIELD_IDS:
            random_field(field_id, 0.42)

    if state["section_enabled"].get("clothing_expression", True) is not False:
        _clear_unlocked(state, CLOTHING_DEGREE_FIELD_IDS)
        if not no_clothing:
            family = _selected_clothing_family(state)
            if family == "standard":
                for field_id in ("clothMat", "clothPattern", "clothDeco", "clothLayer"):
                    random_field(field_id, 0.42)
            else:
                _clear_unlocked(state, {"clothMat", "clothPattern", "clothDeco", "clothLayer"})
            locked_degree = any(_is_locked(state, field_id) and _has_value(state, field_id) for field_id in CLOTHING_DEGREE_FIELD_IDS)
            if not locked_degree and (adult_requested or rng.random() < 0.42):
                degree_ids = ["nsfwExposure"] if adult_requested else [
                    "sfwExposure", "clothTransparency",
                ]
                candidates = [field_id for field_id in degree_ids if field_enabled(field_id)]
                if candidates:
                    random_field(rng.choice(candidates))

    _resolve_clothing_conflicts(state, adult_requested)


def _randomize_state(state, rng, adult_requested):
    for section, field in PORTRAIT_FIELDS:
        field_id = field["id"]
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        if state["enabled"].get(field_id, True) is False:
            continue
        if field_id not in CORE_RANDOM_FIELDS or field_id in CLOTHING_MANAGED_FIELD_IDS or field_id in MOVEMENT_FIELD_IDS:
            continue
        if field.get("adult") and not adult_requested or _is_locked(state, field_id):
            continue
        # Adult mode is an extension of the complete normal portrait recipe,
        # not a small adult-only draw. Keep optional common dimensions in the
        # generated prompt so the result still describes a full person/scene.
        if not adult_requested and field_id not in ALWAYS_RANDOM_FIELDS and rng.random() > 0.42:
            _clear_unlocked(state, {field_id})
            continue
        _choose_random(state, field_id, rng, adult_requested)

    locked_movement = any(_is_locked(state, field_id) and _has_value(state, field_id) for field_id in MOVEMENT_FIELD_IDS)
    if not locked_movement:
        _clear_unlocked(state, MOVEMENT_FIELD_IDS)
        candidates = []
        for section, field in PORTRAIT_FIELDS:
            if field["id"] not in MOVEMENT_FIELD_IDS:
                continue
            if state["section_enabled"].get(section["id"], True) is False:
                continue
            if field.get("adult") and not adult_requested:
                continue
            for option in _usable_options(field, state, adult_requested):
                candidates.append((field["id"], option["value"], bool(field.get("adult"))))
        if adult_requested:
            # Only the movement branch switches to the adult library. All
            # photographic, character, clothing and environment fields remain
            # in the normal prompt skeleton.
            candidates = [item for item in candidates if item[2]]
        else:
            candidates = [item for item in candidates if not item[2]]
        if candidates:
            field_id, value, _ = rng.choice(candidates)
            state["selected"][field_id] = value

    if adult_requested and state["section_enabled"].get("action", True) is not False and not _is_locked(state, "nsfwChain"):
        if rng.random() < 0.42:
            _choose_random(state, "nsfwChain", rng, adult_requested)
        else:
            _clear_unlocked(state, {"nsfwChain"})
    _randomize_clothing(state, rng, adult_requested)


def _has_active_adult_selection(state):
    for section, field in PORTRAIT_FIELDS:
        if not field.get("adult"):
            continue
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        if state["enabled"].get(field["id"], True) is False:
            continue
        override = _clean_text(state["overrides"].get(field["id"]))
        option_text, _ = _option_text(
            field,
            state["selected"].get(field["id"]),
            state["option_overrides"],
        )
        if override or option_text:
            return True
    return False


def _ensure_adult_selection(state, rng):
    """Guarantee an adult overlay without replacing the normal prompt skeleton."""
    if _has_active_adult_selection(state):
        return True
    priority_groups = (
        tuple(sorted(ADULT_DETAIL_FIELD_IDS)),
        ("nsfwState",),
        tuple(
            field["id"]
            for _, field in PORTRAIT_FIELDS
            if field["id"] in MOVEMENT_FIELD_IDS and field.get("adult")
        ),
        ("nsfwExposure", "lingerieItem", "nsfwChain"),
    )
    for field_ids in priority_groups:
        candidates = []
        for field_id in field_ids:
            target = PORTRAIT_FIELD_BY_ID.get(field_id)
            if not target or _is_locked(state, field_id):
                continue
            section, field = target
            if state["section_enabled"].get(section["id"], True) is False:
                continue
            if state["enabled"].get(field_id, True) is False:
                continue
            if _usable_options(field, state, True):
                candidates.append(field_id)
        if not candidates:
            continue
        picked_id = rng.choice(candidates)
        if picked_id == "lingerieItem" and not state["selected"].get("lingerieCat"):
            _choose_random(state, "lingerieCat", rng, True)
        _choose_random(state, picked_id, rng, True)
        if _has_active_adult_selection(state):
            return True
    return False


def _has_active_normal_selection(state):
    """Return whether the state already contains any usable normal material."""
    for section, field in PORTRAIT_FIELDS:
        if field.get("adult"):
            continue
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        if state["enabled"].get(field["id"], True) is False:
            continue
        override = _clean_text(state["overrides"].get(field["id"]))
        option_text, option_is_adult = _option_text(
            field,
            state["selected"].get(field["id"]),
            state["option_overrides"],
        )
        if override or (option_text and not option_is_adult):
            return True
    return False


def _field_texts(state, adult_requested):
    selected = state["selected"]
    enabled = state["enabled"]
    overrides = state["overrides"]
    normal_text = []
    adult_text = []
    by_section = {section_id: [] for section_id in PROMPT_SECTION_ORDER}

    for section, field in PORTRAIT_FIELDS:
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        field_id = field["id"]
        if enabled.get(field_id, True) is False:
            continue
        override = _clean_text(overrides.get(field_id))
        option_text, option_is_adult = _option_text(
            field,
            selected.get(field_id),
            state["option_overrides"],
        )
        text = override or option_text
        if not text:
            continue
        is_adult = bool(field.get("adult") or option_is_adult)
        if is_adult:
            adult_text.append((section["id"], text))
            if not adult_requested:
                continue
        else:
            normal_text.append(text)
        by_section.setdefault(section["id"], []).append(text)
    return normal_text, adult_text, by_section


def _resolved_prompt_fields(state, adult_requested):
    """Resolve the active catalog fields without exposing section metadata."""
    resolved = {}
    adult_present = False
    for section, field in PORTRAIT_FIELDS:
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        field_id = field["id"]
        if state["enabled"].get(field_id, True) is False:
            continue
        override = _clean_text(state["overrides"].get(field_id))
        option_text, option_is_adult = _option_text(
            field,
            state["selected"].get(field_id),
            state["option_overrides"],
        )
        text = override or option_text
        if not text:
            continue
        is_adult = bool(field.get("adult") or option_is_adult)
        if is_adult and not adult_requested:
            continue
        resolved[field_id] = text
        adult_present = adult_present or is_adult
    return resolved, adult_present


def _sentence(text):
    text = _clean_text(text)
    if not text:
        return ""
    if re.search(r"[。！？.!?]$", text):
        return text
    return f"{text}。"


def _join_prompt_parts(parts):
    output = ""
    for part in parts:
        if not part:
            continue
        if (
            output
            and not re.search(r"[\u4e00-\u9fff\u3000。！？，、；：]$", output)
            and re.match(r"[\u4e00-\u9fff]", part)
        ):
            output += " "
        output += part
    return output


def _leg_ratio_description(state, fields):
    custom = _clean_text(state["overrides"].get("legRatio"))
    if custom:
        return custom
    if "legRatio" not in fields:
        return ""
    try:
        ratio = float(state["selected"].get("legRatio", 1) or 1)
    except (TypeError, ValueError):
        return fields["legRatio"]
    if ratio <= 1:
        return ""
    if ratio >= 1.9:
        return "双腿极其修长，腿长接近上半身两倍，九头身超模比例，满屏长腿"
    if ratio >= 1.7:
        return f"双腿极为修长，腿长约为上半身的{ratio:.1f}倍，逆天长腿，九头身比例"
    if ratio >= 1.45:
        return f"双腿修长挺拔，腿长约为上半身的{ratio:.1f}倍，高挑显腿长"
    if ratio >= 1.2:
        return f"双腿修长匀称，腿长约为上半身的{ratio:.1f}倍，身形比例极佳"
    return "双腿比例自然修长，腿长略长于上半身"


def _build_portrait_prompt(state, adult_requested, reference=""):
    """Build the same clean, prose-style prompt shape used by the source HTML."""
    fields, adult_present = _resolved_prompt_fields(state, adult_requested)
    selected = state["selected"]
    parts = []

    # The source HTML places an active wear state before the photographic setup.
    wear_state = fields.get("nsfwState", "")
    if wear_state:
        prefix = "" if adult_present else ""
        parts.append(_sentence(f"{prefix}{wear_state}"))

    camera = []
    for field_id in ("lens", "viewpoint"):
        if fields.get(field_id):
            camera.append(fields[field_id])
    if fields.get("shotSize"):
        camera.append(f"取{fields['shotSize']}景别")
    if fields.get("dof"):
        camera.append(fields["dof"])
    if fields.get("device"):
        camera.append(f"画面以{fields['device']}呈现")
    if camera:
        parts.append(_sentence("，".join(camera)))

    for field_id in ("mainLight", "ambient", "colorTone", "film", "cine"):
        if fields.get(field_id):
            parts.append(_sentence(fields[field_id]))

    person = []
    temperament = fields.get("temperament", "")
    age = fields.get("age", "")
    if temperament and age:
        person.append(f"{temperament}的{age}")
    elif temperament or age:
        person.append(temperament or age)
    if fields.get("race"):
        person.append(fields["race"])
    skin = fields.get("skin", "")
    texture = fields.get("texture", "")
    if skin or texture:
        person.append(f"{skin}{texture}")
    if fields.get("face"):
        person.append(fields["face"])
    body_and_legs = [fields.get(field_id, "") for field_id in ("body", "leg")]
    body_and_legs = [item for item in body_and_legs if item]
    if body_and_legs:
        person.append("、".join(body_and_legs))
    ratio_text = _leg_ratio_description(state, fields)
    if ratio_text:
        person.append(ratio_text)
    for field_id in (
        "breastSize", "breastShape", "shoulder", "chestPos", "waist", "hip", "arm",
        "nsfwLowerBody", "nsfwBreastDetail", "firstImp",
    ):
        if fields.get(field_id):
            person.append(fields[field_id])
    if person:
        parts.append(_sentence(f"人物为{'，'.join(person)}"))

    tattoo = fields.get("tattoo", "")
    tattoo_position = fields.get("tattooPos", "")
    if tattoo and tattoo_position:
        parts.append(_sentence(f"{tattoo_position}有一枚{tattoo}纹身，墨色贴合皮肤轮廓自然晕染"))

    hair = []
    hair_core = "".join(fields.get(field_id, "") for field_id in ("hairLen", "hairColor", "hairCurl"))
    if hair_core:
        hair.append(hair_core)
    for field_id in ("hairTie", "hairBangs", "hairState", "hairAccFront", "hairAccBack", "hairAccSide"):
        if fields.get(field_id):
            hair.append(fields[field_id])
    if hair:
        parts.append(_sentence("，".join(hair)))

    makeup = []
    if fields.get("makeup"):
        makeup.append(f"妆容为{fields['makeup']}")
    for field_id in ("makeupDetail", "smudge", "nails"):
        if fields.get(field_id):
            makeup.append(fields[field_id])
    if makeup:
        parts.append(_sentence("，".join(makeup)))

    expression = [fields.get(field_id, "") for field_id in ("emotion", "eye", "mouth")]
    expression = [item for item in expression if item]
    if expression:
        parts.append(_sentence("，".join(expression)))
    imperfections = [fields.get(field_id, "") for field_id in ("imperf1", "imperf2")]
    imperfections = list(dict.fromkeys(item for item in imperfections if item))
    if imperfections:
        parts.append(_sentence("，".join(imperfections)))

    movement = ""
    for _, field in PORTRAIT_FIELDS:
        if field["id"] in MOVEMENT_FIELD_IDS and fields.get(field["id"]):
            movement = fields[field["id"]]
            break
    reaction = fields.get("nsfwChain", "")
    if reaction:
        movement = f"{movement.rstrip('，,。 ')}，{reaction}" if movement else reaction
    if movement:
        parts.append(_sentence(movement))

    clothing = []
    cloth_item = fields.get("clothItem", "")
    cloth_category = str(selected.get("clothCat") or "")
    if cloth_item:
        if cloth_category == "上下装":
            clothing.append(f"上身穿着{cloth_item}")
        else:
            clothing.append(f"身着{cloth_item}")
    for field_id, prefix in (
        ("clothMat", ""),
        ("clothPattern", ""),
        ("clothDeco", ""),
        ("outerwear", "外搭"),
        ("collarStyle", ""),
        ("topLength", ""),
        ("clothLayer", ""),
        ("bottomStyle", "下身搭配"),
        ("bottomLength", ""),
        ("splitColor", ""),
    ):
        if fields.get(field_id):
            text = fields[field_id]
            if field_id == "clothDeco":
                text = f"{text}装饰细节"
            clothing.append(f"{prefix}{text}")

    lingerie_item = fields.get("lingerieItem", "")
    if lingerie_item:
        lingerie_category = fields.get("lingerieCat", "")
        if lingerie_category:
            clothing.append(f"身着{lingerie_category}风格的情趣内衣")
        clothing.append(lingerie_item)
        if fields.get("lingerieColor1"):
            clothing.append(f"主色调为{fields['lingerieColor1']}")
        if fields.get("lingerieColor2"):
            clothing.append(f"辅色调为{fields['lingerieColor2']}")

    panty = f"{fields.get('pantyColor', '')}{fields.get('pantyStyle', '')}".strip()
    if panty:
        clothing.append(f"下身穿着{panty}")
    for field_id in ("sfwExposure", "clothTransparency", "nsfwExposure"):
        if fields.get(field_id):
            clothing.append(fields[field_id])
    if clothing:
        parts.append(_sentence("，".join(clothing)))

    accessories = []
    if fields.get("shoes"):
        accessories.append(f"脚穿{fields['shoes']}")
    sock_type = fields.get("sockType", "")
    if sock_type:
        sock_name = "".join(
            fields.get(field_id, "")
            for field_id in ("sockColor", "sockLen")
        ) + str(selected.get("sockType") or "")
        sock_details = [sock_type]
        if fields.get("sockOpacity"):
            sock_details.append(fields["sockOpacity"])
        accessories.append(f"双腿穿着{sock_name}，{'，'.join(sock_details)}")
    if fields.get("accessory"):
        accessories.append(fields["accessory"])
    if accessories:
        parts.append(_sentence("，".join(accessories)))

    for field_id in ("scene", "prop", "weather"):
        if fields.get(field_id):
            parts.append(_sentence(fields[field_id]))

    composition = []
    if fields.get("comp"):
        composition.append(fields["comp"])
    if fields.get("compPos"):
        composition.append(f"人物{fields['compPos']}")
    if composition:
        parts.append(_sentence("，".join(composition)))
    if fields.get("styleTag"):
        parts.append(_sentence(f"整体呈现{fields['styleTag']}风格"))

    if reference:
        parts.append(_sentence(f"参考画面要点：{reference}"))
    return _join_prompt_parts(parts)


def _normalize_reference(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        pieces = []
        for key in (
            "image_overview",
            "subjects",
            "composition",
            "materials_and_colors",
            "lighting_and_atmosphere",
            "style_and_creative_concept",
        ):
            value = parsed.get(key)
            if isinstance(value, list):
                pieces.extend(_clean_text(item) for item in value)
            elif isinstance(value, dict):
                pieces.extend(_clean_text(item) for item in value.values())
            else:
                pieces.append(_clean_text(value))
        text = "，".join(item for item in pieces if item)
    text = re.sub(r"```(?:json|text|markdown)?|```", "", text, flags=re.I)
    return _clean_text(text)[:3000]


class ZFPortraitPromptGenerator:
    """Front-end driven portrait prompt generator with optional reference material."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state_json": (
                    "STRING",
                    {
                        "default": DEFAULT_PORTRAIT_STATE,
                        "multiline": True,
                        "tooltip": "由人像生成器界面维护的选择状态。",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0x7FFFFFFF,
                        "tooltip": "点击随机按钮时自动更新。",
                    },
                ),
                "adult_content": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "高级内容选项，默认关闭。",
                    },
                ),
                "quantity": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 100,
                        "step": 1,
                        "display": "number",
                        "tooltip": "连续出图数量。第 1 条沿用当前选择，后续条目随机生成并保留所有锁定项。",
                    },
                ),
            },
            "optional": {
                "reference_analysis": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "可选接入已有的图片反推或结构化视觉分析；随机功能不依赖此输入。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("portrait_prompt", "selection_json", "status")
    OUTPUT_IS_LIST = (True, False, False)
    FUNCTION = "generate"
    CATEGORY = "ZF/提示词创意导演/人像提示词"
    DESCRIPTION = "从可编辑的人像素材目录组装一条或多条人像提示词；多条输出会驱动下游节点连续出图。"
    SEARCH_ALIASES = [
        "ZF portrait prompt generator",
        "portrait batch",
        "人物提示词生成器",
        "人像生成器",
        "人像批量生成",
    ]

    @classmethod
    def IS_CHANGED(cls, state_json, seed=0, adult_content=False, quantity=1, reference_analysis=None):
        state = _parse_state(state_json)
        if state.get("auto_random"):
            return float("nan")
        return f"{state_json}|{int(seed)}|{bool(adult_content)}|{max(1, int(quantity))}|{reference_analysis or ''}"

    def generate(self, state_json, seed=0, adult_content=False, quantity=1, reference_analysis=None):
        base_state = _parse_state(state_json)
        reference = _normalize_reference(reference_analysis)
        adult_requested = bool(adult_content)
        result_count = max(1, min(100, int(quantity)))
        normal_before, _, _ = _field_texts(base_state, False)
        safety_source = " ".join(normal_before + [reference] + list(base_state["overrides"].values()))
        adult_blocked = adult_requested and _minor_marker(safety_source)
        if adult_blocked:
            adult_requested = False

        effective_seed = int(seed)
        if base_state.get("auto_random"):
            effective_seed = secrets.randbelow(0x80000000)

        prompts = []
        first_state = None
        first_active_count = 0
        for index in range(result_count):
            state = copy.deepcopy(base_state)
            variant_seed = (effective_seed + index * 0x1F123BB5) & 0x7FFFFFFF
            rng = random.Random(variant_seed)
            if base_state.get("auto_random") or index > 0:
                _randomize_state(state, rng, adult_requested)
            elif adult_requested and not _has_active_normal_selection(state):
                # The source HTML fills its empty normal fields when NSFW is
                # switched on. Do the same for an empty/legacy node state so merely
                # enabling the extension cannot yield a fragment made only from
                # one adult detail.
                _randomize_state(state, rng, True)
            else:
                _resolve_clothing_conflicts(state, adult_requested)
            _resolve_movement_conflicts(state)
            if adult_requested:
                _ensure_adult_selection(state, random.Random(variant_seed ^ 0x5F3759DF))
                _resolve_clothing_conflicts(state, adult_requested)
                _resolve_movement_conflicts(state)

            _, _, by_section = _field_texts(state, adult_requested)
            prompt_body = _build_portrait_prompt(state, adult_requested, reference)
            prompts.append(prompt_body or "单人肖像创作，人物身份、外观、服装、动作与环境保持统一自然。")
            if first_state is None:
                first_state = state
                first_active_count = sum(len(values) for values in by_section.values())

        state = first_state or base_state

        normalized_state = {
            "version": 6,
            "seed": effective_seed,
            "adult_content": adult_requested,
            "auto_random": bool(state.get("auto_random")),
            "selected": state["selected"],
            "enabled": state["enabled"],
            "overrides": state["overrides"],
            "pinned": state["pinned"],
            "locked": state["locked"],
            "section_locked": state["section_locked"],
            "section_lock_items": state["section_lock_items"],
            "section_enabled": state["section_enabled"],
            "option_overrides": state["option_overrides"],
        }
        if adult_blocked:
            status = f"已生成 {result_count} 条提示词；首条 {first_active_count} 项；检测到未成年描述，成人扩展未参与输出"
        else:
            status = f"已生成 {result_count} 条提示词；首条 {first_active_count} 项；成人内容{'开启' if adult_requested else '关闭'}"
        return (
            prompts,
            json.dumps(normalized_state, ensure_ascii=False, separators=(",", ":")),
            status,
        )
