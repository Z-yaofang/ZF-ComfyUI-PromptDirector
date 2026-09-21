# 节点用途与当前入口

插件有多条独立用途，不是一条必须全部串起来的巨型流程。先选任务，再使用对应入口和已接好的执行模板。

## 先选入口

| 要做什么 | 当前入口 | 不需要什么 |
| --- | --- | --- |
| 导入、剪切、排序、试听素材 | `ZVUniversalMediaEvidenceDesk` · 通用素材取证台 | 采访表、反推模型 |
| 按用途和视觉方法写图像提示词 | `ZFPromptDirector` · 提示词创意导演 | H3、Animate 分段台 |
| 从预设或手填选项组装人像提示词 | `ZIPortraitPromptGenerator` · 人像提示词生成器 | 反推模型、H3 采访表 |
| 写 Music3 音乐提示词 | `ZFMusic3PromptDirector` · 音乐反推导演 | 视频分段台 |
| 生成一段 H3 视频 | `ZVH3InterviewFormV2` · H3 采访表 · 收集对齐整理 | 旧基础采访表、旧阶段文字出口 |
| 分段生成 H3 长视频 | `ZVLongVideoSegmentDesk` · H3 长视频分段台 + `ZVSegmentInterview` · H3 分段采访表 | Animate 配对台 |
| 用原 WanAnimatePlus 流逐段迁移或替换，一次成片 | `ZVAnimateSegmentDesk` · Animate 素材配对台 | H3 采访表、提示词反推 |

## 素材出口不是三个版本

素材台负责素材和剪辑，输出 `media_project`、`project_json` 和“原素材来源”（`ZV_ORIGINAL_SOURCES`，接下游 `original_sources`）。定位、分割和时钟说明见[素材台用法](ZF_MEDIA_EVIDENCE_DESK_V1.md)，通用与 H3 规则区别见[处理预设](ZV_PROCESSING_PRESETS_V2.md)。以下出口读取的范围不同，不能混为重复节点。

| 出口 | 读取什么 | 用在什么地方 |
| --- | --- | --- |
| `ZVOriginalPictureOutlet` / `ZVOriginalVideoOutlet` / `ZVOriginalAudioOutlet` | 素材池中的完整原文件，绑定 `asset_id`，不受时间线剪裁与处理窗口影响 | 想把原素材交给别的加载、编辑或生成链 |
| `ZVPictureOutlet` / `ZVVideoOutlet` / `ZVAudioOutlet` | 已入轨的稳定 `item_id` / `clip_id`；视频、音频取与处理窗口的交集 | 通用工作流需要某张图或某个已剪片段 |
| `ZVH3ReferenceOutlet` | 按 `reference_plan` 发送本次 H3 选定的首尾帧和参考素材 | H3 模板的固定物理输入，不靠文字猜接线 |

另外，`ZVTimelineAudioOutlet` 混合整个窗口的已启用音频；`ZVProcessingWindowOutlet` 只输出窗口时间、帧率和帧数，不解码媒体。二者都是可选工具。

原视频出口输出原生 `VIDEO`；剪辑视频出口输出 `IMAGE` 帧批次及配对 `AUDIO`，它们不是互换接口。详见[原素材绑定](H3_V2_07_SOURCE_BINDING.md)和[稳定素材出口](ZV_MEDIA_OUTLETS.md)。

## H3：一张表，三个独立反推阶段

选择 **ZV H3 采访表 · 收集对齐整理**，技术 ID 为 `ZVH3InterviewFormV2`。它的主要文字输出是中文 `user_prompt` 和 `material_context_json`；空项省略。表格收集用户需求、对齐素材编号并整理原稿，不观察图片、不补剧情、不生成系统提示词。

表格共七个输出：`user_prompt`、`material_context_json`、`duration_seconds`、`interview_json`、`human_report`、`ready`、`reference_plan`。

`ZVH3ReverseStage` 是同一个节点的三个实例，分别选择三个阶段；各自的 `system_prompt` 可以独立替换，并交给实际模型执行。

| 阶段 | 负责的事 |
| --- | --- |
| 素材理解 | 看实际图片和视频抽帧，对齐编号，区分观察事实与用户要求 |
| 中文意图整理 | 结合表格原稿和素材观察，输出供用户检查的中文提示词 |
| H3 提示词生成 | 结合中文要求、观察及视觉素材，按独立预设输出最终 H3 提示词 |

`ZVH3ReverseStage` 负责组织模型输入，不自己装载模型。工作流中的本地或 API 模型完成反推；真实素材通过 `ZVH3ReferenceOutlet` 进入 H3，文字链不改变接线。参见[采访表与模板](H3_INTERVIEW.md)。

### H3 长视频

`ZVLongVideoSegmentDesk` 管分段计划，`ZVSegmentInterview` 收集每段需求。它们使用相同的独立三阶段反推，不是保留了一套旧采访表。

