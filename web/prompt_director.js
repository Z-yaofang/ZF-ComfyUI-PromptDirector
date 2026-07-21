import { app } from "/scripts/app.js";

const EXTENSION_NAME = "ZF.PromptDirector";
const RECOMMENDATION_STORAGE_KEY = "zf-prompt-director:recommended-pairing";
let catalogPromise = null;

function loadRecommendationPreference() {
  try {
    return localStorage.getItem(RECOMMENDATION_STORAGE_KEY) !== "off";
  } catch (_error) {
    return true;
  }
}

function saveRecommendationPreference(enabled) {
  try {
    localStorage.setItem(RECOMMENDATION_STORAGE_KEY, enabled ? "on" : "off");
  } catch (_error) {
    // Browser privacy settings may disable storage; the current dialog still works.
  }
}

function loadCatalog(forceRefresh = false) {
  if (forceRefresh) catalogPromise = null;
  if (!catalogPromise) {
    catalogPromise = fetch(`/zf-prompt-director/catalog?_=${Date.now()}`, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error(`Catalog request failed: ${response.status}`);
      return response.json();
    });
  }
  return catalogPromise;
}

function injectStylesheet() {
  if (document.querySelector("link[data-zf-prompt-director]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/extensions/ZF-ComfyUI-PromptDirector/prompt_director.css";
  link.dataset.zfPromptDirector = "true";
  document.head.appendChild(link);
}

function uid(purpose, visual) {
  return `${purpose}__${visual}__${Date.now()}__${Math.random().toString(16).slice(2)}`;
}

function parseSelection(value, fallback = []) {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value) : value;
    return Array.isArray(parsed) ? parsed : fallback;
  } catch (_error) {
    return fallback;
  }
}

function makeButton(label, title, onClick, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `zf-pd-icon-button ${className}`.trim();
  button.textContent = label;
  button.title = title;
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    onClick(event);
  });
  return button;
}

function escapeSvgText(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
  }[char]));
}

