import { app } from "/scripts/app.js";

const EXTENSION_NAME = "ZF.PromptDirector.PortraitGenerator";
const NODE_NAME = "ZFPortraitPromptGenerator";
const CATALOG_URL = "/zf-prompt-director/portrait-catalog";

const CORE_RANDOM_FIELDS = new Set([
  "lens", "viewpoint", "shotSize", "dof", "device", "mainLight", "ambient", "colorTone",
  "temperament", "age", "race", "face", "skin", "texture", "body", "leg", "firstImp",
  "hairLen", "hairColor", "hairCurl", "hairTie", "hairBangs", "hairState",
  "makeup", "makeupDetail", "emotion", "eye", "mouth", "clothCat", "clothItem",
  "outerwear", "collarStyle", "topLength", "bottomStyle", "bottomLength", "clothMat",
  "clothPattern", "clothDeco", "clothLayer", "shoes", "accessory",
  "scene", "prop", "weather", "comp", "compPos",
]);
const ALWAYS_RANDOM_FIELDS = new Set([
  "lens", "viewpoint", "shotSize", "mainLight", "colorTone", "temperament", "age",
  "race", "face", "skin", "body", "leg", "firstImp", "hairLen", "hairColor",
  "emotion", "eye", "mouth", "clothCat", "clothItem", "scene", "comp", "compPos",
]);
const POSTURE_FIELD_IDS = new Set([
  "postureSupine", "postureProne", "postureSide", "postureKneeling", "postureSitting",
  "postureStanding", "postureSquatting", "postureSuspended", "postureSpecial",
  "adultPostureSupine", "adultPostureProne", "adultPostureSide", "adultPostureKneeling",
  "adultPostureSitting", "adultPostureStanding", "adultPostureSquatting",
  "adultPostureSuspended", "adultPostureSpecial",
]);
const ACTION_FIELD_IDS = new Set([
  "actionTransition", "actionWalking", "actionJumping", "actionSpinning",
  "adultActionTransition", "adultActionWalking", "adultActionJumping", "adultActionSpinning",
]);
const MOVEMENT_FIELD_IDS = new Set([...POSTURE_FIELD_IDS, ...ACTION_FIELD_IDS]);

let catalogPromise;

function getCatalog() {
  if (!catalogPromise) {
    catalogPromise = fetch(CATALOG_URL).then((response) => {
      if (!response.ok) throw new Error("人像素材目录加载失败：" + response.status);
      return response.json();
    });
  }
  return catalogPromise;
}

