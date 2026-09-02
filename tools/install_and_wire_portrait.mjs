import fs from "node:fs";
import path from "node:path";

const [repoRootArg, installedRootArg, directWorkflowArg, directorWorkflowArg] = process.argv.slice(2);
if (!repoRootArg || !installedRootArg || !directWorkflowArg || !directorWorkflowArg) {
  throw new Error("缺少仓库、安装目录或工作流路径参数。");
}

const repoRoot = path.resolve(repoRootArg);
const installedRoot = path.resolve(installedRootArg);
const directWorkflow = path.resolve(directWorkflowArg);
const directorWorkflow = path.resolve(directorWorkflowArg);
const stamp = "20260903-portrait-v4";

const runtimeFiles = [
  "nodes.py",
  "server.py",
  "portrait_nodes.py",
  path.join("data", "portrait_generator_v12.json"),
  path.join("web", "portrait_generator.js"),
];

for (const relative of runtimeFiles) {
  const source = path.join(repoRoot, relative);
  const destination = path.join(installedRoot, relative);
  if (!fs.existsSync(source)) throw new Error(`缺少待安装文件：${source}`);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(source, destination);
}

const backup = (workflowPath) => {
  if (!fs.existsSync(workflowPath)) throw new Error(`工作流不存在：${workflowPath}`);
  const backupRoot = path.join(path.dirname(path.dirname(workflowPath)), "workflow_backups");
  fs.mkdirSync(backupRoot, { recursive: true });
  const backupPath = path.join(backupRoot, `${path.basename(workflowPath)}.${stamp}.bak`);
  if (!fs.existsSync(backupPath)) fs.copyFileSync(workflowPath, backupPath);
  return backupPath;
};

const defaultState = JSON.stringify({
  version: 4,
  adult_content: false,
  selected: {},
  enabled: {},
  overrides: {},
  pinned: {},
  locked: {},
  section_locked: {},
  section_enabled: {},
  option_overrides: {},
});

const migratePortraitState = (node) => {
  let previous = {};
  const source = node.widgets_values_named?.state_json ?? node.widgets_values?.[0];
  try { previous = JSON.parse(String(source || "")); } catch { previous = {}; }
  if (!previous || typeof previous !== "object" || Array.isArray(previous)) previous = {};
  const next = { ...JSON.parse(defaultState), ...previous, version: 4 };
  delete next.expanded;
  for (const key of ["selected", "enabled", "overrides", "pinned", "locked", "section_locked", "section_enabled", "option_overrides"]) {
    if (!next[key] || typeof next[key] !== "object" || Array.isArray(next[key])) next[key] = {};
  }
  const serialized = JSON.stringify(next);
  node.widgets_values = Array.isArray(node.widgets_values) ? node.widgets_values : [serialized, 0, false];
  node.widgets_values[0] = serialized;
  node.widgets_values_named = {
    ...(node.widgets_values_named || {}),
    state_json: serialized,
    seed: Number(node.widgets_values_named?.seed ?? node.widgets_values?.[1] ?? 0),
    adult_content: Boolean(next.adult_content),
  };
  node.widgets_values[2] = Boolean(next.adult_content);
  node.size = [Math.max(470, Number(node.size?.[0]) || 470), 145];
  node.properties = { ...(node.properties || {}), ver: "local-portrait-v4" };
};

const removeLink = (workflow, linkId) => {
  if (linkId == null) return;
  const link = workflow.links.find((item) => item[0] === linkId);
  if (link) {
    const source = workflow.nodes.find((node) => node.id === link[1]);
    const output = source?.outputs?.[link[2]];
    if (output?.links) output.links = output.links.filter((id) => id !== linkId);
  }
  workflow.links = workflow.links.filter((item) => item[0] !== linkId);
};

const nextNodeId = (workflow) => Math.max(Number(workflow.last_node_id || 0), ...workflow.nodes.map((node) => Number(node.id) || 0)) + 1;
const nextLinkId = (workflow) => Math.max(Number(workflow.last_link_id || 0), ...workflow.links.map((link) => Number(link[0]) || 0)) + 1;
const nextOrder = (workflow) => Math.max(0, ...workflow.nodes.map((node) => Number(node.order) || 0)) + 1;

