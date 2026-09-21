# Z 前缀命名

前缀按主要用途分类，不是强制类型系统。完整节点选择见[节点用途与当前入口](NODE_GUIDE.md)。

| 前缀 | 主要用途 |
| --- | --- |
| ZI | 图片创作、图片编辑 |
| ZV | 视频生成、视听素材、视频编排，以及服务于视频的音频 |
| ZT | 文本创作、提示词加工 |
| ZF | 过滤、路由、转换、设置等通用辅助 |
| ZH | 自用保存类，尤其无元数据保存 |
| ZP | API 调用、模型接口配置 |

音频不另设前缀；服务于视频时归 ZV。跨领域节点按主要用途判断。

技术 ID 是工作流接线契约。已发布 ID 不为名称整齐而批量改名；前端匹配、Python 类与注册键须一致。显示名称可以改善，但不能靠改标题把旧端口伪装成新节点。

当前素材台为 `ZVUniversalMediaEvidenceDesk`，工程类型为 `ZV_MEDIA_PROJECT`。当前 H3 表格为 `ZVH3InterviewFormV2`，反推独立使用 `ZVH3ReverseStage`。人像生成器为 `ZIPortraitPromptGenerator`。废弃的旧表、编译器、固定槽位及其别名不注册。

H3 长视频节点在 `ZV/视频创作/H3长视频` 分类，显示名标明 H3；Animate 使用自己的配对台和执行节点。两者的技术 ID、端口没有因分类整理而改变。

`scripts/migrate_zv_workflows.py` 和 `scripts/migrate_zi_workflows.py` 仅用于已有素材台、人像节点的技术 ID 改名；默认只扫描，显式 `--apply` 才备份并修改。它们不转换旧 H3 表格的端口或反推链路，也不会复活废弃节点。H3 请使用[当前模板](H3_INTERVIEW.md)。
