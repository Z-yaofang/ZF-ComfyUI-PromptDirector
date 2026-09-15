import { app } from "/scripts/app.js";
const api = globalThis.comfyAPI?.api?.api ?? {
  apiURL: path => path,
  fetchApi: (path, options) => fetch(path, options),
};
import { pinDOMWidgetFullWidth } from "./dom_widget_layout.mjs";
import { mountPresets } from "./h3_interview_presets.mjs";
import { sampleClipPeaks } from "./media_evidence_core.mjs";

const NAME = "ZVH3InterviewForm";
const VERSION = "zv-h3-interview-v2";
const PLAN_API = "/zf-prompt-director/h3-interview/plan";
const PREVIEW_ROOT = "/zf-media-evidence";
const H3_CONDITIONING = "MiniMaxH3AudioConditioningT8";
const STAGE1_NODE = "ZFPromptDirectorLocalLLM";
const H3_REFERENCE_HUB = "ZVH3ReferenceOutlet";
// The fixed outlet is an append-only physical socket contract. T8's dynamic
// groups are zero-based even though the outlet labels are one-based.
const H3_HUB_CONDITIONING_INPUTS = [
  ["first_frame", 0], ["last_frame", 1],
  ...Array.from({ length: 9 }, (_, index) => [`ref_images.ref_image_${index}`, 2 + index]),
  ...Array.from({ length: 3 }, (_, index) => [`ref_videos.ref_video_${index}`, 11 + index]),
  ...Array.from({ length: 3 }, (_, index) => [`ref_video_audios.ref_video_audio_${index}`, 14 + index]),
  ["drive_audio", 17], ["final_audio", 18],
  ...Array.from({ length: 3 }, (_, index) => [`ref_audios.ref_audio_${index}`, 19 + index]),
];
const H3_HUB_STAGE1_INPUTS = [
  ...Array.from({ length: 11 }, (_, index) => [`image${index + 1}`, index]),
  ["video_frames", 11], ["video_frames2", 12], ["video_frames3", 13],
];
const OUTLET_KIND = {
  ZVPictureOutlet: "picture",
  ZVVideoOutlet: "video",
  ZVAudioOutlet: "audio",
};
const KIND_LABEL = { picture: "Picture", video: "Video", audio: "Audio" };

const style = document.createElement("link");
style.rel = "stylesheet";
style.href = new URL("./h3_interview.css", import.meta.url).href;
document.head.append(style);

const RECIPES = [
  ["custom", "用户编辑"],
  ["performance_transfer", "图定人物 + 视频动作 + 音频台词"],
  ["t2va", "纯文本生成"],
  ["i2va", "首帧生视频"],
  ["fl2va", "首尾帧生视频"],
  ["l2va", "尾帧生视频"],
  ["video_edit", "原视频编辑"],
  ["video_continue", "视频续写"],
];


const ROLES = {
  picture: [
    ["subject_identity", "主体身份/外观"], ["first_frame", "首帧"], ["last_frame", "尾帧"],
    ["keyframe", "关键帧"], ["composition_reference", "构图参考"], ["style_reference", "风格参考"], ["storyboard", "分镜参考"],
  ],
  video: [
    ["motion_reference", "动作参考"], ["camera_reference", "运镜参考"], ["structure_reference", "节奏/结构参考"],
    ["video_edit", "原视频编辑"], ["video_continue", "视频续写"], ["subject_identity", "主体身份/外观"],
  ],
  audio: [
    ["speech_lipsync", "台词与口型"], ["audio_reuse", "直接复用音轨"], ["voice_reference", "音色/说话方式"],
    ["music_reference", "音乐参考"], ["sound_reference", "声音参考"],
  ],
};

const FIELD_GROUPS = [
  ["创作要求", [
    ["intent", "你想生成什么？素材之间是什么关系？", "例如：图一的人物模仿视频一的舞蹈，并按音频一说话。", true],
    ["style", "画面风格 / 质感", "没有明确要求可留空"],
    ["must_keep", "必须保留", "身份、服装、动作次序、对白等"],
    ["must_change", "必须改变", "相对参考素材要改变什么"],
    ["ending", "结尾必须到达", "最终姿势、物体状态或画面落点"],
    ["forbidden", "不能出现 / 避免", "禁止新增、身份边界、连续性禁区"],
  ]],
  ["表演与镜头", [
    ["performance", "动作与表演", "节奏、力度、表情、视线、人物关系"],
    ["camera", "镜头与剪辑", "景别、机位、运镜、是否单镜头"],
    ["dialogue", "对白 / 歌词原文", "保持原语言；如果完全取自音频，可写“严格按 Audio 1”"],
    ["visible_text", "画面可见文字原文", "招牌、字幕或屏幕文字；没有可留空"],
  ]],
  ["声音", [
    ["soundscape", "环境声 / 动作声", "环境、脚步、碰撞、呼吸等；完全静音需明确写"],
    ["music", "观众可听、角色听不到的配乐", "没有配乐可写 N/A 或留空"],
  ]],
];

const emptyState = () => ({
  schema_version: VERSION,
  recipe: "custom",
  mode: "auto",
  director_focus: "balanced",
  media_roles: {},
  media_purposes: {}, bindings: {}, alignment: null, migration: null, reference_texts: {}, preset_pending: [],
  reference_detection: null,
  intent: "", style: "", must_keep: "", must_change: "", ending: "", forbidden: "",
  performance: "", camera: "", dialogue: "", visible_text: "", soundscape: "", music: "",
});

const clone = value => structuredClone(value);
const el = (tag, className = "", text) => {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

function safeDetection(value) {
  if (!value || value.version !== 1 || !["pictures", "videos", "audios"].every(key => Array.isArray(value[key]))) return null;
  const clean = (records, plural) => records.map(record => {
    if (!record || typeof record.item_id !== "string" || !record.item_id) return null;
    const fallback = plural === "audios" ? "standalone" : "reference";
    return {
      item_id: record.item_id,
      source_kind: String(record.source_kind || ""),
      source_port: typeof record.source_port === "number" ? record.source_port : String(record.source_port || ""),
      origin: String(record.origin || fallback),
    };
  }).filter(Boolean);
  const stage = value.stage1 && typeof value.stage1 === "object" ? value.stage1 : {};
  return {
    version: 1,
    pictures: clean(value.pictures, "pictures"),
    videos: clean(value.videos, "videos"),
    audios: clean(value.audios, "audios"),
    stage1: {
      pictures: Array.isArray(stage.pictures) ? stage.pictures.filter(id => typeof id === "string") : [],
      videos: Array.isArray(stage.videos) ? stage.videos.filter(id => typeof id === "string") : [],
    },
    conditioning_count: Math.max(0, Math.trunc(Number(value.conditioning_count) || 0)),
  };
}

function migrateV1(value) {
  const state = clone(value);
  if (state.schema_version !== "zv-h3-interview-v1") return state;
  state.schema_version = VERSION;
  const bindings = {};
  for (const [plural, fallback] of [["pictures", "ref_images"], ["videos", "ref_videos"], ["audios", "ref_audios"]]) {
    for (const entry of state.reference_detection?.[plural] || []) {
      if (!entry || entry.origin === "video_soundtrack" || typeof entry.item_id !== "string") continue;
      const bank = ["first_frame", "last_frame", "drive_audio"].includes(entry.origin) ? entry.origin : fallback;
      const binding = bindings[entry.item_id] ||= { item_id: entry.item_id, participates: true, banks: [] };
      if (!binding.banks.includes(bank)) binding.banks.push(bank);
    }
  }
  for (const [id, assigned] of Object.entries(state.media_roles || {})) {
    const roles = typeof assigned === "string" ? [assigned] : assigned;
    if (!roles?.length || !Array.isArray(roles)) continue;
    const anchors = ["first_frame", "last_frame"].filter(bank => roles.includes(bank));
    if (state.reference_detection) continue;
    const banks = anchors.length ? [...anchors] : ["reference"];
    if (anchors.length && roles.some(role => !["first_frame", "last_frame"].includes(role))) banks.push("ref_images");
    bindings[id] = { item_id: id, participates: true, banks };
  }
  const migration = { from: "zv-h3-interview-v1" };
  if (Object.keys(bindings).length || state.reference_detection) { migration.freeze_pending = true; if (!state.reference_detection) migration.legacy_drive_pending = true; }
  return { ...state, bindings, media_purposes: {}, alignment: null, migration };
}

function safeState(value) {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value || "{}") : clone(value || {});
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    const state = { ...emptyState(), ...migrateV1(parsed) };
    if (state.schema_version !== VERSION) throw new Error("采访版本不受支持");
    state.media_roles = state.media_roles && typeof state.media_roles === "object" && !Array.isArray(state.media_roles) ? state.media_roles : {};
    for (const [id, roles] of Object.entries(state.media_roles)) state.media_roles[id] = [...new Set(Array.isArray(roles) ? roles.filter(x => typeof x === "string") : typeof roles === "string" ? [roles] : [])];
    state.media_purposes ||= {}; state.bindings ||= {};
    if (!Array.isArray(state.preset_pending)) throw new Error("待绑定槽位无效");
    state.reference_detection = safeDetection(state.reference_detection);
    return state;
  } catch {
    return emptyState();
  }
}

const nodeType = node => node?.comfyClass || node?.type || node?.constructor?.comfyClass || "";
const previewURL = (asset, variant) => api.apiURL(`${PREVIEW_ROOT}/preview?source=${encodeURIComponent(asset.source_handle)}&variant=${variant}`);
const widgetValue = (node, name, fallback = undefined) => node?.widgets?.find(widget => widget.name === name)?.value ?? fallback;

