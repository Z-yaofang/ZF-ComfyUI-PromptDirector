# ZV 处理预设 v2 契约与迁移

## 数据与迁移策略

- 新建 `schema_version: 2` 工程默认 `builtin.generic`（通用）；旧 v1 工程缺少预设时，迁为内置 H3 单段预设 v1。原素材、片段 ID、接线及窗口起止秒数均保留。
- `processing_preset` 保存 `{preset_id, preset_version, snapshot}`。snapshot 含名称、模型/用途说明、策略和完整规则。库升级、编辑或删除均不自动替换已保存项目的快照。
- 导入工程及读写预设库时，旧 v2 快照若缺少 `overlap_alignment`，只补 `exact`，保留其请求重叠值、ID 和版本。旧 H3 长参考 v1 快照中的 12 帧因此仍按原值采用，不会被替换为新内置 v2。读取旧库只规范化返回值，不重写磁盘；只有显式保存才写入完整新规则。
- `processing_window` 继续保存秒范围和窗口参考 fps。切换预设不改窗口；目标 fps 不同会提示兼容性差异，窗口参考 fps 可独立编辑。帧网格吸附使用所选规则的目标 fps，仅在要求对齐时量化。
- 规范化丢弃输入中所有旧派生校验结果、标签和计算帧数，重新计算。

## 规则

snapshot 包含 `name`、`description`、`strategy`（`single_window` / `auto_segment`）和 `rules`：`target_fps`、`min_frames`、`max_frames`、`max_seconds`、`align_to_grid`、`segment_min_seconds`、`segment_max_seconds`、`overlap_frames`、`overlap_alignment`。无上/下限用 null，不用 0 伪装无限。

单窗口策略中帧数和秒数限制作用于整个窗口，帧数及秒数同时设置时取更严格的有效上限。自动分段策略中帧数限制与单段秒数限制共同约束每段，max_seconds 是可选的总任务上限；实际重叠帧必须小于有效单段最少帧。目标 fps、限制及请求重叠均校验有限性和合法范围；有帧数约束或对齐要求时必须设置目标 fps。

`overlap_frames` 保存用户请求的重叠帧数，`overlap_alignment` 显式选择如何得到实际采用值：

- `exact`：实际值等于请求值，可为 0；普通用户自动分段默认此策略，不套用 H3 网格。
- `h3_guide`：请求值至少为 1，向下对齐到合法的 1 或 `5 + 17k` 帧（k 为非负整数）。请求 1–4 帧时实际为 1；48→39、22→22、12→5。只有明确选择此策略的快照才采用该规则。

设总范围为 T 帧、有效单段最少/最多帧为 L/U、实际重叠为 O：步长为 `U - O`，预计段数为 `max(1, ceil((T - O) / (U - O)))`；还需满足 `T + (段数 - 1) × O ≥ 段数 × L`，保证最短段约束下仍能覆盖该范围。步长、段数和覆盖校验均使用实际 O，不能直接代入请求值。

内置：

1. `builtin.generic` / 通用（默认）：无模型限制、无强制对齐。
2. `builtin.minimax-h3.single` / MiniMax H3 · 单段生成：24 fps，48–360 帧，最长 15 秒，起止对齐目标帧网格。
3. `builtin.minimax-h3.segmented` v2 / MiniMax H3 · 长参考动作迁移（自动分段）：总任务范围不另设模型时长上限；每段 24 fps、48–360 帧、2–15 秒。参考初始请求重叠为 48 帧，采用 `h3_guide` 得到实际 39 帧，步长为 321 帧。48 是可调整的参考默认值，不是 H3 固定能力；应依据稳定动作区域选择，最终以导演台显示的实际 `GUIDE N帧` 为准。兼容性计算范围是否能由合法分段覆盖，并显示预计段数；尚未执行分段，也不表示 H3 单次可生成无限时长。

H3 长参考重叠语义依据本地 TimelineDirector：

- [长参考节点默认请求 48 帧](E:/AI_Models/ComfyUI-TE/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-TimelineDirector/minimax_h3_finite_segments.py:378)，[先派生实际重叠，再计算步长和段数](E:/AI_Models/ComfyUI-TE/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-TimelineDirector/minimax_h3_finite_segments.py:166)。
- [H3 Guide 合法帧数算法](E:/AI_Models/ComfyUI-TE/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-TimelineDirector/experimental_latent_guide.py:35)以及[长参考文档中的请求值与实际推进规则](E:/AI_Models/ComfyUI-TE/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-TimelineDirector/docs/LONG_REFERENCE_AUTO_SEGMENT_CN.md:35)。
- [长视频指南](E:/AI_Models/ComfyUI-TE/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-TimelineDirector/docs/AGENT_LONG_VIDEO_GUIDE_CN.md:87)要求按稳定、可辨识的动作区选择重叠，不机械固定，并以实际 GUIDE 帧数为最终依据。

