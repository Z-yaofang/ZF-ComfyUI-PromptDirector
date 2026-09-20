# Z 前缀命名软分类

前缀按节点的主要用途提供默认分类，不是强制类型系统。用途模糊或跨领域的节点按主要用途判断，不为了前缀整齐批量重命名旧节点。

| 前缀 | 默认用途 |
| --- | --- |
| ZI | 图片创作、图片编辑 |
| ZV | 视频生成、视听素材、视频编排，以及服务于视频的音频 |
| ZT | 文本创作、提示词加工 |
| ZF | 过滤、路由、转换、设置等通用辅助 |
| ZH | 自用保存类，尤其无元数据、纯净保存节点 |
| ZP | API 调用、API 模型、接口配置 |

音频不设独立前缀；音频服务于视频时与视频共同归 ZV。跨领域节点仍按主要用途判断，例如通过 API 处理视听素材的接口节点以 API 调用为主时归 ZP。

显示名和 CATEGORY 可以随用途整理。今后已稳定发布的技术 ID 默认冻结，除非有用户明确授权、备份及结构校验的显式迁移方案；不为了前缀整齐批量修改稳定节点。

本次是两个尚在开发期的视频节点的正式断代迁移：

| 显示名 | CATEGORY | 旧技术 ID → 正式技术 ID |
| --- | --- | --- |
| ZV 通用素材取证台 | `ZV/视频创作/素材取证` | `ZFUniversalMediaEvidenceDesk` → `ZVUniversalMediaEvidenceDesk` |
| ZV H3 采访表 | `ZV/视频创作/H3` | `ZVH3InterviewFormV2`（唯一当前表格） |
| ZV H3 独立反推阶段 | `ZV/视频创作/H3` | `ZVH3ReverseStage` |

Python 类名、注册键和前端匹配 ID 同步使用新 ZV ID，旧 ID 不再注册，也不增加兼容别名或重复节点。取证台 socket 正式改为 `ZV_MEDIA_PROJECT`；后续采访/适配接口使用该类型。未迁移的旧本地或云端工作流需要迁移或重新建节点，不再承诺旧 ID 自动兼容。

未来新增的视频节点从首次发布起使用 `ZV` 技术 ID，并让类名、前端匹配值及注册键保持一致。

人像提示词生成器按图片创作用途进行用户明确授权的 ZI 断代迁移：`ZFPortraitPromptGenerator` → `ZIPortraitPromptGenerator`，显示名为 **ZI 人像提示词生成器**，分类 `ZI/图片创作/人像提示词`。Python 类名、注册键、前端 `NODE_NAME` 和扩展名 `ZI.PromptDirector.PortraitGenerator` 同步，旧技术 ID 不注册、不留别名。三个 `STRING` 输出、控件和状态 JSON 保持不变；标签删除“（可手动输入）”说明，手动输入、双击编辑和 overrides 机制继续保留。

人像迁移脚本 `scripts/migrate_zi_workflows.py` 默认只扫描，`--apply` 才先生成同目录唯一 `.zi-时间戳-随机.bak` 原字节备份。只修改明确图节点或 API 节点的 `type` / `class_type` 及对应 properties 标识，不替换普通文本、widgets 或 API inputs 内容。复用已测试的 JSON 字符位置解析和图结构核验；保留节点 ID、端口、连线、位置、控件值与原排版。未命中工作流保持原字节，任一解析错误使本次批量写入停止。未迁移的旧副本需显式迁移或重建；加载新注册需重新加载 Python 节点代码和前端。

本次工作流迁移工具为 `scripts/migrate_zv_workflows.py`：默认只扫描；显式 `--apply` 时先生成同目录唯一 `.bak` 原字节备份，再只替换解析定位的节点 `type` / `class_type` 与该节点 properties 内对应名称。保留换行、排版、节点/连接 ID、端口、坐标、控件值及连线；解析与结构核验通过后才交付。没有命中的文件不修改；本轮范围仅限用户指定的本地 `user/default/workflows`，不操作云端副本或当前画布。
