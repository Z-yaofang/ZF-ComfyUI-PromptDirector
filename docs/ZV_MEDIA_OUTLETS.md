# ZV 稳定素材出口

本文描述素材台当前默认的直接出口。出口以稳定 `item_id/clip_id` 绑定一个已入轨素材；旧版[固定出口槽位](ZV_MEDIA_SLOTS.md)只保留执行与恢复兼容，不再作为日常发送流程。

素材台仍输出 `media_project` / `project_json` 两个工程口。下游需要真实媒体时，按轨道项创建小出口节点；每个出口的端口固定，只有参与执行的出口才解码。

## 节点与连接

| 正式技术 ID / 显示名 | 必填输入 | 固定输出顺序 |
| --- | --- | --- |
| `ZVPictureOutlet` / ZV 图片素材出口 | `media_project: ZV_MEDIA_PROJECT`、`item_id: STRING` | `image: IMAGE`、`manifest_json: STRING`、`report: STRING` |
| `ZVVideoOutlet` / ZV 视频素材出口 | `media_project`、`clip_id: STRING`；旧工作流兼容用的可选 `target_width/target_height: INT` | `frames: IMAGE`、`original_audio: AUDIO`、`manifest_json`、`report` |
| `ZVAudioOutlet` / ZV 音频素材出口 | `media_project`、`clip_id: STRING` | `audio: AUDIO`、`manifest_json`、`report` |
| `ZVTimelineAudioOutlet` / ZV 时间线混音出口 | `media_project` | `timeline_audio: AUDIO`、`manifest_json`、`report` |
| `ZVProcessingWindowOutlet` / ZV 处理窗口参数出口 | `media_project` | `start_seconds: FLOAT`、`end_seconds: FLOAT`、`duration_seconds: FLOAT`、`fps: FLOAT`、`frame_count: INT` |

五类均位于 `ZV/视频创作/素材取证`，只注册以上正式 ID。素材台输出 0 连接出口输入 0。手动创建时可填写稳定 ID；自动创建时会写入对应输入控件和属性。`图片N` / `视频N` / `音频N` 只是当前显示标签，不用于查找身份。

图片、视频、独立音频从轨道项检查器的唯一主按钮发送，例如“发送图片6”。按钮只针对当前选择创建直接出口；同一稳定 ID 已有出口时复用。一个出口的媒体端口可正常分出任意数量的下游连线。视频的配对原声复用该视频出口的 `original_audio`，不会再创建独立音频出口；解除视频绑定后的音频可单独发送。素材池未入轨条目没有剪辑窗口与正式标签，不提供发送动作。

检查器的发送按钮固定在顶部，不随机械信息区滚动。不再出现“绑定到预接出口”、目标槽位下拉框或“另建出口”，因此无需理解后端 ID 对应关系。下游换线需求交给独立的 `ZFI` 转接排：右侧消费者一次接好，换素材时只重接 ZFI 左侧对应的一根线。

视频轨左侧“视频 / 秒时间轴”下方常驻两枚纵向按钮：上方“原声：开 / 关”切换当前关联原声，下方“解绑音频”解除现有关联。选中视频或它的关联原声均可操作；未选中、图片、独立音频或没有关联原声的视频时，两按钮仍显示但禁用，并提示“请先选择带原声的视频”。70px 标签栏内文字完整显示，无需滚动检查器。右侧不再重复显示这两个动作，独立音频的开关和重新关联入口仍保留。按钮沿用现有 `audioAction` 的 `toggle` / `unlink` 和撤销重做，不改变工程、出口或删除语义。刷新 ComfyUI 页面即可加载，无需重启后端。

自动生成根据实际工程连线、节点类型与稳定 ID 去重。重排只更新显示标签和标题；已存在节点的绑定及输出序号不变。删除或卸载后，旧出口保留原 ID，执行时报“绑定素材已不存在”，不会自动换到下一项。新增出口是普通可保存、可折叠的 ComfyUI 节点，不会扩展素材台尺寸或端口。缺少有效画布、节点 ID、目标节点类型或连接失败时显示中文错误，并清理本次未完成的创建。

## 时间与输出语义

