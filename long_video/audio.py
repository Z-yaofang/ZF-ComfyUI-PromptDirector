"""Use ComfyUI's sinc resampler, with a lazy fallback for older hosts."""


def resample_audio(waveform, source_rate, target_rate):
    if source_rate == target_rate:
        return waveform
    try:
        from comfy.audio import resample
    except ImportError as error:
        if error.name not in {"comfy", "comfy.audio"}:
            raise
        try:
            from torchaudio.functional import resample
        except (ImportError, OSError, RuntimeError) as error:
            raise RuntimeError(
                "音频重采样需要 ComfyUI 的 comfy.audio.resample；请更新 ComfyUI，"
                "或为旧版环境安装与当前 PyTorch/CUDA 匹配的 torchaudio。"
            ) from error
    return resample(waveform, source_rate, target_rate)
