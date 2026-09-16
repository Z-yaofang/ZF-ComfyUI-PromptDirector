# H3 长视频维护交接（测试版）

## 发布范围

本版本新增长视频分段计划、逐段采访、有限循环执行、实际尾部 Guide、精确音视频拼接，以及可选 C1 MASK 路径。普通和 MASK 两个示例均由 `tools/build_long_video_workflow.py` 从 `tests/fixtures/h3_focus_interview_topology.json` 确定性生成。

发布文件不包含测试媒体、模型、运行目录、缓存、截图、绝对路径证据或用户工作流。示例素材台已清空 `assets`、三轨、出口和来源句柄。

## 必须保持的契约

- H3 固定 24 fps；任务长度与模型 `5+17k` 补长分开保存，输出裁回任务帧数。
- Guide 长度只接受 1 或 `5+17k`，LOW/HIGH 两路都经当前 T8 的 `MiniMaxH3AddGuide` 与 lazy switch。
- Guide 是独立输入，不占普通 reference port。只有 `guide` 接缝加载上一段实际去补帧尾部；`hard_cut` 不加载。
- LLM 只接收文字连续性说明，实际帧/音频由 Entry 和 AddGuide 路径传递。
- Recorder 的运行清单区分“Guide 已计划/已加载”和外部 T8 GPU 应用；后者在插件侧保持未验证。
- C1 一次运行共享同一 raw MASK、来源指纹和采样指纹，LOW/HIGH 同画布 1×；SAM3/SeC 是未捆绑的外部依赖。
- 长视频功能保持 test/beta；RunningHub 未验证。

## 维护与复核

更新后重启 ComfyUI 并强制刷新浏览器。维护者至少运行：

```powershell
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests/test_long_video_plan.py tests/test_long_video_interview.py tests/test_long_video_execution.py tests/test_long_video_masks.py tests/test_long_video_workflow.py
node --check web/long_video.js
node --check web/long_video_core.mjs
node --check tests/long_video_ui_smoke.mjs
git diff --check
```

真实浏览器 smoke 还需 Playwright、Chromium 与可用的 Python 解释器；参数见 `tests/long_video_ui_smoke.mjs`。发布检查应确认两个示例与 builder 输出完全一致、节点映射和两个长视频路由可以在复制目录注册、仓库中没有 `__pycache__`/`.pyc`/媒体运行产物。

修改 T8 节点名称、端口或 LOW/HIGH 连接前，应先更新 builder 的具名端口校验和确定性示例测试。不要把 Guide 改接到 `last_frame`、`Video N` 或普通参考音频端口，也不要把尚未验证的外部 GPU 行为标记为已验证。