- 图片按 `picture_track.item_id` 找到完整原图，不受处理窗口筛选；每次输出单张原尺寸 RGB `float32 [1,H,W,3]`，不为凑 batch 缩放。RGBA 转 RGB，不输出 mask。
- 视频/音频按稳定 `clip_id` 找片段，再与处理窗口的半开区间 `[start,end)` 求交。源入点为 `source_in_seconds + intersection_start - timeline_in_seconds`，源出点相应计算。输入的帧数、时长、出点与旧校验等派生字段均不能决定结果。
- 视频以 `processing_window.fps` 输出 CFR RGB `float32 [frames,H,W,3]`。帧数是 `floor(交集时长 × fps + 0.5)`；取样时刻为源入点 `+ k/fps`。按真实解码 PTS 选择覆盖目标时刻的前一帧；相同时间戳取较新帧。不能用平均 fps 推算源帧时钟。缺失或倒序 PTS、帧尺寸变化会报错。
- 素材台提供统一 `width` / `height` 输入。两者同时连接后会把 `output_canvas` 写入 `media_project`，所有视频直接出口、兼容槽位出口以及消费该工程的 H3 固定出口都会默认继承同一画布，不再逐个接宽高。读取选中源窗时，每解出一帧便保持比例、居中裁切并铺满目标画布，视频使用 BILINEAR，然后才写入最终 float32 批次；不会先形成原尺寸完整批次再缩放。
- 旧视频出口保留 `target_width` / `target_height` 以免破坏既有工作流。优先级固定为：出口上成对显式连接的尺寸 > 素材台 `output_canvas` > 原始视频尺寸。出口只显式连接一个尺寸时不会与素材台另一维拼接，而是明确报错。素材台尺寸也必须成对连接；所有目标尺寸必须是整数、32–16384 范围内的 32 倍数。完全不连接素材台和出口尺寸时仍按源像素输出，因此旧工作流行为不变。目标画布必须来自实际 H3 生成宽高，不根据文件方向猜测。
- 视频实际输出时长为 `frame_count/fps`，其原声采样数为 `floor(该时长 × 44100 + 0.5)`。manifest 分开保存原始交集源窗与按输出帧数对齐的实际源窗；当舍入使视频输出时长增加时，原声仍只读取原交集，额外尾部补零，不读入剪辑范围外声音。原声停用或源没有音频时，`original_audio` 为 `None`，不会伪造波形。
- 独立音频只导出该项与窗口的交集，不混入其他音频。仍与视频绑定的原声不能通过独立音频出口重复导出，应连接视频出口的原声端口。音频停用或没有交集时给出执行错误。
- AUDIO 均为 ComfyUI 标准 `{"waveform": float32 [1,2,samples], "sample_rate":44100}`。固定双声道；单声道复制，多声道按确定的立体声重混处理。样本数使用相同 half-up 规则。缺失的源音频时段与源尾以零填充，并在 manifest 标明。
- 时间线混音覆盖整个处理窗口，长度为 `floor((end-start) × 44100 + 0.5)`。每条已启用音频按交集起点相对窗口的位置落样，不移动音频以消除空白；前导、中间和末尾间隙保留静音。视频绑定原声与独立音频各计一次。无活动音频时返回对应长度的全零标准 AUDIO。
- 混音先按稳定轨道顺序累加；若合成绝对峰值超过 0.98，则全部样本统一乘以 `0.98/peak`，否则增益为 1。manifest 记录原峰值、最终增益、轨道空白与实际未解码样本的补零数量。音视频共用容器时间原点，保留原声晚于画面开始以及 PTS 间隙；不会把每条媒体流单独归零。
- 预设兼容性不替代真实模型校验。出口不会把通用 fps 强改为 24；使用 H3 时，素材台窗口参考 fps 应由用户设为 24，并由下游模型继续检查实际能力。
- 处理窗口参数出口只读取并校验工程 JSON，不访问素材文件，也不解码图片、视频或音频。`duration_seconds = end_seconds - start_seconds`；`frame_count` 使用工程统一的 half-up 起止帧边界计算。开始/结束秒保留窗口在完整工程时间线上的绝对位置，便于字幕、音效、多段生成和生成结果回填；只需要控制单次生成长度时可直接使用总时长、fps 和帧数。

## 执行边界与复现信息

纯计划位于 `media_evidence/outlet.py`；媒体解码位于 `media_evidence/outlet_decode.py`；节点接口位于 `media_evidence/outlet_nodes.py`。解码只通过 `MediaStore.canonical/record/resolve` 使用受控的不透明 handle，不接受外部路径或 URL。Pillow、PyAV、numpy、torch 在执行时导入，不新增依赖，也不复制 TimelineDirector 的私有实现。

每次节点执行重新核实私有素材登记记录，`IS_CHANGED` 与素材台相同返回 NaN；文件失效或变化必须重新导入。标准输出、报告和 manifest 在同一项目及文件事实下确定。异常不能靠空图、空槽或 `ready` 标记掩盖。

manifest 包含当前 label、稳定 item/clip ID、asset ID、不透明 source handle、工程交集、请求与实际源窗、目标 fps/帧数或采样率/样本数，以及 PTS 采样、补零和混音策略。manifest 不包含绝对源路径。