执行模板使用 `ZVLongVideoExecutionSetup`、`ZVLongVideoExecutionEntry`、`ZVLongVideoSegmentRecorder`、`ZVLongVideoExecutionEnd` 完成逐段运行、记录和拼接；这些不是需要用户反复手填的第二套分段界面。

只有 H3 蒙版模板需要 `ZVSegmentVideoMaskSource`、`ZVMaskedSegmentBundle`、`ZVSegmentMaskSlice`、`ZVH3MaskedSegmentLatent`、`ZVH3MaskedLatentRestore`、`ZVH3MaskedFrameCompose`。它们分别处理源视频、外部 MASK 绑定与切片、Latent 和最终像素回贴，不用于 Animate 的 SAM/SeC 路径。参见[H3 长视频与蒙版](LONG_VIDEO_GUIDE.md)。

## Animate：配对并重复执行原流

素材台先剪好视频、排好图片；Animate 配对台按从左到右逐段一一对应，视频保留自身原声。这里不重复剪裁，也不写提示词。

只选择“硬切”或“原生 21 帧承接”，以及整条视频共用的遮罩总开关。关闭遮罩跑动作迁移；开启后逐段填写目标词和参考源帧。切点不由分段台移动，原流继续负责补帧与裁回，Plus 本身不修改。承接输出存在帧数差异时报告实际值，不默默补帧冒充精确一致。

`ZVAnimateExecutionEntry` 取当前段，`ZVAnimateSegmentRecorder` 收集原流成品，`ZVAnimateExecutionEnd` 合成完整视频。`ZVAnimateMaskFrame`、`ZVAnimateMaskSeed`、`ZVAnimateMaskGate` 分别负责遮罩参考帧索引、种子检查和真正跳过遮罩支路；不是三张新表格。使用[原流一次成片附加方案](ANIMATE_ONCE.md)，不要手工重复搭每一段。

## 仍有用的独立辅助节点

| 节点 | 用途 |
| --- | --- |
| `ZFImageReferenceAnalyzer`、`ZFReferenceAnalysisPromptBuilder`、`ZFReferenceCreativeAdapter` | 图像创意参考：观察或构造分析任务，再把分析接入图像导演；不是 H3 的旧表格 |
| `ZFPromptDirectorLocalLLM` | 执行本地多模态写作，依赖 llama.cpp 模型加载器 |
| `ZFDecisiveLlamaParams` | Llama 参数透传 |
| `ZFPromptValidator` | 图像提示词整理与观察 |
| `ZFMusic3ResponseParser` | 将 Music3 结果分为 caption、lyrics 和分析 |
| `ZFTextMemory`、`ZFTextListMemory` | 分别复用单条文本、整组文本；只在需要跨队列缓存时使用 |
| `ZFLazyPromptSwitch`、`ZFPromptDirectorMultiTextSelector` | 按选择执行文字分支 |
| `ZFPromptDirectorAnyFilter` | 显式过滤、透传或移除指定文字 |
| `ZFI` | 纯前端多路转接排，只整理接线，不调用模型或缓存数据 |

## 已废弃，不再添加

| 技术 ID | 去向 |
| --- | --- |
| `ZVH3InterviewForm` | 改用当前 `ZVH3InterviewFormV2` |
| `ZVH3FocusCompiler` | 旧结构化计划编译器已取消，需求整理和反推分开 |
| `ZVPictureSlotOutlet`、`ZVVideoSlotOutlet`、`ZVAudioSlotOutlet` | 旧固定槽位已取消；通用素材用稳定 ID 出口，H3 用 `reference_plan` 固定出口 |
| `ZFBlueprintParser` | 旧蓝图解析入口已取消 |
| `ZFSinglePromptTask` | 旧单任务包装入口已取消 |

这些七类节点不注册兼容别名。旧表右侧若还有 `system_prompt`、`stage1_task`、`stage2_prefix`、`stage3_prefix`，即使标题相近，也不是当前采访表。

## 安装与旧工作流

`custom_nodes` 里只保留一份正式插件。备份和 Git worktree 放在 `custom_nodes` 外；改目录名仍可能被 ComfyUI 扫描加载。多份 Python 注册和同名前端扩展可能互相覆盖，导致新节点没有面板、旧面板反复出现或端口不一致。

在插件目录运行以下只读检查，列出当前 `custom_nodes` 中的重复安装和废弃节点注册；不会导入模型或修改文件：

```text
python tools/audit_installation.py
```

清理重复安装后，先保存工作流，再重启 ComfyUI、刷新浏览器。旧节点保存在工作流 JSON 中，不会因为后台删除了注册就自动消失；先保留需求原文和素材，使用当前模板替换废弃节点并重新接线，不能把旧输出序号原样接到新表上。

程序测试用于证明接口、媒体范围与执行接线，不保证反推模型理解或云端生成质量。不要把旧版验收记录当作新版成片验证。