function installStyles() {
  if (document.getElementById("zf-pd-portrait-generator-style")) return;
  const style = document.createElement("style");
  style.id = "zf-pd-portrait-generator-style";
  style.textContent = [
    ".zf-pg-root{box-sizing:border-box;display:flex;flex-direction:column;gap:8px;padding:8px;color:var(--input-text,#ddd);font:12px/1.4 Inter,system-ui,sans-serif}",
    ".zf-pg-toolbar{display:flex;align-items:center;gap:6px}.zf-pg-button{border:1px solid #56616d;border-radius:7px;background:#262b31;color:#e2e7ec;min-height:29px;padding:4px 10px;cursor:pointer}.zf-pg-button:hover{border-color:#75b9df}.zf-pg-add{margin-left:auto;background:#17374b;border-color:#417b9c}",
    ".zf-pg-home-empty{padding:9px 2px;color:#9da8b3}.zf-pg-pinned{display:flex;flex-direction:column;gap:6px;max-height:315px;overflow:auto;padding-right:2px}",
    ".zf-pg-home-row{display:grid;grid-template-columns:24px minmax(105px,.72fr) minmax(145px,1.28fr) 30px 28px;align-items:center;gap:5px;border:1px solid #465661;border-radius:8px;background:#25323a;padding:5px}",
    ".zf-pg-pin,.zf-pg-lock,.zf-pg-remove{border:0;background:transparent;color:#bfd5df;cursor:pointer;padding:2px;font-size:16px}.zf-pg-pin{color:#60c5f4}.zf-pg-lock{font-size:13px}.zf-pg-remove{font-size:17px;color:#aeb9c2}.zf-pg-home-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.zf-pg-value{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;background:#18242b}",
    ".zf-pg-overlay{position:fixed;inset:0;z-index:100000;background:rgba(3,8,13,.82);display:flex;align-items:center;justify-content:center;padding:18px}.zf-pg-dialog{width:min(1540px,96vw);height:min(920px,94vh);display:grid;grid-template-rows:auto minmax(0,1fr) auto;border:1px solid #496276;border-radius:14px;background:#101821;color:#e4ebf1;box-shadow:0 22px 80px #000b;overflow:hidden;font:13px/1.45 Inter,system-ui,sans-serif}",
    ".zf-pg-modal-header{display:flex;align-items:flex-start;gap:12px;padding:17px 20px;border-bottom:1px solid #31414f}.zf-pg-modal-header h2{font-size:21px;margin:0 0 3px}.zf-pg-modal-header p{margin:0;color:#96a6b4}.zf-pg-close{margin-left:auto;border:0;background:transparent;color:#b9c7d2;font-size:26px;cursor:pointer}",
    ".zf-pg-modal-body{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:0}.zf-pg-section-nav{overflow:auto;border-right:1px solid #31414f;padding:12px;display:flex;flex-direction:column;gap:7px}.zf-pg-section-button{border:1px solid transparent;border-radius:9px;background:transparent;color:#bdcad4;padding:10px;text-align:left;cursor:pointer;display:flex;gap:8px;align-items:center}.zf-pg-section-button.active{border-color:#478eb7;background:#173147;color:#eef8ff}.zf-pg-section-button.disabled{opacity:.45;text-decoration:line-through}.zf-pg-section-name{flex:1}.zf-pg-section-meta{font-size:11px;color:#8da1b0}",
    ".zf-pg-main{display:grid;grid-template-rows:auto auto minmax(0,1fr);min-width:0;min-height:0}.zf-pg-section-tools{display:flex;align-items:center;gap:7px;padding:11px 14px 8px;border-bottom:1px solid #263743}.zf-pg-section-tools strong{margin-right:auto;font-size:15px}.zf-pg-tool-active{border-color:#c7924f;color:#ffd598}.zf-pg-tool-danger{border-color:#765660;color:#efc2ca}",
    ".zf-pg-field-tabs{display:flex;gap:7px;overflow:auto;padding:9px 14px;border-bottom:1px solid #263743}.zf-pg-field-tab{flex:0 0 auto;border:1px solid #3c5060;border-radius:999px;background:#17232d;color:#b8c7d2;padding:6px 10px;cursor:pointer}.zf-pg-field-tab.active{background:#1b506d;border-color:#58a8d3;color:white}.zf-pg-field-tab.locked{box-shadow:inset 0 0 0 1px #c79650}.zf-pg-tab-dot{color:#68c7f2;margin-right:5px}",
    ".zf-pg-detail{min-height:0;display:grid;grid-template-rows:auto auto minmax(0,1fr);padding:12px 14px;gap:8px}.zf-pg-detail-head{display:flex;align-items:center;gap:7px}.zf-pg-detail-head h3{margin:0 auto 0 0;font-size:16px}.zf-pg-search{width:min(330px,35vw);border:1px solid #455867;border-radius:7px;background:#131f28;color:#e5edf3;padding:7px 9px}.zf-pg-notice{min-height:18px;color:#ffd18a;font-size:12px}.zf-pg-notice:empty{display:none}",
    ".zf-pg-options{min-height:0;overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));align-content:start;gap:9px}.zf-pg-option{box-sizing:border-box;min-height:78px;border:1px solid #3b4d5c;border-radius:10px;background:#17232d;color:#dce6ed;padding:10px;text-align:left;cursor:pointer}.zf-pg-option:hover{border-color:#5fb2de;background:#1a2b37}.zf-pg-option.selected{border-color:#62c8fa;background:#17445d;box-shadow:inset 0 0 0 1px #62c8fa}.zf-pg-option.locked{border-color:#d5a252;box-shadow:inset 0 0 0 2px #9d7035}.zf-pg-option.locked.selected{border-color:#ffd074;box-shadow:inset 0 0 0 2px #d09a48}.zf-pg-option.modified{border-style:dashed}.zf-pg-option-value{font-weight:700;margin-bottom:5px}.zf-pg-option-badge{float:right;color:#ffc66d;font-size:11px;margin-left:7px}.zf-pg-option-desc{color:#98aab7;font-size:12px;white-space:pre-wrap}.zf-pg-option-editor{grid-column:1/-1;cursor:default}.zf-pg-option-editor textarea{box-sizing:border-box;width:100%;min-height:88px;resize:vertical;border:1px solid #5a7182;border-radius:7px;background:#0f1a22;color:#edf5fa;padding:8px}.zf-pg-option-edit-actions{display:flex;align-items:center;gap:8px;margin-top:8px}.zf-pg-option-edit-actions small{margin-left:auto;color:#8fa0ad}.zf-pg-no-option{grid-column:1/-1;color:#95a5b2;padding:20px 2px}",
    ".zf-pg-modal-footer{display:flex;align-items:center;gap:8px;padding:11px 16px;border-top:1px solid #31414f}.zf-pg-advanced{position:relative}.zf-pg-advanced summary{list-style:none}.zf-pg-adult-box{position:absolute;left:0;bottom:38px;width:330px;padding:11px;border:1px solid #4b5e6c;border-radius:9px;background:#15212a;box-shadow:0 8px 28px #0008}.zf-pg-adult-row{display:flex;align-items:center;gap:8px}.zf-pg-adult-row small{display:block;color:#91a2af;margin-top:4px}.zf-pg-done{margin-left:auto;background:#1977a9;border-color:#55b8e7}.zf-pg-error{color:#ffb3aa;padding:8px}",
    "@media(max-width:880px){.zf-pg-modal-body{grid-template-columns:190px minmax(0,1fr)}.zf-pg-options{grid-template-columns:1fr}.zf-pg-search{width:180px}}",
  ].join("");
  document.head.appendChild(style);
}

function hideWidget(widget, marker) {
  if (!widget) return;
  widget.hidden = true;
  widget.options = { ...(widget.options || {}), hidden: true };
  widget.computeSize = () => [0, -4];
  widget.type = "converted-widget";
  if (widget._state) {
    widget._state.hidden = true;
    widget._state.options = { ...(widget._state.options || {}), hidden: true };
  }
  if (widget.inputEl) widget.inputEl.style.display = "none";
  if (widget.element) widget.element.style.display = "none";
}

function defaultState() {
  return {
    version: 5,
    adult_content: false,
    selected: {},
    enabled: {},
    overrides: {},
    pinned: {},
    locked: {},
    section_locked: {},
    section_lock_items: {},
    section_enabled: {},
    option_overrides: {},
  };
}