## 工程校验与兼容性

- `validation.errors` 仅包括结构、素材来源、裁剪越界、无效/非正处理范围、12 小时上限等工程错误。
- `preset_compatibility` 是重新计算的派生结果，包含是否兼容、中文原因、当前目标帧数、有效单窗口/单段上下限和预计分段数；分段策略还输出 `requested_overlap_frames`、`effective_overlap_frames`、`segment_stride_frames`。这三个字段在非分段策略下为 null，不能从输入中直接信任。
- 工程错误显示红色；工程有效但预设不兼容显示橙色；工程有效且兼容显示绿色。预设限制不截断用户的值。
- H3 执行编译器继续独立验证真实模型约束，不以用户预设替代执行层检查。

## 用户库与端点

通过宿主 `user_manager.get_request_user_filepath(request, None, create_dir=False)` 获取当前用户根目录，固定文件为 `<用户根目录>/zf_media_evidence/processing_presets.json`。客户端不能指定存储路径；检查路径越界及链接逃逸，写入使用同目录临时文件原子替换。

`GET /zf-media-evidence/presets` 列出内置与用户库；`POST` 创建用户预设；`PUT /presets/{id}` 基于版本更新；`DELETE /presets/{id}` 删除用户预设。内置 ID 不可写/删。用户 ID 由服务器生成，更新递增版本，并拒绝过期写入。端点沿用同源限制、有限请求大小及中文错误。

## UI 与验收

标题中央为当前预设下拉，旁边独立“＋ 添加预设”。新增可复制当前规则；用户预设可编辑/删除，内置只可复制。旧快照在下拉中可辨识，库变动不静默更新项目。

轨道及底部统一称处理窗口；显示名分别为通用窗口、H3 单段窗口、H3 长任务范围或用户名称。自动分段编辑器显示单段最少/最多秒数、请求重叠帧和重叠对齐策略，并随请求值实时预览实际值。复制 H3 长参考后可修改请求值；状态明确显示“请求重叠 48 帧，实际 39 帧（按 H3 Guide 网格向下对齐）”。数字首次点击全选；保存前中文校验。

验证涵盖 v1 迁移、新建通用、17 秒跨预设解释、长任务合法分段规则、范围不变、规则冲突拒绝、库安全/版本/重载、快照复现、内置保护，以及已有时间线监看、混音和剪辑回归。

## 前轮完成记录（2026-09-07，重叠纠偏前）

本节保留前轮的改动范围和已执行测试结果，不作为本次重叠纠偏的测试结果。目标 fps 支持 1–240；H3 48–360 帧等价于 2–15 秒，预设界面直接展示，无需重复填写内置规则。非对齐规则保留亚帧秒数；切换预设不改窗口参考 fps 或起止秒数。如果目标 fps 与窗口参考 fps 不同，给出兼容性提示，可显式调整“窗口参考 fps”。

快照比较不依赖 JSON 键顺序。用户库更新采用版本冲突检查，旧项目显示“项目快照 vN”；删除用户预设后，当前项目仍保留其快照。编辑器使用中文校验，自动分段显示每段帧数与秒数、总任务上限和重叠帧。编辑器及预设下拉的键盘事件与时间线播放/删除快捷键隔离。

H3 执行层未改动：`h3_focus/validation.py:88` 仍独立校验真实 `local_t8` 输入为 24 fps、48–360 帧，用户快照不替代真实模型能力检查。

### 精确改动范围

既有文件 11 个：

- `media_evidence/contract.py`：新建默认 v2 通用、v1 迁移、派生字段重算、工程/兼容性分离。
- `media_evidence/runtime.py`、`media_evidence/server.py`、根 `server.py`：当前用户目录提供器、预设端点和注册。
- `web/media_evidence_core.mjs`、`web/media_evidence_desk.js`、`web/media_evidence_desk.css`：默认项目、可选帧网格、模式管理、编辑器、状态和布局。
- `tests/test_media_evidence.py`：既有窗口断言改为兼容性，并用不同字节长度避免 Windows 同一时钟刻度文件时间戳造成的测试偶发失败。
- `tests/media_evidence_smoke.py`、`tests/media_evidence_ui_smoke.mjs`、`tests/media_evidence_monitor_smoke.mjs`：本地用户库端点、测试容器尺寸与既有交互回归。

新增文件 10 个：

