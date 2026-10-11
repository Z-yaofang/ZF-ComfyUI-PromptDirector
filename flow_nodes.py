import operator
import re


class _ZFPromptDirectorAnyType(str):
    """ComfyUI wildcard type without depending on another custom-node package."""

    def __ne__(self, other):
        return False


ZF_PROMPT_DIRECTOR_ANY_TYPE = _ZFPromptDirectorAnyType("*")
MAX_TEXT_SELECTOR_INPUTS = 32


class ZFPromptDirectorAnyFilter:
    """Apply one explicit condition and output action to arbitrary values."""

    CONDITION_EMPTY = "输入为空"
    CONDITION_NOT_EMPTY = "输入不为空"
    CONDITION_ALWAYS = "始终"
    CONDITION_CONTAINS = "文本包含任一项"
    CONDITION_NOT_CONTAINS = "文本不包含任一项"
    CONDITION_EQUALS = "文本完全等于任一项"
    CONDITION_NOT_EQUALS = "文本不等于任一项"
    CONDITION_STARTS_WITH = "文本以任一项开头"
    CONDITION_ENDS_WITH = "文本以任一项结尾"
    CONDITIONS = (
        CONDITION_EMPTY,
        CONDITION_NOT_EMPTY,
        CONDITION_ALWAYS,
        CONDITION_CONTAINS,
        CONDITION_NOT_CONTAINS,
        CONDITION_EQUALS,
        CONDITION_NOT_EQUALS,
        CONDITION_STARTS_WITH,
        CONDITION_ENDS_WITH,
    )

    OUTPUT_NONE = "无输出（None，跳过此路）"
    OUTPUT_EMPTY_TEXT = "空文本（截断后路）"
    OUTPUT_ORIGINAL = "原样输出"
    OUTPUT_REMOVE = "删除指定内容后输出"
    OUTPUT_ACTIONS = (
        OUTPUT_NONE,
        OUTPUT_EMPTY_TEXT,
        OUTPUT_ORIGINAL,
        OUTPUT_REMOVE,
    )

    TEXT_CONDITIONS = frozenset(
        (
            CONDITION_CONTAINS,
            CONDITION_NOT_CONTAINS,
            CONDITION_EQUALS,
            CONDITION_NOT_EQUALS,
            CONDITION_STARTS_WITH,
            CONDITION_ENDS_WITH,
        )
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "condition": (
                    list(cls.CONDITIONS),
                    {
                        "default": cls.CONDITION_EMPTY,
                        "tooltip": "选择在什么情况下执行输出动作。",
                    },
                ),
                "output_action": (
                    list(cls.OUTPUT_ACTIONS),
                    {
                        "default": cls.OUTPUT_NONE,
                        "tooltip": "选择判断命中后产生的结果。",
                    },
                ),
                "filter_content": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "每行一个普通文字、短语或符号，不使用正则表达式。",
                    },
                ),
                "case_sensitive": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "文字匹配是否区分英文大小写。",
                    },
                ),
            },
            "optional": {
                "value": (
                    ZF_PROMPT_DIRECTOR_ANY_TYPE,
                    {
                        "forceInput": True,
                        "tooltip": "可接任意 ComfyUI 数据，包括空列表。",
                    },
                ),
            },
        }

    RETURN_TYPES = (ZF_PROMPT_DIRECTOR_ANY_TYPE,)
    RETURN_NAMES = ("value",)
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "filter_value"
    CATEGORY = "ZF/提示词创意导演/流程工具"
    DESCRIPTION = (
        "根据一个判断逻辑处理任意输入。None 会让任意切换跳过该路，"
        "空文本会让任意切换在该路停止。"
    )
    SEARCH_ALIASES = [
        "ZF any filter",
        "safe any switch input",
        "empty list guard",
        "任意过滤器",
        "任意过滤",
        "文本过滤",
        "过滤嘴",
        "空列表保护",
    ]

    @staticmethod
    def _first(value, default):
        if isinstance(value, (list, tuple)):
            return value[0] if value else default
        return default if value is None else value

    @staticmethod
    def _is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (bytes, bytearray, list, tuple, dict, set, frozenset)):
            return len(value) == 0

        numel = getattr(value, "numel", None)
        if callable(numel):
            try:
                return int(numel()) == 0
            except (TypeError, ValueError, RuntimeError):
                pass

        size = getattr(value, "size", None)
        if isinstance(size, int):
            return size == 0
        return False

    @staticmethod
    def _rules(text, case_sensitive):
        rules = tuple(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
        if case_sensitive:
            return rules, rules
        return rules, tuple(rule.casefold() for rule in rules)

    @classmethod
    def _matches(cls, value, condition, normalized_rules, case_sensitive):
        if condition == cls.CONDITION_ALWAYS:
            return True
        if condition == cls.CONDITION_EMPTY:
            return cls._is_empty(value)
        if condition == cls.CONDITION_NOT_EMPTY:
            return not cls._is_empty(value)
        if condition not in cls.TEXT_CONDITIONS or not isinstance(value, str) or not normalized_rules:
            return False

        text = value.strip()
        if not case_sensitive:
            text = text.casefold()
        if condition == cls.CONDITION_CONTAINS:
            return any(rule in text for rule in normalized_rules)
        if condition == cls.CONDITION_NOT_CONTAINS:
            return all(rule not in text for rule in normalized_rules)
        if condition == cls.CONDITION_EQUALS:
            return text in normalized_rules
        if condition == cls.CONDITION_NOT_EQUALS:
            return text not in normalized_rules
        if condition == cls.CONDITION_STARTS_WITH:
            return text.startswith(normalized_rules)
        if condition == cls.CONDITION_ENDS_WITH:
            return text.endswith(normalized_rules)
        return False

    @staticmethod
    def _removal_pattern(rules, case_sensitive):
        if not rules:
            return None
        flags = 0 if case_sensitive else re.IGNORECASE
        alternatives = "|".join(re.escape(rule) for rule in sorted(rules, key=len, reverse=True))
        return re.compile(alternatives, flags)

    @classmethod
    def _apply_action(cls, value, output_action, removal_pattern):
        if output_action == cls.OUTPUT_NONE:
            return None
        if output_action == cls.OUTPUT_EMPTY_TEXT:
            return ""
        if output_action == cls.OUTPUT_REMOVE and isinstance(value, str) and removal_pattern is not None:
            return removal_pattern.sub("", value)
        return value

    def filter_value(
        self,
        condition=CONDITION_EMPTY,
        output_action=OUTPUT_NONE,
        filter_content="",
        case_sensitive=True,
        value=None,
    ):
        condition = str(self._first(condition, self.CONDITION_EMPTY))
        output_action = str(self._first(output_action, self.OUTPUT_NONE))
        filter_content = str(self._first(filter_content, "") or "")
        case_sensitive = bool(self._first(case_sensitive, True))

        rules, normalized_rules = self._rules(filter_content, case_sensitive)
        removal_pattern = (
            self._removal_pattern(rules, case_sensitive)
            if output_action == self.OUTPUT_REMOVE
            else None
        )
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        if not values:
            values = [None]

        result = [
            self._apply_action(item, output_action, removal_pattern)
            if self._matches(item, condition, normalized_rules, case_sensitive)
            else item
            for item in values
        ]
        return (result or [None],)


class _MultiRouteSelector:
    INPUT_TYPE = "STRING"
    INPUT_PREFIX = "text"
    INPUT_LABEL = "文本"
    EMPTY_VALUE = ""
    EMPTY_LABEL = "空文本"

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "{}_{}".format(cls.INPUT_PREFIX, index): (
                cls.INPUT_TYPE,
                {
                    "forceInput": True,
                    "lazy": True,
                    "tooltip": "{}路线 {}；只有选中时才会执行。".format(cls.INPUT_LABEL, index),
                },
            )
            for index in range(1, MAX_TEXT_SELECTOR_INPUTS + 1)
        }
        return {
            "required": {
                "input_count": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": MAX_TEXT_SELECTOR_INPUTS,
                        "step": 1,
                        "tooltip": "设置 1 到 32 路{}输入；选择超过当前路数时会报错。".format(cls.INPUT_LABEL),
                    },
                ),
                "selected": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": MAX_TEXT_SELECTOR_INPUTS,
                        "step": 1,
                        "tooltip": "当前路线；整数连线覆盖按钮选择，0 表示明确输出{}。".format(cls.EMPTY_LABEL),
                    },
                ),
            },
            "optional": optional,
        }

    FUNCTION = "select"
    CATEGORY = "ZH/辅助工具"

    @staticmethod
    def _requested_route(input_count, selected):
        try:
            count = operator.index(input_count)
        except TypeError as exc:
            raise ValueError("input_count 必须为 1 到 32 的整数。") from exc
        if not 1 <= count <= MAX_TEXT_SELECTOR_INPUTS:
            raise ValueError("input_count 必须为 1 到 32 的整数。")
        try:
            requested = operator.index(selected)
        except TypeError as exc:
            raise ValueError("selected 必须为 0 到 {} 的整数。".format(count)) from exc
        if not 0 <= requested <= count:
            raise ValueError("当前共 {} 路输入，selected={} 越界；请选择 0 到 {}。".format(count, requested, count))
        return requested

    def check_lazy_status(self, input_count, selected, **kwargs):
        requested = self._requested_route(input_count, selected)
        if requested == 0:
            return []
        key = "{}_{}".format(self.INPUT_PREFIX, requested)
        return [key] if key in kwargs and kwargs[key] is None else []

    def select(self, input_count, selected, **kwargs):
        requested = self._requested_route(input_count, selected)
        if requested == 0:
            return (self.EMPTY_VALUE, 0)
        return (kwargs.get("{}_{}".format(self.INPUT_PREFIX, requested), self.EMPTY_VALUE), requested)


