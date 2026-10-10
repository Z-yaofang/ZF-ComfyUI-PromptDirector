# 示例工作流 / Example workflows

两份完整接线示例分别展示视频素材准备和图片提示词创作。下载 JSON，在 ComfyUI 中打开；工作流不附带模型、素材文件或第三方插件。

| 工作流 | 主要路径 |
| --- | --- |
| [H3-素材台-无反推.json](H3-素材台-无反推.json) | 通用素材台 → H3 提示词直输入与素材对齐 → H3 T8 双采 → 时长裁回与视频输出。 |
| [Infinite Prompt Director Console - Krea2.json](Infinite%20Prompt%20Director%20Console%20-%20Krea2.json) | 世界观／主题与用户要求 → 用途与创意导演台 → 提示词写作和整理 → 图片生成。 |

## 使用前

1. 安装本插件及工作流提示缺少的第三方节点。插件可在本地和 RunningHub 使用，但工作流里也可能包含平台专用节点；仅安装本插件不会自动补齐所有依赖。
2. 重新上传或导入自己的图片、视频、音频。JSON 中保存的文件名、素材 ID 和来源引用不是素材文件，不能跨机器自动恢复。
3. 在模型加载节点重新选择当前环境已有的模型、VAE、文本编码器及 LoRA。Windows 保存的模型相对子目录分隔符可能与 Linux 不同。
4. 调整提示词、画布与时长，检查启用／绕过的分支，再运行。API 分支可能收费，启用前确认自己的账号配置和服务费用；不要把密钥写入工作流。

## H3 无反推示例

- 导入素材台中的参考素材，确认轨道与用途，在提示词节点点击“检测并对齐素材”；提示词中的素材编号要与本次对齐结果一致。
- 在上方填写可选触发词，下方填写提示词，直接送入 H3，不调用反推链。生成尺寸与参考素材尺寸不必相同；按工作流中的画布和时长设计设置。
- 示例保存了 4 张图片的来源引用，图片本体不随仓库发布。公开副本仅清除了上次成片的预览缓存（含视频外链和服务器路径），保留原有节点、连线和生成参数。
- 主要第三方节点包括 MiniMax H3 Audio T8、KJNodes、Easy Use、Impact Pack、Comfyroll、VideoHelperSuite，以及 RunningHub Deepcleaner；其它注意力、分辨率等辅助节点以导入后的缺失节点提示为准。

## Krea2 图片导演台示例

- 根据需要填写自己的世界观／主题和用户要求，选择用途与创意组合及任务数量，再由写作节点生成提示词。
- 使用参考图时，请在 `LoadImage` 节点重新选择图片；使用本地多模态写作时，需安装对应模型加载节点并选择模型。
- 除本插件外，示例还包含 KJNodes、Easy Use、Comfyroll、rgthree、ComfyUI Essentials、StringOps、JDCN 与 llama.cpp 模型加载相关节点。具体安装包应按节点类型核对，旧工作流记录的包名不一定完整。
- 保留了多条 RunningHub 图像 API 备选分支，发布时这些节点处于绕过状态。根据实际环境选择需要的出图分支，不要把全部分支同时开启。

## 验证范围

本次发布检查了两份 JSON 的解析、节点 ID、连线端点、插槽引用及 Set/Get 对应关系；没有重新执行模型生成。RunningHub 上插件正常使用的反馈与完整版本核对的区别见[云端验证状态](../CLOUD_TESTING.md)。第三方节点、模型和平台更新仍可能影响工作流运行。

## English quick setup

Download either JSON and open it in ComfyUI. The H3 example uses direct prompt input and aligned references without reverse analysis; the Krea2 example connects visual-purpose planning and prompt writing to image generation. Install missing custom nodes, re-import your references and select models available in your environment. Saved source handles do not transfer media between machines. RunningHub-only nodes and optional paid API branches need their own setup; the saved API nodes are bypassed. The H3 copy has its previous output preview cache removed. Graph structure was checked for this release, but model generation was not rerun.
