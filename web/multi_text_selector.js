import { app } from "/scripts/app.js";
import { pinDOMWidgetFullWidth } from "./dom_widget_layout.mjs";

const EXTENSION_NAME = "ZF.PromptDirector.MultiTextSelector";
const NODE_NAME = "ZFPromptDirectorMultiTextSelector";
const MAX_ROUTES = 32;
const SELECTORS = {
  [NODE_NAME]: { prefix: "text", type: "STRING", label: "文本" },
  ZHMultiImageSelector: { prefix: "image", type: "IMAGE", label: "图片" },
  ZHMultiVideoSelector: { prefix: "video", type: "IMAGE", label: "视频", note: "视频帧批次，不含原声" },
  ZHMultiAudioSelector: { prefix: "audio", type: "AUDIO", label: "音频" },
};
const MANUAL_SELECTION = "zf_multi_selector_manual_selected";

function installStyles() {
  if (document.getElementById("zf-prompt-director-multi-text-selector-style")) return;
  const style = document.createElement("style");
  style.id = "zf-prompt-director-multi-text-selector-style";
  style.textContent = `
    .zf-pd-mts-root {
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 8px 8px 6px;
      box-sizing: border-box;
      font: 12px/1.25 Inter, system-ui, sans-serif;
      color: var(--input-text, #ddd);
    }
    .zf-pd-mts-title { opacity: .78; }
    .zf-pd-mts-buttons {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(48px, 1fr));
      gap: 5px;
    }
    .zf-pd-mts-buttons button {
      min-height: 26px;
      padding: 3px 4px;
      font: inherit;
      white-space: nowrap;
      border: 1px solid #59616b;
      border-radius: 6px;
      background: #25292f;
      color: #d8dde4;
      cursor: pointer;
    }
    .zf-pd-mts-buttons button:hover { border-color: #8eacc2; }
    .zf-pd-mts-buttons button:focus-visible { outline: 2px solid #8ed8ff; outline-offset: 2px; }
    .zf-pd-mts-buttons button:disabled { cursor: default; }
    .zf-pd-mts-buttons button.active {
      border-color: #58b9e8;
      background: #176587;
      color: white;
      font-weight: 650;
      box-shadow: 0 0 0 1px rgba(88,185,232,.25) inset;
    }
    .zf-pd-mts-status { opacity: .72; font-size: 11px; }
  `;
  document.head.appendChild(style);
}

function clampCount(value) {
  return Math.max(1, Math.min(MAX_ROUTES, Math.round(Number(value) || 1)));
}

function routeNumber(input, prefix) {
  const match = new RegExp(`^${prefix}_(\\d+)$`).exec(input?.name || "");
  return match ? Number(match[1]) : null;
}

function selection(value) {
  return value === undefined ? 1 : value;
}

function validSelection(value, count) {
  return Number.isSafeInteger(value) && value >= 0 && value <= count;
}

function graphLink(graph, id) {
  if (!graph || id == null) return null;
  if (typeof graph.getLink === "function") return graph.getLink(id);
  return graph.links instanceof Map ? graph.links.get(id) : graph.links?.[id];
}

function externalSelection(node) {
  const input = node.inputs?.find(input => input.name === "selected");
  if (input?.link == null) return { linked: false, value: null };
  let link = graphLink(node.graph, input.link);
  const visited = new Set();
  while (link) {
    const source = node.graph?.getNodeById?.(link.origin_id);
    if (!source || visited.has(source.id) || (source.mode != null && source.mode !== 0)) break;
    visited.add(source.id);
    const type = source.comfyClass || source.type || source.constructor?.comfyClass;
    if ((type === "Reroute" && link.origin_slot === 0) || type === "ZFI") {
      const slot = type === "ZFI" ? link.origin_slot : 0;
      link = graphLink(node.graph, source.inputs?.[slot]?.link);
      continue;
    }
    // These nodes return their scalar value unchanged; arbitrary widgets do not
    // describe the result of computation, list, muted, or bypassed nodes.
    if (["PrimitiveInt", "INTConstant", "easy int"].includes(type) && link.origin_slot === 0
      && source.outputs?.[0]?.type === "INT" && !source.outputs[0].is_list
      && source.inputs?.find(input => input.name === "value")?.link == null) {
      const value = source.widgets?.find(widget => widget.name === "value")?.value;
      const afterGenerate = source.widgets?.find(widget => widget.name === "control_after_generate")?.value;
      if (Number.isSafeInteger(value) && (afterGenerate == null || afterGenerate === "fixed")) return { linked: true, value };
    }
    break;
  }
  return { linked: true, value: null };
}

