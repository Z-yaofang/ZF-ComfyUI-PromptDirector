import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "local_multimodal.py"
SPEC = importlib.util.spec_from_file_location("zf_prompt_director_local_multimodal", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_node_keeps_comfy_scalar_mapping_contract():
    node = MODULE.ZFPromptDirectorLocalLLM
    assert not hasattr(node, "INPUT_IS_LIST")
    # This node is normally upstream of the final-list cache.  It must not be
    # an OUTPUT_NODE, otherwise ComfyUI runs it on every queue even when the
    # cache is in “使用缓存” mode and does not request its lazy input.
    assert not getattr(node, "OUTPUT_NODE", False)
    assert node.RETURN_TYPES == ("STRING", "STRING")
    inputs = node.INPUT_TYPES()
    assert list(inputs["required"])[:3] == ["llama_model", "role", "prompt"]
    assert list(inputs["optional"])[2:10] == [
        "image1",
        "image2",
        "image3",
        "image4",
        "image5",
        "image6",
        "image7",
        "image8",
    ]


def test_generation_parameters_override_connected_parameter_node():
    result = MODULE._local_generation_parameters(
        {"temperature": 1.5, "max_tokens": 12, "top_k": 33},
        temperature=0.2,
        max_tokens=4096,
        top_p=0.9,
        frequency_penalty=0.1,
        presence_penalty=0.2,
    )
    assert result["temperature"] == 0.2
    assert result["max_tokens"] == 4096
    assert result["top_k"] == 33
    assert result["frequency_penalty"] == 0.1
    assert result["present_penalty"] == 0.2


def test_scalar_prompt_is_forwarded_whole_to_backend(monkeypatch):
    calls = []

    class Backend:
        def process(self, **kwargs):
            calls.append(kwargs)
            return "<think>hidden</think>完整结果", ["完整结果"], 7

    monkeypatch.setattr(MODULE, "_find_llama_cpp_instruct_class", lambda: Backend)
    node = MODULE.ZFPromptDirectorLocalLLM()
    result = node.chat(
        llama_model=object(),
        role="系统规则",
        prompt="这是完整任务，不得只取首项",
        temperature=0.15,
        max_tokens=4096,
        top_p=0.9,
        presence_penalty=0.0,
        frequency_penalty=0.0,
        max_image_size=512,
        seed=42,
        force_offload=False,
    )

    assert calls[0]["custom_prompt"] == "这是完整任务，不得只取首项"
    assert calls[0]["system_prompt"] == "系统规则"
    assert result["result"][0] == "完整结果"
