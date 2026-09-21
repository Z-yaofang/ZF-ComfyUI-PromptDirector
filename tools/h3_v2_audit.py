"""Read-only workflow audit, explicit runtime copy and neutral wiring example.

Never reads model selections into the report or writes the source workflow.
"""
import argparse
import ast
import copy
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import uuid

PLUGIN = Path(__file__).resolve().parents[1]
COMFY = PLUGIN.parents[1]
EXPRESSION = "max(5, round(a)) + (5 - (max(5, round(a)) % 17)) % 17"
ROOT_FILES = ("__init__.py","nodes.py","server.py","flow_nodes.py","local_multimodal.py","music_nodes.py","portrait_nodes.py")
DATA_FILES = ("purposes.json","visual_methods.json","default_combinations.json","writing_grammar.json","purpose_visual_recommendations.json","portrait_generator_v12.json")
SCHEMA_FILES = ("zv-media-project-v2.schema.json","zv-processing-preset-v1.schema.json","zv-segment-plan-v1.schema.json")
OUTPUT_NAMES = ("H3_V2_03_RUNTIME_MANIFEST.json", "H3_V2_03_WORKFLOW_AUDIT.json", "H3_V2_03_PREPARATION_WORKFLOW.json", "H3_V2_03_SHARE_CHECK.json", "H3_V2_03_COPY_REGISTRATION.json")


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_directory(path):
    """Inspect lexical ancestors before resolve can hide links or junctions."""
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Linked output directory is not allowed: {ancestor}")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"Output ancestor is not a directory: {ancestor}")
    return path.resolve()


def new_target(path):
    path = Path(path).absolute()
    safe_directory(path.parent)
    try:
        path.lstat()
    except FileNotFoundError:
        return path.resolve()
    raise ValueError(f"Output target already exists (including links): {path}")


def check_copy_destination(destination, root):
    if destination.is_relative_to(root.resolve()):
        raise ValueError("Copy destination must be new and outside the plugin")
    if any(parent.name.casefold() == "custom_nodes" for parent in (destination, *destination.parents)):
        raise ValueError("Audit copies must stay outside custom_nodes; ComfyUI would load duplicate nodes and frontends")


def preflight(workflow, output_dir, copy_to=None):
    workflow = Path(workflow).resolve(strict=True)
    if not workflow.is_file():
        raise ValueError("Workflow input must be a file")
    output_dir = safe_directory(output_dir)
    targets = tuple(output_dir / name for name in OUTPUT_NAMES)
    if workflow in targets:
        raise ValueError("Workflow input overlaps an audit output target")
    targets = tuple(new_target(path) for path in targets)
    copy_to = new_target(copy_to) if copy_to is not None else None
    if copy_to is not None:
        check_copy_destination(copy_to, PLUGIN)
        if copy_to == workflow or output_dir.is_relative_to(copy_to) or any(copy_to.is_relative_to(path) for path in targets):
            raise ValueError("Copy destination overlaps an input or audit output")
    return workflow, output_dir, targets, copy_to


def runtime_files(root=PLUGIN):
    files=[root/name for name in ROOT_FILES]+[root/"data"/name for name in DATA_FILES]
    files.extend(root/"schemas"/name for name in SCHEMA_FILES)
    for folder in ("h3_focus","media_evidence","long_video","animate_video"):
        files.extend(path for path in (root/folder).iterdir() if path.suffix in (".py",".json"))
    files.extend(path for path in (root/"web").iterdir() if path.suffix in (".js",".mjs",".css",".json"))
    files.extend((root/"locales").glob("*/nodeDefs.json"))
    catalog=json.loads((root/"data/visual_methods.json").read_text(encoding="utf-8"))
    files.extend(root/"web/thumbnails"/row["thumbnail"] for row in catalog if row.get("thumbnail"))
    result=sorted(set(path.relative_to(root).as_posix() for path in files))
    for relative in result:
        path=root/relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Missing or linked runtime file: {relative}")
    return result


