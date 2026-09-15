const ROOT = "/zf-prompt-director/h3-interview/presets";
const element = (tag, text = "") => { const node = document.createElement(tag); node.textContent = text; return node; };

export function mountPresets(host, readCurrent, applyCurrent, api) {
  const box = element("section"); box.className = "zv-h3-presets";
  const title = element("strong", "我的采访预设");
  const name = element("input"); name.name = "preset-name"; name.placeholder = "为当前填表命名"; name.maxLength = 120;
  const list = element("select"); list.name = "preset-list"; list.multiple = true; list.size = 3; list.setAttribute("aria-label", "用户预设列表");
  const actions = element("div"); actions.className = "zv-h3-preset-actions";
  const status = element("div"); status.className = "zv-h3-preset-status"; status.setAttribute("role", "status");
  const hint = element("small", "可多选导出；名称与数量只作参考，模式由当前物理接口决定。删除预设保留当前表格与素材。");
  box.append(title, name, list, actions, hint, status); host.append(box);
  let items = new Map(), cursor = null, disposed = false, busy = false;
  const buttons = [];
  async function request(path = "", method = "GET", body) {
    const response = await api.fetchApi(ROOT + path, { method, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error?.message || "预设库不可用；正常重启服务加载新接口");
    return result;
  }
  const selected = () => [...list.selectedOptions].map(option => items.get(option.value));
  function one() { const values = selected(); if (values.length !== 1) throw new Error("请选择一个预设操作；多选用于导出"); return values[0]; }
  async function refresh(append = false, chosen = null) {
    const result = await request(append && cursor ? `?cursor=${cursor}` : "");
    if (disposed) return;
    if (!append) { items = new Map(); list.replaceChildren(); }
    for (const item of result.presets) {
      items.set(item.preset_id, item); const option = element("option", `${item.name} · v${item.preset_version}`); option.value = item.preset_id; option.selected = item.preset_id === chosen; list.append(option);
    }
    cursor = result.next_cursor; more.hidden = cursor == null;
  }
  async function run(operation) {
    if (busy || disposed) return;
    busy = true; buttons.forEach(button => button.disabled = true); status.textContent = "正在处理预设…";
    try { await operation(); }
    catch (error) { if (!disposed) status.textContent = error.message; }
    finally { busy = false; if (!disposed) buttons.forEach(button => button.disabled = false); }
  }
  function button(label, operation) { const node = element("button", label); node.type = "button"; node.onclick = () => run(operation); buttons.push(node); actions.append(node); return node; }
  button("保存新预设", async () => { const requestedName = name.value; const saved = await request("", "POST", { name: requestedName, ...readCurrent() }); await refresh(false, saved.preset_id); if(name.value === requestedName) name.value = saved.name; status.textContent = `已保存“${saved.name}”，重启后仍可载入`; });
  button("载入所选", async () => {
    const item = one(), current = readCurrent(), requestedName = name.value;
    const saved = await request(`/${item.preset_id}/apply`, "POST", current);
    if (disposed) return;
    if (JSON.stringify(current) !== JSON.stringify(readCurrent()) || name.value !== requestedName || selected().length !== 1 || selected()[0].preset_id !== item.preset_id) {
      status.textContent = "载入响应已过期，未应用；最新文本、用途与素材状态已保留";
      return;
    }
    applyCurrent(saved); name.value = saved.preset.name; items.set(item.preset_id, { ...item, ...saved.preset });
    status.textContent = [saved.mechanical_changed ? "已载入；物理接口变化，请检测并对齐素材" : "已载入；机械对齐保持", ...saved.notices.map(row => row.message)].join("；");
  });
  button("更新所选", async () => { const item = one(); const saved = await request(`/${item.preset_id}`, "PUT", { name: name.value, preset_version: item.preset_version, ...readCurrent() }); await refresh(false, saved.preset_id); status.textContent = `已更新“${saved.name}” · v${saved.preset_version}`; });
  button("改名所选", async () => { const item = one(); const saved = await request(`/${item.preset_id}`, "PATCH", { name: name.value, preset_version: item.preset_version }); await refresh(false, saved.preset_id); status.textContent = `已改名“${saved.name}”`; });
  button("删除所选", async () => { const item = one(); await request(`/${item.preset_id}`, "DELETE", { preset_version: item.preset_version }); await refresh(); status.textContent = `已删除库条目“${item.name}”；当前表格与素材保留`; });
  button("导出所选", async () => { const ids = selected().map(item => item.preset_id); const value = await request("/export", "POST", { preset_ids: ids }); const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const anchor = element("a"); anchor.href = url; anchor.download = "H3采访预设.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); status.textContent = `已导出 ${ids.length} 项素材无关模板`; });
  const file = element("input"); file.type = "file"; file.accept = ".json,application/json"; file.hidden = true; box.append(file);
  button("导入预设", async () => { file.click(); status.textContent = "选择预设JSON；导入创建新UUID，重名保存为副本"; });
  file.onchange = () => run(async () => {
    try {
      const selectedFile = file.files?.[0]; if (!selectedFile) return;
      if (selectedFile.size > 2 * 1024 * 1024) throw new Error("预设文件最多2 MiB");
      const response = await api.fetchApi(ROOT + "/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: await selectedFile.text() }); const saved = await response.json();
      if (!response.ok) throw new Error(saved.error?.message || "导入失败");
      await refresh(false, saved.presets.at(-1)?.preset_id); if(!disposed) status.textContent = `已导入 ${saved.presets.length} 项新副本`;
    } finally { file.value = ""; }
  });
  button("刷新列表", async () => { await refresh(); status.textContent = "列表已刷新；当前填表保持"; });
  const more = button("更多预设", async () => { await refresh(true); status.textContent = "已加载下一页"; }); more.hidden = true;
  list.onchange = () => { if (selected().length === 1) name.value = selected()[0].name; };
  run(async () => { await refresh(); status.textContent = items.size ? "选择预设载入或继续编辑当前表格" : "还没有用户预设；可命名保存当前表格"; });
  return () => { disposed = true; };
}