const portraitNode = (id, position, order) => ({
  id,
  type: "ZFPortraitPromptGenerator",
  pos: position,
  size: [470, 145],
  flags: {},
  order,
  mode: 0,
  inputs: [
    { label: "state_json", localized_name: "state_json", name: "state_json", type: "STRING", widget: { name: "state_json" } },
    { label: "seed", localized_name: "seed", name: "seed", type: "INT", widget: { name: "seed" } },
    { label: "adult_content", localized_name: "adult_content", name: "adult_content", type: "BOOLEAN", widget: { name: "adult_content" } },
    { label: "reference_analysis", localized_name: "reference_analysis", name: "reference_analysis", shape: 7, type: "STRING" },
  ],
  outputs: [
    { label: "portrait_prompt", localized_name: "portrait_prompt", name: "portrait_prompt", type: "STRING", links: [] },
    { label: "world_asset", localized_name: "world_asset", name: "world_asset", type: "STRING", links: [] },
    { label: "selection_json", localized_name: "selection_json", name: "selection_json", type: "STRING" },
    { label: "status", localized_name: "status", name: "status", type: "STRING" },
  ],
  properties: {
    aux_id: "Z-yaofang/ZF-ComfyUI-PromptDirector",
    ver: "local-portrait-v4",
    "Node name for S&R": "ZFPortraitPromptGenerator",
    widget_ue_connectable: {},
  },
  widgets_values: [defaultState, 0, false],
  widgets_values_named: { state_json: defaultState, seed: 0, adult_content: false },
  color: "#2b3540",
  bgcolor: "#3d4b59",
});

const loadWorkflow = (workflowPath) => JSON.parse(fs.readFileSync(workflowPath, "utf8"));
const saveWorkflow = (workflowPath, workflow) => fs.writeFileSync(workflowPath, JSON.stringify(workflow), "utf8");

const wireDirectPrompt = (workflowPath) => {
  const workflow = loadWorkflow(workflowPath);
  let node = workflow.nodes.find((item) => item.type === "ZFPortraitPromptGenerator");
  if (!node) {
    node = portraitNode(nextNodeId(workflow), [1175, 1810], nextOrder(workflow));
    workflow.nodes.push(node);
  }
  migratePortraitState(node);
  const target = workflow.nodes.find((item) => item.id === 1018 && item.type === "CLIPTextEncode");
  if (!target?.inputs?.[1]) throw new Error("小工作流中没有找到 CLIPTextEncode.text 接点。");
  if (target.inputs[1].link != null) {
    const existing = workflow.links.find((link) => link[0] === target.inputs[1].link);
    if (existing && existing[1] === node.id && existing[2] === 0) {
      saveWorkflow(workflowPath, workflow);
      return { nodeId: node.id, linkId: target.inputs[1].link, target: `${target.id}.text`, unchanged: true };
    }
  }
  removeLink(workflow, target.inputs[1].link);
  const linkId = nextLinkId(workflow);
  workflow.links.push([linkId, node.id, 0, target.id, 1, "STRING"]);
  node.outputs[0].links = [linkId];
  target.inputs[1].link = linkId;
  workflow.last_node_id = Math.max(Number(workflow.last_node_id || 0), node.id);
  workflow.last_link_id = Math.max(Number(workflow.last_link_id || 0), linkId);
  saveWorkflow(workflowPath, workflow);
  return { nodeId: node.id, linkId, target: `${target.id}.text` };
};

const wireDirectorAsset = (workflowPath) => {
  const workflow = loadWorkflow(workflowPath);
  let node = workflow.nodes.find((item) => item.type === "ZFPortraitPromptGenerator");
  if (!node) {
    node = portraitNode(nextNodeId(workflow), [-3740, -1120], nextOrder(workflow));
    workflow.nodes.push(node);
  }
  migratePortraitState(node);
  const selector = workflow.nodes.find((item) => item.id === 885 && item.type === "ZFPromptDirectorMultiTextSelector");
  const inputIndex = selector?.inputs?.findIndex((input) => input.name === "text_17");
  if (!selector || inputIndex == null || inputIndex < 0) throw new Error("导演台工作流中没有找到世界观多路节点的 text_17。");
  const input = selector.inputs[inputIndex];
  if (input.link != null) {
    const existing = workflow.links.find((link) => link[0] === input.link);
    if (!existing || existing[1] !== node.id || existing[2] !== 1) {
      throw new Error("世界观 text_17 已被其它节点占用，未覆盖原接线。");
    }
    saveWorkflow(workflowPath, workflow);
    return { nodeId: node.id, linkId: input.link, target: `${selector.id}.text_17`, unchanged: true };
  }
  const linkId = nextLinkId(workflow);
  workflow.links.push([linkId, node.id, 1, selector.id, inputIndex, "STRING"]);
  node.outputs[1].links = [linkId];
  input.link = linkId;
  workflow.last_node_id = Math.max(Number(workflow.last_node_id || 0), node.id);
  workflow.last_link_id = Math.max(Number(workflow.last_link_id || 0), linkId);
  saveWorkflow(workflowPath, workflow);
  return { nodeId: node.id, linkId, target: `${selector.id}.text_17` };
};

const result = {
  installedRoot,
  directBackup: backup(directWorkflow),
  directorBackup: backup(directorWorkflow),
  direct: wireDirectPrompt(directWorkflow),
  director: wireDirectorAsset(directorWorkflow),
};
console.log(JSON.stringify(result, null, 2));