def manifest(root=PLUGIN):
    tracked=set(subprocess.check_output(["git","ls-files"],cwd=root,text=True,encoding="utf-8").splitlines())
    return {"scope":"current backend registration and frontend runtime, including H3, Animate and ZFI; catalog stock thumbnails only","published":False,"files":[{"path":key,"sha256":sha(root/key),"git_tracked":key in tracked} for key in runtime_files(root)],"excluded":[".git",".env","API/model configuration","user preset databases","registry","cache","imported media","tests","private logs"]}


def copy_runtime(destination, root=PLUGIN):
    destination=new_target(destination)
    check_copy_destination(destination, root)
    destination.mkdir(parents=True)
    for relative in runtime_files(root):
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/relative,target)
    return destination


def copied_registration(destination, comfy=COMFY):
    """Execute copied real __init__; isolate core graph/server boot, not plugin classes."""
    from aiohttp import web
    graph_path=comfy/"comfy_execution/graph_utils.py"
    utilities=importlib.import_module("comfy_execution.graph_utils")
    if Path(utilities.__file__).resolve() != graph_path.resolve():
        raise ValueError("Run the audit with the Python environment for this ComfyUI installation")
    graph=types.ModuleType("comfy_execution.graph");graph.ExecutionBlocker=utilities.ExecutionBlocker
    server=types.ModuleType("server");server.PromptServer=type("PromptServer",(),{"instance":types.SimpleNamespace(routes=web.RouteTableDef())})
    overrides={"server":server,"comfy_execution.graph":graph}
    previous={key:sys.modules.get(key) for key in overrides};sys.modules.update(overrides)
    name="_h3_v2_copied_runtime_" + uuid.uuid4().hex
    try:
        spec=importlib.util.spec_from_file_location(name,destination/"__init__.py",submodule_search_locations=[str(destination)])
        plugin=importlib.util.module_from_spec(spec);sys.modules[name]=plugin;spec.loader.exec_module(plugin)
        required=(
            "ZVUniversalMediaEvidenceDesk","ZVProcessingWindowOutlet","ZVH3InterviewFormV2","ZVH3ReverseStage","ZVH3ReferenceOutlet",
            "ZFPromptDirectorLocalLLM","ZVOriginalPictureOutlet","ZVOriginalVideoOutlet","ZVOriginalAudioOutlet",
            "ZVLongVideoSegmentDesk","ZVSegmentInterview","ZVSegmentVideoMaskSource","ZVMaskedSegmentBundle",
            "ZVSegmentMaskSlice","ZVLongVideoExecutionSetup","ZVLongVideoExecutionEntry",
            "ZVLongVideoSegmentRecorder","ZVLongVideoExecutionEnd",
            "ZVAnimateSegmentDesk","ZVAnimateExecutionEntry","ZVAnimateSegmentRecorder","ZVAnimateExecutionEnd",
            "ZVAnimateMaskFrame","ZVAnimateMaskSeed","ZVAnimateMaskGate",
        )
        for key in required:
            cls=plugin.NODE_CLASS_MAPPINGS[key]
            assert cls.__module__.startswith(name+".")
            assert len(cls.RETURN_TYPES)==len(cls.RETURN_NAMES)
            cls.INPUT_TYPES()
        assert len(plugin.NODE_CLASS_MAPPINGS["ZVH3ReferenceOutlet"].RETURN_TYPES)==24
        routes=[{"method":route.method,"path":route.path} for route in server.PromptServer.instance.routes]
        assert any(route["path"]=="/zf-prompt-director/h3-interview/plan" for route in routes)
        assert any(route["path"].endswith("/presets/{preset_id}/apply") for route in routes)
        assert any(route["path"]=="/zf-prompt-director/long-video/plan" for route in routes)
        assert any(route["path"]=="/zf-prompt-director/long-video/interview" for route in routes)
        assert any(route["path"]=="/zf-prompt-director/animate-video/plan" for route in routes)
        value={"scope":"copied actual plugin __init__ + real classes + aiohttp route registration; server and core graph boot adapters; no Comfy GPU boot","core_execution_blocker_sha256":sha(graph_path),"registered_classes":sorted(plugin.NODE_CLASS_MAPPINGS),"routes":routes,"web_directory":plugin.WEB_DIRECTORY,"passed":True,"full_comfy_service_started":False}
        return value,plugin.NODE_CLASS_MAPPINGS
    finally:
        for key in tuple(sys.modules):
            if key == name or key.startswith(name + "."):
                sys.modules.pop(key, None)
        for key,value in previous.items():
            if value is None:sys.modules.pop(key,None)
            else:sys.modules[key]=value


