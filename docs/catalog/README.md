# 导演台插件节点盘点（2026-09-24）

[打开全节点盘点工作流](导演台插件全部节点.json)。该文件没有测试素材，只用于总览，不应整图排队运行。

盘点范围只包括 `ZF-ComfyUI-PromptDirector`，不包括 ComfyUI 自带节点、其他作者的节点，也不包含测试素材。当前源码注册 **47 种后端节点**，前端另有 **1 种虚拟接线节点 `ZFI`**，合计 **48 种**。随附的《导演台插件全部节点.json》每种放 1 个实例，按 9 个用途区分组；59 条线仅展示可以确认的接口关系。它是节点目录，**不能整张直接排队运行**：模型、SAM/SeC、循环器等外部环节故意留空。

## 先看结论

- **GitHub 有更新。** 本盘点的代码基线为 `7ae48b9735b08650b66d647ed7b22257a3e8a425`；9 月 22 日加入 Animate 一次成片的 `6039d1d` 已有 46 种后端节点，随后循环／保存等修复主要改变既有节点行为。到本盘点时后端节点只净增 1 种：`ZVAnimateFinalComparison`。`7ae48b9` 主要避免 OpenCV 在云端导入时挡住插件注册。Git 更新不等于 RunningHub 已部署；需要平台的拉取 SHA、启动日志或节点列表确认。
- **“节点多”有两种口径。** 48 是插件可选的节点*种类*，不是每个正式工作流都要放 48 个。仓库维护的三张 H3 示例工作流分别有 73、77、80 个总节点，其中本插件节点实例只有 15、22、25 个，其余包含模型和其他插件节点。H3 反推节点虽常放 3 个实例，仍只算 1 种类型。
- **当前没有证据能安全删除某个仍注册的节点。** 29/48 种没有出现在仓库的三张 H3 示例中，但那些示例不覆盖 Animate、Music3、图像导演、人像，不能把“示例未用”当作“无用”。最值得进一步审查的是薄包装辅助节点 `ZFDecisiveLlamaParams`；删除前必须查用户现有工作流兼容性。
- 已废弃的 7 种旧技术 ID 没有加入画布，也不应恢复：`ZVH3InterviewForm`、`ZVH3FocusCompiler`、`ZVPictureSlotOutlet`、`ZVVideoSlotOutlet`、`ZVAudioSlotOutlet`、`ZFBlueprintParser`、`ZFSinglePromptTask`。

以下“入口”是用户选择任务时先放的节点；“配套”用于对应流程；“可选”或“专项”不是无用。

## 01 素材台与出口（9 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZVUniversalMediaEvidenceDesk` | 导入、裁切、排序并记录图片／视频／音频及处理窗口；输出素材工程与原素材来源。 | 入口 |
| `ZVOriginalPictureOutlet` | 从素材池取未被时间线裁切的完整原图。 | 可选原素材出口 |
| `ZVOriginalVideoOutlet` | 从素材池取完整原视频，输出原生 `VIDEO`。 | 可选原素材出口 |
| `ZVOriginalAudioOutlet` | 从素材池取完整原音频。 | 可选原素材出口 |
| `ZVPictureOutlet` | 用稳定 `item_id` 取已经入图片轨的图片。 | 可选入轨出口 |
| `ZVVideoOutlet` | 用稳定 `clip_id` 取已剪视频片段与对应原声，输出图像帧批次。 | 可选入轨出口 |
| `ZVAudioOutlet` | 用稳定 `clip_id` 取已剪音轨片段。 | 可选入轨出口 |
| `ZVTimelineAudioOutlet` | 混合处理窗口内启用的时间线音频。 | 可选混音出口 |
| `ZVProcessingWindowOutlet` | 只输出窗口起止、时长、帧率与帧数，不加载素材。 | 可选参数出口 |

完整原素材出口与已入轨出口读取范围不同，尤其原视频 `VIDEO` 与剪辑视频 `IMAGE` 帧批次不同，不能简单合并。

## 02 H3 单段（3 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZVH3InterviewFormV2` | 收集需求、对齐素材编号，输出中文原稿、素材上下文与参考计划。 | 入口 |
| `ZVH3ReverseStage` | 组织“素材理解／中文意图／H3 成稿”反推阶段的模型任务；本身不加载模型。 | 配套；一个类型可放三次 |
| `ZVH3ReferenceOutlet` | 按参考计划输出首尾帧、参考图／视频／音频到 H3 固定接口。 | 配套 |

## 03 H3 长视频（12 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZVLongVideoSegmentDesk` | 制定 H3 长视频分段、时钟与素材计划。 | 入口 |
| `ZVSegmentInterview` | 收集每段要求并形成执行计划。 | 配套 |
| `ZVSegmentVideoMaskSource` | 为 H3 蒙版流程提供源视频帧和音频。 | 蒙版专项 |
| `ZVMaskedSegmentBundle` | 把外部 MASK 与分段素材、来源信息绑定。 | 蒙版专项 |
| `ZVSegmentMaskSlice` | 从绑定结果取当前分段的 MASK 与时钟证据。 | 蒙版专项 |
| `ZVH3MaskedSegmentLatent` | 将 H3 当前蒙版段准备成音视频 Latent 和模型输入。 | 蒙版专项 |
| `ZVH3MaskedLatentRestore` | 将生成 Latent 与源 Latent 按 MASK 恢复。 | 蒙版专项 |
| `ZVH3MaskedFrameCompose` | 在像素层把生成帧贴回源画面。 | 蒙版专项 |
| `ZVLongVideoExecutionSetup` | 为循环器给出分段数量和准备报告。 | 执行配套 |
| `ZVLongVideoExecutionEntry` | 每轮取当前段的提示词、素材、参考和承接信息。 | 执行配套 |
| `ZVLongVideoSegmentRecorder` | 记录每段实际生成帧、音频与证据。 | 执行配套 |
| `ZVLongVideoExecutionEnd` | 按执行计划精确拼接完整视频。 | 执行配套 |

