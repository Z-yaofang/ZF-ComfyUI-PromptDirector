# SAM3 彩色编号跟踪视频

把官方 SAM3 视频跟踪结果画到原片上：不同对象使用固定颜色的半透明遮罩，遮罩上显示对象编号，再保存为普通 MP4 视频。`ZVSAM3TrackVideo` 只负责已有跟踪结果的可视化，不会再次调用 SAM3 模型。

示例工作流：[sam3_tracking_video_save.json](../examples/sam3_tracking_video_save.json)。这是可导入的接线模板，需要自行上传视频、选好模型，并让目标环境更新到包含新节点的插件版本。示例不是已经发布或通过实跑验收的 RH 应用。

## 最短接线

```text
LoadVideo → GetVideoComponents.images → SAM3_VideoTrack → ZVSAM3TrackVideo → SaveVideo
                        └─ images ────────────────────────────↑
                        └─ fps ───────────────────────────────↑
CheckpointLoaderSimple.MODEL → SAM3_VideoTrack.model
CheckpointLoaderSimple.CLIP → CLIPTextEncode → SAM3_VideoTrack.conditioning
```

1. 在 `LoadVideo` 上传或选择自己的原视频。
2. 在 `CheckpointLoaderSimple` 选择本机或云端实际可用的官方 SAM3.1 模型。示例中的 `sam3.1_multiplex_fp16.safetensors` 只是模型名称，不包含模型文件，也不自动安装模型。
3. `CLIPTextEncode` 默认填写 `person`，用于跟踪原片里的人物。描述的是原片要识别的目标类别，不是换人要求。
4. 把同一批原片图像同时接到跟踪节点和 `ZVSAM3TrackVideo.images`；把对应原片帧率接到 `fps`。不要将裁切、抽帧或重排后的不同图像批次混接到这两处。
5. 将新节点的 `VIDEO` 接到核心 `SaveVideo`，保存格式选 MP4、编码选 Auto，保存前缀例如 `SAM3Tracks/tracking`。

**本轮输出默声视频。** 示例没有把 `GetVideoComponents.audio` 接入新节点，不能宣称保留原声。需要带原声时，必须另行接入并验证音轨合成。

## 新节点输入与输出

| 输入 | 建议值 | 用途 |
| --- | --- | --- |
| `track_data` | 官方 `SAM3_VideoTrack` 输出 | 已计算的跟踪遮罩与对象槽位 |
| `images` | 同一批原片图像 | 保留原片背景、人物和画面内容 |
| `fps` | 连接对应视频帧率 | 决定视频播放速度，不固定为 24fps |
| `opacity` | `0.5` | 彩色遮罩透明度；越高颜色越实 |
| `label_scale` | `6` | 编号字号；可按画面尺寸调整 |
| `show_scores` | `false` | 是否额外显示检测置信度；默认只看编号 |

| 输出 | 用途 |
| --- | --- |
| `VIDEO` | 已编码的彩色编号视频，接核心 `SaveVideo` 正式保存 |
| `report` | 当前输入和导出的技术报告，用于维护与排错 |

编号沿用官方跟踪数据中从 0 开始的对象槽位，与 `SAM3_TrackToMask.object_indices` 的选择含义保持一致；不会逐帧按左右位置重新编号。编号稳定性仍取决于上游跟踪结果：跨镜头重新识别、跟错目标或丢失目标，不会由这个可视化节点自动修复。

节点逐帧渲染、编码后输出原生 `VIDEO`，避免再拼出一整批带编号的浮点 `IMAGE` 张量。原片图像批次和 SAM3 跟踪本身仍需要相应的内存、显存与运行时间。输入帧率是一个固定值；可变帧率素材按该值重建视频，不保留原文件逐帧时间戳。

## RH 应用从哪里拿到视频

应用的最终输出应是 **`SaveVideo` 保存的文件**。新节点的中间编码文件只供下游处理；仅保留预览或仅返回中间 `VIDEO`，不能据此保证应用外部能下载。

发布前需要：

1. 让 RH 对应环境更新本插件，并核对 `ZVSAM3TrackVideo` 已出现在实际节点定义里。GitHub 更新和本机更新不会自动证明 RH 已完成同步。
2. 在 RH 工作流里接好新节点和核心 `SaveVideo`，选 `SaveVideo` 作为应用结果节点，避免选成黑白遮罩、图像预览或临时预览分支。
3. 运行短视频并从应用页面下载实际结果，核对画面里确有原片、半透明多色遮罩和清晰编号。
4. 从应用外部调用接口，检查任务结果列表含对应保存节点的 MP4 下载地址，并实际下载、解码。任务状态为成功或画布里能播放预览，都不能代替这一步。

