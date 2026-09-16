# H3 长视频实现契约（测试版）

## 数据流

`ZVLongVideoSegmentDesk` 从素材台取得三轨快照，生成以整数帧为主时钟的 `ZV_SEGMENT_PLAN`。`ZVSegmentInterview` 把全局与逐段采访编译为冻结的执行计划，并用实际参与素材、提示词、分段与来源范围计算指纹。

`ZVLongVideoExecutionSetup` 冻结计划并给出循环次数。每轮 `ZVLongVideoExecutionEntry` 只读取当前段；`ZVLongVideoSegmentRecorder` 立即编码当前贡献，保存轻量运行清单，并在需要时把实际的去补帧尾部 IMAGE/AUDIO 写为下一段 Guide。`ZVLongVideoExecutionEnd` 验证每段全局范围、音频时钟和清单后完成精确拼接。

有限循环固定使用 `cache_iterations=false` 和 `accumulate=false`，避免把旧段执行缓存或全分辨率张量累积到循环状态。

## H3 长度与双时钟依赖

H3 路径固定 24 fps。任务帧数保持用户需要的逻辑长度，模型长度向上对齐到 `5+17k`；模型输出会裁回任务帧数，之后才按接缝计算最终贡献。Guide 长度是独立约束，只接受 1 或 `5+17k`。

示例依赖当前 MiniMax H3 Audio T8 的 LOW/HIGH 双时钟结构。LOW 和 HIGH 各有一条 `MiniMaxH3AudioConditioningT8 → MiniMaxH3AddGuide → lazy ComfySwitchNode` 路径。`has_guide=false` 时不会执行 AddGuide 分支。

Guide 是独立的生成连续性输入，不属于普通参考出口：

- `guide` 接缝从上一段实际生成结果读取去补帧尾部和同步音频，同时送入 LOW/HIGH AddGuide。
- `hard_cut` 接缝不读取上一段尾部，且不会写入 `last_frame`、`Video N` 或普通参考音频端口。
- LLM 只获得文字连续性要求，不获得上一段像素或音频张量。

工作流记录 `guide_application.external_application_verified=false`，因为插件能够证明计划、实际尾部文件、加载与接线，但不能替外部 T8 节点证明其 GPU 内部行为。目标环境必须通过实际输出复验。

## 普通参考与音频

每一段仍由 `ZVH3ReferenceOutlet` 提供普通首尾帧、参考图片、参考视频、参考视频原声、独立参考音频以及 drive/reuse 音频。这些容量和 Guide 互不占用。

Recorder 优先采用出口明确选择的 drive/reuse `final_audio`，否则使用解码器 `generated_audio`。最终合同是 44.1 kHz、双声道，按全局帧边界换算样本范围；缺音频补静音，mono 复制，超过 2 声道拒绝。

## MASK 路径

MASK 路径使用标准 ComfyUI `MASK` 边界。`ZVSegmentVideoMaskSource` 解码冻结视频源，`ZVMaskedSegmentBundle` 把 raw MASK 绑定到源时钟，`ZVSegmentMaskSlice` 为循环轮次取片。C1 适配器在 LOW 建立 H3 nested AV latent，在 HIGH 调和后恢复黑区源 latent，解码后再执行像素域回贴。

当前 C1 约束：

- 整次运行共享同一 raw MASK、来源指纹和采样指纹。
- LOW/HIGH/源图必须保持相同 1× H3 画布，宽高为 32 的倍数。
- 固定模式只接受 1 帧；逐帧模式必须覆盖真实源帧。
- 尾部模型补帧重复最后一张真实源帧/MASK，并为音频补零。
- raw MASK、像素域 model MASK 和 HIGH 的 5D `video_noise_mask` 分别记录摘要。

SAM3、SeC、手绘及其他跟踪器只作为外部 MASK 提供方；插件与示例不捆绑这些节点或模型。当前发布不声明软边、多对象、遮挡、切镜、动态 ROI、局部放大或每段独立 MASK 已通过验证。

## 路由与前端

后端注册：

- `POST /zf-prompt-director/long-video/plan`
- `POST /zf-prompt-director/long-video/interview`

`web/long_video.js` 为分段台和采访表提供交互。黄色播放头使用透明命中区与 1 px 可见线，支持 pointer/touch 拖动及键盘 Left/Right/Home/End；拖动期间延后时间线 DOM 重绘，避免丢失 pointer capture。

## 发布验证范围

此功能仍为 test/beta。当前发布执行 Python 专项测试、Node 核心测试、真实浏览器 UI smoke、schema/工作流确定性校验和静态差异检查；未执行生产服务、GPU 生成或 RunningHub 验收。
