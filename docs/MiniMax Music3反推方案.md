# MiniMax Music3 音乐反推方案

## 结论

不要把曲风说明和歌词直接串成一个字符串送入 Music3。官方编码节点把输入分成 `caption` 与 `lyrics`：前者控制曲风、情绪、人声、编曲与制作，后者控制可唱文字和段落结构。插件让一个具备音频理解能力的闭源 API 在同一次请求中理解可选参考音频和用户要求，再输出参考分析、Caption 与歌词三个块；拆分节点把后两者分别接回官方节点。

时长以音乐导演节点为单一控制源。预设或自定义秒数同时进入写作任务和 `MiniMax Music3 Text Encode.max_duration`，编码节点输出的实际 `seconds` 再连接 `Empty MiniMax Music3 Latent Audio.seconds`。不要分别手调三个不同的时长。

## 工作流

```text
用户歌曲要求 ─→ ZF Music3 音乐反推导演
                    ├─ writer_system_prompt ─→ ZF 多模态 API.role
                    ├─ writer_task ──────────→ ZF 多模态 API.prompt
                    └─ duration_seconds ─────→ Music3 Text Encode.max_duration
LoadAudio.AUDIO ─────────────────────────────→ ZF 多模态 API.audio（可选）
                                                   ↓
                                         ZF Music3 结果拆分
                                         ├─ caption ─→ Music3 Text Encode.caption
                                         ├─ lyrics ──→ Music3 Text Encode.lyrics
                                         └─ reference_analysis ─→ 检查显示
```

一次 API 调用先按选择分析曲风、词风或两者，再完成或整理歌词，并依据最终歌词的段落、情绪与用户要求反推英文 Structured Caption。没有参考音频时自动进入纯文本反推。结果使用稳定标记拆分；解析器仍兼容 JSON 和普通 Markdown 标题作为降级格式。

## 语言规则

- 自动模式固定以中文歌词为默认值。
- 只有用户明确写出“英文歌词”“用英文唱”“English lyrics”或同等要求时，自动模式才切换英文。
- “English rock”“英伦摇滚”等曲风词本身不等于要求英文歌词。
- 可以在节点上手动锁定“中文”或“English”，手动选择优先于自然语言判断。

## 曲风反推字段

Caption 使用 MiniMax Music3 推荐的三个部分：

1. `Global Metadata`：主风格、子风格、速度、情绪进程、使用场景与整体制作。
2. `Vocal Details`：主唱配置、音域、音色、唱法、和声与克制的人声效果。
3. `Arrangement`：按歌词段落说明乐器生命周期、律动、低频、转场、纹理与空间效果。

Caption 默认使用英文自然句，而不是逗号标签堆。精确 BPM、调性和音阶只在用户明确要求或音乐上确有必要时加入，避免“看起来专业但实际互相冲突”的过度指定。

## 歌词反推规则

- 支持用户只给一句题材，例如校园、武侠、戏剧唱腔，也支持人物、事件、视角、副歌钩子、禁用内容等详细要求。
- 校园、武侠、戏剧首先作为题材或文化语境，再选择可执行的主曲风与融合方式，不把题材名机械当作唯一 Genre。
- 只使用官方段落标签：`[Intro]`、`[Verse]`、`[Pre-Chorus]`、`[Chorus]`、`[Post-Chorus]`、`[Bridge]`、`[Instrumental]`、`[Solo]`、`[Outro]`，并让标签独占一行。
- 乐器、速度、强弱和制作控制进入 Arrangement，不写进歌词正文。
- 目标时长会改变段落数量和歌词密度；导演节点的 `duration_seconds` 应直接连接 Text Encode 的 `max_duration`。
- 有完整已有歌词时，默认保留原文，只规范结构并据此反推曲风；只有用户明确要求改写时才换词。

## 为什么不采用固定文本串联

固定前缀或标签可以作为“附加曲风参考”，但不直接拼入最终 Caption。反推模型会先消化这些约束，再建立一套连贯的主风格、唱腔和段落编曲。这样能避免用户写“校园风 + 武侠风 + 戏剧唱腔”时得到三个平行标签，而是得到一个有主次、有时间进程的融合方案。