每次单个视频/音频输出或时间线混音最多 600 秒，视频最多 8192 帧，预计输出张量最多 12 GiB；H3 固定素材出口还会在任何解码开始前，对本次全部唯一图片、视频与独立音频做一次 12 GiB 合计预算，避免三段视频各自合法、同时驻留却把内存撑爆。未接目标画布时按源尺寸预算；接入目标画布时按真实目标尺寸预算，因此高分辨率原件可以安全地在解码阶段直接生成较小批次，而不会被源尺寸估算误杀。超限报错，不截断或自行猜测尺寸。视频与音频按所需源窗 seek 并流式解码，不先完整解码长文件。解码在包和帧边界检查 120 秒、250000 解码帧、500000 数据包限额，并检查实际尺寸和输出内存。120 秒是处理边界检查，不是操作系统级强制终止。

这一步借用成熟项目的“轻量计划进入消费端、按生成画布解码”边界，但仍保留当前工作流需要的标准 IMAGE/AUDIO 出口。它不是完整复制 TimelineDirector 的 `Material Plan → Plan Encoder`：同一 IMAGE 若继续同时扇出给 LOW、HIGH 与提示模型，下游仍可能各自产生额外张量。当前测试流应把 `ResolutionSelector` 的实际宽高接入素材台一次，由所有视频出口继承；后续若继续收敛内存模型，再把 H3 编码与提示模型低清媒体包分别内聚为消费节点。

视频真实 PTS 覆盖目标时刻时可复用覆盖它的画面；源首尾没有完整覆盖时，会明确记录和报告边界重复帧数。RGBA 丢弃 alpha；多声道音频使用现有 FFmpeg stereo 矩阵重混。输出遵循上述可复现转换，具体模型的像素尺寸、时长和资源限制仍由下游检查。

最初的出口节点工单不创建或改写用户工作流。出口可以输出下游模型直接接受的 IMAGE/AUDIO；具体模型端口映射与三步流程接线由后续 V1 工单完成。

## 验收记录（2026-09-07）

精确改动范围：5 个既有文件、8 个新增文件。既有文件为 `nodes.py`、`README.zh-CN.md`、`web/media_evidence_desk.js`、`tests/media_evidence_monitor_smoke.mjs`、`tests/media_evidence_smoke.py`；后两者仅增加新前端模块的路由加载名或静态白名单。

新增文件：

- `media_evidence/outlet.py`
- `media_evidence/outlet_decode.py`
- `media_evidence/outlet_nodes.py`
- `web/media_evidence_outlets.mjs`
- `tests/test_media_outlets.py`
- `tests/media_outlet_smoke.py`
- `tests/media_evidence_outlets_ui_smoke.mjs`
- `docs/ZV_MEDIA_OUTLETS.md`

在插件目录执行：

```powershell
& 'E:\AI_Models\ComfyUI-TE-0\python_embeded\python.exe' -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests --tb=short -rs
& 'E:\AI_Models\ComfyUI-TE-0\python_embeded\python.exe' tests/media_outlet_smoke.py
& 'E:\AI_Models\ComfyUI-TE\python_embeded\python.exe' tests/media_evidence_smoke.py
& 'E:\AI_Models\ComfyUI-TE-0\python_embeded\python.exe' -m compileall -q media_evidence nodes.py tests/test_media_outlets.py tests/media_outlet_smoke.py tests/media_evidence_smoke.py
node --test tests/media_evidence_core.test.mjs tests/media_evidence_presets.test.mjs
node --check web/media_evidence_desk.js
node --check web/media_evidence_outlets.mjs
node --check tests/media_evidence_outlets_ui_smoke.mjs
node --check tests/media_evidence_monitor_smoke.mjs
```

结果：**322 passed in 5.62s**（新增 53 项出口测试）、**OUTLET_MEDIA_OK 30**、**MEDIA_SMOKE_OK 33**、**54 项 Node 纯函数测试通过**；compileall 与 JS/MJS 语法检查通过。pytest 仅有当前 torch 导入触发的 pynvml 弃用提示。

浏览器命令：

```powershell
$playwrightPackage = 'C:\Users\94319\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$chromiumExecutable = 'C:\Users\94319\AppData\Local\ms-playwright\chromium_headless_shell-1234\chrome-headless-shell-win64\chrome-headless-shell.exe'
$frontendStatic = 'E:\AI_Models\ComfyUI-TE\python_embeded\Lib\site-packages\comfyui_frontend_package\static'
node tests/media_evidence_outlets_ui_smoke.mjs $playwrightPackage $chromiumExecutable $frontendStatic
node tests/media_evidence_monitor_smoke.mjs $playwrightPackage $chromiumExecutable
# 以下两项使用 tests/media_evidence_smoke.py --serve 打印的 HARNESS_URL；本轮为 http://127.0.0.1:11569。
$testUrl = 'http://127.0.0.1:11569'
node tests/media_evidence_presets_ui_smoke.mjs $testUrl $playwrightPackage $chromiumExecutable
node tests/media_evidence_ui_smoke.mjs $testUrl $playwrightPackage $chromiumExecutable --no-screenshot
```

