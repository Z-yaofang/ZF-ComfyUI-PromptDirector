import assert from "node:assert/strict";
import test from "node:test";
import {addSegment,defaultSettings,manual} from "../web/long_video_core.mjs";

test("new H3 segment desks use generated duration, not source duration",()=>{
    const settings=defaultSettings();
    assert.equal(settings.mode,"generation_count");
    assert.equal(settings.segment_frames,360);
    assert.equal(settings.range_end_frame,null);
});

test("an existing source layout can be converted without losing its segment windows",()=>{
    const source={...defaultSettings(),mode:"source_manual",segment_frames:180};
    const plan={mode:"source_manual",range_start_frame:0,effective_overlap_frames:39,segments:[
        {segment_id:"a",start_frame:0,end_frame:180},
        {segment_id:"b",start_frame:141,end_frame:321},
    ]};
    const converted=manual(source,plan,"generation_manual");
    assert.equal(converted.mode,"generation_manual");
    assert.deepEqual(converted.segments,[
        {segment_id:"a",start_frame:0,end_frame:180},
        {segment_id:"b",start_frame:141,end_frame:321},
    ]);
    const extended=addSegment(converted,{...plan,mode:"generation_manual"},()=>"c");
    assert.equal(extended.mode,"generation_manual");
    assert.deepEqual(extended.segments.at(-1),{segment_id:"c",start_frame:282,end_frame:462});
});