class ZFPromptDirectorMultiTextSelector(_MultiRouteSelector):
    """A front-end driven single-choice text router without fallback."""

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("text", "selected_index")
    CATEGORY = "ZF/提示词创意导演/流程工具"
    DESCRIPTION = (
        "显示可配置数量的文本输入，只执行按钮或外部整数选中的一路；"
        "超出当前输入路数时报错，不自动回退，也不根据文本内容猜测路线。"
    )
    SEARCH_ALIASES = [
        "ZF multi text selector",
        "ZF multi text switch",
        "text router",
        "multi route text",
        "文本动态多路点选",
        "多路文本切换",
    ]

    def select(self, input_count, selected, **kwargs):
        value, requested = super().select(input_count, selected, **kwargs)
        return (str(value or ""), requested)


class ZHMultiImageSelector(_MultiRouteSelector):
    INPUT_TYPE = "IMAGE"
    INPUT_PREFIX = "image"
    INPUT_LABEL = "图片"
    EMPTY_VALUE = None
    EMPTY_LABEL = "空值 None"
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("image", "selected_index")
    DESCRIPTION = (
        "只执行选中的一路图片输入并原样输出；整数连线覆盖按钮选择。"
        "0 或未连接的有效路线输出真实空值 None；超出当前输入路数时报错，不自动回退。"
    )
    SEARCH_ALIASES = ["ZH", "Help", "ZH multi image selector", "image switch", "动态多路图片", "多路图片切换"]