def schema(path, node_id):
    """Read a real v3 Schema AST without importing its model/attention code."""
    tree=ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="Schema":
            keywords={kw.arg:kw.value for kw in node.keywords}
            if isinstance(keywords.get("node_id"),ast.Constant) and keywords["node_id"].value==node_id:
                def inputs():
                    result=[]
                    for item in keywords["inputs"].elts:
                        if not isinstance(item,ast.Call) or not item.args or not isinstance(item.args[0],ast.Constant):continue
                        owner=item.func.value
                        kind=owner.attr if isinstance(owner,ast.Attribute) else owner.id
                        key=item.args[0].value;options={kw.arg:kw.value for kw in item.keywords}
                        default=None
                        if "default" in options:
                            try:default=ast.literal_eval(options["default"])
                            except (ValueError,TypeError):pass
                        entry={"name":key,"type":{"Int":"INT","Float":"FLOAT","String":"STRING","Boolean":"BOOLEAN","Image":"IMAGE","Audio":"AUDIO","Clip":"CLIP","Vae":"VAE","Autogrow":"AUTOGROW"}.get(kind,kind.upper()),"default":default,"optional":isinstance(options.get("optional"),ast.Constant) and options["optional"].value is True}
                        if kind=="Autogrow" and isinstance(options.get("template"),ast.Call):
                            template={kw.arg:kw.value for kw in options["template"].keywords}
                            entry["autogrow"]={name:ast.literal_eval(template[name]) for name in ("prefix","min","max") if name in template}
                        result.append(entry)
                    return result
                outputs=[item.func.value.attr.upper() for item in keywords["outputs"].elts]
                return {"node_id":node_id,"path":path.relative_to(COMFY).as_posix(),"line":node.lineno,"sha256":sha(path),"inputs":inputs(),"outputs":outputs}
    raise ValueError(f"No real Schema mapping for {node_id}")


