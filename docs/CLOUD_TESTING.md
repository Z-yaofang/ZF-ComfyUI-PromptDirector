# 云端测试准备

本仓库包含插件后端、Web 界面、素材/H3 schema、内置目录和回归测试。不包含个人素材、用户预设数据库、registry/cache、模型或本机验收日志。Git 同步不等于云端已经测通。

Windows 本地与 Linux/RunningHub 是共同维护目标。后续插件更新均须检查云端兼容性，不能只凭本地界面能打开就发布；平台更新后的真实验收与本地模拟结果分别记录。

## 当前验证状态

2026-10-11：项目维护者反馈，插件目前已可在 RunningHub 云端正常使用。这是实际使用反馈，不是由本地测试推断的结论；本次未取得云端部署提交号，不能据此确认云端与 Git 的文件版本完全一致，也不代表 H3 分段、Animate 或所有模型组合均已逐项验收。

同日、此次示例整理前核对，本地插件运行代码与 GitHub `main` 的 `3213f2f` 一致；未提交差异仅为本地测试与审计工具。此次发布只增加两份[示例工作流](examples/README.md)及说明，不修改插件运行代码。确认具体云端版本时，还需核对平台的插件提交号和已发布前端资源。

## 安装

在目标 ComfyUI 的 `custom_nodes` 目录执行：

```sh
git clone https://github.com/Z-yaofang/ZF-ComfyUI-PromptDirector.git
```

已有副本先确认无本地改动，再 `git pull --ff-only`。正常重启 ComfyUI，并刷新浏览器前端，确保新后端端口和 Web 模块同时生效。

RunningHub 会将前端模块发布为带哈希的 `.js` 并改写导入地址。相对模块导入不要附加 `?v=` 或 `#`：已确认带版本参数的素材出口导入在云端变成不存在的地址（404），导致新旧素材台都只显示原始 JSON。修复仓库后仍需平台重新发布插件前端资源；仅刷新页面不会修复服务器上的错误导入。验收时检查 Console 的 `Error loading extension`，确认新建空素材台和已有素材台都显示面板；不要通过重建素材或恢复旧节点绕过加载失败。

插件运行代码兼容 Python 3.10 及以上；Animate 文件校验使用有界分块 SHA-256，不依赖 Python 3.11 的 `hashlib.file_digest`。ComfyUI 需要提供 UserManager、`comfy_api.latest` 原生 VIDEO（包括 `InputImpl.VideoFromFile`）以及工作流使用的原生循环接口；仅升级本插件不能补齐旧核心缺失的接口。不指定未经验证的最低 ComfyUI 发布号。

素材/采访功能需要 Pillow、PyAV、numpy、torch、aiohttp 等核心环境依赖。音频重采样优先使用 ComfyUI 的 `comfy.audio.resample`；旧核心缺少该接口时，仅在实际重采样时才加载 torchaudio。旧环境须安装与其 PyTorch/CUDA 匹配的 torchaudio，或更新核心；不应盲目升级 torch/CUDA。缺少 torchaudio 不再阻止插件节点注册，同采样率音频不需要该后端。

媒体预览需要 FFmpeg（或 imageio_ffmpeg 提供的可执行文件）及 libx264/AAC 编码器。Animate 的分段缓存和成片编码使用 **PyAV 自身链接的 FFmpeg 库**：分段缓存需要 `libx264rgb`，音轨需要 `aac`，H.264/H.265 成片档分别需要 `libx264`/`libx265`。系统 `ffmpeg -encoders` 不能证明 PyAV 的编码器可用；在云端实际 Python 环境另行检查：

```sh
python -c "import av; print('PyAV', av.__version__); print({name: av.codec.Codec(name, 'w').name for name in ('libx264rgb', 'aac', 'libx264', 'libx265')})"
```

该命令核验全部编码档；若只缺 libx265，不影响默认 H.264 档和节点加载，但不能使用 H.265 档。BT.709 高画质档还需要 PyAV 支持显式色彩转换。下游 SaveVideo 保持 `auto` 才会直接封装已编码成片；显式重编码无法恢复分段缓存已量化的 8 位 RGB 精度。云端更新后仍需用短片验证编码、色彩标记及播放兼容性。

用户素材/预设目录应可写、可持久，使用真实挂载目录；素材注册与截图提交还需要文件系统支持硬链接，不能仅凭“可写”判断对象存储/FUSE 挂载可用。反向代理应保留正确的公开 Host，避免同源写入校验将请求拒绝。不要通过关闭路径边界或同源校验来适配云端。

完整 H3 生成还需要目标工作流实际使用的 T8、VAE、模型、writer 后端及其它第三方节点。这些不是 Git clone 本插件会自动安装的内容，具体版本与 CUDA/ABI 兼容性需在云端核对。

## 每次发布前检查

- 检查缺少可选音频后端时仍可注册节点；核对 Python 3.10 语法/API、Linux 大小写和路径边界，不加入本机盘符或可执行文件路径。
- 前端检查全部入口的哈希模块发布、路径前缀、样式重映射、缩略图与新建/恢复节点。目录请求通过 Comfy API bridge，不能写死插件安装目录或绕过接口前缀。
- 运行受影响的 CPU/浏览器回归。检查跳过和失败项；不要将测试环境缺依赖、模拟通过或代码静态检查写成真实云端生成通过。
- 平台更新须同时重新发布后端与前端资源，重启后刷新浏览器；再按下列顺序进行真实云端验收。公共提交只包含本次指定的发布文件，不夹带个人素材或本地测试产物。

## 云端验收顺序

1. 检查启动日志和节点注册，先用中性图片、短视频及音频重新导入素材池。旧机器的 handle/稳定 ID 不能代替媒体迁移；用户采访预设使用导出/导入 JSON。
2. 分别发送原图片、原视频、原音频，确认真实来源连线、完整时长/尺寸，并验证无效时间轴或未对齐采访表不会阻断所选原素材输出。
3. 检查入轨、分割、就近删除、截图回素材池，以及撤销/重做和保存/重载。
4. 检查采访编号、检测并对齐、首尾帧及音频实际路由。语义标签本身不改变物理接口；音频参考与音频复用须核对真实下游行为，不能只看勾选名称。
5. 最后接完整生成链，记录提交号、ComfyUI/第三方节点版本、模型、提示词、采样参数、时长与显存，验证首尾衔接、动作/身份和声音。帧数正确不代表模型必然遵循姿态要求。

可先运行 CPU 回归（部分测试还需要目标 ComfyUI 核心源码）：

```sh
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests --tb=short -rs
node --test tests/frontend_cloud_compat.test.mjs tests/media_evidence_core.test.mjs tests/media_evidence_original_outlets.test.mjs tests/media_evidence_presets.test.mjs
```

发布前还应运行真实浏览器模块加载回归（使用已安装的 Playwright 和 Chromium 路径）：

```sh
node tests/frontend_cloud_load_smoke.mjs <playwright-package> <chromium-executable>
```

这些测试是本地发布模拟，不访问云端、不运行模型，不能代替平台更新后的实际验收。发布前还应覆盖带接口前缀、资源目录重映射的场景；检查目录、样式和缩略图的真实响应，不能仅以 JavaScript 成功注册为通过标准。