class ZHMultiVideoSelector(_MultiRouteSelector):
    INPUT_TYPE = "IMAGE"
    INPUT_PREFIX = "video"
    INPUT_LABEL = "视频帧批次 IMAGE（不含音轨）"
    EMPTY_VALUE = None
    EMPTY_LABEL = "空值 None"
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("video", "selected_index")
    DESCRIPTION = (
        "只执行选中的一路视频帧批次 IMAGE 并原样输出，不含音轨；整数连线覆盖按钮选择。"
        "原生 VIDEO 请先用 GetVideoComponents 分解，独立音轨使用 AUDIO 选择器。"
        "0 或未连接的有效路线输出真实空值 None；超出当前输入路数时报错，不自动回退。"
    )
    SEARCH_ALIASES = ["ZH", "Help", "ZH multi video selector", "video frames switch", "动态多路视频", "多路视频切换"]


class ZHMultiAudioSelector(_MultiRouteSelector):
    INPUT_TYPE = "AUDIO"
    INPUT_PREFIX = "audio"
    INPUT_LABEL = "音频"
    EMPTY_VALUE = None
    EMPTY_LABEL = "空值 None"
    RETURN_TYPES = ("AUDIO", "INT")
    RETURN_NAMES = ("audio", "selected_index")
    DESCRIPTION = (
        "只执行选中的一路 AUDIO 输入并原样输出；整数连线覆盖按钮选择。"
        "0 或未连接的有效路线输出真实空值 None；超出当前输入路数时报错，不自动回退。"
    )
    SEARCH_ALIASES = ["ZH", "Help", "ZH multi audio selector", "audio switch", "动态多路音频", "多路音频切换"]
