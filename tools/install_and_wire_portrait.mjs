import fs from "node:fs";
import path from "node:path";

const [repoRootArg, installedRootArg, directWorkflowArg] = process.argv.slice(2);
if (!repoRootArg || !installedRootArg || !directWorkflowArg) {
  throw new Error("缺少仓库、安装目录或直连工作流路径参数。");
}

const repoRoot = path.resolve(repoRootArg);
const installedRoot = path.resolve(installedRootArg);
const directWorkflow = path.resolve(directWorkflowArg);
const stamp = "20260904-portrait-batch";

const runtimeFiles = [
  "nodes.py",
  "server.py",
  "portrait_nodes.py",
  path.join("data", "portrait_generator_v12.json"),
  path.join("locales", "zh", "nodeDefs.json"),
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
  version: 6,
  adult_content: false,
  auto_random: false,
  selected: {},
  enabled: {},
  overrides: {},
  pinned: {},
  locked: {},
  section_locked: {},
  section_lock_items: {},
  section_enabled: {},
  option_overrides: {},
});

const migratePortraitState = (node) => {
  let previous = {};
  const source = node.widgets_values_named?.state_json ?? node.widgets_values?.[0];
  try { previous = JSON.parse(String(source || "")); } catch { previous = {}; }
  if (!previous || typeof previous !== "object" || Array.isArray(previous)) previous = {};
  const previousVersion = Number(previous.version || 0);
  const next = { ...JSON.parse(defaultState), ...previous, version: 6 };
  delete next.expanded;
  for (const key of ["selected", "enabled", "overrides", "pinned", "locked", "section_locked", "section_lock_items", "section_enabled", "option_overrides"]) {
    if (!next[key] || typeof next[key] !== "object" || Array.isArray(next[key])) next[key] = {};
  }
  if (previousVersion < 6) {
    const targets = {
      camera: ["shooting_light"], light: ["shooting_light"],
      person: ["subject", "person_detail"],
      makeup: ["styling_expression"], expression: ["styling_expression"],
      cloth: ["wear_state", "clothing", "accessories", "clothing_expression"],
    };
    for (const collectionName of ["section_locked", "section_enabled"]) {
      const collection = next[collectionName];
      for (const [legacyId, nextIds] of Object.entries(targets)) {
        if (!Object.prototype.hasOwnProperty.call(collection, legacyId)) continue;
        const value = collection[legacyId];
        for (const nextId of nextIds) {
          if (collectionName === "section_locked") collection[nextId] = Boolean(collection[nextId] || value);
          else if (collection[nextId] == null || value === false) collection[nextId] = value;
        }
        delete collection[legacyId];
      }
    }
  }
  next.auto_random = Boolean(next.auto_random);
  const serialized = JSON.stringify(next);
  const values = Array.isArray(node.widgets_values) ? node.widgets_values : [];
  const named = node.widgets_values_named || {};
  const seed = Number(named.seed ?? values[1] ?? 0);
  const controlAfterGenerate = String(
    named.control_after_generate ?? (typeof values[2] === "string" ? values[2] : "randomize"),
  );
  const adultContent = Boolean(
    named.adult_content ?? (typeof values[2] === "string" ? values[3] : values[2]) ?? next.adult_content,
  );
  const rawQuantity = Number(
    named.quantity ?? (typeof values[2] === "string" ? values[4] : values[3]) ?? 1,
  );
  const quantity = Math.max(1, Math.min(100, Number.isFinite(rawQuantity) ? Math.trunc(rawQuantity) : 1));
  node.widgets_values = [serialized, seed, controlAfterGenerate, adultContent, quantity];
  node.widgets_values_named = {
    ...named,
    state_json: serialized,
    seed,
    control_after_generate: controlAfterGenerate,
    adult_content: adultContent,
    quantity,
  };
  node.size = [Math.max(470, Number(node.size?.[0]) || 470), 171];
  node.properties = { ...(node.properties || {}), ver: "local-portrait-batch-v1" };
};

const removeLink = (workflow, linkId) => {
  if (linkId == null) return;
  const link = workflow.links.find((item) => item[0] === linkId);
  if (link) {
    const source = workflow.nodes.find((node) => node.id === link[1]);
    const output = source?.outputs?.[link[2]];
    if (output?.links) output.links = output.links.filter((id) => id !== linkId);
    const target = workflow.nodes.find((node) => node.id === link[3]);
    const input = target?.inputs?.[link[4]];
    if (input?.link === linkId) input.link = null;
  }
  workflow.links = workflow.links.filter((item) => item[0] !== linkId);
};