function graphNodes(graph) {
  if (Array.isArray(graph?._nodes)) return graph._nodes;
  if (graph?._nodes_by_id instanceof Map) return [...graph._nodes_by_id.values()];
  return Object.values(graph?._nodes_by_id || {});
}

function inputSource(node, inputName) {
  const input = node?.inputs?.find(row => row.name === inputName);
  let link = graphLink(node?.graph, input?.link);
  let source = link ? node.graph?.getNodeById?.(link.origin_id) : null;
  let outputSlot = link?.origin_slot;
  const route = [];
  const visited = new Set();
  while (source?.isVirtualNode && typeof source.resolveVirtualOutput === "function" && !visited.has(source.id)) {
    visited.add(source.id);
    const channel = source.outputs?.[outputSlot]?.label || source.outputs?.[outputSlot]?.name || String(Number(outputSlot) + 1);
    route.push(`${source.title || nodeType(source) || "转接"}「${channel}」`);
    const resolved = source.resolveVirtualOutput(outputSlot);
    source = resolved?.node || null;
    outputSlot = resolved?.slot;
  }
  return source ? { node: source, slot: Number(outputSlot), route } : null;
}

function dependsOn(candidate, ancestorId) {
  const queue = [candidate];
  const visited = new Set();
  while (queue.length) {
    const current = queue.shift();
    if (!current || visited.has(current.id)) continue;
    visited.add(current.id);
    if (String(current.id) === String(ancestorId)) return true;
    for (const input of current.inputs || []) {
      const link = graphLink(current.graph, input.link);
      const source = link ? current.graph?.getNodeById?.(link.origin_id) : null;
      if (source && !visited.has(source.id)) queue.push(source);
    }
  }
  return false;
}

function distanceToOutput(candidate, ancestorId, outputSlot) {
  const queue = [[candidate, 0]];
  const visited = new Set();
  while (queue.length) {
    const [current, distance] = queue.shift();
    if (!current || visited.has(current.id)) continue;
    visited.add(current.id);
    for (const input of current.inputs || []) {
      const link = graphLink(current.graph, input.link);
      if (!link) continue;
      if (String(link.origin_id) === String(ancestorId) && Number(link.origin_slot) === Number(outputSlot)) return distance + 1;
      const source = current.graph?.getNodeById?.(link.origin_id);
      if (source && !visited.has(source.id)) queue.push([source, distance + 1]);
    }
  }
  return null;
}

function outletRecord(endpoint, expected, origin, inputName, errors) {
  if (!endpoint) return null;
  const type = nodeType(endpoint.node), sourceKind = OUTLET_KIND[type];
  if (!sourceKind) {
    errors.push(`${inputName} 来自“${endpoint.node.title || type || "未知节点"}”，不是素材台出口`);
    return null;
  }
  const expectedKinds = Array.isArray(expected) ? expected : [expected];
  if (!expectedKinds.includes(sourceKind)) {
    errors.push(`${inputName} 接入了 ${KIND_LABEL[sourceKind]} 出口，类型应为 ${expectedKinds.map(kind => KIND_LABEL[kind]).join("/")}`);
    return null;
  }
  const wantedSlot = sourceKind === "video" && (origin === "video_soundtrack" || origin === "drive_audio") ? 1 : 0;
  if (endpoint.slot !== wantedSlot) {
    errors.push(`${inputName} 使用了“${endpoint.node.outputs?.[endpoint.slot]?.name || endpoint.slot}”输出，线路类型不正确`);
    return null;
  }
  const idName = sourceKind === "picture" ? "item_id" : "clip_id";
  const itemId = String(widgetValue(endpoint.node, idName, "") || "").trim();
  if (!itemId) {
    errors.push(`${inputName} 的素材出口尚未绑定稳定 ID`);
    return null;
  }
  return {
    item_id: itemId,
    source_kind: sourceKind,
    source_port: endpoint.node.outputs?.[endpoint.slot]?.name || (wantedSlot ? "original_audio" : sourceKind === "video" ? "frames" : sourceKind === "picture" ? "image" : "audio"),
    origin,
    route: endpoint.route,
    input_name: inputName,
    outlet_title: endpoint.node.title || type,
  };
}

const suffix = name => Number(String(name).match(/_(\d+)$/)?.[1] ?? -1);
const inputNames = (node, pattern) => (node.inputs || []).map(input => input.name).filter(name => pattern.test(name)).sort((a, b) => suffix(a) - suffix(b));

function scanConditioning(node) {
  const errors = [];
  const pictures = [];
  for (const [name, origin] of [["first_frame", "first_frame"], ["last_frame", "last_frame"]]) {
    const endpoint = inputSource(node, name);
    const record = outletRecord(endpoint, "picture", origin, name, errors);
    if (record) pictures.push(record);
  }
  for (const name of inputNames(node, /^ref_images\.ref_image_\d+$/)) {
    const record = outletRecord(inputSource(node, name), "picture", "reference", name, errors);
    if (record) pictures.push(record);
  }

  const videos = [];
  const videoBySocket = new Map();
  for (const name of inputNames(node, /^ref_videos\.ref_video_\d+$/)) {
    const endpoint = inputSource(node, name);
    const record = outletRecord(endpoint, "video", "reference", name, errors);
    if (record) { videos.push(record); videoBySocket.set(suffix(name), record); }
  }

  const audios = [];
  for (const [socket, video] of videoBySocket) {
    const name = `ref_video_audios.ref_video_audio_${socket}`;
    const endpoint = inputSource(node, name);
    if (!endpoint) continue;
    const record = outletRecord(endpoint, "video", "video_soundtrack", name, errors);
    if (record && record.item_id !== video.item_id) errors.push(`${name} 与同序视频不是同一个素材出口`);
    else if (record) audios.push(record);
  }
  for (const name of inputNames(node, /^ref_video_audios\.ref_video_audio_\d+$/)) {
    const socket = suffix(name);
    if (inputSource(node, name) && !videoBySocket.has(socket)) errors.push(`${name} 已接线，但同序参考视频为空`);
  }

  const drive = inputSource(node, "drive_audio");
  const addDrive = ![false, 0, "false", "0"].includes(widgetValue(node, "add_source_as_reference", true));
  if (drive && addDrive) {
    const record = outletRecord(drive, ["audio", "video"], "drive_audio", "drive_audio", errors);
    if (record) audios.push(record);
  }
  for (const name of inputNames(node, /^ref_audios\.ref_audio_\d+$/)) {
    const record = outletRecord(inputSource(node, name), "audio", "standalone", name, errors);
    if (record) audios.push(record);
  }
  return { pictures, videos, audios, errors, title: node.title || `H3 #${node.id}` };
}

function scanStage1(node) {
  const errors = [];
  const pictures = [];
  const videos = [];
  for (const name of (node.inputs || []).map(input => input.name).filter(name => /^image(?:[1-9]|1[01])$/.test(name)).sort((a, b) => Number(a.slice(5)) - Number(b.slice(5)))) {
    const record = outletRecord(inputSource(node, name), "picture", "stage1", name, errors);
    if (record) pictures.push(record.item_id);
  }
  const videoNames = ["video_frames", "video_frames2", "video_frames3"];
  for (const name of videoNames) {
    const record = outletRecord(inputSource(node, name), "video", "stage1", name, errors);
    if (record) videos.push(record.item_id);
  }
  return { pictures, videos, errors, title: node.title || `Stage① #${node.id}` };
}

function compactRecord(record) {
  return { item_id: record.item_id, source_kind: record.source_kind, source_port: record.source_port, origin: record.origin };
}

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const same = (left, right) => JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
const BANKS = { picture: [["ref_images", "参考图片"], ["first_frame", "首帧"], ["last_frame", "尾帧"]], video: [["ref_videos", "参考视频"]], audio: [["ref_audios", "独立参考音频"], ["drive_audio", "驱动音频"]] };
function bindingFor(state, row) {
  const binding = clone(state.bindings?.[row.id] || { item_id: row.id, participates: row.enabled && !row.linked && !state.migration?.freeze_pending, banks: [BANKS[row.kind][0][0]] });
  if (state.migration && same(binding.banks, ["reference"])) binding.banks = [BANKS[row.kind][0][0]];
  return binding;
}
function mechanicalContext(state, project, rows) {
  return { version: 1, items: rows.map(row => ({
    item_id: row.id, kind: row.kind, asset_id: row.trackItem.asset_id,
    source_handle: row.asset?.source_handle ?? null, probe: clone(row.asset?.probe || {}),
    enabled: row.enabled, in_window: row.inWindow, linked_video_clip_id: row.linkedVideoId,
    source_audio_enabled: !!row.trackItem.source_audio_enabled, audio_link_id: row.trackItem.audio_link_id ?? null,
    timeline_in_seconds: row.trackItem.timeline_in_seconds ?? null, timeline_out_seconds: row.trackItem.timeline_out_seconds ?? null,
    source_in_seconds: row.trackItem.source_in_seconds ?? null, source_out_seconds: row.trackItem.source_out_seconds ?? null,
    binding: bindingFor(state, row),
  })), window: clone(project?.processing_window || {}), canvas: clone(project?.output_canvas ?? null), preset: clone(project?.processing_preset || {}) };
}