function legacyMovementField(fieldId, value) {
  const adult = fieldId === "simPick";
  const code = String(value || "").toUpperCase();
  const prefix = adult ? "adultPosture" : "posture";
  const postureNames = {
    A: "Supine", B: "Prone", C: "Side", D: "Kneeling", E: "Sitting",
    F: "Standing", G: "Squatting", H: "Suspended", J: "Special",
  };
  if (postureNames[code[0]]) return prefix + postureNames[code[0]];
  if (code[0] !== "I") return "";
  const number = Number(code.slice(1));
  if (adult) {
    if (number <= 20 || number >= 81) return "adultActionTransition";
    if (number <= 40) return "adultActionWalking";
    if (number <= 60) return "adultActionJumping";
    return "adultActionSpinning";
  }
  if (number <= 10 || number >= 26) return "actionTransition";
  if (number <= 18) return "actionWalking";
  if (number <= 22) return "actionJumping";
  return "actionSpinning";
}

function migrateLegacyMovement(state) {
  for (const legacyId of ["sfwSimPick", "simPick"]) {
    const targetId = legacyMovementField(legacyId, state.selected[legacyId]);
    if (targetId) {
      state.selected[targetId] ??= state.selected[legacyId];
      if (state.overrides[legacyId]) state.overrides[targetId] ??= state.overrides[legacyId];
      if (state.pinned[legacyId]) state.pinned[targetId] = true;
      if (state.locked[legacyId]) state.locked[targetId] = true;
      if (state.section_lock_items[legacyId]) state.section_lock_items[targetId] = true;
      if (state.enabled[legacyId] === false) state.enabled[targetId] = false;
    }
    for (const [key, text] of Object.entries(state.option_overrides)) {
      if (!key.startsWith(legacyId + "::")) continue;
      const value = key.slice(legacyId.length + 2);
      const optionTarget = legacyMovementField(legacyId, value);
      if (optionTarget) state.option_overrides[optionTarget + "::" + value] ??= text;
      delete state.option_overrides[key];
    }
    for (const collection of [state.selected, state.overrides, state.pinned, state.locked, state.section_lock_items, state.enabled]) {
      delete collection[legacyId];
    }
  }
  for (const legacyId of ["sfwSimMode", "sfwSimCoreCat", "sfwSimCat", "simMode", "simCoreCat", "simCat"]) {
    for (const collection of [state.selected, state.overrides, state.pinned, state.locked, state.section_lock_items, state.enabled]) {
      delete collection[legacyId];
    }
  }
  if (Object.prototype.hasOwnProperty.call(state.section_locked, "pose")) {
    state.section_locked.posture ??= state.section_locked.pose;
    state.section_locked.action ??= state.section_locked.pose;
    delete state.section_locked.pose;
  }
  if (Object.prototype.hasOwnProperty.call(state.section_enabled, "pose")) {
    state.section_enabled.posture ??= state.section_enabled.pose;
    state.section_enabled.action ??= state.section_enabled.pose;
    delete state.section_enabled.pose;
  }
  state.version = 5;
  return state;
}

function normalizeState(raw) {
  let value;
  try { value = JSON.parse(String(raw || "")); } catch { value = {}; }
  if (!value || typeof value !== "object" || Array.isArray(value)) value = {};
  const previousVersion = Number(value.version || 0);
  const next = { ...defaultState(), ...value, version: 5 };
  for (const key of ["selected", "enabled", "overrides", "pinned", "locked", "section_locked", "section_lock_items", "section_enabled", "option_overrides"]) {
    next[key] = value[key] && typeof value[key] === "object" && !Array.isArray(value[key]) ? value[key] : {};
  }
  next.__snapshotLegacySectionLocks = previousVersion < 5;
  delete next.expanded;
  return migrateLegacyMovement(next);
}

function optionFor(field, value) {
  return (field.options || []).find((item) => String(item.value) === String(value));
}

function optionKey(field, value) {
  return field.id + "::" + String(value || "");
}

function displayValue(field, state) {
  const override = String(state.overrides[field.id] || "").trim();
  if (override) return override;
  const option = optionFor(field, state.selected[field.id]);
  const customized = String(state.option_overrides[optionKey(field, option?.value)] || "").trim();
  return customized || String(option?.value || "").trim();
}

function shortLabel(label) {
  return String(label || "").replace(/[（(][^）)]*[）)]/g, "").trim();
}

function usableOptions(field, state) {
  let values = (field.options || []).filter((item) => {
    if (!state.adult_content && (field.adult || item.adult)) return false;
    return String(item.value || "").trim() && String(item.value) !== "不启用";
  });
  if (field.id === "clothItem" && state.selected.clothCat) {
    const matched = values.filter((item) => item.group === state.selected.clothCat);
    if (matched.length) values = matched;
  }
  if (field.id === "lingerieItem" && state.selected.lingerieCat) {
    const matched = values.filter((item) => item.group === state.selected.lingerieCat);
    if (matched.length) values = matched;
  }
  return values;
}

function makeButton(text, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "zf-pg-button" + (className ? " " + className : "");
  button.textContent = text;
  return button;
}

