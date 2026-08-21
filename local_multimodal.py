"""Local llama.cpp multimodal writer used by PromptDirector workflows.

The node intentionally does not declare ``INPUT_IS_LIST``.  ComfyUI therefore
maps a ``writer_tasks`` STRING list to repeated scalar calls, producing one
model response per director task instead of silently consuming only item zero.
"""

import json
import logging
import re
import sys
from typing import Any, Dict, Iterable, List, Optional


log = logging.getLogger(__name__)


def _clean_local_text(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("<|begin_of_box|>", "").replace("<|end_of_box|>", "")
    return cleaned.strip()


def _find_llama_cpp_instruct_class():
    """Find the loaded llama.cpp writer without importing its hyphenated package."""
    preferred = (
        "custom_nodes.ComfyUI-llama-cpp_vlm.nodes",
        "custom_nodes.ComfyUI-llama-cpp_vllm.nodes",
        "ComfyUI-llama-cpp_vlm.nodes",
        "ComfyUI-llama-cpp_vllm.nodes",
    )
    for module_name in preferred:
        module = sys.modules.get(module_name)
        module_dict = getattr(module, "__dict__", None) if module is not None else None
        if not isinstance(module_dict, dict):
            continue
        candidate = module_dict.get("llama_cpp_instruct_adv")
        if isinstance(candidate, type) and callable(getattr(candidate, "process", None)):
            return candidate

    for module in list(sys.modules.values()):
        module_dict = getattr(module, "__dict__", None)
        if not isinstance(module_dict, dict):
            continue
        candidate = module_dict.get("llama_cpp_instruct_adv")
        if isinstance(candidate, type) and callable(getattr(candidate, "process", None)):
            return candidate
    return None


def _local_image_frames(images: Iterable[Any], max_image_size: int) -> List[Any]:
    """Flatten ComfyUI IMAGE batches and cap each frame without distortion."""
    images = [image for image in images if image is not None]
    if not images:
        return []

    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as error:
        raise RuntimeError("本地多模态写作节点需要 ComfyUI 自带的 PyTorch 环境。") from error

    frames: List[Any] = []
    max_image_size = max(128, int(max_image_size))
    for image in images:
        if not torch.is_tensor(image):
            raise TypeError("本地多模态写作节点的图片输入必须是 ComfyUI IMAGE 张量。")

        batch = image
        if batch.ndim == 3:
            batch = batch.unsqueeze(0)
        if batch.ndim != 4:
            raise ValueError(f"无法识别 IMAGE 张量形状：{tuple(batch.shape)}")

        for frame in batch:
            if frame.shape[-1] == 1:
                frame = frame.repeat(1, 1, 3)
            elif frame.shape[-1] > 3:
                frame = frame[..., :3]

            height, width = int(frame.shape[0]), int(frame.shape[1])
            longest_edge = max(height, width)
            if longest_edge > max_image_size:
                scale = max_image_size / longest_edge
                target_height = max(1, round(height * scale))
                target_width = max(1, round(width * scale))
                frame = functional.interpolate(
                    frame.movedim(-1, 0).unsqueeze(0),
                    size=(target_height, target_width),
                    mode="bicubic",
                    align_corners=False,
                    antialias=True,
                ).squeeze(0).movedim(0, -1)
            frames.append(frame.detach().cpu().float().clamp(0, 1))
    return frames


def _local_media_note(images: Iterable[Any]) -> str:
    labels: List[str] = []
    for picture_index, image in enumerate(images, start=1):
        if image is None:
            continue
        batch_size = 1
        shape = getattr(image, "shape", None)
        if shape is not None and len(shape) == 4:
            batch_size = int(shape[0])
        if batch_size == 1:
            labels.append(f"image {len(labels) + 1} = <Picture {picture_index}>")
        else:
            for batch_index in range(1, batch_size + 1):
                labels.append(
                    f"image {len(labels) + 1} = "
                    f"<Picture {picture_index}, image {batch_index}/{batch_size}>"
                )
    if not labels:
        return ""
    return "[Local media order: " + "; ".join(labels) + "]"


def _local_video_frames(video_frames: Any, max_image_size: int, max_frames: int) -> List[Any]:
    """Uniformly sample an IMAGE batch used as a visual-only video proxy."""
    if video_frames is None:
        return []
    max_frames = max(1, int(max_frames))
    sampled_input = video_frames
    try:
        import torch

        if torch.is_tensor(video_frames) and video_frames.ndim == 4:
            frame_count = int(video_frames.shape[0])
            if frame_count > max_frames:
                indices = torch.linspace(
                    0,
                    frame_count - 1,
                    steps=max_frames,
                    device=video_frames.device,
                ).round().long()
                sampled_input = video_frames.index_select(0, indices)
    except ImportError:
        pass

    frames = _local_image_frames([sampled_input], max_image_size)
    if len(frames) <= max_frames:
        return frames
    if max_frames == 1:
        return [frames[0]]
    indices = [round(i * (len(frames) - 1) / (max_frames - 1)) for i in range(max_frames)]
    return [frames[index] for index in indices]


def _local_generation_parameters(
    parameters: Optional[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    top_p: float,
    frequency_penalty: float,
    presence_penalty: float,
) -> Dict[str, Any]:
    merged = {
        "top_k": 20,
        "min_p": 0.05,
        "typical_p": 1.0,
        "repeat_penalty": 1.05,
        "mirostat_mode": 0,
        "mirostat_eta": 0.1,
        "mirostat_tau": 5.0,
        "state_uid": -1,
    }
    if parameters:
        merged.update(dict(parameters))
    merged.update(
        {
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "top_p": float(top_p),
            "frequency_penalty": max(0.0, float(frequency_penalty)),
            # This is the spelling currently exposed by ComfyUI-llama-cpp_vlm.
            "present_penalty": max(0.0, float(presence_penalty)),
        }
    )
    return merged


class ZFPromptDirectorLocalLLM:
    DESCRIPTION = (
        "导演台专用的本地 llama.cpp 多模态写作节点。支持文本、多图和视频抽帧，"
        "不会发送网络请求；导演台任务列表会由 ComfyUI 自动逐条执行。"
    )
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "raw_response")
    FUNCTION = "chat"
    CATEGORY = "ZF/提示词创意导演/本地模型"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "llama_model": ("LLAMACPPMODEL",),
                "role": (
                    "STRING",
                    {"multiline": True, "default": "You are a helpful assistant."},
                ),
                "prompt": ("STRING", {"multiline": True, "default": "Hello"}),
                "temperature": (
                    "FLOAT",
                    {"default": 0.15, "min": 0.0, "max": 2.0, "step": 0.01},
                ),
                "max_tokens": (
                    "INT",
                    {"default": 4096, "min": 1, "max": 32768, "step": 1},
                ),
                "top_p": (
                    "FLOAT",
                    {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "presence_penalty": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 2.0, "step": 0.01},
                ),
                "frequency_penalty": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "max_image_size": (
                    "INT",
                    {
                        "default": 512,
                        "min": 128,
                        "max": 4096,
                        "step": 64,
                        "tooltip": "每张图最长边上限；保持原始宽高比，不裁剪、不拉伸。",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 42,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "step": 1,
                        "control_after_generate": True,
                    },
                ),
                "force_offload": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "完成后卸载本地 VLM；随后运行大型成图/视频模型时建议开启。",
                    },
                ),
            },
            "optional": {
                "skip_error": ("BOOLEAN", {"default": False}),
                "parameters": (
                    "LLAMACPPARAMS",
                    {"tooltip": "可选高级参数；节点面板中的同名采样参数优先。"},
                ),
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",),
                "image6": ("IMAGE",),
                "image7": ("IMAGE",),
                "image8": ("IMAGE",),
                "video_frames": (
                    "IMAGE",
                    {"tooltip": "视频抽帧后的 IMAGE 批次；只分析画面，不读取音轨。"},
                ),
                "video_max_frames": (
                    "INT",
                    {
                        "default": 8,
                        "min": 1,
                        "max": 32,
                        "step": 1,
                        "tooltip": "按时间均匀抽样后送入本地模型的最大帧数。",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    def _error_result(self, error: Exception):
        message = f"[ERROR] ZFPromptDirectorLocalLLM：{error}"
        raw = json.dumps(
            {"backend": "ComfyUI-llama-cpp_vlm", "error": str(error)},
            ensure_ascii=False,
            indent=2,
        )
        return {"ui": {"text": [message, raw]}, "result": (message, raw)}

    def chat(
        self,
        llama_model,
        role,
        prompt,
        temperature,
        max_tokens,
        top_p,
        presence_penalty,
        frequency_penalty,
        max_image_size,
        seed,
        force_offload,
        skip_error=False,
        parameters=None,
        image1=None,
        image2=None,
        image3=None,
        image4=None,
        image5=None,
        image6=None,
        image7=None,
        image8=None,
        video_frames=None,
        video_max_frames=8,
        unique_id=None,
    ):
        try:
            connected_images = [
                image
                for image in (image1, image2, image3, image4, image5, image6, image7, image8)
                if image is not None
            ]
            frames = _local_image_frames(connected_images, max_image_size)
            video_proxy_frames = _local_video_frames(
                video_frames,
                max_image_size,
                video_max_frames,
            )
            media_note = _local_media_note(connected_images)
            if video_proxy_frames:
                media_note = (f"{media_note}\n" if media_note else "") + (
                    f"[<Video 1> local visual proxy: {len(video_proxy_frames)} uniformly sampled "
                    "frames; visual-only; synchronized audio was not analyzed.]"
                )
            effective_prompt = str(prompt or "")
            if media_note:
                effective_prompt = f"{effective_prompt}\n\n{media_note}"

            local_parameters = _local_generation_parameters(
                parameters,
                temperature,
                max_tokens,
                top_p,
                frequency_penalty,
                presence_penalty,
            )
            backend_class = _find_llama_cpp_instruct_class()
            if backend_class is None:
                raise RuntimeError(
                    "未找到 llama_cpp_instruct_adv。请安装并启用 "
                    "lihaoyun6/ComfyUI-llama-cpp_vlm，然后重启 ComfyUI。"
                )
            backend = backend_class()
            output, _output_list, state_uid = backend.process(
                llama_model=llama_model,
                preset_prompt="Empty - Nothing",
                custom_prompt=effective_prompt,
                system_prompt=str(role or ""),
                inference_mode="images",
                max_frames=max(2, len(frames) + len(video_proxy_frames)),
                max_size=int(max_image_size),
                seed=int(seed),
                force_offload=bool(force_offload),
                save_states=False,
                unique_id=str(unique_id or "zf-prompt-director-local-llm"),
                parameters=local_parameters,
                images=(frames + video_proxy_frames) or None,
                queue_handler=None,
            )
            text = _clean_local_text(str(output))
            if not text:
                raise RuntimeError("本地模型返回了空文本。")
            raw = json.dumps(
                {
                    "backend": "ComfyUI-llama-cpp_vlm",
                    "image_count": len(frames) + len(video_proxy_frames),
                    "video_proxy_frame_count": len(video_proxy_frames),
                    "audio_analyzed": False,
                    "state_uid": state_uid,
                    "response": text,
                },
                ensure_ascii=False,
                indent=2,
            )
            return {"ui": {"text": [text, raw]}, "result": (text, raw)}
        except Exception as error:
            if skip_error:
                log.error("ZFPromptDirectorLocalLLM failed: %s", str(error))
                return self._error_result(error)
            raise
