"""Neutral CPU integration: real registry, HTTP planning, fixed sockets and decoded signatures."""
import asyncio
import copy
from fractions import Fraction
import importlib
import importlib.util
import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "tests/test_h3_presets.py"))
I, C, S, P = (H[key] for key in ("I", "C", "S", "P"))
V2 = H["H"]
PACKAGE = H["PACKAGE"]
STORE = importlib.import_module(PACKAGE + ".media_evidence.storage")
RUN = importlib.import_module(PACKAGE + ".media_evidence.runtime")
DESK = importlib.import_module(PACKAGE + ".media_evidence.node")
WINDOW = importlib.import_module(PACKAGE + ".media_evidence.outlet_nodes")
OUT = importlib.import_module(PACKAGE + ".h3_focus.outlet_node")
REF = importlib.import_module(PACKAGE + ".h3_focus.references")


def setup(directory):
    import av
    import numpy as np
    from PIL import Image

    store = STORE.MediaStore(directory / "input")
    sources = directory / "fixtures"; sources.mkdir()
    assets = {kind: [] for kind in ("picture", "video", "audio")}
    for kind, count in (("picture", 10), ("video", 4), ("audio", 4)):
        for index in range(1, count + 1):
            path = sources / f"neutral-{kind}-{index}.{'png' if kind == 'picture' else 'mkv' if kind == 'video' else 'wav'}"
            if kind == "picture":
                Image.new("RGB", (32, 24), (index * 20, 30, 60)).save(path)
            elif kind == "audio":
                signal = np.concatenate([np.full(44100, value + index * 100, dtype="<i2") for value in (4096, 8192, -4096)])
                with wave.open(str(path), "wb") as sound:
                    sound.setparams((1, 2, 44100, 0, "NONE", "not compressed")); sound.writeframes(signal.tobytes())
            else:
                with av.open(str(path), "w") as container:
                    video = container.add_stream("ffv1", rate=24); video.width=32; video.height=24; video.pix_fmt="yuv444p"
                    audio = container.add_stream("pcm_s16le", rate=48000); audio.layout="mono"
                    for frame_index in range(72):
                        pixels = np.empty((24, 32, 3), dtype=np.uint8); pixels[:] = (index * 40, frame_index * 3, 100)
                        frame = av.VideoFrame.from_ndarray(pixels, format="rgb24"); frame.pts=frame_index; frame.time_base=Fraction(1,24)
                        for packet in video.encode(frame): container.mux(packet)
                        sound = av.AudioFrame.from_ndarray(np.full((1,2000), index * 2000 + (frame_index // 24) * 500, dtype=np.int16),format="s16",layout="mono")
                        sound.sample_rate=48000; sound.pts=frame_index * 2000; sound.time_base=Fraction(1,48000)
                        for packet in audio.encode(sound): container.mux(packet)
                    for stream in (video,audio):
                        for packet in stream.encode(None): container.mux(packet)
            target, handle, name = store.allocate(path.name); shutil.copyfile(path,target)
            asset = store.finish_import(target,handle,name); assets[kind].append(asset)
            for variant in ({"picture":["thumbnail"],"video":["thumbnail","proxy","audio","peaks"],"audio":["audio","peaks"]}[kind]):
                store.preview(handle,variant)
    def forbidden(*args, **kwargs): raise AssertionError("Planning or presets must not import, probe or build previews")
    store.worker = forbidden
    return store, assets


def project(assets, pictures=0, videos=0, audios=0, paired=True, duration=5, start=0, source_in=0):
    value = V2["source"](pictures,videos,audios,soundtracks=paired,target=duration)
    value["processing_window"]={"start_seconds":start,"end_seconds":start+duration,"fps":24}
    value["assets"]=copy.deepcopy([asset for values in assets.values() for asset in values])
    for kind in ("picture","video","audio"):
        for index,row in enumerate(value[kind+"_track"]):
            if kind == "audio" and row["linked_video_clip_id"]:
                row["asset_id"]=assets["video"][int(row["linked_video_clip_id"][1:])-1]["asset_id"]
            else:
                ordinal=int(row.get("item_id",row.get("clip_id"))[1:])-1
                row["asset_id"]=assets[kind][ordinal]["asset_id"]
            if kind != "picture": row.update(source_in_seconds=source_in,source_out_seconds=source_in+2)
    return C.normalize_project(value)


def prompt():
    value=V2["H"]["fixed_hub_prompt"]()
    value["14"]=copy.deepcopy(value["7"])
    value["171"]={"class_type":"ZVProcessingWindowOutlet","inputs":{"media_project":["165",0]}}
    value["30"]={"class_type":"ComfyMathExpression","inputs":{"expression":"max(5, round(a)) + (5 - (max(5, round(a)) % 17)) % 17","values.a":["171",4]}}
    for node_id in ("7","14"): value[node_id]["inputs"].update(length=["30",1],task_type="auto",audio_mode="native")
    return value


def summary(media):
    if media is None: return None
    tensor=media["waveform"] if isinstance(media,dict) else media
    return {"shape":list(tensor.shape),"dtype":str(tensor.dtype),"device":str(tensor.device),"signature":float(tensor.flatten()[0]),**({"sample_rate":media["sample_rate"]} if isinstance(media,dict) else {})}


async def run_matrix(directory):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import torch

    store,assets=setup(directory); previous=RUN._store; RUN._store=store
    previous_server=S.get_store;S.get_store=lambda:store
    routes=web.RouteTableDef();S.register_interview_routes(routes);app=web.Application();app.add_routes(routes)
    results=[]; assertions=0
    def check(condition):
        nonlocal assertions
        assert condition;assertions+=1
    async with TestClient(TestServer(app)) as client:
        async def detect(current,state=None,graph=None):
            state=state or I.empty_interview();graph=graph or prompt()
            response=await client.post('/zf-prompt-director/h3-interview/plan',json={"state":state,"media_project":current,"align":True,"prompt":graph,"interview_id":"172","conditioning_count":2})
            check(response.status==200); result=await response.json()
            state=result["state"];state["reference_detection"]=result["snapshot"];state["alignment"]=result["alignment_context"]
            return result,state
        async def execute(name,current,state=None,expected_mode=None,expected_error=None):
            current,_,_=DESK.ZVUniversalMediaEvidenceDesk().export_project(json.dumps(current),width=64,height=96)
            graph=prompt();planned,state=await detect(current,state,graph)
            check(planned["validation"]["ready"]==(expected_error is None))
            built=V2["N"].ZVH3InterviewFormV2().build(current,I.dumps(state),prompt=graph,unique_id="172")
            plan=built[6];check(len(built)==7)
            record={"case":name,"mode":planned["validation"]["effective_mode"],"ready":plan["ready"],"mixed_sources":planned["validation"]["mixed_sources"],"errors":[row["code"] for row in plan["errors"]],"model_length":planned["validation"]["conditioning"]["model_length"],"source_selection":plan["reference_selection"]}
            if expected_error:
                check(expected_error in record["errors"])
                try:OUT.ZVH3ReferenceOutlet().export_references(plan)
                except OUT.ReferencePlanError:check(True)
                else:raise AssertionError("Invalid plan decoded")
                record["decoded"]=False;results.append(record);return record,state,current
            if expected_mode:check(record["mode"]==expected_mode)
            output=OUT.ZVH3ReferenceOutlet().export_references(plan);check(isinstance(output,tuple) and len(output)==24)
            manifest=json.loads(output[22]);record["calls"]=[]
            ports=OUT.ZVH3ReferenceOutlet.RETURN_NAMES
            snapshot={row["item_id"]+":"+row["origin"]:row for plural in ("pictures","videos","audios") for row in planned["snapshot"][plural]}
            for call in plan["call_references"]:
                source=REF.source_for_call(call,I.media_inventory(current));bank=source["bank"]
                endpoint=snapshot[call["item_id"]+":"+call["origin"]]["source_port"];slot=ports.index(endpoint);media=output[slot]
                check(media is not None);tensor=media["waveform"] if isinstance(media,dict) else media
                check(tensor.dtype==torch.float32 and tensor.device.type=="cpu")
                for node_id in ("7","14"):
                    matches=[(key,value) for key,value in graph[node_id]["inputs"].items() if value==["180",slot]];check(len(matches)==1)
                if call["kind"] != "audio":
                    matches=[value for key,value in graph["146"]["inputs"].items() if value==["180",slot]];check(len(matches)==1)
                if call["kind"]=="picture":
                    expected=int(call["item_id"][1:])*20/255;check(abs(float(tensor[0,0,0,0])-expected)<.01)
                elif call["kind"]=="video":
                    check(list(tensor.shape)==[48,96,64,3]);check(abs(float(tensor[0,0,0,0])-int(call["item_id"][1:])*40/255)<.015)
                    requested=next(row for row in current["video_track"] if row["clip_id"]==call["item_id"])["source_in_seconds"]
                    check(abs(float(tensor[0,0,0,1])-requested*72/255)<.015)
                    check(abs(float(tensor[-1,0,0,1])-(requested*24+47)*3/255)<.015)
                else:
                    if call["soundtrack"]:
                        expected=(int(call["item_id"][1:])*2000+int(next(row for row in current["video_track"] if row["clip_id"]==call["item_id"])["source_in_seconds"])*500)/32768
                    else:
                        clip=next(row for row in current["audio_track"] if row["clip_id"]==call["item_id"]);expected=((4096,8192,-4096)[int(clip["source_in_seconds"])]+int(call["item_id"][1:])*100)/32768
                    check(abs(float(tensor[0,0,1000])-expected)<.003)
                    check(list(tensor.shape)==[1,2,88200])
                key=("video:" if call["soundtrack"] else call["kind"]+":")+call["item_id"]
                decoded=manifest["decoded_manifests"][key]["items"][0]
                record["calls"].append({"kind":call["kind"],"item_id":call["item_id"],"purpose_item_id":call["purpose_item_id"],"bank":bank,"label":call["call_label"],"output_slot":slot,"port":endpoint,"LOW_HIGH_endpoint_verified":True,"Stage1_visual_endpoint_verified":call["kind"]!="audio","media":summary(media),"source_window":decoded.get("source_window"),"requested_source_window":decoded.get("requested_source_window")})
            record["canvas"]={"width":64,"height":96};record["tuple_outputs"]=[summary(value) for value in output[:22]]
            record["visibility"]=plan.get("model_visibility",[]);record["decoded"]=True
            check(current["output_canvas"]=={"width":64,"height":96})
            results.append(record);return record,state,current
        try:
            await execute("empty T2VA",project(assets),expected_mode="T2VA")
            three=project(assets,3,1);state=I.empty_interview();state["intent"]="<Picture 1> 的人物替换 <Video 1>，<Picture 2> <Picture 3> 自由参考"
            _,state,three=await execute("3 pictures + video identity replacement",three,state,expected_mode="Ref2VA")
            changed=copy.deepcopy(three);changed["picture_track"][0]["order"]=9
            await execute("reorder with original fixed graph",C.normalize_project(changed),state,expected_mode="Ref2VA")
            pair=project(assets,2);state=I.empty_interview();state["bindings"]={"p1":{"item_id":"p1","participates":True,"banks":["first_frame"]},"p2":{"item_id":"p2","participates":True,"banks":["last_frame"]}}
            await execute("physical first + last",pair,state,expected_mode="FL2VA")
            state["bindings"]["p1"]["banks"].append("ref_images")
            record,_,_=await execute("anchors + references local Hybrid",pair,state,expected_mode="Hybrid")
            state=I.empty_interview();state["media_roles"]={"p1":["first_frame"],"p2":["last_frame"]}
            await execute("semantic anchors do not change banks",pair,state,expected_mode="Ref2VA")
            await execute("last 2 seconds outside later GEN",project(assets,0,1,1,start=10,source_in=1),expected_mode="Ref2VA")
            bridge=project(assets,0,2,start=5,source_in=1);bridge["video_track"][1]["timeline_in_seconds"]=12
            await execute("two contexts outside middle GEN preparation",C.normalize_project(bridge),expected_mode="Ref2VA")
            full=project(assets,6,3,3);_,state,full=await execute("6 + 3 voiced + 3 independent = 12",full,expected_mode="Ref2VA")
            full["video_track"][1]["source_audio_enabled"]=False
            record,_,_=await execute("muted pair reindexes remaining sources",C.normalize_project(full),state,expected_mode="Ref2VA")
            check([(row["item_id"],row["label"]) for row in record["calls"] if row["kind"]=="audio"]==[("v1","<Audio 1>"),("v3","<Audio 2>"),("a1","<Audio 3>"),("a2","<Audio 4>"),("a3","<Audio 5>")])
            await execute("9 pictures + 3 independent = 12",project(assets,9,0,3),expected_mode="Ref2VA")
            for name,counts,error in [("13 sources",(7,3,3),"mixed_sources"),("4 videos",(0,4,0),"media_limit"),("10 pictures",(10,0,0),"media_limit"),("4 independent audios",(0,0,4),"media_limit")]:
                await execute(name,project(assets,*counts),expected_error=error)
            for seconds,length in [(4,107),(5,124),(15,362)]:
                record,_,_=await execute(f"GEN {seconds}s grid",project(assets,0,1,duration=seconds),expected_mode="Ref2VA");check(record["model_length"]==length)
            current=project(assets,0,1)
            for kind in ("different_length","unknown_dynamic"):
                graph=prompt();graph["14"]["inputs"]["length"]=362 if kind=="different_length" else ["unknown",0]
                if kind=="unknown_dynamic":graph["7"]["inputs"]["length"]=["unknown",0];graph["unknown"]={"class_type":"PrimitiveInt","inputs":{"value":124}}
                result,_=await detect(current,graph=graph)
                check(result["validation"]["ready"]==(kind=="unknown_dynamic"))
                if kind=="unknown_dynamic":check(not result["validation"]["conditioning"]["length_verified"])
                results.append({"case":kind,"ready":result["validation"]["ready"],"conditioning":result["validation"]["conditioning"],"decoded":False})
            core_spec=importlib.util.spec_from_file_location('comfy_execution.graph_utils',ROOT.parents[1]/'comfy_execution/graph_utils.py')
            core=importlib.util.module_from_spec(core_spec);core_spec.loader.exec_module(core)
            with patch.dict(sys.modules,{'comfy_execution.graph_utils':core}):
                for dimension in ("width","height"):
                    blocked,text,catalog=DESK.ZVUniversalMediaEvidenceDesk().export_project(json.dumps(current),**{dimension:64})
                    check(isinstance(blocked,core.ExecutionBlocker) and isinstance(text,core.ExecutionBlocker))
                    check("同时" in blocked.message)
                    check(len(catalog.entries)==len(current['assets']))
            result,state=await detect(current);current["output_canvas"]={"width":96,"height":64}
            stale=I.compile_interview(state,current);check(any(row["code"]=="alignment_stale" for row in stale["validation"]["errors"]))
            results.append({"case":"single dimensions reject and canvas stales alignment","ready":False,"decoded":False})
            # Execute both pending surfaces on real registry assets, not synthetic media descriptions.
            old=project(assets,0,1);_,state=await detect(old,I.empty_interview()|{"intent":"<Video 1> 同源"})
            state["media_purposes"]["va1"]="use <Audio 1> own voice with <Video 1>";preset=P.capture_template(state,old)
            silent=project(assets,0,1,paired=False);loaded=P.apply_template(preset,I.empty_interview(),silent)["state"]
            extra=project(assets,0,2);extra["video_track"][0].update(source_audio_enabled=False,audio_link_id=None,timeline_in_seconds=1);extra["audio_track"]=[row for row in extra["audio_track"] if row["clip_id"]!="va1"]
            extra=C.normalize_project(extra);_,waiting=await detect(extra,loaded)
            exported=P.capture_template(waiting,extra)
            own=next(row for row in exported["slots"] if row["kind"]=="video" and row["slot"]==2)
            check({row["source"]["slot"] for row in own["soundtrack"]["purpose"]["definitions"]}=={2})
            voiced=project(assets,0,2);voiced["video_track"][0]["timeline_in_seconds"]=1;voiced=C.normalize_project(voiced)
            record,state,_=await execute("pending restore after front video",voiced,waiting,expected_mode="Ref2VA")
            check(state["media_purposes"]["va1"]=="use <Audio 2> own voice with <Video 2>")
            check({row["source"]["item_id"] for row in state["reference_texts"]["purpose:va1"]["definitions"]}=={"v1"})
            loaded=P.apply_template(exported,I.empty_interview(),project(assets,0,2))["state"]
            await execute("pending export current slots reload",project(assets,0,2),loaded,expected_mode="Ref2VA")
        finally:
            RUN._store=previous;S.get_store=previous_server
    return {"scope":"real temporary neutral registry/cache + aiohttp HTTP planning + actual CPU 24-output node; no model/GPU execution","cases":results,"assertions":assertions,"case_count":len(results),"failed":0,"skipped":0,"planning_import_probe_preview_processing":0,"fixed_graph_reused":True}


def run():
    with tempfile.TemporaryDirectory(prefix="h3-v2-03-matrix-") as temporary:
        return asyncio.run(run_matrix(Path(temporary)))


if __name__=="__main__":
    import sys
    value=run()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"H3_V2_03_MATRIX_OK {value['case_count']} cases / {value['assertions']} assertions / 0 failed / 0 skipped; CPU only")