RunningHub 的任务查询接口通过 `results[].url` 返回下载地址，并说明结果链接有效期为 24 小时；调用方应在有效期内下载或转存。参考：[官方任务查询说明](https://www.runninghub.cn/runninghub-api-doc-cn/api-425767306)。需要长期保留的成片应下载到自己的存储，不能把临时结果链接当长期网盘链接。

前次对官方原版 `SAM3_TrackPreview` 的测试只证明该临时预览未被 RH 返回为下载结果；它不属于本新增节点的成功验收。新节点和核心保存节点的组合仍须以目标 RH 版本的真实结果为准。

## 原生 ComfyUI API 示例

下面是同一条接线的 API 结构。`your_uploaded_video.mp4` 必须替换为目标环境实际上传返回的文件名，模型名也必须是目标环境可用的名称。此示例不含账号、密钥或素材。

```json
{
  "1": {
    "class_type": "LoadVideo",
    "inputs": {"file": "your_uploaded_video.mp4"}
  },
  "2": {
    "class_type": "GetVideoComponents",
    "inputs": {"video": ["1", 0]}
  },
  "3": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}
  },
  "4": {
    "class_type": "CLIPTextEncode",
    "inputs": {"clip": ["3", 1], "text": "person"}
  },
  "5": {
    "class_type": "SAM3_VideoTrack",
    "inputs": {
      "images": ["2", 0],
      "model": ["3", 0],
      "conditioning": ["4", 0],
      "detection_threshold": 0.5,
      "max_objects": 0,
      "detect_interval": 1
    }
  },
  "6": {
    "class_type": "ZVSAM3TrackVideo",
    "inputs": {
      "track_data": ["5", 0],
      "images": ["2", 0],
      "fps": ["2", 2],
      "opacity": 0.5,
      "label_scale": 6,
      "show_scores": false
    }
  },
  "7": {
    "class_type": "SaveVideo",
    "inputs": {
      "video": ["6", 0],
      "filename_prefix": "SAM3Tracks/tracking",
      "format": "mp4",
      "format.codec": "auto",
      "codec": "auto"
    }
  }
}
```

核心 `SaveVideo` 在不同 ComfyUI 版本的格式控件有所变化。上例按本次前端实际导出的 API 使用 `format`、`format.codec`、`codec` 三个扁平字段，均保留 Auto 编码选择。其中 `format.codec` 是包含点号的完整字段名，不是嵌套对象。

ComfyUI 会在执行前把动态控件字段组装为内部嵌套参数；这些内部参数不是直接提交的 API 结构。不要将代码中执行函数收到的嵌套对象照抄到 API `inputs`。其他版本应使用目标环境实际导出的 API JSON，并核对其节点定义；此说明不是目标 RH 版本已经通过验证的声明。

## 应用输入草稿

以下是用于准备应用界面的描述，未分配发布编号，也未决定公开或私密范围。

| 显示名称 | 默认建议 | 使用说明 |
| --- | --- | --- |
| 原视频 | 必填 | 上传要查看跟踪效果的视频 |
| 跟踪对象 | `person` | 填原片中目标的英文类别，如 `person`；不是换人提示词 |
| 遮罩透明度 | `0.5` | 调整遮罩颜色覆盖的强度 |
| 编号字号 | `6` | 编号太小时调高，遮挡画面太多时调低 |
| 显示置信度 | 关闭 | 开启后在编号之外显示检测分数 |
| 文件名前缀 | `SAM3Tracks/tracking` | 用于识别本次导出文件，不改变画面内容 |

## 发布前验收清单

- 新插件节点可注册，未安装 SAM 模型时也能正常导入插件；实际跟踪所需的官方节点和模型另行核对。
- 原片、跟踪数据的帧数与空间尺寸兼容；输入异常应报出原因，不能用黑帧补齐后当作成功。
- 同一槽位在移动、短暂消失和重新出现时沿用同色同号；首次出现于后续帧的对象不挤占旧编号。
- 输出可完整解码，帧数和帧率吻合；检查零对象、更多对象、边缘编号、非整数帧率和编码画幅处理。
- 本地保存落到 `output`，保存结果可下载，连续运行不会将旧任务当作新结果。
- RH 实际节点版本、保存节点、应用结果和 API 下载四者分别验收；未经真实下载验证时保持“云端待验收”。
- 确认本轮视频默声；后续若加入音轨，必须补测有声、无声、时长与同步。
- 发布范围、应用编号和封面按实际发布约定处理；本示例不代表已获额外付费试跑或对外发布授权。