- 本契约文档 `docs/ZV_PROCESSING_PRESETS_V2.md`。
- `media_evidence/presets.py`、`media_evidence/preset_store.py`。
- `schemas/zv-media-project-v2.schema.json`、`schemas/zv-processing-preset-v1.schema.json`。
- `web/media_evidence_presets.mjs`、`web/media_processing_presets.json`。
- `tests/test_media_presets.py`、`tests/media_evidence_presets.test.mjs`、`tests/media_evidence_presets_ui_smoke.mjs`。

开工 SHA256 对比：除此 21 个文件外，仓库其余既有未提交文件全部保持原样；56 个工作流不变，TimelineDirector 不变，ZI 与 H3 编译器未改。旧 v1 schema 文件保留。未 commit/push，未重启运行中的 ComfyUI。

### 测试命令与结果

在插件根目录执行：

```powershell
& 'E:\AI_Models\ComfyUI-TE-0\python_embeded\python.exe' -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests --tb=short -rs
node --test tests/media_evidence_core.test.mjs tests/media_evidence_presets.test.mjs
& 'E:\AI_Models\ComfyUI-TE\python_embeded\python.exe' tests/media_evidence_smoke.py
```

结果为 **254 passed in 1.79s**、**49 纯函数测试通过**、**MEDIA_SMOKE_OK 33**。后者包含原来的 18 项媒体检查以及 15 项预设端点检查，覆盖保存、重载、更新版本、旧快照隔离、内置不可写/删、拒绝任意路径参数、同源限制、冲突规则、请求大小和删除。

隔离浏览器使用以下配置；真实上传检查需串行运行，避免共享测试服务的单批导入锁：

```powershell
& 'E:\AI_Models\ComfyUI-TE\python_embeded\python.exe' tests/media_evidence_smoke.py --serve
# 取上一步打印的 HARNESS_URL，替换下方 $testUrl。
$testUrl = 'http://127.0.0.1:端口'
$playwrightPackage = 'C:\Users\94319\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$chromiumExecutable = 'C:\Users\94319\AppData\Local\ms-playwright\chromium_headless_shell-1234\chrome-headless-shell-win64\chrome-headless-shell.exe'
node tests/media_evidence_presets_ui_smoke.mjs $testUrl $playwrightPackage $chromiumExecutable
node tests/media_evidence_ui_smoke.mjs $testUrl $playwrightPackage $chromiumExecutable --no-screenshot
node tests/media_evidence_monitor_smoke.mjs $playwrightPackage $chromiumExecutable
node tests/media_evidence_monitor_media_smoke.mjs $testUrl $playwrightPackage $chromiumExecutable 'C:\Users\94319\Documents\ChatGPT\vibex\timeline-monitor-fixtures-4048d328b0db4089913b8755b1ee6c92'
```

结果分别为 **PRESETS_UI_OK 21**、**UI_SMOKE_OK 96**、**MONITOR_SMOKE_OK 26**、**MONITOR_MEDIA_OK 12**，无浏览器页面异常。最后一项使用真实静音 MP4、含原声 MP4 和 MP3 验证原生解码及播放时钟，包含跨边界启动、混音开关隔离和释放；不等同于人工听音评测。

所有本次涉及的 JS/MJS 文件通过 `node --check`；指定 TE-0 Python 的 `compileall` 通过；`git diff --check` 及全部 21 个文件的 no-index 空白检查通过。最终隔离测试服务已停止。

截图已视觉检查，位于：

- `C:\Users\94319\Documents\ChatGPT\vibex\zv-processing-presets.png`
- `C:\Users\94319\Documents\ChatGPT\vibex\zv-processing-presets.editor.png`

## 重叠语义纠偏（2026-09-07）

新内置 H3 长参考预设升级为 v2：把原先误作参考默认值的 12 帧改为请求 48 帧，并通过独立的 `h3_guide` 策略派生实际 39 帧。请求值和对齐策略均写入完整规则快照；普通自动分段使用 `exact`，旧缺字段快照补 `exact` 后保留原版本与数值。编辑器和状态同时呈现请求值、实际值，预计段数使用实际重叠。本次没有新增切片或模型调用。

### 人工复现（当前契约）

