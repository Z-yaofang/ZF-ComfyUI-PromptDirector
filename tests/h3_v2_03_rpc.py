"""03 browser bridge extends neutral 02 harness; actual registry and CPU outputs."""
import copy
import json
from pathlib import Path
import runpy
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
B=runpy.run_path(str(ROOT/"tests/h3_v2_plan_rpc.py"))
M=runpy.run_path(str(ROOT/"tests/h3_v2_03_matrix.py"))
TEMP=tempfile.TemporaryDirectory(prefix="h3-v2-03-ui-")
store=None;last_value=None;matrix_assets=None


def execute(request):
    global store,last_value,matrix_assets
    if request["action"]=="matrix_setup":
        store,assets=M["setup"](Path(TEMP.name))
        matrix_assets=assets
        M["RUN"]._store=store
        B["cached_path"].__globals__.update(NEUTRAL_ROOT=store.root,NEUTRAL_HANDLES={row["source_handle"] for values in assets.values() for row in values})
        cases=[]
        for name,counts,paired,duration,start,source_in in [("empty",(0,0,0),True,5,0,0),("3+1",(3,1,0),True,5,0,0),("tail selected context",(0,1,1),True,5,10,1),("two bridge contexts",(0,2,0),True,5,5,1),("6+3+3 Audio6",(6,3,3),True,5,0,0),("9+0+3",(9,0,3),True,5,0,0),("13 source rejection",(7,3,3),True,5,0,0),("4 videos rejection",(0,4,0),True,5,0,0),("10 pictures rejection",(10,0,0),True,5,0,0),("4 audio rejection",(0,0,4),True,5,0,0),("4s",(0,1,0),True,4,0,0),("15s",(0,1,0),True,15,0,0)]:
            current=M["project"](assets,*counts,paired=paired,duration=duration,start=start,source_in=source_in)
            if name=="two bridge contexts":current["video_track"][1]["timeline_in_seconds"]=12
            current["output_canvas"]={"width":64,"height":96};current=M["C"].normalize_project(current)
            cases.append({"name":name,"project":current,"state":M["I"].empty_interview(),"ready":"rejection" not in name})
        anchors=M["project"](assets,2);anchors["output_canvas"]={"width":64,"height":96}
        for hybrid in (False,True):
            state=M["I"].empty_interview();state["bindings"]={"p1":{"item_id":"p1","participates":True,"banks":["first_frame"]+(["ref_images"] if hybrid else [])},"p2":{"item_id":"p2","participates":True,"banks":["last_frame"]}}
            cases.append({"name":"Hybrid" if hybrid else "FL2VA","project":anchors,"state":state,"ready":True})
        return cases
    if request["action"]=="matrix_missing":
        old=M["project"](matrix_assets,3);old["output_canvas"]={"width":64,"height":96}
        state=M["V2"]["aligned"](old,M["I"].empty_interview()|{"intent":"<Picture 1> original / <Picture 2> added / <Picture 3> later"})
        state["media_purposes"]={f"p{i}":f"<Picture {i}> purpose {i}" for i in range(1,4)}
        template=M["P"].capture_template(state,old)
        current=M["project"](matrix_assets,1);current["output_canvas"]={"width":64,"height":96}
        loaded=M["P"].apply_template(template,M["I"].empty_interview(),current)
        return {"project":current,"state":loaded["state"],"full":old}
    if request["action"]=="matrix_reload":
        current=store.canonical(request["project"]);template=M["P"].capture_template(request["state"],current)
        new=M["project"](matrix_assets,3);new["output_canvas"]={"width":64,"height":96}
        for index,row in enumerate(new['picture_track'],1):row['item_id']=f'n{index}'
        new=M["C"].normalize_project(new)
        loaded=M["P"].apply_template(template,M["I"].empty_interview(),new)
        assert 'item_id' not in json.dumps(template)
        return {"project":new,"state":loaded["state"]}
    if request["action"]=="plan" and store:
        last_value=copy.deepcopy(request["value"])
        last_value["media_project"]=store.canonical(M["S"]._planning_project(M["C"].normalize_project(last_value["media_project"]), last_value.get("prompt"), str(last_value.get("interview_id", ""))))
        return M["S"].plan_interview(last_value, prepared_project=last_value["media_project"])
    if request["action"]=="matrix_cpu":
        current=store.canonical(request["project"]);state=request["state"]
        compiled=M["I"].compile_interview(state,current)
        try:built=M["V2"]["N"].ZVH3InterviewForm().build(current,M["I"].dumps(state),prompt=last_value["prompt"],unique_id="172")
        except RuntimeError:
            if compiled["validation"]["ready"]:raise
            plan=M["V2"]["RP"].build_reference_plan(current,compiled)
            try:M["OUT"].ZVH3ReferenceOutlet().export_references(plan)
            except M["OUT"].ReferencePlanError:return {"ready":False,"decoded":False,"errors":[row["code"] for row in plan["errors"]]}
            raise AssertionError("Rejected plan decoded after node early rejection")
        plan=built[8]
        if not plan["ready"]:
            try:M["OUT"].ZVH3ReferenceOutlet().export_references(plan)
            except M["OUT"].ReferencePlanError:return {"ready":False,"decoded":False,"errors":[row["code"] for row in plan["errors"]]}
            raise AssertionError("Rejected source plan decoded")
        output=M["OUT"].ZVH3ReferenceOutlet().export_references(plan);assert len(output)==24
        payload=json.loads(output[22]);calls=[];ports=M["OUT"].ZVH3ReferenceOutlet.RETURN_NAMES
        snap=M["V2"]["RP"].planned_detection({"call_references":plan["call_references"]})
        rows=[row for plural in ("pictures","videos","audios") for row in snap[plural]]
        for call in plan["call_references"]:
            source=M["REF"].source_for_call(call,M["I"].media_inventory(current))
            port=next(row["source_port"] for row in rows if row["item_id"]==call["item_id"] and row["origin"]==call["origin"])
            slot=ports.index(port);media=output[slot];tensor=media["waveform"] if isinstance(media,dict) else media
            signatures={"audio_sample":float(tensor[0,0,1000])} if isinstance(media,dict) else {"rgb_first":tensor[0,0,0].tolist(),"rgb_last":tensor[-1,0,0].tolist()}
            key=("video:" if call["soundtrack"] else call["kind"]+":")+call["item_id"]
            calls.append({"kind":call["kind"],"item_id":call["item_id"],"bank":source["bank"],"label":call["call_label"],"port":port,"output_slot":slot,"media":M["summary"](media),"signatures":signatures,"source_window":payload["decoded_manifests"][key]["items"][0].get("source_window")})
        return {"ready":True,"decoded":True,"calls":calls,"tuple_count":24,"routes":plan["routes"],"model_visibility":plan.get("model_visibility",[]),"rendered_intent":state["intent"],"source_bindings":state["reference_texts"]}
    return B["execute"](request)


if __name__=="__main__":
    sys.stdin.reconfigure(encoding="utf-8");sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        request=json.loads(line)
        try:print(json.dumps({"id":request["id"],"result":execute(request)},ensure_ascii=False),flush=True)
        except Exception as error:print(json.dumps({"id":request["id"],"error":str(error)},ensure_ascii=False),flush=True)