def audit_workflow(path):
    raw=path.read_bytes();workflow=json.loads(raw.decode("utf-8-sig"));nodes={node["id"]:node for node in workflow["nodes"]};links={row[0]:row for row in workflow["links"]}
    errors=[]
    if len(nodes)!=len(workflow["nodes"]) or len(links)!=len(workflow["links"]):errors.append("Duplicate node/link IDs")
    for link in links.values():
        _,source,output,target,input_slot,_=link
        if source not in nodes or target not in nodes:errors.append("Missing endpoint");continue
        if output>=len(nodes[source].get("outputs",[])) or input_slot>=len(nodes[target].get("inputs",[])):errors.append("Out-of-range endpoint");continue
        if nodes[target]["inputs"][input_slot].get("link")!=link[0] or link[0] not in (nodes[source]["outputs"][output].get("links") or []):errors.append("Nonreciprocal endpoint")
    def endpoint(node_id,name):
        item=next(row for row in nodes[node_id]["inputs"] if row["name"]==name)
        link=links.get(item.get("link"));return {"source_id":link[1],"output_slot":link[2]} if link else None
    forms=[node for node in nodes.values() if node["type"]=="ZVH3InterviewFormV2"]
    outlets=[node for node in nodes.values() if node["type"]=="ZVH3ReferenceOutlet"]
    if len(forms)!=1 or len(outlets)!=1:
        raise ValueError("Audit requires one current interview form and one reference outlet")
    form,outlet=forms[0],outlets[0]
    media=[]
    for target in [node["id"] for node in nodes.values() if node["type"]=="MiniMaxH3AudioConditioningT8"]:
        ports=[row for row in nodes[target]["inputs"] if row.get("link") in links and links[row["link"]][1]==outlet["id"]]
        if len(ports)!=22:errors.append("Not all 22 fixed media inputs connected")
        media.append({"target":target,"ports":[{"name":row["name"],"slot":links[row["link"]][2]} for row in ports]})
    original_hash=hashlib.sha256(raw).hexdigest();assert sha(path)==original_hash
    roots=[COMFY/"nodes.py",COMFY/"comfy_extras"]+[COMFY/"custom_nodes"/folder for folder in ("ZF-ComfyUI-PromptDirector","comfyui-minimax-h3-audio-T8","ComfyUI-KJNodes","ComfyUI-SolAttn_triton","rgthree-comfy","ComfyUI_Comfyroll_CustomNodes","ComfyUI-Custom-Scripts","ComfyUI-Easy-Use","ComfyUI-Impact-Pack","ComfyUI-VideoHelperSuite","ComfyUI-llama-cpp_vllm")]
    classes={row["type"] for row in nodes.values()};matches={key:[] for key in classes}
    for root in roots:
        paths=[root] if root.is_file() else sorted(root.rglob("*.py"))+sorted(root.rglob("*.js"))
        for source in paths:
            if any(part in {"__pycache__","tests","tools","scripts","docs",".git"} for part in source.parts):continue
            text=source.read_text(encoding="utf-8-sig",errors="replace")
            for key in classes:
                pattern=re.compile(r"(?:['\"]"+re.escape(key)+r"['\"]|\bclass\s+"+re.escape(key)+r"\b)")
                match=pattern.search(text)
                if match is None and '(rgthree)' in key and 'rgthree-comfy' in source.parts:
                    match=re.search(r"(?:addRgthree|get_name)\(['\"]"+re.escape(key.removesuffix(' (rgthree)'))+r"['\"]\)",text)
                if match:matches[key].append({"path":source.relative_to(COMFY).as_posix(),"line":text.count('\n',0,match.start())+1,"sha256":sha(source),"evidence":"installed literal/class source occurrence; registration/execute not GPU tested"})
    ownership=[{"type":key,"node_ids":[row["id"] for row in nodes.values() if row["type"]==key],"source_matches":matches[key],"frontend_only":key in {"Note","Fast Groups Bypasser (rgthree)"}} for key in sorted(classes)]
    unresolved=[row["type"] for row in ownership if not row["source_matches"] and not row["frontend_only"]]
    return {"sha256":original_hash,"node_count":len(nodes),"link_count":len(links),"structural_errors":errors,
            "interview_to_outlet":endpoint(outlet["id"],"reference_plan"),"fixed_outputs":len(outlet["outputs"]),
            "interview_outputs":[row["name"] for row in form["outputs"]],
            "reverse_stage_count":sum(node["type"]=="ZVH3ReverseStage" for node in nodes.values()),
            "LOW_HIGH_media":media,"ownership":ownership,"unresolved_source_classes":unresolved,
            "private_text_exported":False,"model_selection_names_exported":False,"workflow_written":False}