const normalizePortraitPorts = (workflow, node) => {
  const oldInputs = Array.isArray(node.inputs) ? node.inputs : [];
  const oldOutputs = Array.isArray(node.outputs) ? node.outputs : [];
  const inputDefs = [
    { label: "state_json", localized_name: "state_json", name: "state_json", type: "STRING", widget: { name: "state_json" } },
    { label: "seed", localized_name: "seed", name: "seed", type: "INT", widget: { name: "seed" } },
    { label: "adult_content", localized_name: "adult_content", name: "adult_content", type: "BOOLEAN", widget: { name: "adult_content" } },
    { label: "数量", localized_name: "数量", name: "quantity", type: "INT", widget: { name: "quantity" } },
    { label: "reference_analysis", localized_name: "reference_analysis", name: "reference_analysis", shape: 7, type: "STRING" },
  ];
  const outputDefs = [
    { label: "portrait_prompt", localized_name: "portrait_prompt", name: "portrait_prompt", shape: 6, type: "STRING", links: [] },
    { label: "selection_json", localized_name: "selection_json", name: "selection_json", type: "STRING", links: [] },
    { label: "status", localized_name: "status", name: "status", type: "STRING", links: [] },
  ];

  for (const link of [...workflow.links]) {
    if (link[3] === node.id) {
      const inputName = oldInputs[link[4]]?.name;
      const nextSlot = inputDefs.findIndex((input) => input.name === inputName);
      if (nextSlot < 0) removeLink(workflow, link[0]);
      else link[4] = nextSlot;
    }
    if (link[1] === node.id) {
      const outputName = oldOutputs[link[2]]?.name;
      const nextSlot = outputDefs.findIndex((output) => output.name === outputName);
      if (nextSlot < 0) removeLink(workflow, link[0]);
      else {
        link[2] = nextSlot;
        outputDefs[nextSlot].links.push(link[0]);
      }
    }
  }
  for (const input of inputDefs) {
    input.link = workflow.links.find((link) => link[3] === node.id && inputDefs[link[4]]?.name === input.name)?.[0] ?? null;
  }
  node.inputs = inputDefs;
  node.outputs = outputDefs;
};

const nextNodeId = (workflow) => Math.max(Number(workflow.last_node_id || 0), ...workflow.nodes.map((node) => Number(node.id) || 0)) + 1;
const nextLinkId = (workflow) => Math.max(Number(workflow.last_link_id || 0), ...workflow.links.map((link) => Number(link[0]) || 0)) + 1;
const nextOrder = (workflow) => Math.max(0, ...workflow.nodes.map((node) => Number(node.order) || 0)) + 1;

const portraitNode = (id, position, order) => ({
  id,
  type: "ZFPortraitPromptGenerator",
  pos: position,
  size: [470, 171],
  flags: {},
  order,
  mode: 0,
  inputs: [
    { label: "state_json", localized_name: "state_json", name: "state_json", type: "STRING", widget: { name: "state_json" } },
    { label: "seed", localized_name: "seed", name: "seed", type: "INT", widget: { name: "seed" } },
    { label: "adult_content", localized_name: "adult_content", name: "adult_content", type: "BOOLEAN", widget: { name: "adult_content" } },
    { label: "数量", localized_name: "数量", name: "quantity", type: "INT", widget: { name: "quantity" } },
    { label: "reference_analysis", localized_name: "reference_analysis", name: "reference_analysis", shape: 7, type: "STRING" },
  ],
  outputs: [
    { label: "portrait_prompt", localized_name: "portrait_prompt", name: "portrait_prompt", shape: 6, type: "STRING", links: [] },
    { label: "selection_json", localized_name: "selection_json", name: "selection_json", type: "STRING" },
    { label: "status", localized_name: "status", name: "status", type: "STRING" },
  ],
  properties: {
    aux_id: "Z-yaofang/ZF-ComfyUI-PromptDirector",
    ver: "local-portrait-batch-v1",
    "Node name for S&R": "ZFPortraitPromptGenerator",
    widget_ue_connectable: {},
  },
  widgets_values: [defaultState, 0, "randomize", false, 1],
  widgets_values_named: {
    state_json: defaultState,
    seed: 0,
    control_after_generate: "randomize",
    adult_content: false,
    quantity: 1,
  },
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
  normalizePortraitPorts(workflow, node);
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
  node.outputs[0].links = [...new Set([...(node.outputs[0].links || []), linkId])];
  target.inputs[1].link = linkId;
  workflow.last_node_id = Math.max(Number(workflow.last_node_id || 0), node.id);
  workflow.last_link_id = Math.max(Number(workflow.last_link_id || 0), linkId);
  saveWorkflow(workflowPath, workflow);
  return { nodeId: node.id, linkId, target: `${target.id}.text` };
};

const result = {
  installedRoot,
  directBackup: backup(directWorkflow),
  direct: wireDirectPrompt(directWorkflow),
};
console.log(JSON.stringify(result, null, 2));
