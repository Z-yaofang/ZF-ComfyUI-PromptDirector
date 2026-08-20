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


class ZFPromptDirectorMultiTextSelector:
    """A front-end driven single-choice text router with deterministic fallback."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "text_{}".format(index): (
                "STRING",
                {
                    "forceInput": True,
                    "lazy": True,
                    "tooltip": "文本路线 {}；只有选中时才会执行。".format(index),
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
                        "tooltip": "显示 1 到 32 路文本输入。",
                    },
                ),
                "selected": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": MAX_TEXT_SELECTOR_INPUTS,
                        "step": 1,
                        "tooltip": "当前路线；0 表示明确输出空文本。",
                    },
                ),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("text", "selected_index")
    FUNCTION = "select"
    CATEGORY = "ZF/提示词创意导演/流程工具"
    DESCRIPTION = (
        "显示可配置数量的文本输入，并且只执行按钮明确选中的一路；"
        "不自动回退，也不根据文本内容猜测路线。"
    )
    SEARCH_ALIASES = [
        "ZF multi text selector",
        "ZF multi text switch",
        "text router",
        "multi route text",
        "文本动态多路点选",
        "多路文本切换",
    ]

    @staticmethod
    def _requested_route(input_count, selected):
        count = max(1, min(MAX_TEXT_SELECTOR_INPUTS, int(input_count)))
        requested = int(selected)
        if requested == 0:
            return 0
        return max(1, min(count, requested))

    def check_lazy_status(self, input_count, selected, **kwargs):
        requested = self._requested_route(input_count, selected)
        if requested == 0:
            return []
        key = "text_{}".format(requested)
        return [key] if key in kwargs and kwargs[key] is None else []

    def select(self, input_count, selected, **kwargs):
        requested = self._requested_route(input_count, selected)
        if requested == 0:
            return ("", 0)
        requested_value = str(kwargs.get("text_{}".format(requested), "") or "")
        return (requested_value, requested)
