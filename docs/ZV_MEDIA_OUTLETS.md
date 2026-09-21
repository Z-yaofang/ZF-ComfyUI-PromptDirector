# ZV 稳定素材出口

本文描述素材台当前的直接出口。出口以稳定 `item_id/clip_id` 绑定一个已入轨素材；废弃的固定槽位节点与面板已经移除。

素材台输出 `media_project`、`project_json` 和“原素材来源”（`ZV_ORIGINAL_SOURCES`）。本文的剪辑出口读取 `media_project`；完整原素材出口的 `original_sources` 输入口连接“原素材来源”，详见[原素材来源绑定](H3_V2_07_SOURCE_BINDING.md)。H3 固定出口则读取 `reference_plan`，三者的范围和用途不同，见[节点指南](NODE_GUIDE.md)。每个出口的端口固定，只有参与执行的媒体出口才解码。

## 节点与连接

| 正式技术 ID / 显示名 | 必填输入 | 固定输出顺序 |
| --- | --- | --- |
| `ZVPictureOutlet` / ZV 图片素材出口 | `media_project: ZV_MEDIA_PROJECT`、`item_id: STRING` | `image: IMAGE`、`manifest_json: STRING`、`report: STRING` |
| `ZVVideoOutlet` / ZV 视频素材出口 | `media_project`、`clip_id: STRING`；可选 `target_width/target_height: INT` | `frames: IMAGE`、`original_audio: AUDIO`、`manifest_json`、`report` |
| `ZVAudioOutlet` / ZV 音频素材出口 | `media_project`、`clip_id: STRING` | `audio: AUDIO`、`manifest_json`、`report` |
| `ZVTimelineAudioOutlet` / ZV 时间线混音出口 | `media_project` | `timeline_audio: AUDIO`、`manifest_json`、`report` |
| `ZVProcessingWindowOutlet` / ZV 处理窗口参数出口 | `media_project` | `start_seconds: FLOAT`、`end_seconds: FLOAT`、`duration_seconds: FLOAT`、`fps: FLOAT`、`frame_count: INT` |

五类均位于 `ZV/视频创作/素材取证`，只注册以上正式 ID。素材台输出 0 连接出口输入 0。手动创建时可填写稳定 ID；自动创建时会写入对应输入控件和属性。`图片N` / `视频N` / `音频N` 只是当前显示标签，不用于查找身份。

图片、视频、独立音频从轨道项检查器的唯一主按钮发送，例如“发送图片6”。按钮只针对当前选择创建直接出口；同一稳定 ID 已有出口时复用。一个出口的媒体端口可正常分出任意数量的下游连线。视频的配对原声复用该视频出口的 `original_audio`，不会再创建独立音频出口；解除视频绑定后的音频可单独发送。素材池未入轨条目没有剪辑窗口与正式标签，不提供剪辑出口；可以通过“发送原素材”读取完整原文件。

检查器的发送按钮固定在顶部，不随机械信息区滚动。不再出现“绑定到预接出口”、目标槽位下拉框或“另建出口”，因此无需理解后端 ID 对应关系。下游换线需求交给独立的 `ZFI` 转接排：右侧消费者一次接好，换素材时只重接 ZFI 左侧对应的一根线。

视频轨左侧“视频 / 秒时间轴”下方常驻两枚纵向按钮：上方“原声：开 / 关”切换当前关联原声，下方“解绑音频”解除现有关联。选中视频或它的关联原声均可操作；未选中、图片、独立音频或没有关联原声的视频时，两按钮仍显示但禁用，并提示“请先选择带原声的视频”。70px 标签栏内文字完整显示，无需滚动检查器。右侧不再重复显示这两个动作，独立音频的开关和重新关联入口仍保留。按钮沿用现有 `audioAction` 的 `toggle` / `unlink` 和撤销重做，不改变工程、出口或删除语义。刷新 ComfyUI 页面即可加载，无需重启后端。