结果：**OUTLETS_UI_OK 24**、**MONITOR_SMOKE_OK 30**、**PRESETS_UI_OK 27**、**UI_SMOKE_OK 96**，没有页面异常。出口检查包含本地实际 LiteGraph 的 4 项验证：创建与连线、serialize/configure 后稳定绑定与去重、标签更新与原生折叠、失败节点回滚。另覆盖单项/批量创建、配对原声复用、20 个紧凑节点不增加素材台尺寸/端口、删除不重绑、无画布/ID/节点类型时的错误与池外拖动拦截。

真实媒体测试生成两张不同尺寸 RGB/RGBA 图片、静音视频、含原声视频和独立音频，并实际调用四类节点取得 torch 张量；另生成原声晚于画面开始且中间有音频 PTS 空洞的 MKV，确认 22050 个样本精确补零。测试覆盖帧数、尺寸、RGB 范围、帧音同长、取整扩长尾部 2205 样本补零、窗口静音与重叠混音、VFR 真实 PTS 选择、缺失/倒序 PTS 与变尺寸拒绝、登记来源失效和修改后拒绝、资源限额、manifest 私密性与输入不变。

已实际加载注册表确认 4 个新 ID/类名/显示名唯一，原素材台两个端口不变。主界面截图已视觉检查：`C:\Users\94319\Documents\ChatGPT\vibex\zv-small-media-outlets-desk.png`。本轮隔离测试服务已停止；未 commit/push，未重启用户 ComfyUI，也未创建或改写用户工作流。

## 预接出口绑定追加验收（2026-09-07）

“绑定到预接出口”只改 `web/media_evidence_outlets.mjs`、`web/media_evidence_desk.js`、`tests/media_evidence_outlets_ui_smoke.mjs` 和本文档，未改 Python 后端。现有出口的保存 ID 字段、端口与下游连线不变。

结果：**OUTLETS_UI_OK 49**（原 24 + 新增 25）、**54 项 Node 纯函数测试通过**、**MONITOR_SMOKE_OK 30**，JS 语法和空白检查通过。新增用例覆盖图片/视频/独立音频、关联原声归视频、解除关联音频、widget 优先于旧 property、候选不存在/多个/跨素材台/类型错/已绑定/外部绑定输入时零修改；成功绑定保留双下游连线、工程、播放头与其他节点，记录图更改，实际 LiteGraph 保存重载后绑定仍在。

唯一用户工作流副本 `MiniMax H3 10Eros Beta4 三步测试-ZV素材出口V1.json` 仅更新 #169 Note 的操作说明，不改节点、连线或空绑定。更新后仍 121 节点/192 连线，原件仍 116/189 且 SHA256 不变。静态范围复验 `V1_NOTE_ONLY_OK` 与实际前端加载往返复验 `H3_V1_LITEGRAPH_OK` 均通过。已打开的页面需刷新加载前端更新，无需重启服务；未执行生成、未提交或推送。

## 轨道原声按钮及出口主操作布局验收（2026-09-07）

原检查器底部“开 / 关原声”和“解除绑定”分别沿用 `audioAction(...,"toggle")` / `audioAction(...,"unlink")`，移至视频轨左侧，显示“原声：开 / 关”和“解绑音频”，无重复入口。检查器固定出口区使用与实际绑定相同的候选查询，唯一合法空预接出口时优先绑定，其余情况优先创建。新增布局没有修改 `media_evidence_core.mjs` 或任何 Python 文件，也没有改写原工作流或 V1。

本轮精确改动 8 个既有文件：`web/media_evidence_desk.js`、`web/media_evidence_desk.css`、`web/media_evidence_outlets.mjs`；测试 `media_evidence_outlets_ui_smoke.mjs`、`media_evidence_ui_smoke.mjs`、`media_evidence_monitor_smoke.mjs`、`media_evidence_monitor_media_smoke.mjs`；以及本文档。后三个测试仅跟随按钮最终文案更新定位。

结果：**OUTLETS_UI_OK 71**（原 49 + 新增 22）、**UI_SMOKE_OK 96**、**MONITOR_SMOKE_OK 30**、**MONITOR_MEDIA_OK 12**、**Node 54 passed**。覆盖双选择入口、状态切换及撤销重做、现有解绑路径、无选择/图片/独立音频/无关联视频的可见禁用态、70px轨道标签栏和低节点高度、无重复按钮、固定主次出口操作、绑定保留双消费者、另建出口、多个候选不猜测。JS语法和空白检查通过，测试浏览器无页面异常。隔离测试服务已停止；未重启用户服务、未运行模型生成、未提交或推送。