function visualPlaceholder(method) {
  const palettes = [
    ["#172c45", "#3d8ab8"], ["#302544", "#8c68bb"], ["#123a39", "#4aa18b"],
    ["#4a2b27", "#c27b50"], ["#3b3340", "#b17ba2"], ["#23362b", "#8eb66e"],
  ];
  let hash = 0;
  for (const char of String(method.id || method.name || "")) hash = ((hash * 31) + char.charCodeAt(0)) >>> 0;
  const [from, to] = palettes[hash % palettes.length];
  const name = escapeSvgText(String(method.name || "创意方法").slice(0, 18));
  const category = escapeSvgText(String(method.category || "").slice(0, 18));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient></defs><rect width="640" height="360" fill="url(#g)"/><path d="M42 286C142 178 232 292 322 176S494 89 604 162" fill="none" stroke="rgba(255,255,255,.24)" stroke-width="4"/><circle cx="510" cy="94" r="70" fill="none" stroke="rgba(255,255,255,.18)" stroke-width="18"/><rect x="43" y="47" width="204" height="14" rx="7" fill="rgba(255,255,255,.3)"/><rect x="43" y="76" width="132" height="8" rx="4" fill="rgba(255,255,255,.22)"/><text x="43" y="238" fill="#fff" font-family="Inter, Microsoft YaHei, sans-serif" font-size="32" font-weight="700">${name}</text><text x="43" y="274" fill="rgba(255,255,255,.74)" font-family="Inter, Microsoft YaHei, sans-serif" font-size="18">${category}</text></svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function createChooser(catalog, initialPurposeId, onChoose) {
  const purposeById = new Map(catalog.purposes.map((item) => [item.id, item]));
  const visualById = new Map(catalog.visual_methods.map((item) => [item.id, item]));
  const visualCatalogOrder = new Map(catalog.visual_methods.map((item, index) => [item.id, index]));
  const recommendationPreference = loadRecommendationPreference();
  const recommendations = catalog.purpose_visual_recommendations || {};
  const initialPurpose = purposeById.has(initialPurposeId) ? initialPurposeId : catalog.purposes[0]?.id;
  const recommendedVisuals = (purposeId) =>
    (Array.isArray(recommendations[purposeId]) ? recommendations[purposeId] : [])
      .filter((visualId) => visualById.has(visualId));
  const overlay = document.createElement("div");
  overlay.className = "zf-pd-overlay";
  const modal = document.createElement("div");
  modal.className = "zf-pd-modal";
  overlay.appendChild(modal);

  const state = {
    purposeId: initialPurpose,
    purposeQuery: "",
    query: "",
    visualCategory: "全部",
    visualId: recommendationPreference ? recommendedVisuals(initialPurpose)[0] || null : null,
    recommendationEnabled: recommendationPreference,
  };

  const close = () => overlay.remove();
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) close();
  });

  const header = document.createElement("header");
  header.className = "zf-pd-modal-header";
  header.innerHTML = `<div><h2>添加创意组合</h2><p>先选择作品用途，再选择一种主视觉方法。</p></div>`;
  header.appendChild(makeButton("×", "关闭", close, "zf-pd-close"));
  modal.appendChild(header);

  const toolbar = document.createElement("div");
  toolbar.className = "zf-pd-toolbar";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "搜索视觉方法、说明或分类…";
  search.addEventListener("input", () => {
    state.query = search.value.trim().toLowerCase();
    renderVisuals();
  });
  toolbar.appendChild(search);
  modal.appendChild(toolbar);

  const body = document.createElement("div");
  body.className = "zf-pd-modal-body";
  const purposePane = document.createElement("aside");
  purposePane.className = "zf-pd-purpose-pane";
  const visualPane = document.createElement("div");
  visualPane.className = "zf-pd-visual-pane";
  body.append(purposePane, visualPane);
  modal.appendChild(body);

  const purposeHeader = document.createElement("div");
  purposeHeader.className = "zf-pd-purpose-header";
  const purposeTitle = document.createElement("h3");
  purposeTitle.textContent = "用途";
  const recommendationToggle = document.createElement("label");
  recommendationToggle.className = "zf-pd-recommend-toggle";
  recommendationToggle.title = "选择用途时自动搭配更合适的视觉方法";
  const recommendationInput = document.createElement("input");
  recommendationInput.type = "checkbox";
  recommendationInput.checked = state.recommendationEnabled;
  const recommendationTrack = document.createElement("span");
  recommendationTrack.className = "zf-pd-recommend-track";
  const recommendationLabel = document.createElement("span");
  recommendationLabel.textContent = "推荐搭配";
  recommendationToggle.append(recommendationInput, recommendationTrack, recommendationLabel);
  purposeHeader.append(purposeTitle, recommendationToggle);
  purposePane.appendChild(purposeHeader);
  const purposeSearch = document.createElement("input");
  purposeSearch.type = "search";
  purposeSearch.className = "zf-pd-purpose-search";
  purposeSearch.placeholder = "搜索用途…";
  purposeSearch.addEventListener("input", () => {
    state.purposeQuery = purposeSearch.value.trim().toLowerCase();
    renderPurposes();
  });
  purposePane.appendChild(purposeSearch);
  const purposeList = document.createElement("div");
  purposeList.className = "zf-pd-purpose-list";
  purposePane.appendChild(purposeList);

  function renderPurposes() {
    purposeList.replaceChildren();
    const groupedPurposes = new Map();
    for (const item of catalog.purposes) {
      const haystack = `${item.name} ${item.description} ${item.category}`.toLowerCase();
      if (state.purposeQuery && !haystack.includes(state.purposeQuery)) continue;
      if (!groupedPurposes.has(item.category)) groupedPurposes.set(item.category, []);
      groupedPurposes.get(item.category).push(item);
    }
    for (const [category, items] of groupedPurposes.entries()) {
      const group = document.createElement("section");
      const label = document.createElement("div");
      label.className = "zf-pd-category-label";
      label.textContent = category;
      group.appendChild(label);
      for (const purpose of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "zf-pd-purpose-item";
        button.dataset.id = purpose.id;
        button.innerHTML = `<strong>${purpose.name}</strong><span>${purpose.description}</span>`;
        button.addEventListener("click", () => {
          state.purposeId = purpose.id;
          if (state.recommendationEnabled) {
            state.visualId = recommendedVisuals(purpose.id)[0] || null;
            state.visualCategory = "全部";
            state.query = "";
            search.value = "";
            categoryBar.querySelectorAll("button").forEach((node) =>
              node.classList.toggle("selected", node.textContent === "全部"),
            );
            visualPane.scrollTop = 0;
          }
          renderPurposes();
          renderVisuals();
        });
        button.classList.toggle("selected", purpose.id === state.purposeId);
        group.appendChild(button);
      }
      purposeList.appendChild(group);
    }
    if (!groupedPurposes.size) {
      const empty = document.createElement("div");
      empty.className = "zf-pd-empty";
      empty.textContent = "没有匹配用途。";
      purposeList.appendChild(empty);
    }
  }

  const categoryBar = document.createElement("div");
  categoryBar.className = "zf-pd-filter-chips";
  visualPane.appendChild(categoryBar);
  const categories = ["全部", ...new Set(catalog.visual_methods.map((item) => item.category))];
  for (const category of categories) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = category;
    button.className = category === "全部" ? "selected" : "";
    button.addEventListener("click", () => {
      state.visualCategory = category;
      categoryBar.querySelectorAll("button").forEach((node) =>
        node.classList.toggle("selected", node.textContent === category),
      );
      renderVisuals();
    });
    categoryBar.appendChild(button);
  }

  const cards = document.createElement("div");
  cards.className = "zf-pd-card-grid";
  visualPane.appendChild(cards);

  recommendationInput.addEventListener("change", () => {
    state.recommendationEnabled = recommendationInput.checked;
    saveRecommendationPreference(state.recommendationEnabled);
    if (state.recommendationEnabled) {
      state.visualId = recommendedVisuals(state.purposeId)[0] || state.visualId;
      state.visualCategory = "全部";
      state.query = "";
      search.value = "";
      categoryBar.querySelectorAll("button").forEach((node) =>
        node.classList.toggle("selected", node.textContent === "全部"),
      );
      visualPane.scrollTop = 0;
    }
    renderVisuals();
  });

  function renderVisuals() {
    cards.replaceChildren();
    const methods = catalog.visual_methods.filter((method) => {
      const categoryMatch = state.visualCategory === "全部" || method.category === state.visualCategory;
      const haystack = `${method.name} ${method.description} ${method.category}`.toLowerCase();
      return categoryMatch && (!state.query || haystack.includes(state.query));
    });
    if (state.recommendationEnabled) {
      const recommendedOrder = new Map(recommendedVisuals(state.purposeId).map((visualId, index) => [visualId, index]));
      methods.sort((left, right) => {
        const leftOrder = recommendedOrder.has(left.id) ? recommendedOrder.get(left.id) : Number.MAX_SAFE_INTEGER;
        const rightOrder = recommendedOrder.has(right.id) ? recommendedOrder.get(right.id) : Number.MAX_SAFE_INTEGER;
        return leftOrder - rightOrder
          || (visualCatalogOrder.get(left.id) ?? 0) - (visualCatalogOrder.get(right.id) ?? 0);
      });
    }
    for (const method of methods) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "zf-pd-card";
      card.dataset.id = method.id;
      card.classList.toggle("selected", method.id === state.visualId);
      const image = document.createElement("img");
      image.loading = "lazy";
      image.alt = method.name;
      image.src = method.thumbnail
        ? `/zf-prompt-director/thumbnail/${encodeURIComponent(method.thumbnail)}`
        : visualPlaceholder(method);
      image.addEventListener("error", () => { image.src = visualPlaceholder(method); }, { once: true });
      const content = document.createElement("div");
      content.innerHTML = `<div class="zf-pd-card-top"><strong>${method.name}</strong><small>${method.category}</small></div><p>${method.description}</p>`;
      card.append(image, content);
      card.addEventListener("click", () => {
        state.visualId = method.id;
        cards.querySelectorAll(".zf-pd-card").forEach((node) =>
          node.classList.toggle("selected", node.dataset.id === method.id),
        );
        updateFooter();
      });
      cards.appendChild(card);
    }
    updateFooter();
  }

  const footer = document.createElement("footer");
  footer.className = "zf-pd-modal-footer";
  const summary = document.createElement("span");
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "取消";
  cancel.addEventListener("click", close);
  const add = document.createElement("button");
  add.type = "button";
  add.className = "primary";
  add.textContent = "添加组合";
  add.addEventListener("click", () => {
    if (!state.purposeId || !state.visualId) return;
    onChoose(state.purposeId, state.visualId);
    close();
  });
  footer.append(summary, cancel, add);
  modal.appendChild(footer);

  function updateFooter() {
    const purpose = purposeById.get(state.purposeId);
    const visual = visualById.get(state.visualId);
    summary.textContent = visual ? `${purpose?.name || "未选用途"} / ${visual.name}` : `${purpose?.name || "未选用途"} / 请选择视觉方法`;
    add.disabled = !(purpose && visual);
  }

  renderPurposes();
  renderVisuals();
  document.body.appendChild(overlay);
  search.focus();
}

