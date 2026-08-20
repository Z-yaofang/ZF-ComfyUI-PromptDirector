import { app } from "/scripts/app.js";

const EXTENSION_NAME = "ZF.PromptDirector.MultiTextSelector";
const NODE_NAME = "ZFPromptDirectorMultiTextSelector";
const MAX_ROUTES = 32;

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
      border: 1px solid #59616b;
      border-radius: 6px;
      background: #25292f;
      color: #d8dde4;
      cursor: pointer;
    }
    .zf-pd-mts-buttons button:hover { border-color: #8eacc2; }
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

function routeNumber(input) {
  const match = /^text_(\d+)$/.exec(input?.name || "");
  return match ? Number(match[1]) : null;
}

function hideStateWidget(widget) {
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.type = "converted-widget:zf-prompt-director-multi-text-selector";
  if (widget.inputEl) widget.inputEl.style.display = "none";
  if (widget.element) widget.element.style.display = "none";
}

function firstLinkedRoute(node, count) {
  for (let index = 1; index <= count; index++) {
    const input = node.inputs?.find((item) => item.name === `text_${index}`);
    if (input?.link != null) return index;
  }
  return 1;
}

function attachMultiTextSelector(node) {
  if (node.__zfPromptDirectorMultiTextSelectorAttached) {
    node.__zfPromptDirectorMultiTextSelectorSync?.();
    return;
  }

  const countWidget = node.widgets?.find((widget) => widget.name === "input_count");
  const selectedWidget = node.widgets?.find((widget) => widget.name === "selected");
  if (!countWidget || !selectedWidget) return;
  node.__zfPromptDirectorMultiTextSelectorAttached = true;
  hideStateWidget(selectedWidget);

  const root = document.createElement("div");
  root.className = "zf-pd-mts-root";
  const title = document.createElement("div");
  title.className = "zf-pd-mts-title";
  title.textContent = "单路选择";
  const buttons = document.createElement("div");
  buttons.className = "zf-pd-mts-buttons";
  const status = document.createElement("div");
  status.className = "zf-pd-mts-status";
  root.append(title, buttons, status);

  const markChanged = () => {
    node.graph?.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
  };

  const setSelected = (index) => {
    const count = clampCount(countWidget.value);
    const requested = Number(index) || 0;
    selectedWidget.value = requested === 0 ? 0 : Math.max(1, Math.min(count, requested));
    selectedWidget.callback?.(selectedWidget.value);
    renderButtons();
    markChanged();
  };

  const renderButtons = () => {
    const count = clampCount(countWidget.value);
    const rawSelected = Number(selectedWidget.value);
    const selected = rawSelected === 0 ? 0 : Math.max(1, Math.min(count, rawSelected || 1));
    buttons.replaceChildren();
    for (let index = 1; index <= count; index++) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = String(index);
      button.title = `选择文本路线 ${index}`;
      button.classList.toggle("active", index === selected);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setSelected(index);
      });
      buttons.appendChild(button);
    }
    const emptyButton = document.createElement("button");
    emptyButton.type = "button";
    emptyButton.textContent = "空文本";
    emptyButton.title = "显式输出空文本";
    emptyButton.classList.toggle("active", selected === 0);
    emptyButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      setSelected(0);
    });
    buttons.appendChild(emptyButton);
    status.textContent = selected === 0
      ? "当前路线：空文本"
      : `当前路线 ${selected}；只执行这一条路线`;
  };

  const syncInputs = () => {
    const count = clampCount(countWidget.value);
    countWidget.value = count;

    const currentRoutes = (node.inputs || [])
      .map((input) => ({ input, number: routeNumber(input) }))
      .filter((entry) => entry.number != null)
      .sort((left, right) => right.number - left.number);
    for (const entry of currentRoutes) {
      if (entry.number <= count) continue;
      const slot = node.inputs.indexOf(entry.input);
      if (slot >= 0) node.removeInput(slot);
    }

    for (let index = 1; index <= count; index++) {
      if (node.inputs?.some((input) => input.name === `text_${index}`)) continue;
      node.addInput(`text_${index}`, "STRING", { label: `文本 ${index}`, shape: 7 });
    }

    const selected = Number(selectedWidget.value) || 1;
    if (selected > count || selected < 0) {
      selectedWidget.value = firstLinkedRoute(node, count);
      selectedWidget.callback?.(selectedWidget.value);
    }

    renderButtons();
    const computed = node.computeSize?.();
    if (computed) node.setSize([Math.max(340, node.size?.[0] || 0), Math.max(computed[1], 150)]);
    markChanged();
  };

  const originalCountCallback = countWidget.callback;
  countWidget.callback = function (value) {
    originalCountCallback?.call(this, value);
    setTimeout(syncInputs, 0);
  };

  const domWidget = node.addDOMWidget("route_buttons", "zf-prompt-director-multi-text-selector", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 72 + Math.ceil(clampCount(countWidget.value) / 5) * 30,
    getMaxHeight: () => 72 + Math.ceil(clampCount(countWidget.value) / 5) * 30,
  });
  domWidget.serialize = false;
  node.__zfPromptDirectorMultiTextSelectorSync = syncInputs;
  syncInputs();
}

installStyles();

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onNodeCreated = function () {
      originalCreated?.apply(this, arguments);
      setTimeout(() => attachMultiTextSelector(this), 0);
    };
    nodeType.prototype.onConfigure = function () {
      originalConfigure?.apply(this, arguments);
      setTimeout(() => attachMultiTextSelector(this), 0);
    };
  },
});