function isFixedHubSnapshot(snapshot) {
  if (!snapshot) return false;
  const records = [...(snapshot.pictures || []), ...(snapshot.videos || []), ...(snapshot.audios || [])];
  // An empty snapshot carries no source-kind marker and has no material route
  // whose ordering could drift. More importantly, do not reinterpret a saved
  // legacy-outlet snapshot merely because a fixed hub was later added nearby.
  return records.length > 0 && records.every(record => record.source_kind === H3_REFERENCE_HUB);
}

function plannedReferenceSnapshot(rows, candidate, conditioningCount = 0) {
  const active = kind => rows.filter(row => row.kind === kind && bindingFor(candidate, row).participates);
  const pictures = active("picture"), videos = active("video"), independent = active("audio").filter(row => !row.linked);
  const records = { pictures: [], videos: [], audios: [] };
  const record = (row, port, origin) => ({ item_id: row.id, source_kind: H3_REFERENCE_HUB, source_port: port, origin });
  for (const bank of ["first_frame", "last_frame", "ref_images"]) {
    let ordinal = 0;
    pictures.filter(row => bindingFor(candidate, row).banks.includes(bank)).forEach(row => records.pictures.push(record(row, bank === "ref_images" ? `ref_image_${++ordinal}` : bank, bank === "ref_images" ? "reference" : bank)));
  }
  videos.filter(row => bindingFor(candidate, row).banks.includes("ref_videos")).forEach((row, index) => {
    records.videos.push(record(row, `ref_video_${index + 1}`, "reference"));
    if (row.trackItem.source_audio_enabled && row.trackItem.audio_link_id) records.audios.push(record(row, `ref_video_audio_${index + 1}`, "video_soundtrack"));
  });
  for (const bank of ["drive_audio", "ref_audios"]) {
    let ordinal = 0;
    independent.filter(row => bindingFor(candidate, row).banks.includes(bank)).forEach(row => records.audios.push(record(row, bank === "ref_audios" ? `ref_audio_${++ordinal}` : bank, bank === "ref_audios" ? "standalone" : bank)));
  }
  return { version: 1, ...records, stage1: { pictures: records.pictures.map(row => row.item_id), videos: records.videos.map(row => row.item_id) }, conditioning_count: conditioningCount };
}

function connectedReferenceHubs(interviewNode) {
  return graphNodes(interviewNode?.graph).filter(node => {
    if (nodeType(node) !== H3_REFERENCE_HUB) return false;
    const endpoint = inputSource(node, "reference_plan");
    return endpoint && String(endpoint.node?.id) === String(interviewNode.id) && endpoint.slot === 8;
  });
}

function fixedHubLinkError(target, inputName, hub, outputSlot) {
  const endpoint = inputSource(target, inputName);
  if (endpoint && String(endpoint.node?.id) === String(hub.id) && endpoint.slot === outputSlot) return null;
  const expected = hub.outputs?.[outputSlot]?.name || hub.outputs?.[outputSlot]?.label || `输出 ${outputSlot}`;
  const actual = endpoint
    ? `“${endpoint.node?.title || nodeType(endpoint.node) || endpoint.node?.id}”的输出 ${endpoint.slot}`
    : "未连接";
  return `${target.title || nodeType(target) || `节点 #${target.id}`}：${inputName} 应连接固定出口“${expected}”（槽位 ${outputSlot}），当前为${actual}`;
}

