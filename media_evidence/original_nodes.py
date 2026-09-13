"""Independent standard outputs bound only to a registered original source."""
import json
from pathlib import Path
import subprocess
import tempfile

from .outlet import OutletError
from .storage import FORMATS, MediaError
from .original_worker import MAX_BYTES
from .original_sources import selected_source


def export_original(store, source_handle, kind, *, asset_id=None):
    try:
        facts=store.record(source_handle)
        source=store.resolve(source_handle)
        if asset_id is not None and facts['asset_id']!=asset_id:
            raise OutletError('绑定稳定资产ID与原文件登记不匹配，请检查来源线')
        if facts["kind"]!=kind:
            raise OutletError("绑定素材种类不匹配，请连接对应原素材出口")
        manifest={"version":1,"binding":"catalog_original" if asset_id is not None else "registered_original","kind":kind,"source_handle":source_handle,"asset_id":facts["asset_id"],"name":facts["name"],"source_path":str(source),"source_bytes_unchanged":True}
        if kind=="video":
            import av
            from comfy_api.latest import InputImpl
            # Header validation only. VideoFromFile leaves frames/audio to downstream nodes.
            with source.open("rb") as handle, av.open(handle,format=FORMATS[source.suffix[1:]],options={"protocol_whitelist":"file,pipe","threads":"1"}) as container:
                if not container.streams.video:
                    raise OutletError("绑定原文件没有实际视频流")
                stream=container.streams.video[0]
                manifest.update(source_fps=float(stream.average_rate or stream.guessed_rate or 0),has_audio=bool(container.streams.audio),full_source=True,video_decoded_frames=0)
            media=InputImpl.VideoFromFile(str(source))
            if media.get_stream_source()!=str(source):
                raise OutletError("本机原生VIDEO未保持受控原文件路径")
        else:
            import numpy as np
            import torch
            if not store.jobs.acquire(blocking=False):
                raise OutletError("素材CPU解码忙，请稍后重试")
            try:
                with tempfile.TemporaryDirectory(prefix="zv-original-") as temporary:
                    output=Path(temporary)/"media.npy"
                    args=[store.python,str(Path(__file__).with_name("original_worker.py")),kind,str(source),str(output)]
                    try:
                        result=subprocess.run(args,capture_output=True,timeout=30,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                    except subprocess.TimeoutExpired:
                        raise OutletError("原素材解码超过30秒安全预算；未输出截断结果") from None
                    data=json.loads(result.stdout.decode("utf-8"))
                    if result.returncode or not data.get("ok"):
                        raise OutletError(data.get("message","原素材标准解码失败"))
                    if output.stat().st_size>MAX_BYTES:
                        raise OutletError("原素材输出超过768 MiB内存安全预算")
                    values=np.load(output,allow_pickle=False)
                    media=torch.from_numpy(values)
                    manifest.update(data["result"],full_source=True)
                    if kind=="audio":
                        media={"waveform":media,"sample_rate":data["result"]["sample_rate"]}
            finally:
                store.jobs.release()
        if store.record(source_handle)!=facts or store.resolve(source_handle)!=source:
            raise OutletError("原素材在执行时改变，请重新导入")
    except MediaError:
        raise OutletError("原素材来源未登记、丢失、改变或路径无效，请重新导入") from None
    except (OSError,KeyError,ValueError) as error:
        if isinstance(error,OutletError):
            raise
        raise OutletError("原素材实际文件或登记数据无效，无法输出") from None
    report={"picture":"原图片自然显示尺寸，EXIF显示方向，RGB IMAGE；alpha与元数据保留在原文件", "video":"原生VIDEO保留原文件及原音轨；未解码全片。接GetVideoComponents或source_path接VHS_LoadVideoPath", "audio":"全原音频标准解码，保持源采样率、声道与全部样本"}[kind]
    return media,str(source),json.dumps(manifest,ensure_ascii=False,allow_nan=False,separators=(",",":")),report


class _OriginalOutlet:
    CATEGORY="ZV/视频创作/素材取证"
    FUNCTION="export_media"
    RETURN_NAMES=("media","source_path","manifest_json","report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"source_handle":("STRING",{"default":""})},"optional":{"original_sources":("ZV_ORIGINAL_SOURCES",{"forceInput":True}),"asset_id":("STRING",{"default":""})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def export_media(self,source_handle,original_sources=None,asset_id=""):
        from .runtime import get_store
        if asset_id!="" or original_sources is not None:
            handle=selected_source(original_sources,asset_id,self.KIND)
            return export_original(get_store(),handle,self.KIND,asset_id=asset_id)
        return export_original(get_store(),source_handle,self.KIND)


class ZVOriginalPictureOutlet(_OriginalOutlet):
    KIND="picture"
    RETURN_TYPES=("IMAGE","STRING","STRING","STRING")
    RETURN_NAMES=("image","source_path","manifest_json","report")


class ZVOriginalVideoOutlet(_OriginalOutlet):
    KIND="video"
    RETURN_TYPES=("VIDEO","STRING","STRING","STRING")
    RETURN_NAMES=("video","source_path","manifest_json","report")


class ZVOriginalAudioOutlet(_OriginalOutlet):
    KIND="audio"
    RETURN_TYPES=("AUDIO","STRING","STRING","STRING")
    RETURN_NAMES=("audio","source_path","manifest_json","report")