自动生成根据实际工程连线、节点类型与稳定 ID 去重。重排只更新显示标签和标题；已存在节点的绑定及输出序号不变。删除或卸载后，旧出口保留原 ID，执行时报“绑定素材已不存在”，不会自动换到下一项。新增出口是普通可保存、可折叠的 ComfyUI 节点，不会扩展素材台尺寸或端口。缺少有效画布、节点 ID、目标节点类型或连接失败时显示中文错误，并清理本次未完成的创建。

## 时间与输出语义

- 图片按 `picture_track.item_id` 找到完整原图，不受处理窗口筛选；每次输出单张原尺寸 RGB `float32 [1,H,W,3]`，不为凑 batch 缩放。RGBA 转 RGB，不输出 mask。
- 视频/音频按稳定 `clip_id` 找片段，再与处理窗口的半开区间 `[start,end)` 求交。源入点为 `source_in_seconds + intersection_start - timeline_in_seconds`，源出点相应计算。输入的帧数、时长、出点与旧校验等派生字段均不能决定结果。
- 视频以 `processing_window.fps` 输出 CFR RGB `float32 [frames,H,W,3]`。帧数是 `floor(交集时长 × fps + 0.5)`；取样时刻为源入点 `+ k/fps`。按真实解码 PTS 选择覆盖目标时刻的前一帧；相同时间戳取较新帧。不能用平均 fps 推算源帧时钟。缺失或倒序 PTS、帧尺寸变化会报错。
- 素材台提供统一 `width` / `height` 输入。两者同时连接后会把 `output_canvas` 写入 `media_project`，视频直接出口以及消费该工程的 H3 固定出口都会默认继承同一画布，不再逐个接宽高。读取选中源窗时，每解出一帧便保持比例、居中裁切并铺满目标画布，视频使用 BILINEAR，然后才写入最终 float32 批次；不会先形成原尺寸完整批次再缩放。
- 视频出口支持单独指定 `target_width` / `target_height`。优先级固定为：出口上成对显式连接的尺寸 > 素材台 `output_canvas` > 原始视频尺寸。出口只显式连接一个尺寸时不会与素材台另一维拼接，而是明确报错。素材台尺寸也必须成对连接；所有目标尺寸必须是整数、32–16384 范围内的 32 倍数。完全不连接素材台和出口尺寸时仍按源像素输出，因此旧工作流行为不变。目标画布必须来自实际 H3 生成宽高，不根据文件方向猜测。
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

按生成画布解码只控制本插件的媒体输出批次。相同 IMAGE 扇出给多个模型后，下游仍可能各自产生额外张量；这些出口不负责模型加载或显存卸载。

视频真实 PTS 覆盖目标时刻时可复用覆盖它的画面；源首尾没有完整覆盖时，会明确记录和报告边界重复帧数。RGBA 丢弃 alpha；多声道音频使用现有 FFmpeg stereo 矩阵重混。输出遵循上述可复现转换，具体模型的像素尺寸、时长和资源限制仍由下游检查。

具体 H3 端口映射使用[当前采访表模板](H3_INTERVIEW.md)。Animate 的原流附加层按已剪片段运行，参见[一次成片方案](ANIMATE_ONCE.md)，不要把这里的窗口交集规则套到原素材出口或 Animate 批次上。

## 回归入口

在已具备插件依赖的 Python 环境、插件根目录执行：

```text
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests/test_media_outlets.py tests/test_h3_reference_outlet.py
python tests/media_outlet_smoke.py
node --test tests/media_evidence_original_outlets.test.mjs
```

浏览器交互回归为 `tests/media_evidence_outlets_ui_smoke.mjs`，监看回归为 `tests/media_evidence_monitor_smoke.mjs`；运行参数见脚本开头。旧版本的次数统计和已取消的“预接出口绑定”验收日记不再作为当前操作说明。
