# H3 分段长视频与蒙版

示例：[普通分段](examples/H3焦点访谈_长视频分段.json)、[长视频蒙版](examples/H3焦点访谈_长视频蒙版.json)。它们使用当前采访边界和三个独立反推节点，不再依赖旧四路阶段提示词。

## 操作

1. 在素材台导入素材，将本次使用的素材放到对应轨道。
2. 在分段台点击“获取素材台三轨”。`source_auto` 按素材时长计算段数，`generation_count` 使用所填段数；手动模式可调整边界。
3. 检查每段范围和重叠。默认请求 360 帧/段、48 帧重叠，H3 Guide 对齐后实际重叠为39 帧。
4. 填写分段采访表的全局及逐段要求，点击“检测并对齐全部分段”。改素材、范围、用途或文字后重新对齐。
5. 运行时每次循环取一段，输出中文原稿与素材事实；独立三阶段反推生成该段 H3 提示词。前段 Guide 按执行计划注入，不占用户手工参考编号。
6. Recorder 落盘每段贡献帧，ExecutionEnd 按全局帧钟裁掉重叠和模型补帧，拼接 native VIDEO。

Entry 的14个输出依次为 `segment_context`、`reference_plan`、`user_prompt`、`material_context_json`、`duration_seconds`、`frame_count`、`model_length`、`model_adapter`、`has_guide`、`guide_frames`、`guide_audio`、`guide_frame_idx`、`segment_id`、`report`。三个反推节点均从 Entry 获取原稿和事实清单；系统词由各自节点控制。

H3 执行固定24 fps，Guide 重叠是1 或5+17k 帧。源自动分段会处理短末尾，不能安全回摆的短参考须调整参数。`cache_iterations=false`、`accumulate=false` 避免跨段缓存全分辨率张量。整条长视频不受单次15秒生成窗口约束。

## 音频和蒙版

普通流的 `final_audio` 来自素材出口的 drive/reuse 路由；独立参考音频不会自动复用。没有复用音频时采用解码器 `generated_audio`。选中音频统一重采样到44.1 kHz 双声道，再按全局帧钟裁切；缺音频补同钟静音，超过2声道明确拒绝。

蒙版流需在遮罩视频源选择冻结工程里的 `clip_id` 并连接标准 MASK。采访表的 ready 只表示分段和要求对齐，不证明外部蒙版可执行。空来源、范围覆盖不足、MASK 帧数/尺寸/形状错误都会在生成前报错。

当前蒙版路径要求 LOW/HIGH 同一1×画布。黑色保留源画面，白色采用生成画面，灰色线性混合；固定 MASK 广播，逐帧 MASK 按冻结源时钟取片，补尾只重复最后一个真实 MASK。HIGH 前恢复源 latent，解码后回贴黑区源像素；运行清单记录源、采样、MASK 和每段执行证据。整次运行须共享同一 raw MASK、来源和采样指纹，不支持每段独立换遮罩。

普通示例的下方 MASK 支路只是接口示例，不进入生成；蒙版示例才启用 latent/像素合成。`ImageToMask` 不能代替 SAM3、SeC 或手绘遮罩。

## 验证边界

历史隔离 GPU 检查覆盖256×416同画布、普通双段200帧/39帧Guide，以及全黑、全白、半幅蒙版。固定半幅还完成379帧四段循环；源在200帧处人工重复，因此不代表自然长源连续性。SAM3.1 + SeC 曾完成200帧玩具火车跟踪与两段编辑，颜色修改仅部分成功。

以上是机械路径和有限样本证据，不保证其他模型/画布/云端环境或语义效果。当前采访及反推链改造还需真实模型与云端复测，不沿用历史结果宣称新链已经端到端验收。

从当前普通工作流创建新示例：

```powershell
python tools/build_long_video_workflow.py current.json long-video.json
python tools/build_long_video_workflow.py current.json masked-video.json --mask-mode
```

工具只写新文件，清空示例素材，不更改源文件。蒙版模式要求源工作流的放大倍率已设为1。