function attachPortraitGenerator(node) {
  const stateWidget = node.widgets?.find((widget) => widget.name === "state_json");
  const seedWidget = node.widgets?.find((widget) => widget.name === "seed");
  const adultWidget = node.widgets?.find((widget) => widget.name === "adult_content");
  if (!stateWidget || !seedWidget || !adultWidget) return;
  hideWidget(stateWidget, "zf-portrait-state");
  hideWidget(seedWidget, "zf-portrait-seed");
  hideWidget(adultWidget, "zf-portrait-adult");
  for (const widget of node.widgets || []) {
    if (String(widget.name || "").includes("control_after_generate")) {
      hideWidget(widget, "zf-portrait-control-after-generate");
    }
  }
  if (node.__zfPortraitGeneratorAttached) return;
  node.__zfPortraitGeneratorAttached = true;

  const root = document.createElement("div");
  root.className = "zf-pg-root";
  let overlay = null;

  const markChanged = () => {
    node.graph?.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
  };

  getCatalog().then((catalog) => {
    const all = catalog.sections.flatMap((section) => section.fields.map((field) => ({ section, field })));
    const fieldMap = new Map(all.map((item) => [item.field.id, item]));
    let state = normalizeState(stateWidget.value);
    if (state.__snapshotLegacySectionLocks) {
      for (const section of catalog.sections) {
        if (!state.section_locked[section.id]) continue;
        for (const field of section.fields) {
          if (state.selected[field.id] || state.overrides[field.id]) state.section_lock_items[field.id] = true;
        }
      }
    }
    delete state.__snapshotLegacySectionLocks;
    state.adult_content = Boolean(state.adult_content || adultWidget.value);
    let activeSectionId = catalog.sections.find((section) => section.fields.some((field) => !field.adult))?.id || catalog.sections[0]?.id;
    let activeFieldId = null;
    let searchTerm = "";
    let modalNotice = "";
    let lastCleared = null;

    const visibleFields = (section) => section.fields.filter((field) => state.adult_content || !field.adult);
    const sectionFor = (id) => catalog.sections.find((section) => section.id === id);
    const currentSection = () => sectionFor(activeSectionId) || catalog.sections[0];
    const currentField = () => {
      const section = currentSection();
      const fields = visibleFields(section);
      return fields.find((field) => field.id === activeFieldId) || fields[0];
    };
    const hasFieldValue = (fieldId, selected = state.selected) => Boolean(
      String(selected[fieldId] || "").trim() || String(state.overrides[fieldId] || "").trim()
    );
    const isFieldLocked = (fieldId) => Boolean(state.locked[fieldId] || state.section_lock_items[fieldId]);
    const fieldLockSource = (fieldId) => state.section_lock_items[fieldId] ? "section" : (state.locked[fieldId] ? "item" : "");

    const persist = () => {
      state.version = 5;
      stateWidget.value = JSON.stringify(state);
      adultWidget.value = Boolean(state.adult_content);
      stateWidget.callback?.(stateWidget.value);
      adultWidget.callback?.(adultWidget.value);
      markChanged();
    };

    const resize = () => {
      const pinnedCount = all.filter(({ field }) => state.pinned[field.id] && (state.adult_content || !field.adult)).length;
      const width = Math.max(470, node.size?.[0] || 0);
      const height = Math.max(145, Math.min(470, 112 + pinnedCount * 43));
      node.setSize?.([width, height]);
      markChanged();
    };

    const clearMovementPeers = (fieldId, selected = state.selected) => {
      if (!MOVEMENT_FIELD_IDS.has(fieldId)) return;
      for (const id of MOVEMENT_FIELD_IDS) {
        if (id === fieldId || isFieldLocked(id)) continue;
        delete selected[id];
        delete state.overrides[id];
      }
    };

    const applyPreset = (name) => {
      const preset = catalog.style_presets?.[name];
      if (!preset) return;
      for (const [fieldId, value] of Object.entries(preset)) {
        const target = fieldMap.get(fieldId);
        if (!target || isFieldLocked(fieldId) || (target.field.adult && !state.adult_content)) continue;
        if (optionFor(target.field, value)) state.selected[fieldId] = value;
      }
    };

    const chooseRandom = (field, selected) => {
      const candidates = usableOptions(field, { ...state, selected });
      if (!candidates.length) return;
      const picked = candidates[Math.floor(Math.random() * candidates.length)];
      selected[field.id] = picked.value;
    };

    const randomizeMovement = (next, sectionIds) => {
      const allowedSections = new Set(sectionIds);
      const hasLockedSelection = [...MOVEMENT_FIELD_IDS].some((id) => isFieldLocked(id) && next[id]);
      if (hasLockedSelection) return;
      for (const id of MOVEMENT_FIELD_IDS) {
        if (!isFieldLocked(id)) delete next[id];
      }
      let candidates = all.filter(({ section, field }) => (
        allowedSections.has(section.id)
        && MOVEMENT_FIELD_IDS.has(field.id)
        && !isFieldLocked(field.id)
        && (state.adult_content || !field.adult)
      ));
      if (state.adult_content) {
        const chooseAdult = Math.random() < 0.5;
        const sameSide = candidates.filter(({ field }) => Boolean(field.adult) === chooseAdult);
        if (sameSide.length) candidates = sameSide;
      }
      const weighted = candidates.flatMap(({ field }) => usableOptions(field, { ...state, selected: next })
        .map((option) => ({ field, option })));
      if (!weighted.length) return;
      const picked = weighted[Math.floor(Math.random() * weighted.length)];
      next[picked.field.id] = picked.option.value;
    };

    const randomizeSection = (section) => {
      if (!section || state.section_enabled[section.id] === false) return;
      lastCleared = null;
      const next = { ...state.selected };
      if (section.id === "posture" || section.id === "action") {
        randomizeMovement(next, [section.id]);
      } else {
        for (const field of visibleFields(section)) {
          if (!CORE_RANDOM_FIELDS.has(field.id) || field.custom || isFieldLocked(field.id)) continue;
          if (!ALWAYS_RANDOM_FIELDS.has(field.id) && Math.random() > 0.42) {
            delete next[field.id];
            continue;
          }
          chooseRandom(field, next);
        }
      }
      if (section.id === "action" && state.adult_content && !isFieldLocked("nsfwChain")) {
        if (Math.random() < 0.42) chooseRandom(fieldMap.get("nsfwChain")?.field || {}, next);
        else delete next.nsfwChain;
      }
      state.selected = next;
      seedWidget.value = Math.floor(Math.random() * 0x7fffffff);
      seedWidget.callback?.(seedWidget.value);
      persist();
    };

    const randomizeAll = () => {
      lastCleared = null;
      const next = { ...state.selected };
      for (const section of catalog.sections) {
        if (state.section_enabled[section.id] === false) continue;
        for (const field of visibleFields(section)) {
          if (!CORE_RANDOM_FIELDS.has(field.id) || field.custom || isFieldLocked(field.id)) continue;
          if (!ALWAYS_RANDOM_FIELDS.has(field.id) && Math.random() > 0.42) {
            delete next[field.id];
            continue;
          }
          chooseRandom(field, next);
        }
      }
      const movementSections = ["posture", "action"].filter((id) => (
        state.section_enabled[id] !== false
      ));
      if (movementSections.length) randomizeMovement(next, movementSections);
      if (state.adult_content && !isFieldLocked("nsfwChain") && state.section_enabled.action !== false) {
        if (Math.random() < 0.42) chooseRandom(fieldMap.get("nsfwChain")?.field || {}, next);
        else delete next.nsfwChain;
      }
      state.selected = next;
      seedWidget.value = Math.floor(Math.random() * 0x7fffffff);
      seedWidget.callback?.(seedWidget.value);
      persist();
      renderHome();
    };

    const closeModal = () => {
      overlay?.remove();
      overlay = null;
      renderHome();
    };

    const openModal = (sectionId, fieldId) => {
      if (sectionId) activeSectionId = sectionId;
      if (fieldId) activeFieldId = fieldId;
      searchTerm = "";
      renderModal();
    };

    const renderHome = () => {
      root.replaceChildren();
      const toolbar = document.createElement("div");
      toolbar.className = "zf-pg-toolbar";
      const random = makeButton("随机");
      random.addEventListener("click", randomizeAll);
      const clear = makeButton("清空所有");
      clear.addEventListener("click", () => {
        state.selected = Object.fromEntries(Object.entries(state.selected).filter(([fieldId]) => isFieldLocked(fieldId)));
        state.overrides = Object.fromEntries(Object.entries(state.overrides).filter(([fieldId]) => isFieldLocked(fieldId)));
        lastCleared = null;
        persist();
        renderHome();
      });
      const add = makeButton("＋ 添加项目", "zf-pg-add");
      add.addEventListener("click", () => openModal());
      toolbar.append(random, clear, add);
      root.appendChild(toolbar);

      const pinned = all.filter(({ field }) => state.pinned[field.id] && (state.adult_content || !field.adult));
      if (!pinned.length) {
        const empty = document.createElement("div");
        empty.className = "zf-pg-home-empty";
        empty.textContent = "暂无首页项目；点击“添加项目”选择需要常驻操作的内容。";
        root.appendChild(empty);
      } else {
        const rows = document.createElement("div");
        rows.className = "zf-pg-pinned";
        for (const { section, field } of pinned) {
          const row = document.createElement("div");
          row.className = "zf-pg-home-row";
          const pin = document.createElement("button");
          pin.type = "button";
          pin.className = "zf-pg-pin";
          pin.textContent = "●";
          pin.title = "从首页移除（不会清除当前选择）";
          pin.addEventListener("click", () => {
            delete state.pinned[field.id];
            persist();
            renderHome();
          });
          const label = document.createElement("span");
          label.className = "zf-pg-home-label";
          label.textContent = shortLabel(field.label);
          label.title = field.label;
          const value = makeButton(displayValue(field, state) || "点击选择", "zf-pg-value");
          value.title = displayValue(field, state) || "打开选项";
          value.addEventListener("click", () => openModal(section.id, field.id));
          const lock = document.createElement("button");
          lock.type = "button";
          lock.className = "zf-pg-lock";
          lock.textContent = isFieldLocked(field.id) ? "🔒" : "🔓";
          lock.title = isFieldLocked(field.id) ? "本项已锁定，点击查看" : "锁定本项";
          lock.addEventListener("click", () => {
            if (fieldLockSource(field.id) === "section") {
              modalNotice = "这一项由“本段锁定”保护；请先解锁本段。";
              openModal(section.id, field.id);
              return;
            }
            if (!hasFieldValue(field.id)) {
              modalNotice = "请先选择一个素材，再锁定本项。";
              openModal(section.id, field.id);
              return;
            }
            state.locked[field.id] = !state.locked[field.id];
            persist();
            renderHome();
          });
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "zf-pg-remove";
          remove.textContent = "×";
          remove.title = isFieldLocked(field.id) ? "本项已锁定，不能清除" : "清除本项内容";
          remove.addEventListener("click", () => {
            if (isFieldLocked(field.id)) {
              modalNotice = "本项已锁定；解锁后才能清除。";
              openModal(section.id, field.id);
              return;
            }
            lastCleared = {
              fieldId: field.id,
              selected: state.selected[field.id],
              override: state.overrides[field.id],
            };
            delete state.selected[field.id];
            delete state.overrides[field.id];
            persist();
            renderHome();
          });
          row.append(pin, label, value, lock, remove);
          rows.appendChild(row);
        }
        root.appendChild(rows);
      }
      setTimeout(resize, 0);
    };

    const renderModal = () => {
      const previousView = overlay ? {
        sectionId: overlay.dataset.sectionId || "",
        fieldId: overlay.dataset.fieldId || "",
        navTop: overlay.querySelector(".zf-pg-section-nav")?.scrollTop || 0,
        tabsLeft: overlay.querySelector(".zf-pg-field-tabs")?.scrollLeft || 0,
        optionsTop: overlay.querySelector(".zf-pg-options")?.scrollTop || 0,
      } : null;
      overlay?.remove();
      overlay = document.createElement("div");
      overlay.className = "zf-pg-overlay";
      const dialog = document.createElement("div");
      dialog.className = "zf-pg-dialog";
      overlay.appendChild(dialog);

      const header = document.createElement("div");
      header.className = "zf-pg-modal-header";
      const heading = document.createElement("div");
      const title = document.createElement("h2");
      title.textContent = "添加人像项目";
      const subtitle = document.createElement("p");
      subtitle.textContent = "单击选中，双击任意资产卡片可原地修改；实心圆点表示固定到节点首页。";
      heading.append(title, subtitle);
      const close = document.createElement("button");
      close.type = "button";
      close.className = "zf-pg-close";
      close.textContent = "×";
      close.addEventListener("click", closeModal);
      header.append(heading, close);
      dialog.appendChild(header);

      const body = document.createElement("div");
      body.className = "zf-pg-modal-body";
      const nav = document.createElement("div");
      nav.className = "zf-pg-section-nav";
      for (const section of catalog.sections) {
        const fields = visibleFields(section);
        if (!fields.length) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "zf-pg-section-button"
          + (section.id === currentSection()?.id ? " active" : "")
          + (state.section_enabled[section.id] === false ? " disabled" : "");
        const name = document.createElement("span");
        name.className = "zf-pg-section-name";
        name.textContent = section.title;
        const meta = document.createElement("span");
        meta.className = "zf-pg-section-meta";
        meta.textContent = (state.section_locked[section.id] ? "🔒 " : "") + fields.length + "项";
        button.append(name, meta);
        button.addEventListener("click", () => {
          activeSectionId = section.id;
          activeFieldId = visibleFields(section)[0]?.id;
          searchTerm = "";
          renderModal();
        });
        nav.appendChild(button);
      }

      const main = document.createElement("div");
      main.className = "zf-pg-main";
      const section = currentSection();
      const sectionFields = visibleFields(section);
      if (!sectionFields.some((field) => field.id === activeFieldId)) activeFieldId = sectionFields[0]?.id;
      const field = currentField();
      overlay.dataset.sectionId = section?.id || "";
      overlay.dataset.fieldId = field?.id || "";

      const sectionTools = document.createElement("div");
      sectionTools.className = "zf-pg-section-tools";
      const sectionName = document.createElement("strong");
      sectionName.textContent = section.title;
      const sectionRandom = makeButton("本段随机");
      sectionRandom.disabled = Boolean(state.section_enabled[section.id] === false);
      sectionRandom.addEventListener("click", () => {
        randomizeSection(section);
        modalNotice = state.section_locked[section.id]
          ? "本段已锁定的选择保持不变；未锁定分类已重新随机。"
          : "本段已重新随机。";
        renderModal();
      });
      const sectionLock = makeButton(
        state.section_locked[section.id] ? "🔒 本段已锁定" : "🔓 锁定本段",
        state.section_locked[section.id] ? "zf-pg-tool-active" : "",
      );
      sectionLock.addEventListener("click", () => {
        const willLock = !state.section_locked[section.id];
        state.section_locked[section.id] = willLock;
        if (willLock) {
          for (const item of section.fields) {
            if (hasFieldValue(item.id)) state.section_lock_items[item.id] = true;
          }
          modalNotice = "已锁定本段当前选择；尚未选择的分类仍会继续随机。";
        } else {
          for (const item of section.fields) delete state.section_lock_items[item.id];
          modalNotice = "本段锁定已解除；单独锁定的项目仍保持锁定。";
        }
        persist();
        renderModal();
      });
      const disabled = state.section_enabled[section.id] === false;
      const sectionEnable = makeButton(disabled ? "本段已停用" : "本段不启用", disabled ? "zf-pg-tool-danger" : "");
      sectionEnable.addEventListener("click", () => {
        state.section_enabled[section.id] = disabled;
        persist();
        renderModal();
      });
      sectionTools.append(sectionName, sectionRandom, sectionLock, sectionEnable);
      main.appendChild(sectionTools);

      const tabs = document.createElement("div");
      tabs.className = "zf-pg-field-tabs";
      for (const item of sectionFields) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = "zf-pg-field-tab"
          + (item.id === field?.id ? " active" : "")
          + (isFieldLocked(item.id) ? " locked" : "");
        const dot = document.createElement("span");
        dot.className = "zf-pg-tab-dot";
        dot.textContent = state.pinned[item.id] ? "●" : "○";
        dot.title = state.pinned[item.id] ? "已固定到首页" : "点击固定到首页";
        dot.addEventListener("click", (event) => {
          event.stopPropagation();
          state.pinned[item.id] = !state.pinned[item.id];
          persist();
          renderModal();
        });
        const text = document.createElement("span");
        text.textContent = shortLabel(item.label) + (isFieldLocked(item.id) ? " 🔒" : "");
        tab.append(dot, text);
        tab.addEventListener("click", () => {
          activeFieldId = item.id;
          searchTerm = "";
          renderModal();
        });
        tabs.appendChild(tab);
      }
      main.appendChild(tabs);

      const detail = document.createElement("div");
      detail.className = "zf-pg-detail";
      const detailHead = document.createElement("div");
      detailHead.className = "zf-pg-detail-head";
      const fieldTitle = document.createElement("h3");
      fieldTitle.textContent = field?.label || "";
      const fieldLock = makeButton(
        isFieldLocked(field?.id) ? "🔒 本项已锁定" : "🔓 锁定本项",
        isFieldLocked(field?.id) ? "zf-pg-tool-active" : "",
      );
      fieldLock.addEventListener("click", () => {
        if (fieldLockSource(field.id) === "section") {
          modalNotice = "这一项由“本段锁定”保护；请先解锁本段。";
          renderModal();
          return;
        }
        if (!hasFieldValue(field.id)) {
          modalNotice = "请先选择一个素材，再锁定本项。";
          renderModal();
          return;
        }
        state.locked[field.id] = !state.locked[field.id];
        modalNotice = state.locked[field.id] ? "本项已锁定；解锁前选择、清除和随机都不会改变它。" : "本项锁定已解除。";
        persist();
        renderModal();
      });
      const canUndoClear = lastCleared?.fieldId === field?.id && !hasFieldValue(field.id);
      const fieldClear = makeButton(canUndoClear ? "撤销清除" : (hasFieldValue(field?.id) ? "清除本项" : "本项未选择"));
      fieldClear.disabled = !canUndoClear && !hasFieldValue(field?.id);
      fieldClear.addEventListener("click", () => {
        if (canUndoClear) {
          if (lastCleared.selected != null) state.selected[field.id] = lastCleared.selected;
          if (lastCleared.override != null) state.overrides[field.id] = lastCleared.override;
          const restored = displayValue(field, state) || shortLabel(field.label);
          lastCleared = null;
          modalNotice = `已恢复“${restored}”。`;
          persist();
          renderModal();
          return;
        }
        if (isFieldLocked(field.id)) {
          modalNotice = "本项已锁定；解锁后才能清除。";
          renderModal();
          return;
        }
        const cleared = displayValue(field, state) || shortLabel(field.label);
        lastCleared = {
          fieldId: field.id,
          selected: state.selected[field.id],
          override: state.overrides[field.id],
        };
        delete state.selected[field.id];
        delete state.overrides[field.id];
        modalNotice = `已清除“${cleared}”；点击“撤销清除”可以恢复。`;
        persist();
        renderModal();
      });
      const search = document.createElement("input");
      search.className = "zf-pg-search";
      search.placeholder = "搜索当前项目的内容…";
      search.value = searchTerm;
      detailHead.append(fieldTitle, fieldLock, fieldClear, search);
      detail.appendChild(detailHead);

      const notice = document.createElement("div");
      notice.className = "zf-pg-notice";
      notice.textContent = modalNotice;
      detail.appendChild(notice);

      const options = document.createElement("div");
      options.className = "zf-pg-options";
      const renderOptions = () => {
        options.replaceChildren();
        const keyword = searchTerm.trim().toLowerCase();
        const matches = usableOptions(field, state).filter((item) => {
          if (!keyword) return true;
          return [
            item.value,
            item.text,
            item.group,
            state.option_overrides[optionKey(field, item.value)],
          ].some((part) => String(part || "").toLowerCase().includes(keyword));
        });
        for (const item of matches.slice(0, 180)) {
          const key = optionKey(field, item.value);
          const customized = String(state.option_overrides[key] || "").trim();
          const card = document.createElement("div");
          card.setAttribute("role", "button");
          card.tabIndex = 0;
          const selectedOption = String(state.selected[field.id]) === String(item.value);
          const selectedLocked = selectedOption && isFieldLocked(field.id);
          card.className = "zf-pg-option"
            + (selectedOption ? " selected" : "")
            + (selectedLocked ? " locked" : "")
            + (customized ? " modified" : "");
          const value = document.createElement("div");
          value.className = "zf-pg-option-value";
          value.textContent = item.value || item.text;
          if (customized) {
            const badge = document.createElement("span");
            badge.className = "zf-pg-option-badge";
            badge.textContent = "已修改";
            value.appendChild(badge);
          }
          if (selectedLocked) {
            const lockBadge = document.createElement("span");
            lockBadge.className = "zf-pg-option-badge";
            lockBadge.textContent = "🔒 已锁定";
            value.appendChild(lockBadge);
          }
          const description = document.createElement("div");
          description.className = "zf-pg-option-desc";
          description.textContent = customized
            || (item.text && item.text !== item.value ? item.text : (item.group || "选择此项"));
          card.title = "单击选中；双击修改这个资产选项";
          card.append(value, description);
          card.addEventListener("click", () => {
            if (card.classList.contains("zf-pg-option-editor")) return;
            if (isFieldLocked(field.id)) {
              modalNotice = "本项已锁定；先解锁才能更换选择。";
              notice.textContent = modalNotice;
              return;
            }
            const preservedTop = options.scrollTop;
            state.selected[field.id] = item.value;
            delete state.overrides[field.id];
            clearMovementPeers(field.id);
            if (field.id === "stylePreset") applyPreset(item.value);
            lastCleared = null;
            if (state.section_locked[section.id]) {
              state.section_lock_items[field.id] = true;
              modalNotice = "已选择并纳入本段锁定；解锁本段前不会被改变。";
              persist();
              renderModal();
              return;
            }
            modalNotice = "";
            persist();
            for (const sibling of options.querySelectorAll(".zf-pg-option")) {
              sibling.classList.remove("selected", "locked");
            }
            card.classList.add("selected");
            fieldClear.textContent = "清除本项";
            fieldClear.disabled = false;
            notice.textContent = "";
            options.scrollTop = preservedTop;
            requestAnimationFrame(() => { options.scrollTop = preservedTop; });
          });
          card.addEventListener("dblclick", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (card.classList.contains("zf-pg-option-editor")) return;
            if (isFieldLocked(field.id)) {
              modalNotice = "本项已锁定；先解锁才能修改素材内容。";
              notice.textContent = modalNotice;
              return;
            }
            card.className = "zf-pg-option zf-pg-option-editor selected" + (customized ? " modified" : "");
            card.removeAttribute("role");
            card.removeAttribute("tabindex");
            const editTitle = document.createElement("div");
            editTitle.className = "zf-pg-option-value";
            editTitle.textContent = "修改资产：" + (item.value || item.text);
            const editor = document.createElement("textarea");
            editor.value = customized || item.text || item.value || "";
            editor.placeholder = "输入这个资产选项实际输出的内容";
            const actions = document.createElement("div");
            actions.className = "zf-pg-option-edit-actions";
            const confirm = makeButton("确认保存", "zf-pg-tool-active");
            const cancel = makeButton("取消");
            const hint = document.createElement("small");
            hint.textContent = "保存后会固定在此选项；节点修复可恢复全部内置原文。";
            confirm.addEventListener("click", (clickEvent) => {
              clickEvent.stopPropagation();
              const nextText = editor.value.trim();
              if (nextText) state.option_overrides[key] = editor.value;
              else delete state.option_overrides[key];
              persist();
              renderModal();
            });
            cancel.addEventListener("click", (clickEvent) => {
              clickEvent.stopPropagation();
              renderModal();
            });
            editor.addEventListener("click", (clickEvent) => clickEvent.stopPropagation());
            editor.addEventListener("dblclick", (clickEvent) => clickEvent.stopPropagation());
            actions.append(confirm, cancel, hint);
            card.replaceChildren(editTitle, editor, actions);
            setTimeout(() => {
              editor.focus();
              editor.select();
            }, 0);
          });
          options.appendChild(card);
        }
        if (!matches.length || matches.length > 180) {
          const note = document.createElement("div");
          note.className = "zf-pg-no-option";
          note.textContent = !matches.length ? "没有匹配内容。" : "当前显示前 180 项，请输入关键词继续筛选。";
          options.appendChild(note);
        }
      };
      search.addEventListener("input", () => {
        searchTerm = search.value;
        renderOptions();
      });
      renderOptions();
      detail.appendChild(options);
      main.appendChild(detail);
      body.append(nav, main);
      dialog.appendChild(body);

      const footer = document.createElement("div");
      footer.className = "zf-pg-modal-footer";
      const repair = makeButton("节点修复");
      repair.title = "恢复所有资产卡片的内置原文，保留选择、首页固定、锁定和分段设置";
      repair.addEventListener("click", () => {
        state.overrides = {};
        state.option_overrides = {};
        persist();
        renderModal();
      });
      const advanced = document.createElement("details");
      advanced.className = "zf-pg-advanced";
      const advancedSummary = document.createElement("summary");
      advancedSummary.className = "zf-pg-button";
      advancedSummary.textContent = "高级设置";
      const adultBox = document.createElement("div");
      adultBox.className = "zf-pg-adult-box";
      const adultRow = document.createElement("label");
      adultRow.className = "zf-pg-adult-row";
      const adultToggle = document.createElement("input");
      adultToggle.type = "checkbox";
      adultToggle.checked = Boolean(state.adult_content);
      const adultText = document.createElement("span");
      adultText.textContent = "成人内容（默认关闭）";
      adultRow.append(adultToggle, adultText);
      const adultHint = document.createElement("small");
      adultHint.textContent = "关闭时不进入随机、当前提示词或完整人物资产库；开启后完整资产库会追加对应内容。";
      adultToggle.addEventListener("change", () => {
        state.adult_content = adultToggle.checked;
        if (!state.adult_content) {
          for (const { field: adultField } of all) {
            if (!adultField.adult) continue;
            delete state.pinned[adultField.id];
          }
        }
        persist();
        renderModal();
      });
      adultBox.append(adultRow, adultHint);
      advanced.append(advancedSummary, adultBox);
      const done = makeButton("完成", "zf-pg-done");
      done.addEventListener("click", closeModal);
      footer.append(repair, advanced, done);
      dialog.appendChild(footer);
      overlay.addEventListener("mousedown", (event) => {
        if (event.target === overlay) closeModal();
      });
      document.body.appendChild(overlay);
      if (previousView) {
        requestAnimationFrame(() => {
          const nextNav = overlay?.querySelector(".zf-pg-section-nav");
          const nextTabs = overlay?.querySelector(".zf-pg-field-tabs");
          const nextOptions = overlay?.querySelector(".zf-pg-options");
          if (nextNav) nextNav.scrollTop = previousView.navTop;
          if (nextTabs) nextTabs.scrollLeft = previousView.tabsLeft;
          if (
            nextOptions
            && previousView.sectionId === (overlay?.dataset.sectionId || "")
            && previousView.fieldId === (overlay?.dataset.fieldId || "")
          ) {
            nextOptions.scrollTop = previousView.optionsTop;
          }
        });
      }
    };

    renderHome();
  }).catch((error) => {
    root.innerHTML = '<div class="zf-pg-error"></div>';
    root.firstElementChild.textContent = error?.message || String(error);
  });

  const originalRemoved = node.onRemoved;
  node.onRemoved = function () {
    overlay?.remove();
    originalRemoved?.apply(this, arguments);
  };
  const domWidget = node.addDOMWidget("portrait_ui", "zf-portrait-generator", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 110,
    getMaxHeight: () => 470,
  });
  domWidget.serialize = false;
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
      setTimeout(() => attachPortraitGenerator(this), 0);
    };
    nodeType.prototype.onConfigure = function () {
      originalConfigure?.apply(this, arguments);
      setTimeout(() => attachPortraitGenerator(this), 0);
    };
  },
});