function validateFixedHubWiring(interviewNode, hubs, conditionings) {
  const graph = interviewNode?.graph;
  const errors = [];
  if (hubs.length !== 1) {
    errors.push(`本采访表必须连接且只连接一个 H3 固定素材出口；当前 ${hubs.length} 个`);
    return { errors, stageNodes: [] };
  }
  const hub = hubs[0];
  if (!conditionings.length) errors.push("固定素材出口尚未接入使用本采访表的 H3 Conditioning");
  for (const conditioning of conditionings) {
    for (const [inputName, outputSlot] of H3_HUB_CONDITIONING_INPUTS) {
      const message = fixedHubLinkError(conditioning, inputName, hub, outputSlot);
      if (message) errors.push(message);
    }
    const addSource = widgetValue(conditioning, "add_source_as_reference", undefined);
    const addSourceIsTrue = addSource === true || addSource === 1 || (typeof addSource === "string" && addSource.trim().toLowerCase() === "true");
    if (!addSourceIsTrue) errors.push(`${conditioning.title || `H3 #${conditioning.id}`}：固定出口要求 add_source_as_reference=true，才能保持采访表的 <Audio N> 编号`);
    const primaryAudio = widgetValue(conditioning, "prompt_primary_audio_ordinal", undefined);
    if (!(primaryAudio === 0 || primaryAudio === "0")) errors.push(`${conditioning.title || `H3 #${conditioning.id}`}：固定出口要求 prompt_primary_audio_ordinal=0，避免节点重新排列 <Audio N>`);
  }

  const stageCandidates = graphNodes(graph)
    .filter(node => nodeType(node) === STAGE1_NODE)
    .map(node => ({ node, distance: distanceToOutput(node, interviewNode.id, 1) }))
    .filter(row => row.distance != null);
  const nearest = stageCandidates.length ? Math.min(...stageCandidates.map(row => row.distance)) : null;
  const stageNodes = stageCandidates.filter(row => row.distance === nearest).map(row => row.node);
  if (!stageNodes.length) errors.push("固定素材出口没有找到使用本采访表的 Stage① 多模态节点");
  for (const stage of stageNodes) {
    for (const [inputName, outputSlot] of H3_HUB_STAGE1_INPUTS) {
      const message = fixedHubLinkError(stage, inputName, hub, outputSlot);
      if (message) errors.push(message);
    }
  }
  return { errors, stageNodes };
}

function detectReferenceGraph(interviewNode, project, rows, candidate = emptyState()) {
  const graph = interviewNode?.graph;
  const errors = [], warnings = [];
  const conditionings = graphNodes(graph).filter(node => nodeType(node) === H3_CONDITIONING && dependsOn(node, interviewNode.id));
  const hubs = connectedReferenceHubs(interviewNode);
  if (hubs.length) {
    if (!project) errors.push("素材台工程尚未就绪");
    const physical = validateFixedHubWiring(interviewNode, hubs, conditionings);
    errors.push(...physical.errors);
    const snapshot = errors.length ? null : plannedReferenceSnapshot(rows, candidate, conditionings.length);
    return {
      snapshot, errors, warnings,
      details: {
        mode: "fixed_h3_reference_hub",
        hubs: hubs.map(node => node.id),
        conditionings: conditionings.map(node => node.id),
        stage1: physical.stageNodes.map(node => node.id),
      },
    };
  }
  const scans = conditionings.map(scanConditioning);
  scans.forEach(scan => errors.push(...scan.errors.map(message => `${scan.title}：${message}`)));
  if (!scans.length) errors.push("没有找到使用本采访表提示词的 H3 Conditioning");

  const base = scans[0] || { pictures: [], videos: [], audios: [] };
  const signature = scan => ({ pictures: scan.pictures.map(compactRecord), videos: scan.videos.map(compactRecord), audios: scan.audios.map(compactRecord) });
  for (const scan of scans.slice(1)) if (!same(signature(base), signature(scan))) errors.push(`${base.title} 与 ${scan.title} 的 LOW/HIGH 参考素材或顺序不一致`);

  for (const [kind, records] of [["Picture", base.pictures], ["Video", base.videos], ["Audio", base.audios]]) {
    const duplicate = records.map(record => record.item_id).find((id, index, all) => all.indexOf(id) !== index);
    if (duplicate) errors.push(`${kind} 中同一素材被重复接入：${duplicate}`);
  }
  const known = new Set(rows.map(row => row.id));
  for (const record of [...base.pictures, ...base.videos, ...base.audios]) {
    if (!known.has(record.item_id) && record.origin !== "video_soundtrack") errors.push(`线路中的稳定 ID ${record.item_id} 不在当前素材台轨道`);
  }

  const stageCandidates = graphNodes(graph)
    .filter(node => nodeType(node) === STAGE1_NODE)
    .map(node => ({ node, distance: distanceToOutput(node, interviewNode.id, 1) }))
    .filter(row => row.distance != null);
  const nearestStage = stageCandidates.length ? Math.min(...stageCandidates.map(row => row.distance)) : null;
  const stageNodes = stageCandidates.filter(row => row.distance === nearestStage).map(row => row.node);
  const stageScans = stageNodes.map(scanStage1);
  stageScans.forEach(scan => errors.push(...scan.errors.map(message => `${scan.title}：${message}`)));
  const expectedStage = { pictures: base.pictures.map(record => record.item_id), videos: base.videos.map(record => record.item_id) };
  if ((expectedStage.pictures.length || expectedStage.videos.length) && !stageScans.length) errors.push("H3 已接视觉素材，但没有找到使用本采访表的 Stage① 多模态节点");
  for (const scan of stageScans) if (!same(expectedStage, { pictures: scan.pictures, videos: scan.videos })) errors.push(`${scan.title} 与 H3 的 Picture/Video 顺序不一致`);

  const actualRoleIds = new Set([
    ...base.pictures.map(record => record.item_id),
    ...base.videos.map(record => record.item_id),
    ...base.audios.filter(record => record.origin !== "video_soundtrack").map(record => record.item_id),
  ]);
  const selectedIds = new Set(rows.filter(row => !row.linked && candidate.media_roles?.[row.id]?.length).map(row => row.id));
  for (const id of selectedIds) if (!actualRoleIds.has(id)) warnings.push(`已填写用途的素材未实际接入 H3：${rows.find(row => row.id === id)?.label || id}`);
  for (const id of actualRoleIds) if (!selectedIds.has(id)) warnings.push(`已接入 H3 的素材尚未填写用途：${rows.find(row => row.id === id)?.label || id}`);

  const snapshot = errors.length ? null : {
    version: 1,
    pictures: base.pictures.map(compactRecord),
    videos: base.videos.map(compactRecord),
    audios: base.audios.map(compactRecord),
    stage1: stageScans[0] ? { pictures: stageScans[0].pictures, videos: stageScans[0].videos } : { pictures: [], videos: [] },
    conditioning_count: scans.length,
  };
  return { snapshot, errors, warnings, details: { pictures: base.pictures, videos: base.videos, audios: base.audios } };
}

function graphLink(graph, linkId) {
  if (!graph || linkId == null) return null;
  if (typeof graph.getLink === "function") return graph.getLink(linkId);
  if (graph.links instanceof Map) return graph.links.get(linkId) || null;
  return graph.links?.[linkId] || null;
}

function sourceForMediaInput(node) {
  const slot = node.inputs?.findIndex(input => input.name === "media_project") ?? -1;
  let link = graphLink(node.graph, node.inputs?.[slot]?.link);
  let source = link ? node.graph?.getNodeById?.(link.origin_id) : null;
  let outputSlot = link?.origin_slot;
  const visited = new Set();
  while (source?.isVirtualNode && typeof source.resolveVirtualOutput === "function" && !visited.has(source.id)) {
    visited.add(source.id);
    const resolved = source.resolveVirtualOutput(outputSlot);
    source = resolved?.node || null;
    outputSlot = resolved?.slot;
  }
  return source;
}

function readProject(node) {
  const source = sourceForMediaInput(node);
  if (!source) return { project: null, message: "请把素材台 media_project 接到本节点" };
  const type = source.comfyClass || source.type || source.constructor?.comfyClass;
  if (type !== "ZVUniversalMediaEvidenceDesk") return { project: null, message: "media_project 必须来自 ZV 通用素材取证台（可经过 ZFI）" };
  try {
    const value = source.zfMediaDesk?.getProject?.() || JSON.parse(source.widgets?.find(widget => widget.name === "project_data")?.value || "null");
    if (!value?.assets || !value?.processing_window) throw new Error();
    const project = clone(value);
    const window = project.processing_window, first = Math.floor(Number(window.start_seconds) * Number(window.fps) + .5), last = Math.floor(Number(window.end_seconds) * Number(window.fps) + .5);
    project.processing_window = {...window, start_frame: first, end_frame: last, frame_count: Math.max(0, last-first)};
    const widthLink = source.inputs?.find(input => input.name === "width")?.link, heightLink = source.inputs?.find(input => input.name === "height")?.link;
    const widthValue = widthLink != null ? staticDimension(inputSource(source, "width")) : widgetValue(source, "width");
    const heightValue = heightLink != null ? staticDimension(inputSource(source, "height")) : widgetValue(source, "height");
    if (widthValue !== undefined || heightValue !== undefined || widthLink != null || heightLink != null) {
      if (![widthValue, heightValue].every(value => Number.isInteger(value) && value >= 32 && value <= 16384 && value % 32 === 0) || widthValue * heightValue > 50000000) throw new Error("生成画布尚未核实：素材台宽高必须成对连接有效静态尺寸；或取消两条尺寸连接后重新检测");
      project.output_canvas = {width: widthValue, height: heightValue};
    }
    return { project, message: "" };
  } catch (error) {
    return { project: null, message: error.message || "素材台工程尚未恢复完成" };
  }
}

function staticDimension(endpoint) {
  if (!endpoint) throw new Error("生成画布尚未核实：无法读取尺寸来源，请成对连接静态宽高");
  const {node, slot} = endpoint, type = nodeType(node);
  if (["PrimitiveInt", "INTConstant"].includes(type) && slot === 0) {
    const value = widgetValue(node, "value");
    if (Number.isInteger(value) && node.inputs?.find(input => input.name === "value")?.link == null) return value;
  }
  if (type === "ResolutionSelector" && [0,1].includes(slot)) {
    if (["aspect_ratio", "megapixels", "multiple"].some(name => node.inputs?.find(input => input.name === name)?.link != null)) throw new Error("生成画布尚未核实：分辨率节点参数是动态来源，请改为静态参数后重新检测");
    const ratios = {"1:1 (Square)": [1,1], "2:3 (Portrait Photo)": [2,3], "3:2 (Photo)": [3,2], "3:4 (Portrait Standard)": [3,4], "4:3 (Standard)": [4,3], "9:16 (Portrait Widescreen)": [9,16], "16:9 (Widescreen)": [16,9], "21:9 (Ultrawide)": [21,9]};
    const ratio = ratios[widgetValue(node, "aspect_ratio")], megapixels = widgetValue(node, "megapixels", 1), multiple = widgetValue(node, "multiple", 8);
    if (ratio && Number.isFinite(megapixels) && megapixels > 0 && Number.isInteger(multiple) && multiple > 0) {
      const value = ratio[slot] * Math.sqrt(megapixels*1024*1024/(ratio[0]*ratio[1])) / multiple;
      const lower = Math.floor(value), rounded = value-lower === .5 ? lower+(lower%2) : Math.round(value);
      return rounded * multiple;
    }
  }
  throw new Error("生成画布尚未核实：上游尺寸是动态值或不支持静态核实，请改用静态分辨率或取消两条尺寸连接");
}

function inventory(project) {
  if (!project) return [];
  const assets = new Map((project.assets || []).map(asset => [asset.asset_id, asset]));
  const labels = new Map((project.label_map || []).map(row => [row.item_id, row]));
  const fallback = [];
  const pictureTrack = [...(project.picture_track || [])].sort((a, b) => Number(a.order) - Number(b.order) || String(a.item_id).localeCompare(String(b.item_id)));
  const videoTrack = [...(project.video_track || [])].sort((a, b) => Number(a.timeline_in_seconds) - Number(b.timeline_in_seconds) || String(a.clip_id).localeCompare(String(b.clip_id)));
  const audioTrack = [...(project.audio_track || [])].sort((a, b) => Number(a.timeline_in_seconds) - Number(b.timeline_in_seconds) || String(a.clip_id).localeCompare(String(b.clip_id)));
  pictureTrack.forEach((item, index) => fallback.push([item.item_id, `Picture ${index + 1}`, index + 1]));
  videoTrack.forEach((item, index) => fallback.push([item.clip_id, `Video ${index + 1}`, index + 1]));
  let audioIndex = 0;
  audioTrack.forEach(item => {
    const video = videoTrack.find(row => row.clip_id === item.linked_video_clip_id);
    const videoLabel = fallback.find(row => row[0] === video?.clip_id)?.[1];
    fallback.push([item.clip_id, item.linked_video_clip_id ? `${videoLabel || "视频"} 原声` : `Audio ${++audioIndex}`, item.linked_video_clip_id ? null : audioIndex]);
  });
  const fallbackLabels = new Map(fallback.map(([id, label, ordinal]) => [id, { label, ordinal }]));
  const rows = [];
  const windowStart = Number(project.processing_window?.start_seconds), windowEnd = Number(project.processing_window?.end_seconds);
  for (const [kind, track] of [["picture", pictureTrack], ["video", videoTrack], ["audio", audioTrack]]) {
    for (const item of track) {
      const id = item.item_id || item.clip_id;
      const label = labels.get(id) || fallbackLabels.get(id) || { label: "未编号", ordinal: null };
      const timelineIn = Number(item.timeline_in_seconds), timelineOut = Number(item.timeline_out_seconds ?? timelineIn + Number(item.source_out_seconds) - Number(item.source_in_seconds));
      const asset = assets.get(item.asset_id) || null;
      rows.push({
        kind,
        id,
        label: label.label,
        displayLabel: label.label,
        ordinal: label.ordinal,
        name: asset?.name || "素材不存在",
        asset,
        trackItem: kind === "picture" ? item : {...item, timeline_out_seconds: timelineOut},
        linked: !!item.linked_video_clip_id,
        linkedVideoId: item.linked_video_clip_id || null,
        enabled: item.enabled !== false,
        timelineIn,
        timelineOut,
        inWindow: kind === "picture" || (timelineOut > windowStart && timelineIn < windowEnd),
      });
    }
  }
  return rows;
}

function inferMode(state, rows) {
  const plan = state.reference_detection && !isFixedHubSnapshot(state.reference_detection) ? state.reference_detection : plannedReferenceSnapshot(rows, state);
  const anchors = plan.pictures.filter(row => row.origin !== "reference").map(row => row.origin);
  const refs = plan.videos.length || plan.audios.length || plan.pictures.some(row => row.origin === "reference");
  if (refs) return anchors.length ? "Hybrid" : "Ref2VA";
  if (anchors.includes("first_frame") && anchors.includes("last_frame")) return "FL2VA";
  if (anchors.includes("first_frame")) return "I2VA";
  if (anchors.includes("last_frame")) return "L2VA";
  return "T2VA";
}

function applyRecipe(state, recipe) { state.recipe = recipe; }

function attachInterview(node) {
  const widget = node.widgets?.find(item => item.name === "interview_json");
  if (!widget) return;
  if (node.zvH3Interview) { node.zvH3Interview.refresh(); return; }
  widget.type = "converted-widget";
  widget.computeSize = () => [0, -4];
  if (widget.inputEl) widget.inputEl.style.display = "none";

  let state = safeState(widget.value);
  let draft = clone(state);
  let disposed = false;
  let project = null;
  let projectMessage = "";
  let rows = [];
  let sourceRoot = null;
  let detectionResult = null;
  let persistTimer = 0;
  let previewPlayers = [];
  let previewToken = 0;
  let validationResult = null, validationTimer = 0, validationToken = 0;
  const peakCache = new Map();
  const root = el("div", "zv-h3i");
  root.tabIndex = 0;
  root.innerHTML = `<div class="zv-h3i-head"><div class="zv-h3i-brand"><strong>ZV H3 基础采访表</strong><small>常驻大表 · 填写内容随工作流保存 · H3 单窗口约束</small></div><div class="zv-h3i-chips"></div></div><div class="zv-h3i-toolbar"></div><div class="zv-h3i-body"><main><div class="zv-h3i-fields-host"></div></main><aside><div class="zv-h3i-aside-head"><div><h3>本次素材与用途</h3><small>从素材台读取预览缓存；常用 6图·3视频·3独立音频，固定出口保留 9 图、3 视频、3 配对原声和 3 独立音频接口。</small></div><button data-action="clear-roles">清空用途</button></div><div class="zv-h3-detect-row"><button class="zv-h3-detect-button" data-action="detect">检测并对齐素材</button><div class="zv-h3-detection-status" data-state="idle">尚未检测本次素材计划</div></div><div class="zv-h3-shared-preview"><span>检测后点击素材缩略图，可在这里预览或试听</span></div><p>一个按钮同时读取当前素材、生成连续编号并交给固定 H3 出口。素材台编号只负责找素材；提示词只使用“本次 H3”编号。参考段使用素材台选定源入/出点，可在目标 GEN 窗口外；总长受 H3 规则约束。</p><div class="zv-h3i-media"></div></aside></div><div class="zv-h3i-foot"><span class="zv-h3i-editor-status"></span><span class="zv-h3-model-status"></span><span class="zv-h3-semantic-status"></span></div>`;
  const $ = selector => root.querySelector(selector);
  const fieldInputs = new Map();
  let lastTextInput = null;
  let detectionToken = 0, detectionNotice = "";
  root.addEventListener("focusin", event => { if (event.target.tagName === "TEXTAREA") lastTextInput = event.target; });

  const toolbar = $(".zv-h3i-toolbar");
  const recipeLabel = el("label"); recipeLabel.append(el("span", "", "旧配方（教学参考，不改路由）"));
  const recipe = el("select"); RECIPES.forEach(([value, label]) => { const option = el("option", "", label); option.value = value; recipe.append(option); }); recipeLabel.append(recipe);
  const modeLabel = el("label"); modeLabel.append(el("span", "", "模式备注（真实接口自动判定）"));
  const mode = el("select"); [["auto", "自动判定"], ["T2VA", "T2VA"], ["I2VA", "I2VA"], ["FL2VA", "FL2VA"], ["L2VA", "L2VA"], ["Ref2VA", "Ref2VA"], ["Hybrid", "混合参考"]].forEach(([value, label]) => { const option = el("option", "", label); option.value = value; mode.append(option); }); modeLabel.append(mode);
  const focusLabel = el("label"); focusLabel.append(el("span", "", "导演侧重"));
  const focus = el("select"); [["balanced", "均衡"], ["dialogue", "文戏 / 对白表演"], ["action", "武戏 / 动作因果"]].forEach(([value, label]) => { const option = el("option", "", label); option.value = value; focus.append(option); }); focusLabel.append(focus);
  toolbar.append(modeLabel, focusLabel);

  const presetHost = el("div"); root.insertBefore(presetHost, toolbar);
  const disposePresets = mountPresets(presetHost, () => { persistDraft(); return {state: clone(draft), media_project: readProject(node).project}; }, result => {
    ++validationToken; draft = safeState(result.state); state = clone(draft);
    validationResult = result.validation;
    if (result.mechanical_changed) detectionResult = {errors: ["预设物理接口变化，请检测并对齐素材"]};
    syncForm(); persistDraft(); renderMedia(); updateStatus();
  }, api);

  const fieldsHost = $(".zv-h3i-fields-host");
  const pendingView = el("details", "zv-h3-pending"); pendingView.hidden = true; fieldsHost.append(pendingView);
  const teaching = el("details", "zv-h3-teaching"); teaching.append(el("summary", "", "可选教学示例（不改物理路由）"), recipeLabel); fieldsHost.append(teaching);
  const rulesView = el("details", "zv-h3-rules"); rulesView.append(el("summary", "", "接口规则与来源")); fieldsHost.append(rulesView);
  for (const [title, fields] of FIELD_GROUPS) {
    const section = el("section", "zv-h3i-fields"); section.append(el("h3", "", title));
    for (const [name, label, placeholder, large] of fields) {
      const field = el("label", large ? "wide" : ""); field.append(el("span", "", label));
      const input = el("textarea"); input.name = name; input.placeholder = placeholder; input.rows = large ? 4 : 2;
      input.addEventListener("input", () => { draft[name] = input.value; updateStatus(); schedulePersist(); });
      fieldInputs.set(name, input); field.append(input); section.append(field);
    }
    fieldsHost.append(section);
  }

  function persistDraft() {
    if (persistTimer) { clearTimeout(persistTimer); persistTimer = 0; }
    state = safeState(draft);
    draft = clone(state);
    widget.value = JSON.stringify(state);
    widget.callback?.(widget.value);
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
  }

  function schedulePersist() {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => { persistDraft(); updateStatus(); }, 140);
  }

  function invalidateReferenceDetection(reason) {
    detectionNotice = "";
    if (!draft.reference_detection) return false;
    draft.reference_detection = null;
    draft.alignment = null;
    detectionResult = { snapshot: null, errors: [reason], warnings: [], details: {} };
    return true;
  }

  function detectedEntriesFor(row) {
    const detected = draft.reference_detection;
    if (!detected) return [];
    const entries = [];
    detected.pictures.forEach((record, index) => { if (record.item_id === row.id) entries.push({ ...record, callLabel: `<Picture ${index + 1}>` }); });
    detected.videos.forEach((record, index) => { if (record.item_id === row.id) entries.push({ ...record, callLabel: `<Video ${index + 1}>` }); });
    detected.audios.forEach((record, index) => {
      const belongs = record.origin === "video_soundtrack" ? (row.kind === "audio" ? row.linkedVideoId === record.item_id : row.kind === "video" && row.id === record.item_id) : record.item_id === row.id;
      if (belongs) entries.push({ ...record, callLabel: `<Audio ${index + 1}>` });
    });
    return entries;
  }

  function detectedRows() {
    const detected = draft.reference_detection;
    if (!detected) return [];
    const ids = [...detected.pictures, ...detected.videos, ...detected.audios].map(record => record.item_id);
    const ordered = [];
    for (const id of ids) {
      const row = rows.find(candidate => candidate.id === id) || rows.find(candidate => candidate.kind === "audio" && candidate.linkedVideoId === id);
      if (row && !ordered.includes(row)) ordered.push(row);
    }
    return ordered;
  }

  function drawPeaks(canvas, peaks, progress = 0) {
    const context = canvas.getContext?.("2d");
    if (!context) return;
    const width = canvas.width || 480, height = canvas.height || 64;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#101b25";
    context.fillRect(0, 0, width, height);
    if (!peaks.length) {
      context.fillStyle = "#557082";
      context.fillRect(0, Math.floor(height / 2), width, 1);
      return;
    }
    const step = width / peaks.length;
    peaks.forEach((peak, index) => {
      const size = Math.max(1, Number(peak) * (height - 8));
      context.fillStyle = index / peaks.length < progress ? "#b5f2dc" : "#59bac2";
      context.fillRect(index * step, (height - size) / 2, Math.max(1, step), size);
    });
  }

  async function loadPeaks(asset, canvas, token = null, row = null) {
    if (!asset?.source_handle) return;
    try {
      if (!peakCache.has(asset.source_handle)) peakCache.set(asset.source_handle, (async () => {
        const response = await api.fetchApi(`${PREVIEW_ROOT}/preview?source=${encodeURIComponent(asset.source_handle)}&variant=peaks`);
        return response.ok ? response.json() : null;
      })());
      const data = await peakCache.get(asset.source_handle);
      if ((token == null || token === previewToken) && canvas.isConnected && Array.isArray(data?.peaks)) drawPeaks(canvas, row ? sampleClipPeaks(data.peaks, asset.probe.duration_seconds, row.trackItem.source_in_seconds, row.trackItem.source_out_seconds) : data.peaks);
    } catch { /* Preview failure never changes material or interview data. */ }
  }

  function stopSharedPreview() {
    previewToken += 1;
    for (const player of previewPlayers) {
      try { player.pause?.(); player.removeAttribute?.("src"); player.load?.(); } catch { /* already detached */ }
    }
    previewPlayers = [];
  }

  function showSharedPreview(row) {
    const host = $(".zv-h3-shared-preview");
    const asset = row?.asset;
    stopSharedPreview();
    const token = previewToken;
    host.replaceChildren();
    if (!asset?.source_handle) { host.append(el("span", "", "素材源不可用，无法预览")); return; }
    host.title = `${row.label} · ${row.name}`;
    if (row.kind === "picture") {
      const image = el("img"); image.alt = row.name; image.src = previewURL(asset, "original"); image.draggable = false; host.append(image); return;
    }
    const start = Number(row.trackItem.source_in_seconds), end = Number(row.trackItem.source_out_seconds);
    host.append(el("small", "zv-h3-source-range", `原片源入 ${start.toFixed(3)} 秒 / 出 ${end.toFixed(3)} 秒 · 本段 ${(end-start).toFixed(3)} 秒`));
    function constrain(player) {
      player.dataset.sourceIn = start; player.dataset.sourceOut = end;
      player.addEventListener("loadedmetadata", () => { if (token === previewToken) player.currentTime = start; });
      player.addEventListener("seeking", () => {
        if (token === previewToken && (player.currentTime < start || player.currentTime > end)) player.currentTime = Math.max(start, Math.min(end, player.currentTime));
      });
      player.addEventListener("play", () => { if (token === previewToken && (player.currentTime < start || player.currentTime >= end)) player.currentTime = start; });
      player.addEventListener("timeupdate", () => {
        if (token !== previewToken) return;
        if (player.currentTime >= end) { player.pause(); if (player.currentTime > end) player.currentTime = end; }
        else if (player.currentTime < start) player.currentTime = start;
      });
    }
    if (row.kind === "video") {
      const video = el("video"); video.controls = true; video.playsInline = true; video.preload = "metadata"; video.muted = true; video.src = previewURL(asset, "proxy");
      constrain(video);
      previewPlayers.push(video); host.append(video);
      if (asset.probe?.has_audio && row.trackItem.source_audio_enabled && rows.some(audio => audio.id === row.trackItem.audio_link_id && audio.linkedVideoId === row.id && audio.enabled)) {
        const sound = el("audio"); sound.preload = "metadata"; sound.src = previewURL(asset, "audio"); previewPlayers.push(sound);
        constrain(sound);
        video.addEventListener("play", () => { if (token === previewToken) { sound.currentTime = video.currentTime; sound.play().catch(() => {}); } });
        video.addEventListener("pause", () => sound.pause());
        video.addEventListener("seeking", () => { sound.currentTime = video.currentTime; });
        video.addEventListener("timeupdate", () => { if (Math.abs(sound.currentTime - video.currentTime) > .18) sound.currentTime = video.currentTime; });
      }
      return;
    }
    const stack = el("div", "zv-h3-audio-preview");
    const waveform = el("canvas", "zv-h3-waveform"); waveform.width = 720; waveform.height = 80; drawPeaks(waveform, []);
    const audio = el("audio"); audio.controls = true; audio.preload = "metadata"; audio.src = previewURL(asset, "audio");
    constrain(audio);
    previewPlayers.push(audio); stack.append(waveform, audio); host.append(stack); loadPeaks(asset, waveform, token, row);
  }

  function tinyPreview(row) {
    const box = el("button", "zv-h3-media-thumb"); box.type = "button"; box.title = `预览 ${row.label}：${row.name}`;
    if (row.kind === "audio") {
      const canvas = el("canvas", "zv-h3-waveform"); canvas.width = 224; canvas.height = 112; drawPeaks(canvas, []); box.append(canvas); loadPeaks(row.asset, canvas, null, row);
    } else {
      const image = el("img"); image.alt = ""; image.loading = "lazy"; image.draggable = false;
      if (row.asset?.source_handle) image.src = previewURL(row.asset, "thumbnail");
      box.append(image);
    }
    box.addEventListener("click", () => showSharedPreview(row));
    return box;
  }

  async function requestPlan(candidate, align = false, conditioningCount = 0) {
    const prompt = Object.fromEntries(graphNodes(node.graph).map(item => {
      const inputs = {};
      for (const input of item.inputs || []) { const source = inputSource(item, input.name); if (source) inputs[input.name] = [String(source.node.id), source.slot]; }
      for (const name of ["task_type", "audio_mode", "add_source_as_reference", "prompt_primary_audio_ordinal", "length", "expression", "item_id", "clip_id", "width", "height", "aspect_ratio", "megapixels", "multiple", "value"]) {
        const value = widgetValue(item, name);
        if (!(name in inputs) && value !== undefined) inputs[name] = value;
      }
      return [String(item.id), { class_type: nodeType(item), inputs }];
    }));
    const response = await api.fetchApi(PLAN_API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: candidate, media_project: project, align, conditioning_count: conditioningCount, prompt, interview_id: String(node.id) }) });
    const data = await response.json();
    if (!response.ok) throw new Error((data.errors || []).map(row => row.message).join("；") || "服务端计划不可用；更新插件后重启 ComfyUI 服务");
    return data;
  }

  function scheduleValidation() {
    clearTimeout(validationTimer);
    const token = ++validationToken;
    validationTimer = setTimeout(async () => {
      if (disposed || !project) return;
      try {
        const result = await requestPlan(clone(draft));
        if (disposed || token !== validationToken) return;
        validationResult = result.validation;
        adoptReferenceTexts(result.state);
        rulesView.replaceChildren(el("summary", "", "接口规则与来源"));
        for (const note of result.rules.notes) rulesView.append(el("p", "", note));
        for (const [label, url] of Object.entries(result.rules.sources)) { const link = el("a", "", label); link.href = url; link.target = "_blank"; link.rel = "noopener"; rulesView.append(link, document.createTextNode(" · ")); }
        renderValidation();
      } catch (error) {
        if (disposed || token !== validationToken) return;
        validationResult = { errors: [{ message: error.message }], warnings: [] }; renderValidation();
      }
    }, 160);
  }

  function adoptReferenceTexts(next) {
    draft.preset_pending = clone(next.preset_pending || []);
    draft.bindings = clone(next.bindings); draft.media_roles = clone(next.media_roles); draft.media_purposes = clone(next.media_purposes);
    draft.reference_texts = clone(next.reference_texts || {});
    for (const [key, entry] of Object.entries(draft.reference_texts)) {
      const actual = key.startsWith("purpose:") ? next.media_purposes[key.slice(8)] : next[key];
      if (actual !== entry.rendered) continue; // Never overwrite an unresolved user edit.
      if (key.startsWith("purpose:")) { draft.media_purposes[key.slice(8)] = entry.rendered; const input = root.querySelector(`textarea[name="purpose-${key.slice(8)}"]`); if (input) input.value = entry.rendered; }
      else { draft[key] = entry.rendered; const input = fieldInputs.get(key); if (input) input.value = entry.rendered; }
    }
    persistDraft();
  }

  function renderValidation() {
    pendingView.replaceChildren(el("summary", "", `待补齐预设用途（${draft.preset_pending.length} 项）`));
    pendingView.hidden = !draft.preset_pending.length;
    for (const pending of draft.preset_pending) {
      const slot = pending.slot, purpose = pending.soundtrack_only ? slot.soundtrack.purpose.text : slot.purpose.text;
      pendingView.append(el("p", "", `${slot.kind} 槽${slot.slot}${pending.soundtrack_only ? " 原声" : ""}：${purpose.replace(/\{\{h3:r\d+\}\}/g, "［待绑定引用］") || "用途可留空"}；保留期望，不修改素材台原声开关`));
    }
    const hard = $(".zv-h3-model-status"), semantic = $(".zv-h3-semantic-status");
    const errors = validationResult?.errors || [], warnings = validationResult?.warnings || [];
    hard.textContent = projectMessage || (errors.length ? `模型硬错误：${errors.map(row => row.message).join("；")}` : validationResult ? "模型机械检查已通过" : "正在核对模型机械规则…");
    hard.classList.toggle("error", !!errors.length || !!projectMessage);
    const visible = validationResult?.model_visible_references || [];
    semantic.textContent = [...warnings.slice(0, 3).map(row => row.message), ...visible.map(row => `${row.call_label} 出口 ${row.export_frames} 帧 → ${row.model_length_verified ? "按已核实 length 的模型输入" : `假设下游 length=${row.assumed_model_length} 的预测（实际length未核实）`} ${row.model_frames} 帧`), ...(warnings.length > 3 ? [`另有 ${warnings.length - 3} 项提醒`] : [])].join("；");
  }

  function syncForm() {
    recipe.value = draft.recipe;
    mode.value = draft.mode;
    focus.value = draft.director_focus;
    for (const [name, input] of fieldInputs) input.value = draft[name] || "";
  }

  function renderMedia() {
    const media = $(".zv-h3i-media"), scroller = media.closest("aside"), scrollTop = scroller?.scrollTop || 0; media.replaceChildren();
    const stale = [...new Set([...Object.keys(draft.media_roles), ...Object.keys(draft.media_purposes)])].filter(id => !rows.some(row => row.id === id) && (draft.media_roles[id]?.length || draft.media_purposes[id]));
    if (stale.length) {
      const notice = el("div", "zv-h3i-empty error", `${stale.length} 项用途指向已删除素材`), clear = el("button", "", "清理失效用途");
      clear.onclick = () => {
        stale.forEach(id => { delete draft.media_roles[id]; delete draft.media_purposes[id]; delete draft.reference_texts["purpose:"+id]; });
        renderMedia(); updateStatus(); persistDraft();
      };
      notice.append(document.createElement("br"), clear); media.append(notice);
    }
    if (projectMessage) media.append(el("div", "zv-h3i-empty error", projectMessage));
    else if (!rows.length) media.append(el("div", "zv-h3i-empty", "素材台轨道为空；可做 T2VA。"));
    const visibleRows = rows;
    if (draft.reference_detection && visibleRows.length) media.append(el("div", "zv-h3i-detected-summary", `全部 ${visibleRows.length} 项素材均可见；是否参与与物理接口独立于语义用途。`));
    for (const row of visibleRows) {
      const entries = detectedEntriesFor(row);
      const selected = bindingFor(draft, row).participates;
      const cardState = entries.length ? "connected" : selected ? "warning" : "idle";
      const card = el("section", `zv-h3i-media-card zv-h3-media-card ${row.linked ? "linked" : ""} ${cardState}`);
      card.dataset.state = cardState;
      card.append(tinyPreview(row));
      const title = el("div", "zv-h3i-media-title"), name = el("span", "", row.name); name.title = row.name; title.append(el("b", "", `素材台 ${row.label}`), name); card.append(title);
      if (entries.length) {
        const map = el("div", "zv-h3-call-map");
        map.append(el("span", "", `${row.label} → 本次 H3`));
        for (const entry of entries) {
          const badge = el("strong", "", entry.callLabel); badge.title = `${entry.origin} · ${entry.source_port}`; map.append(badge);
        }
        card.append(map);
      } else if (draft.reference_detection) {
        card.append(el("div", "zv-h3-call-map", selected ? "已参与，等待对齐" : "未参与本次 H3（素材仍可见）"));
      }
      const binding = bindingFor(draft, row);
      const controls = el("div", "zv-h3-routing");
      const participation = el("label"), enabled = el("input"); enabled.type = "checkbox"; enabled.name = "participates";
      const pairedVideo = row.linked ? rows.find(candidate => candidate.id === row.linkedVideoId && candidate.kind === "video") : null;
      enabled.checked = pairedVideo ? bindingFor(draft, pairedVideo).participates && !!pairedVideo.trackItem.source_audio_enabled && pairedVideo.trackItem.audio_link_id === row.id && row.enabled : binding.participates;
      enabled.disabled = row.linked;
      participation.append(enabled, document.createTextNode(row.linked ? "原声随同源视频参与" : "参与 H3")); controls.append(participation);
      enabled.onchange = () => { binding.participates = enabled.checked; draft.bindings[row.id] = binding; invalidateReferenceDetection("素材参与状态已改变，请重新检测并对齐素材"); renderMedia(); updateStatus(); persistDraft(); };
      if (!row.linked) for (const [bank, label] of BANKS[row.kind]) {
        const option = el("label"), input = el("input"); input.type = row.kind === "audio" ? "radio" : "checkbox"; input.name = `bank-${row.id}`; input.value = bank; input.checked = binding.banks.includes(bank);
        input.onchange = () => {
          binding.banks = row.kind === "audio" ? [bank] : input.checked ? [...new Set([...binding.banks, bank])] : binding.banks.filter(value => value !== bank);
          if (!binding.banks.length) { binding.banks = [BANKS[row.kind][0][0]]; binding.participates = false; }
          draft.bindings[row.id] = binding; invalidateReferenceDetection("物理接口已改变，请重新检测并对齐素材"); renderMedia(); updateStatus(); persistDraft();
        };
        option.append(input, document.createTextNode(label)); controls.append(option);
      }
      card.append(controls);
      if (row.kind !== "picture") card.append(el("small", "zv-h3-source-range", `原片源入 ${Number(row.trackItem.source_in_seconds).toFixed(3)} 秒 / 出 ${Number(row.trackItem.source_out_seconds).toFixed(3)} 秒 · 本段 ${(row.trackItem.source_out_seconds-row.trackItem.source_in_seconds).toFixed(3)} 秒`));
      card.append(el("small", "zv-h3-bank-hint", row.kind === "picture" ? "首/尾是画面锚点；参考图保留自由参考。选择多个接口会实际发送多项，首尾锚点加参考素材为混合参考。" : row.kind === "video" ? `发送当前轨道选段；原声跟随同源视频选段${row.inWindow ? "" : "；目标窗口外上下文"}` : "发送当前轨道音频选段；驱动仅在明确需要固定/混合成片声音时选择。"));
      if (row.linked) card.append(el("p", "warning", "这是视频绑定原声，不单独发送；同序原声口接入 H3 时会占用本次 <Audio N>。"));
      const options = el("div", "zv-h3i-role-options");
      for (const [value, label] of ROLES[row.kind]) {
        const option = el("label"); const input = el("input"); input.type = "checkbox"; input.value = value; input.checked = (draft.media_roles[row.id] || []).includes(value); input.disabled = !row.enabled;
        input.addEventListener("change", () => {
          const current = new Set(draft.media_roles[row.id] || []); input.checked ? current.add(value) : current.delete(value);
          if (current.size) draft.media_roles[row.id] = [...current]; else delete draft.media_roles[row.id];
          renderMedia(); updateStatus(); persistDraft();
        });
        option.append(input, el("span", "", label)); options.append(option);
      }
      card.append(el("small", "", "语义标签（可多选/留空，不改路由）"), options);
      const purpose = el("textarea", "zv-h3-purpose"); purpose.name = `purpose-${row.id}`; purpose.placeholder = "自由用途：可描述多个 Subject、剧情关系、时间位置…"; purpose.rows = 2; purpose.value = draft.media_purposes[row.id] || "";
      purpose.oninput = () => { draft.media_purposes[row.id] = purpose.value; updateStatus(); schedulePersist(); };
      card.append(purpose); media.append(card);
      for (const entry of detectedEntriesFor(row)) {
        const insert = el("button", "zv-h3-insert-reference", `插入 ${entry.callLabel} · ${entry.origin}`);
        insert.type = "button"; insert.onclick = () => {
          const target = lastTextInput?.isConnected ? lastTextInput : fieldInputs.get("intent");
          const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
          target.setRangeText(entry.callLabel, start, end, "end"); target.dispatchEvent(new Event("input", {bubbles:true})); target.focus({preventScroll:true});
        };
        card.append(insert);
      }
    }
    if (scroller) scroller.scrollTop = scrollTop;
  }

  function updateDetectionStatus() {
    const output = $(".zv-h3-detection-status");
    if (detectionNotice) { output.dataset.state="warning"; output.className="zv-h3-detection-status warning"; output.textContent=detectionNotice+(draft.reference_detection ? "；已有机械对齐保持" : ""); return; }
    output.className = "zv-h3-detection-status";
    if (detectionResult?.errors?.length) {
      output.dataset.state = "error"; output.classList.add("error"); output.textContent = detectionResult.errors.join("；"); return;
    }
    if (detectionResult?.snapshot) {
      const counts = detectionResult.snapshot;
      const summary = `${counts.pictures.length} 图 / ${counts.videos.length} 视频 / ${counts.audios.length} 音频，${counts.conditioning_count} 个 H3 Conditioning 一致`;
      output.dataset.state = "success"; output.classList.add("success");
      output.textContent = `${summary}；路由已对齐，编号与 Stage① 已对齐${detectionResult.syncNotes?.length ? `；${detectionResult.syncNotes.join("；")}` : ""}`;
      return;
    }
    if (draft.reference_detection) {
      output.dataset.state = "warning"; output.classList.add("warning"); output.textContent = "已载入上次检测结果；换过素材或线路后请重新检测"; return;
    }
    output.dataset.state = "idle"; output.textContent = "尚未检测本次素材计划";
  }

  function updateStatus() {
    draft.recipe = recipe.value; draft.mode = mode.value; draft.director_focus = focus.value;
    const derived = inferMode(draft, rows);
    const active = rows.filter(row => bindingFor(draft, row).participates && !row.linked);
    const output = $(".zv-h3i-editor-status");
    output.textContent = `${derived === "Hybrid" ? "混合参考" : derived} · ${active.length} 个参与素材 · 内容自动写入工作流`;
    output.classList.remove("dirty", "error");
    updateDetectionStatus(); scheduleValidation();
    const chips = $(".zv-h3i-chips"); chips.replaceChildren();
    const values = [derived === "Hybrid" ? "混合参考" : derived, draft.director_focus === "dialogue" ? "文戏" : draft.director_focus === "action" ? "武戏" : "均衡"];
    const window = project?.processing_window;
    if (window) values.push(`${(Number(window.end_seconds) - Number(window.start_seconds)).toFixed(3)} 秒`, `${window.frame_count ?? Math.round((Number(window.end_seconds) - Number(window.start_seconds)) * Number(window.fps))} 帧`);
    values.forEach(value => chips.append(el("span", "", value)));
  }

  function bindProjectSource() {
    const next = sourceForMediaInput(node)?.zfMediaDesk?.root || null;
    if (next === sourceRoot) return;
    sourceRoot?.removeEventListener?.("zf-media-project-change", refreshProject);
    sourceRoot = next;
    sourceRoot?.addEventListener?.("zf-media-project-change", refreshProject);
  }

  function refreshProject() {
    if (disposed) return;
    const external = safeState(widget.value);
    if (!persistTimer && JSON.stringify(external) !== JSON.stringify(state)) { state = external; draft = clone(state); syncForm(); }
    const context = readProject(node); project = context.project; projectMessage = context.message; rows = inventory(project);
    if (draft.migration?.freeze_pending && project) {
      for (const row of rows) draft.bindings[row.id] = bindingFor(draft, row);
      if (draft.migration.legacy_drive_pending) {
        const drive = rows.find(row => row.kind === "audio" && !row.linked && draft.bindings[row.id].participates && draft.media_roles[row.id]?.some(role => ["speech_lipsync", "audio_reuse"].includes(role)));
        if (drive) draft.bindings[drive.id].banks = ["drive_audio"];
      }
      draft.migration = { from: "zv-h3-interview-v1" };
    }
    let invalidated = false;
    if (draft.reference_detection) {
      const known = new Set(rows.map(row => row.id));
      const missing = [...draft.reference_detection.pictures, ...draft.reference_detection.videos, ...draft.reference_detection.audios]
        .some(record => !known.has(record.item_id) && !(record.origin === "video_soundtrack" && rows.some(row => row.kind === "audio" && row.linkedVideoId === record.item_id)));
      if (!project) {
        invalidated = invalidateReferenceDetection(projectMessage || "无法核实当前素材工程，请重新检测并对齐素材");
      } else if (missing) {
        invalidated = invalidateReferenceDetection("上次检测使用的素材已删除，请重新检测并对齐素材");
      } else if (draft.alignment && !same(draft.alignment, mechanicalContext(draft, project, rows))) {
        invalidated = invalidateReferenceDetection("素材/顺序/原声/尺寸/窗口已改变，请重新检测并对齐素材");
      } else if (connectedReferenceHubs(node).length === 1 && isFixedHubSnapshot(draft.reference_detection)) {
        const expected = plannedReferenceSnapshot(rows, draft, draft.reference_detection.conditioning_count);
        if (!same(expected, draft.reference_detection)) {
          invalidated = invalidateReferenceDetection("素材/顺序/原声/尺寸/窗口已改变，请重新检测并对齐素材");
        }
      }
    }
    if (invalidated) persistDraft();
    bindProjectSource(); renderMedia(); updateStatus();
  }

  function save() {
    updateStatus(); persistDraft(); syncForm(); updateStatus();
  }

  function synchronizeConditioning() {
    const notes = [];
    for (const conditioning of graphNodes(node.graph).filter(candidate => nodeType(candidate) === H3_CONDITIONING && dependsOn(candidate, node.id))) {
      const drive = plannedReferenceSnapshot(rows, draft).audios.some(row => row.origin === "drive_audio");
      const values = { task_type: "auto", add_source_as_reference: true, prompt_primary_audio_ordinal: 0, ...(drive ? {} : { audio_mode: "native" }) };
      for (const [name, value] of Object.entries(values)) {
        const input = conditioning.inputs?.find(input => input.name === name);
        if (input?.link != null) continue;
        const target = conditioning.widgets?.find(widget => widget.name === name);
        if (target && target.value !== value) { target.value = value; target.callback?.(value); notes.push(`${conditioning.title || conditioning.id}: ${name}→${value}`); }
      }
      conditioning.setDirtyCanvas?.(true, true);
    }
    return notes;
  }

  async function detect() {
    refreshProject();
    const token = ++detectionToken; detectionNotice = "";
    const status = $(".zv-h3-detection-status");
    status.dataset.state = "busy"; status.className = "zv-h3-detection-status busy"; status.textContent = "正在核对稳定素材、固定出口与模型规则…";
    const before = mechanicalContext(draft, project, rows);
    const syncNotes = synchronizeConditioning();
    const capturedDraft = clone(draft), capturedProject = clone(project);
    try {
      if (!project) throw new Error(projectMessage || "素材台项目尚未就绪");
      const physical = detectReferenceGraph(node, project, rows, draft);
      if (physical.errors.length) { detectionResult = physical; draft.reference_detection = null; draft.alignment = null; }
      else {
        const candidate = clone(draft); candidate.reference_detection = null; candidate.alignment = null;
        const result = await requestPlan(candidate, true, physical.snapshot.conditioning_count);
        if (disposed || token !== detectionToken) return;
        const current = readProject(node); const currentRows = inventory(current.project);
        if (!same(capturedDraft, draft) || !same(capturedProject, current.project)) {
          detectionNotice = "检测响应已过期，未应用；最新文本、用途与素材状态已保留";
          persistDraft(); updateStatus(); return;
        }
        validationResult = result.validation; renderValidation();
        if (result.routing_errors?.length) throw new Error(result.routing_errors.map(row => row.message).join("；"));
        if (result.wiring?.errors?.length) throw new Error(result.wiring.errors.map(row => row.message).join("；"));
        if (!same(before, mechanicalContext(draft, current.project, currentRows))) throw new Error("检测期间素材或机械条件改变，请重新检测并对齐素材");
        if (physical.details.mode === "fixed_h3_reference_hub" && !same(result.snapshot, physical.snapshot)) throw new Error("前后端机械计划不一致，请刷新素材台后重新检测");
        if (result.validation?.errors?.length) {
          adoptReferenceTexts(result.state);
          draft.reference_detection = null; draft.alignment = null;
          detectionResult = {errors: result.validation.errors.map(row => row.message)};
          persistDraft(); renderMedia(); updateStatus(); return;
        }
        draft.bindings = result.state.bindings;
        adoptReferenceTexts(result.state);
        draft.reference_detection = physical.details.mode === "fixed_h3_reference_hub" ? result.snapshot : physical.snapshot;
        draft.alignment = result.alignment_context;
        validationResult = result.validation;
        detectionResult = { ...physical, snapshot: draft.reference_detection, syncNotes };
        renderValidation();
      }
    } catch (error) {
      if (disposed || token !== detectionToken) return;
      if (!same(capturedDraft, draft) || !same(capturedProject, readProject(node).project)) {
        detectionNotice = "检测响应已过期，失败未应用；最新文本、用途与素材状态已保留";
        persistDraft(); updateStatus(); return;
      }
      detectionResult = { errors: [error.message] }; draft.reference_detection = null; draft.alignment = null;
    }
    persistDraft(); renderMedia(); updateStatus();
  }

  recipe.addEventListener("change", () => { applyRecipe(draft, recipe.value); updateStatus(); persistDraft(); });
  mode.addEventListener("change", () => { updateStatus(); persistDraft(); });
  focus.addEventListener("change", () => { updateStatus(); persistDraft(); });
  $("[data-action=clear-roles]").onclick = () => {
    draft.media_roles = {}; draft.media_purposes = {};
    Object.keys(draft.reference_texts).filter(key => key.startsWith("purpose:")).forEach(key => delete draft.reference_texts[key]);
    for (const pending of draft.preset_pending) {
      pending.slot.roles=[]; pending.slot.purpose={text:"",definitions:[]};
      pending.reference_texts={purpose:{text:"",definitions:[],rendered:""}};
      if(pending.slot.soundtrack){pending.slot.soundtrack.roles=[];pending.slot.soundtrack.purpose={text:"",definitions:[]};pending.reference_texts.soundtrack={text:"",definitions:[],rendered:""};}
    }
    renderMedia(); updateStatus(); persistDraft();
  };
  $("[data-action=detect]").onclick = detect;
  root.addEventListener("pointerdown", event => { event.stopPropagation(); if (!event.target.closest("input,textarea,select,button,label")) root.focus({ preventScroll: true }); });
  root.addEventListener("wheel", event => event.stopPropagation(), { passive: true });
  const dom = node.addDOMWidget("h3_interview_ui", "zv-h3-interview", root, { serialize: false, hideOnZoom: false, getMinHeight: () => 760, getMaxHeight: () => 1050 });
  dom.serialize = false;
  pinDOMWidgetFullWidth(dom);
  const oldRemoved = node.onRemoved;
  const canvasWatch = setInterval(() => {
    if (disposed) return;
    const current = readProject(node);
    if (!same(project?.output_canvas ?? null, current.project?.output_canvas ?? null) || projectMessage !== current.message) refreshProject();
  }, 500);
  node.onRemoved = function () { disposed = true; clearInterval(canvasWatch); ++detectionToken; disposePresets(); clearTimeout(validationTimer); ++validationToken; if (persistTimer) clearTimeout(persistTimer); stopSharedPreview(); sourceRoot?.removeEventListener?.("zf-media-project-change", refreshProject); sourceRoot = null; root.remove(); oldRemoved?.apply(this, arguments); };
  const oldConnections = node.onConnectionsChange;
  node.onConnectionsChange = function () { oldConnections?.apply(this, arguments); setTimeout(refreshProject, 0); };
  node.zvH3Interview = { root, refresh: refreshProject, getState: () => clone(state), getDraft: () => clone(draft), save, detect, open: () => { root.scrollIntoView?.({ block: "nearest" }); fieldInputs.get("intent")?.focus(); } };
  node.setSize?.([Math.max(1180, Number(node.size?.[0]) || 0), Math.max(900, Number(node.size?.[1]) || 0)]);
  syncForm(); refreshProject();
}

app.registerExtension({
  name: "ZV.H3InterviewForm",
  async beforeRegisterNodeDef(type, data) {
    if (data.name !== NAME) return;
    for (const hook of ["onNodeCreated", "onConfigure"]) {
      const previous = type.prototype[hook];
      type.prototype[hook] = function () { previous?.apply(this, arguments); setTimeout(() => attachInterview(this), 0); };
    }
  },
  nodeCreated(node) { if ([node.comfyClass, node.type, node.constructor?.comfyClass].includes(NAME)) setTimeout(() => attachInterview(node), 0); },
  loadedGraphNode(node) { if ([node.comfyClass, node.type, node.constructor?.comfyClass].includes(NAME)) setTimeout(() => attachInterview(node), 0); },
});

export { bindingFor, mechanicalContext, migrateV1, safeState, applyRecipe, attachInterview, detectReferenceGraph, emptyState, inferMode, inputSource, inventory, plannedReferenceSnapshot, readProject, scanConditioning, scanStage1, validateFixedHubWiring };