def skeleton(mappings):
    schemas=[schema(COMFY/"comfy_extras/nodes_resolution.py","ResolutionSelector"),schema(COMFY/"comfy_extras/nodes_math.py","ComfyMathExpression"),schema(COMFY/"custom_nodes/comfyui-minimax-h3-audio-T8/h3_t8/nodes.py","MiniMaxH3AudioConditioningT8")]
    t8=schemas[2];assert t8["outputs"]==["CONDITIONING","LATENT","AUDIO","STRING","STRING","STRING"]
    nodes=[];links=[]
    def add(node_id,node_type,title,inputs,outputs,widgets):
        node={"id":node_id,"type":node_type,"title":title,"pos":[(node_id%3)*450,(node_id//3)*340],"size":[420,290],"flags":{},"order":node_id-1,"mode":0,"inputs":[{"name":key,"type":kind,"link":None} for key,kind in inputs],"outputs":[{"name":key,"type":kind,"links":[]} for key,kind in outputs],"properties":{"Node name for S&R":node_type},"widgets_values":widgets};nodes.append(node);return node
    def defaults(name):
        result=[]
        for section in ("required","optional"):
            for key,entry in mappings[name].INPUT_TYPES().get(section,{}).items():
                if isinstance(entry[0],list) or entry[0] in {"STRING","INT","FLOAT","BOOLEAN"}:
                    options=entry[1] if len(entry)>1 else {}
                    if options.get("forceInput"):continue
                    result.append(options.get("default",entry[0][0] if isinstance(entry[0],list) else ""))
                    if options.get("control_after_generate"):result.append("fixed")
        return result
    def cls_outputs(name):return list(zip(mappings[name].RETURN_NAMES,mappings[name].RETURN_TYPES))
    resolution=add(1,"ResolutionSelector","Canvas — connect once to desk",[],[("width","INT"),("height","INT")],["9:16 (Portrait Widescreen)",1.0,32])
    desk=add(2,"ZVUniversalMediaEvidenceDesk","Import your own media",[("width","INT"),("height","INT")],cls_outputs("ZVUniversalMediaEvidenceDesk"),defaults("ZVUniversalMediaEvidenceDesk"))
    interview=add(3,"ZVH3InterviewFormV2","Collect, align, organize user requirements",[("media_project","ZV_MEDIA_PROJECT")],cls_outputs("ZVH3InterviewFormV2"),defaults("ZVH3InterviewFormV2"))
    outlet=add(4,"ZVH3ReferenceOutlet","Fixed 24 outputs — keep these wires",[("reference_plan","ZV_H3_REFERENCE_PLAN")],cls_outputs("ZVH3ReferenceOutlet"),[])
    window=add(5,"ZVProcessingWindowOutlet","GEN frame count",[("media_project","ZV_MEDIA_PROJECT")],cls_outputs("ZVProcessingWindowOutlet"),[])
    math=add(6,"ComfyMathExpression","Exact H3 17n+5 grid",[("values.a","FLOAT,INT,BOOLEAN")],[("FLOAT","FLOAT"),("INT","INT"),("BOOL","BOOLEAN")],[EXPRESSION])
    media=[("first_frame",0),("last_frame",1)]+[(f"ref_images.ref_image_{i}",i+2) for i in range(9)]+[(f"ref_videos.ref_video_{i}",i+11) for i in range(3)]+[(f"ref_video_audios.ref_video_audio_{i}",i+14) for i in range(3)]+[("drive_audio",17),("final_audio",18)]+[(f"ref_audios.ref_audio_{i}",i+19) for i in range(3)]
    widget_values=["",1344,768,124,"auto","native",.35,True,0,True,"match","official_2_to_15s",True]
    for node_id in (7,8):add(node_id,t8["node_id"],f"{'LOW' if node_id==7 else 'HIGH'} — add your CLIP/VAEs/sampling",[("clip","CLIP"),("video_vae","VAE"),("audio_vae","VAE"),("prompt","STRING"),("width","INT"),("height","INT"),("length","INT")]+[(key,mappings["ZVH3ReferenceOutlet"].RETURN_TYPES[slot]) for key,slot in media],[(name,kind) for name,kind in zip(("positive","av_latent","mux_audio","conditioned_prompt","media_map_json","report"),t8["outputs"])],copy.deepcopy(widget_values))
    stage_inputs=[("llama_model","LLAMACPPMODEL"),("role","STRING"),("prompt","STRING"),("parameters","LLAMACPPARAMS")]+[(f"image{i+1}","IMAGE") for i in range(11)]+[("video_frames"+(str(i+1) if i else ""),"IMAGE") for i in range(3)]
    for node_id in (9,11):
        widgets=defaults("ZFPromptDirectorLocalLLM")
        if node_id==11:
            names=[key for section in ("required","optional") for key,entry in mappings["ZFPromptDirectorLocalLLM"].INPUT_TYPES().get(section,{}).items()
                   if (isinstance(entry[0],list) or entry[0] in {"STRING","INT","FLOAT","BOOLEAN"}) and not (entry[1] if len(entry)>1 else {}).get("forceInput")]
            widgets[names.index("force_offload")+1]=True
        add(node_id,"ZFPromptDirectorLocalLLM",f"Stage {node_id-8} — connect your writer backend",stage_inputs,cls_outputs("ZFPromptDirectorLocalLLM"),widgets)
    add(10,"llama_cpp_instruct_adv","Stage 2 — organize Chinese user intent",
        [("llama_model","LLAMACPPMODEL"),("parameters","LLAMACPPARAMS"),("system_prompt","STRING"),("custom_prompt","STRING")],
        [("output","STRING"),("output_list","STRING"),("state_uid","INT")],
        ["Prompt Style - Detailed","","","one by one",24,256,42,"fixed",False,False])
    for node_id,label in zip((12,13,14),("素材理解","中文意图整理","H3提示词生成")):
        add(node_id,"ZVH3ReverseStage",label,[("user_prompt","STRING"),("material_context_json","STRING"),("material_evidence","STRING"),("chinese_user_prompt","STRING")],cls_outputs("ZVH3ReverseStage"),[label,""])
    def wire(source,slot,target,name):
        origin=next(row for row in nodes if row["id"]==source);destination=next(row for row in nodes if row["id"]==target);index=next(i for i,row in enumerate(destination["inputs"]) if row["name"]==name);link_id=len(links)+1;kind=origin["outputs"][slot]["type"]
        links.append([link_id,source,slot,target,index,kind]);origin["outputs"][slot]["links"].append(link_id);destination["inputs"][index]["link"]=link_id
    wire(1,0,2,"width");wire(1,1,2,"height");wire(2,0,3,"media_project");wire(3,6,4,"reference_plan");wire(2,0,5,"media_project");wire(5,4,6,"values.a")
    for target in (7,8):
        wire(1,0,target,"width");wire(1,1,target,"height");wire(6,1,target,"length");wire(11,0,target,"prompt")
        for key,slot in media:wire(4,slot,target,key)
    for llm,stage_id in ((9,12),(10,13),(11,14)):
        wire(3,0,stage_id,"user_prompt");wire(3,1,stage_id,"material_context_json")
        wire(stage_id,0,llm,"system_prompt" if llm==10 else "role")
        wire(stage_id,1,llm,"custom_prompt" if llm==10 else "prompt")
    wire(9,0,13,"material_evidence");wire(9,0,14,"material_evidence");wire(10,0,14,"chinese_user_prompt")
    for llm in (9,11):
        for i in range(11):wire(4,i,llm,f"image{i+1}")
        for i in range(3):wire(4,i+11,llm,"video_frames"+(str(i+1) if i else ""))
    graph={"last_node_id":14,"last_link_id":len(links),"nodes":nodes,"links":links,"groups":[],"config":{},"extra":{"generation_ready":False,"h3_example":"Current interview and independent three-stage wiring. Supply your writer models, CLIP/VAEs, and generation/sampling chain. Not one-click generation."},"version":.4}
    for node in nodes:
        if node["type"] in mappings:
            actual=mappings[node["type"]];declared=actual.INPUT_TYPES()
            inputs={key:entry[0] for section in ("required","optional") for key,entry in declared.get(section,{}).items()}
            assert node["outputs"]==[{"name":name,"type":kind,"links":row["links"]} for row,(name,kind) in zip(node["outputs"],zip(actual.RETURN_NAMES,actual.RETURN_TYPES))]
            assert all(row["name"] in inputs and inputs[row["name"]]==row["type"] for row in node["inputs"])
        if node["type"]==t8["node_id"]:
            inputs={row["name"]:row for row in t8["inputs"]}
            for row in node["inputs"]:
                if '.' in row["name"]:
                    bank,child=row["name"].split('.');template=inputs[bank]["autogrow"]
                    assert child.startswith(template["prefix"]) and 0<=int(child[len(template["prefix"]):])<template["max"]
                else:assert row["name"] in inputs and inputs[row["name"]]["type"]==row["type"]
    api={str(node["id"]):{"class_type":node["type"],"inputs":{row["name"]:[str(links[row["link"]-1][1]),links[row["link"]-1][2]] for row in node["inputs"] if row["link"]}} for node in nodes}
    for target in ('7','8'):api[target]['inputs'].update(task_type='auto',audio_mode='native',add_source_as_reference=True,prompt_primary_audio_ordinal=0)
    api['6']['inputs']['expression']=EXPRESSION
    # The copied temporary package is already cleaned; use its real retained function.
    validate = mappings['ZVH3InterviewFormV2'].build.__globals__['validate_reference_hub_wiring']
    wiring=validate(api,'3');assert not wiring['errors'],wiring['errors']
    text=json.dumps(graph)
    for forbidden in ("originals/","source_handle","asset_id",".gguf",".safetensors","ZFI","x_v1"):
        assert forbidden not in text,forbidden
    return graph,{"verified_classes":[row["type"] for row in nodes],"copied_plugin_classes":[key for key in mappings if key in {row["type"] for row in nodes}],"static_real_core_T8_schema":schemas,"media_wires_per_conditioning":22,"actual_plugin_input_output_and_T8_autogrow_checked":True,"backend_fixed_hub_wiring_errors":wiring['errors'],"no_test_stub_serialized":True,"generation_ready":False,"needs":"writer backend, CLIP, video/audio VAEs, models and sampling/upscale chain"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--workflow",type=Path,required=True);parser.add_argument("--output-dir",type=Path,required=True);parser.add_argument("--copy-to",type=Path);args=parser.parse_args(argv)
    try:
        workflow, output_dir, targets, copy_to = preflight(args.workflow, args.output_dir, args.copy_to)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    value=manifest()
    audit=audit_workflow(workflow)
    with tempfile.TemporaryDirectory(prefix="h3-v2-03-copy-") as temporary:
        target=copy_runtime(copy_to or Path(temporary)/"ZF-ComfyUI-PromptDirector")
        registration,mappings=copied_registration(target)
        registration["file_hashes_match"]=all(sha(target/row["path"])==row["sha256"] for row in value["files"])
        assert registration["file_hashes_match"]
        graph,proof=skeleton(mappings)
    # Recheck after computation; reserve every target exclusively before writing payloads.
    safe_directory(output_dir)
    for path in targets:
        new_target(path)
    output_dir.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        handles = [stack.enter_context(path.open("xb")) for path in targets]
        for handle, payload in zip(handles, (value, audit, graph, proof, registration)):
            handle.write(json.dumps(payload,ensure_ascii=False,indent=2).encode("utf-8"))
    print(f"H3_V2_03_AUDIT_OK workflow={audit['node_count']}/{audit['link_count']} errors={len(audit['structural_errors'])} unresolved={audit['unresolved_source_classes']}; runtime={len(value['files'])} copy registration passed; neutral graph={len(graph['nodes'])}/{len(graph['links'])}; no GPU/service start")


if __name__=="__main__":main()