这里的六个 MASK 节点专供 H3 蒙版模板，不应与 Animate 的 SAM/SeC 三节点混作一套。

## 04 Animate（8 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZVAnimateSegmentDesk` | 把素材台已剪视频与图片逐段配对，选择硬切／21 帧承接和遮罩总开关。 | 入口 |
| `ZVAnimateExecutionEntry` | 循环中读当前段源帧、图片、原声和段上下文。 | 执行配套 |
| `ZVAnimateSegmentRecorder` | 收集原流真正生成并裁回的当前段成品。 | 执行配套 |
| `ZVAnimateExecutionEnd` | 用各段真实成品合成完整视频。 | 执行配套 |
| `ZVAnimateFinalComparison` | 把完整原片与完整成片排列成对照视频。 | 可选输出 |
| `ZVAnimateMaskFrame` | 把素材台指定源帧映射到当前段的遮罩参考索引。 | 遮罩专项 |
| `ZVAnimateMaskSeed` | 检查参考帧种子 MASK 是否对应正确画面。 | 遮罩专项 |
| `ZVAnimateMaskGate` | 整条视频遮罩总开关；关闭时跳过对应支路。 | 遮罩专项 |

三个遮罩节点分别做索引、校验和开关，不是三张重复的表。目录画布不含外部 WanAnimatePlus、SAM/SeC 或循环器节点，所以这些接口保持开放。

## 05 图像提示词（8 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZFPromptDirector` | 按用户提示、用途、视觉方法与参考图组织图像创意写作任务。 | 入口 |
| `ZFReferenceAnalysisPromptBuilder` | 生成给外部模型使用的参考图分析指令。 | 可选参考图配套 |
| `ZFImageReferenceAnalyzer` | 整理参考图观察结果、参考强度与可迁移说明。 | 可选参考图配套 |
| `ZFReferenceCreativeAdapter` | 将参考图分析转成导演节点可消费的临时创意 JSON。 | 可选参考图配套 |
| `ZFPromptDirectorLocalLLM` | 通过外部 llama.cpp 模型执行本地多模态写作。 | 可选模型接口 |
| `ZFDecisiveLlamaParams` | 透传 llama 参数并移除 `grammar` 限制。 | 薄包装辅助；后续可审查 |
| `ZFPromptValidator` | 清理生成文本并报告长度、空输出等情况。 | 可选结果整理 |
| `ZFLazyPromptSwitch` | 在原始提示词与增强提示词之间按开关懒执行选择。 | 可选旁路 |

## 06 Music3（2 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZFMusic3PromptDirector` | 把歌词语言、声乐模式、时长、参考风格整理成 Music3 写作任务。 | 入口 |
| `ZFMusic3ResponseParser` | 把外部模型返回拆为 caption、lyrics 和参考分析。 | 配套 |

## 07 文字辅助（4 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZFPromptDirectorAnyFilter` | 按条件过滤、移除或透传任意输入。 | 可选工具 |
| `ZFPromptDirectorMultiTextSelector` | 从多路文本中选定一路。 | 可选工具 |
| `ZFTextMemory` | 跨队列复用一条文本。 | 可选缓存 |
| `ZFTextListMemory` | 跨队列复用整组文本。 | 可选缓存 |

单文本缓存与文本列表缓存的数据粒度不同，不能仅凭名称认为重复。

## 08 人像（1 种）与 09 前端转接（1 种）

| 技术 ID | 做什么 | 定位 |
| --- | --- | --- |
| `ZIPortraitPromptGenerator` | 从选项或参考分析组装人像提示词。 | 独立入口 |
| `ZFI` | 前端最多 32 路线缆转接排；不执行后端推理，不出现在 `/object_info`。 | 纯画布工具 |

## 怎样据此精简

1. **先按场景收起节点，不删接口。** 普通 Animate 只看素材台＋Animate 组；普通 H3 不放长视频蒙版六件套；图像／音乐／人像各自独立。
2. **再按实际用户工作流统计。** 需要拿到 RunningHub 已发布工作流及日常本地工作流，统计哪些技术 ID 真正出现、是否仍有旧 JSON 依赖；仓库三张 H3 示例不足以判废弃。
3. **若要减注册数量，优先评估薄包装辅助节点**，但先提供迁移路径和旧图兼容性检查。不要直接删除出口、缓存、执行链或遮罩节点。

核查依据：插件 `nodes.py` 的 `NODE_CLASS_MAPPINGS`、`web/zfi_reroute.js` 的前端注册、`docs/NODE_GUIDE.md`、`docs/examples/` 三张维护模板及 Git `main`。盘点时本地 6500 端口未运行；该目录画布的结构通过源码接口检查，但不能据此断言 RunningHub 当前已加载同一版本。
