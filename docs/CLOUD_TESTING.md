# 云端测试准备

本仓库包含插件后端、Web 界面、素材/H3 schema、内置目录和回归测试。不包含个人素材、用户预设数据库、registry/cache、模型或本机验收日志。Git 同步不等于云端已经测通。

## 安装

在目标 ComfyUI 的 `custom_nodes` 目录执行：

```sh
git clone https://github.com/Z-yaofang/ZF-ComfyUI-PromptDirector.git
```

已有副本先确认无本地改动，再 `git pull --ff-only`。正常重启 ComfyUI，并刷新浏览器前端，确保新后端端口和 `h3-v2-07` Web 模块同时生效。

素材/采访功能需要近期支持 UserManager 和原生 VIDEO 的 ComfyUI，以及 Pillow、PyAV、numpy、torch、aiohttp；媒体代理还需要 FFmpeg（或 imageio_ffmpeg 提供的可执行文件）及 libx264/AAC 编码器。用户目录应可写、可持久，使用真实挂载目录；存储边界拒绝逃逸路径、符号链接及相关不安全链接。

完整 H3 生成还需要目标工作流实际使用的 T8、VAE、模型、writer 后端及其它第三方节点。这些不是 Git clone 本插件会自动安装的内容，具体版本与 CUDA/ABI 兼容性需在云端核对。

## 建议测试顺序

1. 检查启动日志和节点注册，先用中性图片、短视频及音频重新导入素材池。旧机器的 handle/稳定 ID 不能代替媒体迁移；用户采访预设使用导出/导入 JSON。
2. 分别发送原图片、原视频、原音频，确认真实来源连线、完整时长/尺寸，并验证无效时间轴或未对齐采访表不会阻断所选原素材输出。
3. 检查入轨、分割、就近删除、截图回素材池，以及撤销/重做和保存/重载。
4. 检查采访编号、检测并对齐、首尾帧及音频实际路由。语义标签本身不改变物理接口；音频参考与音频复用须核对真实下游行为，不能只看勾选名称。
5. 最后接完整生成链，记录提交号、ComfyUI/第三方节点版本、模型、提示词、采样参数、时长与显存，验证首尾衔接、动作/身份和声音。帧数正确不代表模型必然遵循姿态要求。

可先运行 CPU 回归（部分测试还需要目标 ComfyUI 核心源码）：

```sh
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests --tb=short -rs
node --test tests/media_evidence_core.test.mjs tests/media_evidence_original_outlets.test.mjs tests/media_evidence_presets.test.mjs tests/media_evidence_slots.test.mjs
```
