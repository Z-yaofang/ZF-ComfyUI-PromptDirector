"""Disposable full-source IMAGE/AUDIO decoder with CPU and memory budgets."""
import json
from pathlib import Path
import sys
import time

import numpy as np

MAX_BYTES = 768 * 1024 * 1024
MAX_SECONDS = 30
MAX_PACKETS = 500000
MAX_FRAMES = 250000
MAX_PIXELS = 50_000_000
FORMATS = {"mp4":"mov", "mov":"mov", "m4a":"mov", "mkv":"matroska", "webm":"matroska", "avi":"avi", "wav":"wav", "mp3":"mp3", "flac":"flac", "ogg":"ogg"}


def decode(kind, path, output):
    started=time.monotonic()
    def check(size=0):
        if time.monotonic()-started>MAX_SECONDS:
            raise ValueError("原素材解码超过30秒安全预算；未输出截断结果")
        if size>MAX_BYTES:
            raise ValueError("原素材解码超过768 MiB内存预算；未输出截断结果")
    if kind=="picture":
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS=MAX_PIXELS
        with Image.open(path) as picture:
            width,height=picture.size
            if min(width,height)<=0 or width*height>MAX_PIXELS or max(width,height)>16384 or getattr(picture,"n_frames",1)!=1:
                raise ValueError("原图片尺寸或帧数超出安全解码预算")
            check(width*height*32)
            displayed=ImageOps.exif_transpose(picture).convert("RGB")
            values=np.asarray(displayed,dtype=np.float32)[None,...]
            values/=255.0
        info={"shape":list(values.shape),"output_width":values.shape[2],"output_height":values.shape[1],"display_orientation":"EXIF transpose", "color_conversion":"RGB float32 0–1；IMAGE不含alpha，受控原文件保留透明通道与元数据"}
    elif kind=="audio":
        import av
        chunks=[];samples=packets=frames=0
        with path.open("rb") as source, av.open(source,format=FORMATS[path.suffix[1:]],options={"protocol_whitelist":"file,pipe","threads":"1"}) as container:
            if container.streams.video or not container.streams.audio:
                raise ValueError("绑定素材的实际种类不是独立音频文件")
            stream=container.streams.audio[0]
            rate,channels=stream.codec_context.sample_rate,stream.codec_context.channels
            if not 0<rate<=768000 or not 0<channels<=64:
                raise ValueError("原音频采样率或声道超出安全解码预算")
            stream.codec_context.thread_count=1
            if stream.duration is not None:
                check(int(float(stream.duration*stream.time_base)*rate+1)*channels*8)
            resampler=av.AudioResampler(format="fltp",layout=stream.codec_context.layout,rate=rate)
            def consume(chunk):
                nonlocal samples
                samples+=chunk.samples
                check(samples*channels*8+chunk.samples*channels*8)
                chunks.append(chunk.to_ndarray())
            for packet in container.demux(stream):
                packets+=1;check()
                if packets>MAX_PACKETS:
                    raise ValueError("原音频扫描包数超出安全预算；未输出截断结果")
                for frame in packet.decode():
                    frames+=1;check()
                    if frames>MAX_FRAMES:
                        raise ValueError("原音频扫描帧数超出安全预算；未输出截断结果")
                    if frame.sample_rate!=rate or frame.layout.name!=stream.codec_context.layout.name:
                        raise ValueError("原音频采样率或声道布局在文件内变化，无法保持统一AUDIO格式")
                    for chunk in resampler.resample(frame):
                        consume(chunk)
            for chunk in resampler.resample(None):
                consume(chunk)
            if not samples:
                raise ValueError("原音频没有可解码样本")
            values=np.concatenate(chunks,axis=1)[None,...]
        info={"shape":list(values.shape),"sample_rate":rate,"channels":channels,"sample_count":samples,"output_duration_seconds":samples/rate,"audio_stream_index":stream.index,"decoded_packets":packets,"decoded_frames":frames,"format_conversion":"float32 planar；保留源采样率和声道，不补零、不混音"}
    else:
        raise ValueError("原素材解码种类无效")
    check();np.save(output,values,allow_pickle=False);check()
    return info


if __name__=="__main__":
    try:
        result={"ok":True,"result":decode(sys.argv[1],Path(sys.argv[2]),sys.argv[3])}
    except Exception as error:
        result={"ok":False,"message":str(error) if isinstance(error,ValueError) else "原素材标准解码失败"}
    print(json.dumps(result,ensure_ascii=True,allow_nan=False))