function attachDirectorUI(node) {
  const configWidget = node.widgets?.find((widget) => widget.name === "selection_json");
  const presetWidget = node.widgets?.find((widget) => widget.name === "additional_preset");
  const referenceModeWidget = node.widgets?.find((widget) => widget.name === "reference_mode");
  if (!configWidget || node.__zfPromptDirectorAttached) return;
  node.__zfPromptDirectorAttached = true;

  [configWidget, presetWidget, referenceModeWidget].filter(Boolean).forEach((widget) => {
    widget.hidden = true;
    widget.options = { ...(widget.options || {}), hidden: true };
    widget.computeSize = () => [0, -4];
    widget.type = "converted-widget";
    if (widget.inputEl) widget.inputEl.style.display = "none";
    if (widget.element) widget.element.style.display = "none";
  });

  const root = document.createElement("div");
  root.className = "zf-pd-node";
  const controls = document.createElement("div");
  controls.className = "zf-pd-native-controls";
  if (referenceModeWidget) {
    const row = document.createElement("label");
    row.className = "zf-pd-native-control";
    const label = document.createElement("span");
    label.textContent = "参考图模式";
    const select = document.createElement("select");
    select.title = "选择创意迁移，或只测试参考图提取出的临时用途与创意";
    const values = Array.isArray(referenceModeWidget.options?.values)
      ? referenceModeWidget.options.values
      : [referenceModeWidget.value].filter(Boolean);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = String(value);
      select.appendChild(option);
    }
    select.value = String(referenceModeWidget.value ?? values[0] ?? "");
    select.addEventListener("change", () => {
      referenceModeWidget.value = select.value;
      referenceModeWidget.callback?.(referenceModeWidget.value);
      node.graph?.setDirtyCanvas?.(true, true);
      node.setDirtyCanvas?.(true, true);
    });
    row.append(label, select);
    controls.appendChild(row);
  }
  const status = document.createElement("div");
  status.className = "zf-pd-node-status";
  const list = document.createElement("div");
  list.className = "zf-pd-node-list";
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "zf-pd-add";
  addButton.textContent = "＋ 添加创意组合";
  const presetToggle = document.createElement("button");
  presetToggle.type = "button";
  presetToggle.className = "zf-pd-preset-toggle";
  const presetWrap = document.createElement("div");
  presetWrap.className = "zf-pd-preset-wrap";
  const presetEditor = document.createElement("textarea");
  presetEditor.placeholder = "只填写当前任务确实需要、且用途与视觉模块无法表达的特殊规则；通常留空。";
  presetEditor.value = String(presetWidget?.value || "");
  presetWrap.appendChild(presetEditor);
  root.append(controls, status, list, addButton, presetToggle, presetWrap);

  let catalog = null;
  let selection = parseSelection(configWidget.value, []);
  let presetOpen = Boolean(presetEditor.value.trim());
  const controlsHeight = referenceModeWidget ? 36 : 0;

  const getDirectorHeight = () => (
    132 + controlsHeight + selection.length * 42 + (presetOpen ? 116 : 0)
  );

  const resizeNode = ({ allowShrink = false } = {}) => {
    const computed = node.computeSize?.();
    const requiredHeight = Math.max(360, 245 + getDirectorHeight(), Number(computed?.[1] || 0));
    const currentHeight = Number(node.size?.[1] || 0);
    const height = allowShrink ? requiredHeight : Math.max(currentHeight, requiredHeight);
    node.setSize([Math.max(node.size?.[0] || 0, Number(computed?.[0] || 0), 520), height]);
  };

  const renderPreset = () => {
    presetToggle.textContent = `${presetOpen ? "－" : "＋"} 高级：附加规则（可选${presetEditor.value.trim() ? "，已有内容" : ""}）`;
    presetWrap.classList.toggle("open", presetOpen);
    resizeNode();
  };

  presetToggle.addEventListener("click", () => {
    presetOpen = !presetOpen;
    renderPreset();
    if (presetOpen) presetEditor.focus();
  });

  presetEditor.addEventListener("input", () => {
    if (presetWidget) {
      presetWidget.value = presetEditor.value;
      presetWidget.callback?.(presetWidget.value);
    }
    node.graph?.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
  });

  const save = () => {
    configWidget.value = JSON.stringify(selection);
    configWidget.callback?.(configWidget.value);
    node.graph?.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
  };

  const updateStatus = () => {
    const activeCount = selection.filter((item) => item.enabled !== false).length;
    status.innerHTML = `<strong>${activeCount}</strong> 个组合生效 <span>首项为主导，后续项仅作补充</span>`;
  };

  const render = () => {
    if (!catalog) return;
    const purposeMap = new Map(catalog.purposes.map((item) => [item.id, item]));
    const visualMap = new Map(catalog.visual_methods.map((item) => [item.id, item]));
    list.replaceChildren();
    updateStatus();

    selection.forEach((entry, index) => {
      const purpose = purposeMap.get(entry.purpose);
      const visual = visualMap.get(entry.visual);
      if (!purpose || !visual) return;
      const row = document.createElement("div");
      row.className = `zf-pd-row ${entry.enabled === false ? "disabled" : ""}`;
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = entry.enabled !== false;
      toggle.title = "启用此组合";
      toggle.addEventListener("change", () => {
        entry.enabled = toggle.checked;
        row.classList.toggle("disabled", !toggle.checked);
        save();
        updateStatus();
      });
      const label = document.createElement("div");
      label.className = "zf-pd-row-label";
      label.innerHTML = `<strong>${purpose.name}</strong><span>${visual.name}</span>`;
      label.title = `${purpose.description}\n${visual.description}`;
      const strength = document.createElement("input");
      strength.type = "number";
      strength.min = "0";
      strength.max = "2";
      strength.step = "0.1";
      strength.value = Number(entry.strength ?? 1).toFixed(1);
      strength.title = "组合权重";
      strength.addEventListener("change", () => {
        entry.strength = Math.max(0, Math.min(2, Number(strength.value) || 0));
        save();
      });
      const actions = document.createElement("div");
      actions.className = "zf-pd-row-actions";
      actions.append(
        makeButton("↑", "上移", () => {
          if (index <= 0) return;
          [selection[index - 1], selection[index]] = [selection[index], selection[index - 1]];
          save(); render();
        }),
        makeButton("↓", "下移", () => {
          if (index >= selection.length - 1) return;
          [selection[index + 1], selection[index]] = [selection[index], selection[index + 1]];
          save(); render();
        }),
        makeButton("×", "删除", () => {
          selection.splice(index, 1);
          save(); render();
        }, "danger"),
      );
      row.append(toggle, label, strength, actions);
      list.appendChild(row);
    });

    if (!selection.length) {
      const empty = document.createElement("div");
      empty.className = "zf-pd-empty";
      empty.textContent = "尚未添加组合；运行时采用“人物与场景摄影 / 直接表现”作为默认组合。";
      list.appendChild(empty);
    }
    resizeNode();
  };

  addButton.addEventListener("click", async () => {
    catalog = await loadCatalog(true);
    const lastPurpose = selection.at(-1)?.purpose || catalog.purposes[0]?.id;
    createChooser(catalog, lastPurpose, (purpose, visual) => {
      selection.push({ id: uid(purpose, visual), purpose, visual, enabled: true, strength: 1.0 });
      save();
      render();
    });
  });

  const domWidget = node.addDOMWidget("zf_prompt_director_ui", "zf-prompt-director", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => getDirectorHeight(),
    getMaxHeight: () => getDirectorHeight(),
  });
  domWidget.serialize = false;
  renderPreset();

  loadCatalog()
    .then((data) => {
      catalog = data;
      if (!selection.length) selection = parseSelection(configWidget.value, data.default_combinations || []);
      save();
      render();
    })
    .catch((error) => {
      status.textContent = `目录加载失败：${error.message}`;
    });
}

injectStylesheet();

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "ZFPromptDirector") return;
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      original?.apply(this, arguments);
      setTimeout(() => attachDirectorUI(this), 0);
    };
  },
});
