# ZV 处理预设

处理预设只说明“这段范围准备给什么用途、应满足哪些时间规则”。它不调用模型、不生成提示词，也不会仅因切换预设就移动窗口或素材切点。素材编辑见[通用素材取证台](ZF_MEDIA_EVIDENCE_DESK_V1.md)，下游选择见[节点指南](NODE_GUIDE.md)。

## 选择哪种预设

| 内置预设 | 规则 | 适用范围 |
| --- | --- | --- |
| 通用（默认） · `builtin.generic` | 无模型 fps、帧数、时长限制，不强制对齐网格 | 一般素材编排；仍遵守工程与媒体资源上限 |
| MiniMax H3 · 单段生成 · `builtin.minimax-h3.single` | 24 fps、48–360 帧、最多 15 秒，窗口起止按目标网格对齐 | H3 单次生成范围 |
| MiniMax H3 · 长参考动作迁移 · `builtin.minimax-h3.segmented` | 每段 24 fps、48–360 帧、2–15 秒；请求重叠默认 48 帧，实际 Guide 重叠 39 帧 | 估算 H3 长任务能否由合法分段覆盖 |

新建工程默认通用，不是默认 H3。窗口参考 fps 可独立编辑；24 fps 只是 H3 内置规则及新工程的初始值，不是所有视频的固定帧率。

长参考预设仅保存和展示规则、预计段数，不在素材台执行切片。实际 H3 分段由[H3 长视频分段台](LONG_VIDEO_GUIDE.md)执行。Animate 使用已经剪好的片段及自己的“硬切 / 原生 21 帧承接”方案，不使用这里的 H3 Guide 重叠规则。

## 编辑和保存

在预设下拉选择已有规则，或点“＋ 添加预设”复制、填写自己的规则。内置预设只能复制，不能直接改删；用户预设可以编辑、删除。

切换预设保留窗口起止秒、窗口参考 fps、素材及稳定 ID。若新规则不兼容，只显示原因，不自动截短或回摆。例如 24 fps 下的 17 秒范围，通用预设可接受；H3 单段会提示超过 15 秒 / 360 帧，但原范围仍为 17 秒。

工程保存 `processing_preset = {preset_id, preset_version, snapshot}`。快照包含完整规则，用户库后来更新或删除，不会悄悄改变已有工程。旧快照会在列表中标识；要采用新规则需显式选择。

## 规则契约

snapshot 包含 `name`、`description`、`strategy` 和 `rules`。规则定义见 [zv-processing-preset-v1.schema.json](../schemas/zv-processing-preset-v1.schema.json)。

| 规则 | 含义 |
| --- | --- |
| `strategy` | `single_window` 单窗口，或 `auto_segment` 分段兼容性估算 |
| `target_fps` | 目标帧率，支持 1–240；通用无固定目标时为 null |
| `min_frames` / `max_frames` | 单窗口或每段的帧数上下限 |
| `max_seconds` | 单窗口最长秒数；分段策略下是可选总任务时长上限 |
| `align_to_grid` | 是否要求窗口起止对齐目标帧网格 |
| `segment_min_seconds` / `segment_max_seconds` | 自动分段每段的时长上下限 |
| `overlap_frames` / `overlap_alignment` | 请求重叠帧和实际重叠的计算策略 |

未设上下限使用 null，不用 0 表示无限。有帧数限制、网格对齐或自动分段时必须有目标 fps；自动分段还需设置单段最短和最长秒数。帧数与时长同时约束时，取更严格的有效上下限。单窗口不能带分段时长、重叠或专用重叠策略。

### 请求重叠与实际重叠

- `exact`：实际值就是请求值，可以是 0；普通自定义分段使用此策略，不套 H3 网格。
- `h3_guide`：请求至少 1 帧，向下对齐到 1 或 `5 + 17k` 帧（k 为非负整数）。例如 48→39、22→22、12→5，1–4→1。

实际重叠必须小于有效单段最少帧数。48 是 H3 长参考的可调初始请求值，不是模型固定能力；要看分段台实际采用的 Guide 帧数。

总范围为 T 帧、有效单段最少/最多为 L/U、实际重叠为 O 时，步长为 `U - O`，预计段数为 `max(1, ceil((T - O) / (U - O)))`。还需满足 `T + (段数 - 1) × O ≥ 段数 × L`，保证短段约束下能覆盖范围。计算使用实际 O，不直接使用请求值。例如 672 帧、每段最多 360 帧、实际重叠 39 帧时，步长为 321，预计 2 段。

## 工程错误与预设不兼容

`validation.errors` 表示工程本身有问题，例如结构错误、来源失效、裁剪越界、非正范围或超出工程上限。`preset_compatibility` 表示工程是否适合当前规则，包含中文原因、目标帧数、有效上下限和预计段数。

分段结果另含 `requested_overlap_frames`、`effective_overlap_frames`、`segment_stride_frames`；非分段策略下这些派生字段为 null。标签、帧数、兼容性在规范化时重新计算，不信任保存过的旧结果。

界面用红色表示工程错误，橙色表示工程有效但预设不兼容，绿色表示两者通过。预设不是模型能力证明；H3 素材出口、长视频执行及实际模型仍独立检查各自契约。

## 已保存工程与用户库

旧 `schema_version: 1` 工程缺少预设时，按原语义读取为 H3 单段预设；新建 `schema_version: 2` 工程默认通用。读取保留原素材、片段 ID 与窗口秒数。

旧快照缺少 `overlap_alignment` 时补为 `exact`，保留原请求值、ID 和版本。旧 H3 长参考中保存的 12 帧不会自动升级为 48 或改成 5 帧。用户数据兼容不意味着旧节点仍注册。

用户库在当前 ComfyUI 用户目录的 `zf_media_evidence/processing_presets.json`，路径由宿主确定，不由网页任意指定。读取旧库只规范化返回值，显式保存才写入；更新使用版本校验，拒绝覆盖较新的修改。

本地接口为 `GET /zf-media-evidence/presets`、`POST /zf-media-evidence/presets`、`PUT /zf-media-evidence/presets/{id}`、`DELETE /zf-media-evidence/presets/{id}`。内置 ID 只读，用户 ID 由服务器生成；文件写入检查路径并使用原子替换。

## 回归入口

在具备插件依赖的 Python 环境、插件根目录执行：

```text
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests/test_media_presets.py
node --test tests/media_evidence_presets.test.mjs
python tests/media_evidence_smoke.py
```

预设浏览器回归为 `tests/media_evidence_presets_ui_smoke.mjs`，参数见脚本开头。主要检查范围保留、快照隔离、请求/实际重叠、库版本冲突和内置保护；不宣称视频模型或云端成片已通过。
