# H3-V2-07 原素材来源绑定

素材台原有输出 0 `ZV_MEDIA_PROJECT/media_project` 和 1 `STRING/project_json` 保持顺序，新增输出 2 `ZV_ORIGINAL_SOURCES/原素材来源`。原素材来源只承载素材池的稳定 `asset_id/kind/source_handle` 引用。时间轴处理出口继续使用工程口。

发送原素材会把素材台输出 2 真实连接至对应 Original 节点的 `original_sources` 输入口，写入所选 `asset_id`，并把旧 `source_handle` 留空。三类 Original 的四输出顺序保持：标准媒体、原文件路径、清单、报告。原生 VIDEO 可接 GetVideoComponents；原文件路径可接 VHS_LoadVideoPath。

新绑定的 `asset_id` 非空时，断线、来源缺项、重复 ID、种类不符、登记与 ID 不一致、原文件丢失或 size/mtime 改变都会拒绝执行，即使 `source_handle` 有值也不会回退。旧节点没有来源数据且 `asset_id` 为空时，继续按旧 `source_handle` 独立运行。发送按钮只复用当前素材台来源线、相同稳定 ID 和完整端口契约的节点；旧独立节点不会被借用。

来源目录单独解析有界 JSON（2 MiB、32 层、最多 128 个池条目），只校验所选资产引用，不逐项读取未选文件。整个运输 JSON 或池本身的歧义仍会阻断来源口。工程内部可控解析、shape、preset、canvas 参数异常改为输出 0/1 的真实 ExecutionBlocker，来源口仍可用。width/height 是非 lazy 上游依赖；上游异常发生在素材台函数执行前，以及同一 prompt 中其它未捕获异常，不在该隔离保证之内。

加载新后端定义后，旧保存的两输出素材台会在正常配置/恢复时尾部补第三口，保留旧 0/1 和连线。旧后端定义不会伪造第三口。此版有后端 schema 变化，用户须正常重启 ComfyUI 加载插件后刷新页面；缺少新契约时按钮会显示对应中文提示。

素材台对当前直接出口模块使用固定 `?v=h3-v2-07` 依赖键；相关接口升级须同步修改调用方与浏览器夹具。固定槽位模块已经移除。版本键没有时间戳或随机数。

新增来源节点和边作为一次原生事务提交，创建、undo、redo 的 ChangeTracker 计数均须回到 0。仅在同步 connect 调用期间暂缓其内部 beforeChange/afterChange 通知，随后恢复原方法，由外层完整创建统一提交。接线或提交失败只清理本次所属新节点/新边；无法清理时明确报告回滚不完整。

本地 CPU、接线事务和前端缓存升级验收已通过独立复核。包含个人路径、素材或预设的本机验收记录不随仓库公开；Linux/cloud 和 GPU 成片质量仍需单独验证。
