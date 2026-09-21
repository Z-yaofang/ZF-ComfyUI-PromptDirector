import assert from "node:assert/strict";
import test from "node:test";
import {defaultSettings,parseSettings,readWorkflowFps} from "../web/animate_video_core.mjs";
test("fixed seams and a global mask toggle",()=>assert.deepEqual(defaultSettings(),{schema_version:1,seam_mode:"hard_cut",mask_enabled:false,mask_tasks:{}}));
test("fixed continuation roundtrip",()=>assert.deepEqual(parseSettings('{"schema_version":1,"seam_mode":"continuation_21"}'),{...defaultSettings(),seam_mode:"continuation_21"}));
test("global toggle and clip-bound fields survive save and reopen",()=>{
    const value={...defaultSettings(),mask_enabled:true,mask_tasks:{clip1:{asset_id:"asset1",prompt:"shirt",source_frame:0}}};
    assert.deepEqual(parseSettings(JSON.stringify(value)),value);
});
test("malformed or old controls are not migrated",()=>{for(const text of ["bad","[]","null",'{"overlap_frames":21}','{"schema_version":2,"seam_mode":"hard_cut"}','{"schema_version":1,"seam_mode":"hard_cut","fps":24}'])assert.deepEqual(parseSettings(text),defaultSettings());});
test("unlinked fps uses no frontend override",()=>assert.deepEqual(readWorkflowFps({inputs:[]}),{fps:null,linked:false}));
test("direct original fps constant is readable",()=>assert.deepEqual(readWorkflowFps({inputs:[{name:'fps',link:1}],getInputNode:()=>({widgets:[{name:'value',value:30000/1001}]})}),{fps:30000/1001,linked:true}));
test("original Get/Set fps bus is readable",()=>{
    const constant={type:'FloatConstant',widgets:[{name:'value',value:30}]};
    const set={type:'SetNode',widgets:[{value:'fps'}],getInputNode:()=>constant};
    const get={type:'GetNode',widgets:[{value:'fps'}]};
    assert.deepEqual(readWorkflowFps({inputs:[{name:'fps',link:1}],getInputNode:()=>get,graph:{_nodes:[get,set,constant]}}),{fps:30,linked:true});
});
test("dynamic computed fps is not guessed from its first input",()=>assert.deepEqual(readWorkflowFps({inputs:[{name:'fps',link:1}],getInputNode:()=>({type:'MathExpression',inputs:[{link:2}],getInputNode:()=>({widgets:[{name:'value',value:10}]})})}),{fps:null,linked:true}));
