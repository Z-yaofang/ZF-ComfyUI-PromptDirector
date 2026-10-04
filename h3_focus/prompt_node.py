from .interview import InterviewError, dumps, parse_interview
from .node import ZVH3InterviewFormV2, _prompt_uses_reference_hub
from .reference_detection import validate_prompt_without_hub


class ZVH3PromptInput(ZVH3InterviewFormV2):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = super().INPUT_TYPES()
        inputs["required"] = {
            "media_project": inputs["required"]["media_project"],
            "trigger_words": ("STRING", {"multiline": True, "default": ""}),
            "prompt_text": ("STRING", {"multiline": True, "default": ""}),
            "interview_json": inputs["required"]["interview_json"],
        }
        return inputs

    RETURN_NAMES = ("prompt", *ZVH3InterviewFormV2.RETURN_NAMES[1:])

    def build(self, media_project, trigger_words, prompt_text, interview_json, prompt=None, unique_id=None):
        text = "\n".join(part for value in (trigger_words, prompt_text) if (part := value.strip()))
        try:
            state = parse_interview(interview_json)
        except InterviewError:
            state = None
        if state is not None:
            state["intent"] = text
            reference_texts = state.get("reference_texts")
            if isinstance(reference_texts, dict):
                reference_texts.pop("intent", None)
            interview_json = dumps(state)
        result, reference_plan, _project = self._compile(media_project, interview_json, prompt, unique_id)
        if prompt is not None and not _prompt_uses_reference_hub(prompt, unique_id):
            if result.get("call_references"):
                raise RuntimeError("已选择 H3 参考素材，请把本节点 reference_plan 接到固定 H3 素材对齐出口，并连接模型参考接口。")
            wiring = validate_prompt_without_hub(prompt, unique_id)
            if wiring["errors"]:
                raise RuntimeError("；".join(row["message"] for row in wiring["errors"]))
        result["state"]["intent"] = text
        result["state"]["reference_texts"].pop("intent", None)
        return (
            text, result["material_context_json"], result["duration_seconds"],
            dumps(result["state"], indent=2), result["human_report"], result["validation"]["ready"],
            reference_plan,
        )