function hideStateWidget(widget) {
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.type = "converted-widget:zf-prompt-director-multi-text-selector";
  if (widget.inputEl) widget.inputEl.style.display = "none";
  if (widget.element) widget.element.style.display = "none";
}

function attachMultiTextSelector(node, config, configured = false) {
  if (node.__zfPromptDirectorMultiTextSelectorAttached) {
    if (configured) node.__zfPromptDirectorMultiTextSelectorRestore?.();
    node.__zfPromptDirectorMultiTextSelectorSync?.();
    return;
  }

  const countWidget = node.widgets?.find((widget) => widget.name === "input_count");
  const selectedWidget = node.widgets?.find((widget) => widget.name === "selected");
  if (!countWidget || !selectedWidget) return;
  node.__zfPromptDirectorMultiTextSelectorAttached = true;
  hideStateWidget(selectedWidget);
  node.properties ||= {};
  let wasExternal = externalSelection(node).linked;
  let manualSelected = selection(wasExternal ? node.properties[MANUAL_SELECTION] ?? selectedWidget.value : selectedWidget.value);
  let renderedState = "";
  let syncing = false;

  const root = document.createElement("div");
  root.className = "zf-pd-mts-root";
  const title = document.createElement("div");
  title.className = "zf-pd-mts-title";
  title.textContent = "单路选择";
  const buttons = document.createElement("div");
  buttons.className = "zf-pd-mts-buttons";
  buttons.setAttribute("role", "group");
  buttons.setAttribute("aria-label", `${config.label}路线选择`);
  const status = document.createElement("div");
  status.className = "zf-pd-mts-status";
  status.setAttribute("role", "status");
  root.append(title, buttons, status);

  const markChanged = () => {
    node.graph?.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
  };

  const setSelected = (index) => {
    if (externalSelection(node).linked) return;
    selectedWidget.value = selection(index);
    selectedWidget.callback?.(selectedWidget.value);
    syncInputs();
  };

  const renderButtons = (external) => {
    const count = clampCount(countWidget.value);
    const selected = external.linked ? external.value : manualSelected;
    const state = JSON.stringify([count, selected, external.linked]);
    if (state === renderedState) return;
    renderedState = state;
    if (buttons.children.length !== count + 1) {
      const focused = buttons.contains(document.activeElement) ? document.activeElement.dataset.route : null;
      buttons.replaceChildren();
      for (const index of [...Array.from({ length: count }, (_, i) => i + 1), 0]) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.route = String(index);
        button.textContent = index === 0 ? `空${config.label}` : String(index);
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          setSelected(index);
        });
        buttons.appendChild(button);
      }
      if (focused != null) buttons.querySelector(`[data-route="${focused}"]`)?.focus();
    }
    for (const button of buttons.children) {
      const index = Number(button.dataset.route);
      const label = index === 0 ? `0：空${config.label}，不执行任何路线` : `选择${config.label}路线 ${index}`;
      button.title = label + (config.note ? `；${config.note}` : "") + (external.linked ? "；请调整上游整数或断开 selected 后手动选择" : "");
      button.setAttribute("aria-label", label);
      button.disabled = external.linked;
      const pressed = validSelection(selected, count) && index === selected;
      button.classList.toggle("active", pressed);
      button.setAttribute("aria-pressed", String(pressed));
    }
    title.textContent = external.linked ? "外部整数控制" : "单路选择";
    const route = selected === 0 ? `0 · 空${config.label}；不执行任何路线` : `路线 ${selected}；只执行这一条路线`;
    status.textContent = external.linked && external.value == null
      ? "外部整数控制：执行时决定；按钮不参与选择"
      : !Number.isSafeInteger(selected) ? `选择 ${selected} 无效；请选择 0–${count} 之间的整数`
        : !validSelection(selected, count) ? `当前共${count}路，选择${selected}越界；请修改整数或增加路线数量`
          : external.linked ? `外部整数控制：${route}` : `当前${route}`;
    if (config.note) status.textContent += `；${config.note}`;
    markChanged();
  };

  const syncInputs = () => {
    if (syncing) return;
    syncing = true;
    try {
      const external = externalSelection(node);
      if (!external.linked) {
        if (wasExternal) selectedWidget.value = manualSelected;
        else manualSelected = selection(selectedWidget.value);
      }
      wasExternal = external.linked;
      node.properties[MANUAL_SELECTION] = manualSelected;
      const count = clampCount(countWidget.value);
      countWidget.value = count;
      let inputsChanged = false;

      const currentRoutes = (node.inputs || [])
        .map((input) => ({ input, number: routeNumber(input, config.prefix) }))
        .filter((entry) => entry.number != null)
        .sort((left, right) => right.number - left.number);
      for (const entry of currentRoutes) {
        if (entry.number <= count) continue;
        const slot = node.inputs.indexOf(entry.input);
        if (slot >= 0) { node.removeInput(slot); inputsChanged = true; }
      }

      for (let index = 1; index <= count; index++) {
        if (node.inputs?.some((input) => input.name === `${config.prefix}_${index}`)) continue;
        node.addInput(`${config.prefix}_${index}`, config.type, { label: `${config.label} ${index}`, shape: 7 });
        inputsChanged = true;
      }

      renderButtons(external);
      if (inputsChanged) {
        const computed = node.computeSize?.();
        if (computed) node.setSize([Math.max(340, node.size?.[0] || 0), Math.max(computed[1], 150)]);
        markChanged();
      }
    } finally { syncing = false; }
  };

  const originalCountCallback = countWidget.callback;
  countWidget.callback = function (value) {
    originalCountCallback?.call(this, value);
    setTimeout(syncInputs, 0);
  };

  const domWidget = node.addDOMWidget("route_buttons", "zf-prompt-director-multi-text-selector", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 72 + Math.ceil((clampCount(countWidget.value) + 1) / 5) * 30,
    getMaxHeight: () => 72 + Math.ceil((clampCount(countWidget.value) + 1) / 5) * 30,
  });
  domWidget.serialize = false;
  pinDOMWidgetFullWidth(domWidget);
  node.__zfPromptDirectorMultiTextSelectorSync = syncInputs;
  node.__zfPromptDirectorMultiTextSelectorRestore = () => {
    wasExternal = externalSelection(node).linked;
    manualSelected = selection(wasExternal ? node.properties[MANUAL_SELECTION] ?? selectedWidget.value : selectedWidget.value);
  };
  // Upstream scalar widget edits do not notify downstream connections. Polling
  // only updates changed DOM state and also works when the canvas is not drawn.
  let refresh = null;
  const startRefresh = () => {
    if (refresh == null) refresh = setInterval(syncInputs, 250);
    syncInputs();
  };
  const originalAdded = node.onAdded;
  node.onAdded = function () {
    const result = originalAdded?.apply(this, arguments);
    startRefresh();
    return result;
  };
  const originalRemoved = node.onRemoved;
  node.onRemoved = function () {
    clearInterval(refresh);
    refresh = null;
    return originalRemoved?.apply(this, arguments);
  };
  startRefresh();
}

installStyles();

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const config = SELECTORS[nodeData.name];
    if (!config) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    const originalConfigure = nodeType.prototype.onConfigure;
    const originalConnectionsChange = nodeType.prototype.onConnectionsChange;
    const originalSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onNodeCreated = function () {
      originalCreated?.apply(this, arguments);
      setTimeout(() => attachMultiTextSelector(this, config), 0);
    };
    nodeType.prototype.onConfigure = function () {
      originalConfigure?.apply(this, arguments);
      setTimeout(() => attachMultiTextSelector(this, config, true), 0);
    };
    nodeType.prototype.onConnectionsChange = function () {
      originalConnectionsChange?.apply(this, arguments);
      setTimeout(() => this.__zfPromptDirectorMultiTextSelectorSync?.(), 0);
    };
    nodeType.prototype.onSerialize = function (info) {
      this.__zfPromptDirectorMultiTextSelectorSync?.();
      if (info) {
        info.properties ||= {};
        info.properties[MANUAL_SELECTION] = this.properties?.[MANUAL_SELECTION];
      }
      return originalSerialize?.apply(this, arguments);
    };
  },
});
