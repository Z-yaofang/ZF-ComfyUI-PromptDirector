# H3 焦点访谈长视频（测试版）

长视频节点与示例处于 test/beta 阶段。当前发布已通过本地 Python、Node 和真实浏览器交互测试；尚未在 RunningHub 或其他云端 GPU 环境完成验证。外部 T8 节点是否实际消费 Guide，需要以目标环境的逐段输出和运行清单为准。

## 示例与依赖

- 普通分段：`docs/examples/H3焦点访谈_长视频分段_V1.json`
- C1 MASK：`docs/examples/H3焦点访谈_长视频蒙版_C1.json`

两个示例都基于当前 MiniMax H3 Audio T8 的 LOW/HIGH 双时钟工作流，需要同时存在两路 `MiniMaxH3AudioConditioningT8`、两路 `MiniMaxH3AddGuide`、双时钟采样与两阶段 latent 节点。示例还继承基础 H3 焦点访谈工作流使用的 rgthree、Comfyroll、Impact、pysssss、llama.cpp 和注意力相关节点；导入后如出现红色缺失节点，请先补齐对应自定义节点。

SAM3、SeC 和手绘工具都是可选的外部 MASK 提供方，本插件不安装模型，也不捆绑这些节点。示例中的 `ImageToMask` 只演示标准 ComfyUI `MASK` 接口。

## 更新与启用

在插件目录更新主分支，然后重启 ComfyUI，并在浏览器中强制刷新前端资源：

```powershell
git pull --ff-only origin main
```

如果平台通过节点管理器更新，请完成更新后同样重启 ComfyUI，并执行一次浏览器强制刷新。旧版本仍显示在节点面板时，先确认插件目录已更新，再清理平台的前端缓存。

## 普通分段操作

1. 在 `ZV 通用素材取证台` 导入素材，并把本次任务需要的图片、视频和音频拖入三条轨道。素材池中未入轨的项目不会参加任务。
2. 在 `ZV 长视频分段台` 点击“获取素材台三轨”。`source_auto` 按素材范围、单段帧数和重叠自动计算段数；`generation_count` 才使用手工填写的生成段数。
3. 检查每段起止帧、重叠和接缝类型。黄色播放头可拖动，也可用方向键、Home、End 精确移动；“黄线处分割”作用于当前选中段。
4. 在 `ZV 分段采访表` 填写全局要求和逐段动作、镜头、声音及素材用途，然后点击“检测并对齐全部分段”。
5. 报告显示 ready 后再运行。任何素材、轨道、分段、参与开关、用途或文字变化都会要求重新检测并对齐。
6. `StartLoop` 每次只执行一段，Recorder 立即落盘，`ZV 长视频执行终点` 按全局帧钟去除 Guide 重叠和模型补帧后输出完整 native `VIDEO`。

H3 执行固定为 24 fps。任务帧数可以直接填写，模型长度会向上补到 `5+17k`，Recorder 再裁回任务帧数。H3 常用单段为 8–15 秒；单次模型窗口仍受当前 T8 限制，长视频依靠有限循环延长。

Guide 重叠独立按 1 帧或 `5+17k` 对齐。默认请求 48 帧会向下对齐为 39 帧。源自动分段会尝试修复不足 48 个真实参考帧的短尾；无法安全调整时会停止并提示修改范围或单段长度。

## Guide、普通参考与 LLM 的边界

Guide 不占 `ZVH3ReferenceOutlet` 的普通参考图、参考视频、独立参考音频或 drive/reuse 音频端口。它由上一段实际生成结果中去除补帧后的尾帧和同步音频产生，通过 `ZV 当前分段执行入口` 分别送入 LOW/HIGH 的 `MiniMaxH3AddGuide`。

只有接缝类型为 `guide` 时才加载上一段实际尾部，并令 `has_guide=true`。`hard_cut` 会令 LOW/HIGH 懒切换直接使用普通 conditioning，不会把上一段尾帧塞进 `last_frame`、`Video N` 或任何普通参考端口。

分段 LLM 只收到文字连续性说明，例如当前段开头若干秒延续上一段；它看不到上一段实际帧或音频。视觉和声音 Guide 由执行节点与外部 `MiniMaxH3AddGuide` 完成。

## 音频

Recorder 优先使用 `ZVH3ReferenceOutlet.final_audio` 中明确选择的 drive/reuse 内容；没有该内容时使用解码器的 `generated_audio`。选中后统一重采样为 44.1 kHz 双声道并按全局帧钟裁切。mono 会复制为 stereo，超过 2 声道会被拒绝，缺失音频会补同帧钟静音。复用原声表示内容优先，不表示输出编码比特不变。

## C1 MASK 操作与限制

C1 示例把冻结源帧、标准 `MASK` 和源音频送入 `ZVH3MaskedSegmentLatent`。黑色保留源画面，白色采用生成画面，灰色线性混合。LOW/HIGH 使用同一 1×画布；HIGH 前恢复黑区源 latent，解码后再次回贴黑区源像素。

固定 MASK 只能提供 1 帧并广播；逐帧 MASK 必须覆盖冻结源时钟，源尾补帧只重复最后一张真实 MASK。当前一次 End 运行要求所有分段共享同一 raw MASK、同一来源指纹和采样指纹，并要求源、生成和 HIGH 使用相同 1× H3 画布。每段更换 MASK、动态 ROI、局部放大、软边、多对象、遮挡后重现、切镜和其他画布/模型组合都未纳入当前签收范围。

采访表的 ready 只表示分段、提示词和素材用途已对齐。C1 仍需选择冻结工程中的视频 `clip_id` 并连接合法 MASK；缺少片段、覆盖不足、零帧、帧数/尺寸/数值非法都会在生成前失败并给出错误码。