1. 插件下次正常加载后，新建 ZV 节点，顶部应为“通用（默认）”。将结束改为 17 秒，应显示工程有效且符合预设。
2. 切换 H3 单段：起止值不变；显示橙色预设不兼容，并明确当前 17 秒 / 408 帧、有效上限 15 秒 / 360 帧、多 2 秒 / 48 帧，以及“工程本身有效”。切回通用恢复绿色。
3. 切到新 H3 长参考 v2 预设：17 秒可兼容，展示每段 48–360 帧、2–15 秒、请求重叠 48 帧、按 H3 Guide 网格向下对齐后的实际 39 帧、预计 2 段，以及“尚未执行分段”。把总范围改为 28 秒 / 672 帧，应按 321 帧步长预计 2 段；直接误用请求 48 会得出 3 段。增大到 90 秒，预计 7 段，不会截成 15 秒。
4. 点击“＋ 添加预设”输入名称和规则，或点击“复制当前”从现有规则开始。测试最少帧大于有效上限、负值、空名称、实际重叠达到有效单段最少帧，保存应被阻止且有中文说明。自动分段时应看到单段秒数、请求重叠和对齐策略字段；复制 H3 长参考后，请求从 48 改为 22 应实时显示实际 22，改为 12 显示实际 5；切换 `exact` 后请求 12 应原样得到实际 12。
5. 保存后具体名称出现在下拉。编辑后稳定 ID 不变、版本递增；保存旧项目再更新库、重载旧项目，仍使用旧快照。删除库条目不删除项目快照；清空浏览器存储后，用户库仍能由本地配置端点读回。
6. 通用模式关闭吸附后拖动处理窗口，非 24 fps 网格的秒数应被保留；预设切换不移动范围。不同目标 fps 的用户预设可通过显式修改“窗口参考 fps”解决帧率差异。
7. 按既有监看步骤播放重叠的静音视频和独立音频，切换预设，音频应继续；素材预览、黄线定位、裁剪、原声开关、卸载和删除行为保持原样。

运行中的用户 ComfyUI 未被重启或热修改。本次验收运行在隔离服务中；新增后端端点会在插件下次正常加载时注册。

### 本次纠偏的精确文件与复测结果

相对于纠偏开工时的 SHA256 基线，本次仅改动以下 12 个文件，无新增或删除仓库文件：

- `media_evidence/presets.py`：请求/实际重叠、受约束的对齐策略、按实际重叠计算段数和步长。
- `media_evidence/contract.py`：旧快照缺少对齐字段时，补 `exact` 后规范化。
- `media_evidence/preset_store.py`：旧库条目只在内存中补 `exact`，保存完整快照。
- `web/media_processing_presets.json`：新普通规则显式 `exact`；H3 长参考内置 v2 请求 48、`h3_guide`，说明可调初始值。
- `web/media_evidence_presets.mjs`：与 Python 相同的计算、迁移和请求/实际值摘要。
- `web/media_evidence_desk.js`：请求重叠输入、对齐策略选择和实时实际值预览。
- `schemas/zv-processing-preset-v1.schema.json`：完整快照规则及对齐枚举约束。
- `schemas/zv-media-project-v2.schema.json`：同步规则与三个派生字段。
- `tests/test_media_presets.py`：新增 15 个 Python 用例。
- `tests/media_evidence_presets.test.mjs`：新增 5 项纯函数测试。
- `tests/media_evidence_presets_ui_smoke.mjs`：新增 6 项浏览器检查，并输出本轮纠偏截图。
- `docs/ZV_PROCESSING_PRESETS_V2.md`：本次契约、证据、复现和复测记录。

沿用上方命令和运行时，本轮实际结果：

| 检查 | 本轮结果 |
| --- | --- |
| 指定 TE-0 Python 全部 pytest | **269 passed in 1.84s** |
| Node 核心 + 预设纯函数 | **54 passed**（35 + 19） |
| HTTP 预设库与媒体端点 | **MEDIA_SMOKE_OK 33** |
| 预设浏览器交互 | **PRESETS_UI_OK 27** |
| 既有剪辑交互 | **UI_SMOKE_OK 96** |
| 监看与混音控制 | **MONITOR_SMOKE_OK 26** |
| 原生解码/播放时钟/真实媒体 | **MONITOR_MEDIA_OK 12** |

新增断言涵盖 `48→39`、`22→22`、`12→5`、1/4/5 边界、`exact` 的 0/12 原值、非法对齐策略、实际重叠达到最短段时拒绝保存、672 帧按实际 39 得到步长 321 和 2 段、单窗口无重叠派生、旧 v2 与旧用户库语义保留、复制 H3 规则实时修改及保存重载。旧 v1 迁移、通用 17 秒、H3 单段 408 帧橙色提示、用户库版本和冻结快照均继续通过。

本次 4 个 JS/MJS 文件通过语法检查，4 个 Python 文件通过指定 TE-0 `compileall`；两份 schema 验证通过。截图已视觉检查，无字段或操作按钮被遮挡：

- `C:\Users\94319\Documents\ChatGPT\vibex\zv-processing-overlap-correction.png`
- `C:\Users\94319\Documents\ChatGPT\vibex\zv-processing-overlap-correction.editor.png`

独立只读复核未发现问题。其余既有工作、56 个工作流、TimelineDirector、ZI 与 H3 执行编译器未改；未 commit/push，未重启用户 ComfyUI。本轮隔离测试服务已停止。
