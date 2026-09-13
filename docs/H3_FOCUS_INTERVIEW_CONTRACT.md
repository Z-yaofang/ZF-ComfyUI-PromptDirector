# ZV H3 结构化计划编译器（高级）：数据契约

版本：`h3-focus-plan-v1`。本阶段建立纯 Python 计划、校验、受限补槽和确定性编译；不调用模型、翻译服务、媒体探测器或 ffmpeg，不安装依赖，不执行媒体切片。旧 `h3-plan-v6` 不会被静默迁移。

## 入口与示例

ComfyUI 节点：**ZV H3 结构化计划编译器（高级）**，正式 ID 与类名均为 `ZVH3FocusCompiler`，分类 `ZV/视频创作/H3`。原始节点类型、计划契约和六路输出不变；这里只调整显示名，以便与面向日常使用的 `ZV H3 基础采访表` 区分。

输入是必填 `plan_json` 和可选 `llm_patch_json`。六路输出按顺序为：

1. `normalized_plan_json`：保存稳定编号、任务绑定和派生 `ready` 的计划。
2. `final_prompt`：通过校验时的 H3 提示词；未就绪时为空字符串。
3. `reverse_task_json`：精确字段任务、锁及 accepted/rejected 补槽报告。
4. `human_report`：模式、时长、素材对应关系、镜头和待处理事项。
5. `validation_report_json`：带 `path/code/message` 的错误及分段提示层。
6. `ready`：原生 ComfyUI `BOOLEAN`，与 JSON 中的派生值一致。

完整可粘贴示例位于 `tests/fixtures/h3_focus/`：`t2va.json`、`i2va.json`、`fl2va.json`、`l2va.json`、`ref2va.json`；另有 `uniform_edit.json` 和 `narrative.json` 展示 20 秒源素材的两段计划。示例句子为短小原创占位内容，不用于展示模型生成质量。

纯 Python 调用：

```python
import json
from pathlib import Path
from h3_focus import compile_plan, parse_json

plan = parse_json(Path("tests/fixtures/h3_focus/i2va.json").read_text(encoding="utf-8"))
result = compile_plan(plan)
assert result["ready"], result["validation"]
print(result["final_prompt"])
```

`h3_focus` 不导入 ComfyUI、torch 或任何网络/媒体库。运行时只使用标准库；读取的文件只有随包发布的 JSON Schema。节点包装位于 `h3_focus/node.py`，原 `nodes.py` 只增加导入、类映射和显示名称三行。

## 计划字段

JSON Schema 位于 `schemas/h3-focus-plan.schema.json`。对象采用明确字段白名单；运行时校验器只实现这份资源使用的 Schema 词汇，不声称是通用 JSON Schema 引擎。

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 必须为 `h3-focus-plan-v1` |
| `profile` | `local_t8` 或 `cloud_strict` |
| `profile_limits` | 可选的 cloud_strict 部署策略覆盖：`video_total_seconds`、`audio_total_seconds` |
| `mode` | `auto`、T2VA、I2VA、FL2VA、L2VA、Ref2VA |
| `mode_override` | 可选、人工指定的非 auto 模式；优先于 mode |
| `effective_mode` | 归一化结果派生，输入自报值被忽略 |
| `duration_seconds` | 本计划的完整目标时长；必须为正数 |
| `label_counters` | 四类标签的持久最高编号，删除素材后也须保留 |
| `media_assets[]` | 物理图片、视频、音频资产库，包括暂未选中的长素材 |
| `subjects[]` | 从物理素材抽象的可见主体，与文件独立 |
| `shots[]` | 稳定 ID、播放顺序、切点及逐字段镜头描述 |
| `style` | 用户提供的风格句；不会推断或补写 |
| `ref2va` | 显式 `task_types[]` 和不含任务前缀的 `summary` |
| `overall_soundscape` / `non_diegetic_music` | 原文声音字段；需要无声时由调用方明确写入 `N/A` |
| `locks[]` | JSON Pointer、锁定快照 `value`、派生并持久保存的 `target_id` |
| `gaps[]` | 精确字段任务及 pending/resolved/skipped 状态 |
| `segmentation` | 统一源时钟、共享提示、共享锁及每段局部提示与选择窗口 |
| `ready` | 完全由本次校验结果派生，输入的 true/false 都不作为凭据 |

用户缺少创作内容时，使用空字符串或允许的 null，并单独创建 gap；不把 `SLOT:`、`【反推:…】` 等原型标记混入成品提示词。结构错误返回报告；语义未完成的草稿可以序列化，但 `ready=false`。

## 素材、主体与稳定编号

`media_assets` 的 `asset_id` 由调用方创建并持久保存；`kind` 只能是 `picture/video/audio`。`source.handle` 使用上传相对标识或不透明句柄，例如 `uploads/cup.png`，不能使用绝对路径、URL 或 `..` 路径穿越。此阶段不解析、不读取句柄。

`probe` 支持源时长、源 fps/总帧数、采样率/总采样数、尺寸与音轨存在信息。未知探测值可以是 null；被选择的时序素材必须提供源时长才能通过校验。元数据由未来可信媒体服务提供，本节点不凭文件名猜测。

`ordinal` 与 `official_label` 必须一致，例如 `3` 和 `<Video 3>`。已存在的编号不会随数组重排、删除其他素材或分段而改变。初次缺少编号时，按种类和稳定 ID 排序后分配，计数器只增加；首次归一化结果必须回存。即使最高编号对应的素材被删除，也不要删除 `label_counters`。v1 没有隐式或自动重新编号操作；用户显式重新编号时须同时更新所有引用、锁快照及计数器。

人物、动物、环境、服装、动作和风格等内容单位放在 `subjects` 中。`subject_id` 和 `<Subject N>` 独立编号；`source_asset_ids` 可指向多个图片/视频，同一文件也可供多个 Subject 使用。只有声音的文件不能作为可见 Subject 的唯一来源。

物理资产角色：

| kind | role |
| --- | --- |
| picture | subject_source、first_frame、last_frame、keyframe、storyboard |
| video | subject_source、video_edit、video_continue、structure_reference |
| audio | audio_reuse、audio_reference |

Ref2VA 中，`subject_source` 仅供 Subject 定义引用，不单独生成物理标签定义/保留条目。其他参与的物理资产及全部 Subject 都需要 `definition` 与 `retention`。`definition` 是标签后的原文，例如 `is the cup in <Picture 1>.`。Subject 定义必须明确提到其来源标签。脱离定义而在 summary、镜头、声音或分段提示中单独使用的物理标签，必须有独立定义和保留条目。

`retention` 包含 `relationship/placement/details`。可见内容使用 fully_preserved、partially_preserved、attribute_transfer、weak_reference；音频使用 fully_copy、partially_copy、reference、weak_reference。检查定义、使用、来源、Shot 引用及保留标记的机械一致性，不由代码判断真实图像相似度或语义保真程度。

## 时间、帧与音画配对

所有时间窗使用 `[in, out)`，两个秒端点必须同时存在、非负且 out > in。选中的视频和音频必须有显式窗口；原素材可以远长于窗口。可选的 `in_frame/out_frame` 和 `in_sample/out_sample` 也必须成对，并与源 fps/采样率、总数量和秒边界一致，允许 1e-6 秒的浮点表示误差。数字限制在 JSON/JavaScript 可安全持久表达的整数幅度内，禁止 NaN/Infinity。

`model_input.fps/frame_count` 描述已经准备好、真正送入模型的帧序列，与 `probe.fps/frame_count` 的原素材数据分开。不能拿短帧数掩盖长窗口，也不会用输入计划冒充已完成媒体转换。CFR 帧边界可用源 fps 校验；VFR 的精确逐帧映射需要后续媒体服务提供，不应假装平均 fps 等于逐帧时钟。

视频自身音轨启用时：

- video 设置 `audio_enabled=true`、`paired_audio_asset_id`，且 probe.has_audio 必须为 true。
- 创建独立 audio 条目，设置 `source_video_asset_id`，双方互相对应。
- 配对条目使用相同 source 句柄、clock_id 和偏移；同次调用选择相同秒窗口。帧与采样边界可以分别表示。
- `<Video 1>` 可以对应 `<Audio 7>`。标签编号不表示配对；存在音轨的文件不会自动获得 Audio 标签。
- 关闭自身音轨时移除活动配对关系，未使用的音频可作为资产库记录保存。

图片在 v1 中代表准备好的静态文件，保留完整物理契约，但不把视频片段伪装成 picture 时间窗。未来从视频抽首尾帧的准备任务应产生图片句柄，再交给当前契约。

## 模式与确定性编译

auto 只基于显式资产角色和选择关系路由：无参与素材为 T2VA；无 Subject 且仅 first_frame 图片为 I2VA、仅 last_frame 图片为 L2VA、两者各一为 FL2VA；其余为 Ref2VA。不会分析文件内容或自然语言猜模式。人工覆盖后仍校验其物理输入。

基础模式严格要求固定 Picture 1 / Picture 2 角色；空号不会被偷偷修正。若选择的持久标签与基础模式不兼容，报告 mode_assets，调用方可显式调整编号或选择 Ref2VA。I2VA、FL2VA、L2VA 都保留 `media_assets`；T2VA 也序列化资产库，只是不允许选中参考输入。

三个核心字段的顺序为 integrated_multimodal_description、overall_soundscape、non_diegetic_music。T2VA 直接开始核心字段；I2VA、FL2VA、L2VA 使用技能要求的精确首行，之后空一行。FL2VA 首行的 `Shot N` 无方括号，L2VA 使用 `[Shot N]`；N 是实际最终镜头，时长固定两位小数。Ref2VA 的六个 heading 严格按 subject_definitions、summary、retention_analysis、detailed_description、overall_soundscape、non_diegetic_music 排列。

四种基础模式的字段名、冒号、一个空格和字段值在同一行开始，字段之间空一行，例如 `integrated_multimodal_description: [Shot 1] ...`、`overall_soundscape: ...`、`non_diegetic_music: ...`。Ref2VA 保持六个 heading 各自独占一行、定义或正文从下一行开始的多行结构。

`shots` 通过 `order` 排序，ID 不变，order 从 1 连续排列。Shot 1 的 cut_seconds 必须是 0，输出不带时间戳；后续切点严格递增且小于目标时长，并能准确表示为整数毫秒。后续输出为 `[Shot N] At MM:SS.mmm, ...`。构图、主体描述、环境、动作、镜头、声效等只按字段顺序拼接，语句连接和镜头转场用语由调用方写好，编译器不补写故事。

`dialogue[]` 同时用于对白/歌词：提供 source、稳定 speaker_id、delivery、language、text 和 after。说话人编号按实际首次发声顺序检验。直接重用音轨中的歌词提示可以使用 Audio source 且 speaker_id=null。编译器保留 `<scenetrans>`/`<cutoff>` 和原词标点；跨切点音频连续描述由作者写入 after。画外音使用固定 `says in an off-screen voiceover`，并由 after 明确描述嘴唇保持闭合。

`visible_text[]` 的 description 描述位置，text 是可见原文，输出自动加英文双引号。`reference_placements[]` 记录 label、text 与可选 target_seconds；描述必须实际提到该标签，落点须位于所属镜头范围内。

`【图1】/【图片1】/【视频1】/【音频1】/【主体1】/【人物1】` 在编译时规范化为对应标签。保存的原文和锁快照不改写；对白、歌词、可见文字以及已有 `<d>`/英文双引号中的文字不做标签替换。发现明显中日韩文描述时报告需要提供已审核英文，不会翻译。此检查不等于完整语言识别，英文质量仍需人审。

## 锁、反推任务和 patch

示例任务（授权由调用方创建，不能来自 LLM 返回）：

```json
{
  "id": "gap-action",
  "path": "/shots/0/action",
  "target_id": "shot-a",
  "required": true,
  "value_type": "string",
  "context": "Describe the cup motion.",
  "status": "pending"
}
```

字段锁示例：`{"path":"/style","value":"Live-action.","target_id":null}`。快照必须与当前值相等。第一次归一化自动补齐 target_id；之后必须随计划保存。数组字段的目标绑定最近的 asset_id/subject_id/shot id/segment id，重排后指向另一对象会被判为 stale_binding；存在失效锁时拒绝全部补槽，防止错位覆盖。UI 显式编辑/重排后需要同步重绑相关 pointer、target_id 和快照；对同一镜头内的对白等无独立 ID 子列表重排，也必须同步更新指针。

本阶段只授权既有**文本叶字段**：风格、声音、定义/保留描述、summary、镜头描述、对白内容、可见文字和分段提示。素材 ID、标签、源句柄、时间边界、模式、任务状态、锁、结构数组不能通过 LLM patch 修改。value_type 为类型声明；阶段 1 的可补内容只接受 string，数字/布尔声明不会扩大授权。后续媒体测量和结构编辑由明确的用户操作或可信服务负责。

LLM 可返回 field map，或仅含 `replace` 的 JSON Patch 数组：

```json
{"/shots/0/action":"The cup stops turning."}
```

```json
[{"op":"replace","path":"/shots/0/action","value":"The cup stops turning."}]
```

路径遵循 RFC 6901，索引不能写成 01、- 或负数。未知路径、未授权/重复 gap、与锁相交的路径（含父子路径）、已有非空内容、非 string 值、空结果和新增校验错误均被拒绝。逐项独立接受/拒绝，接受后将对应任务置为 resolved；不会顺带接受其他修改。报告只记录路径和原因，不回显被拒绝的内容。

required gap 未 resolved 或仍无值时 ready=false；可选 gap 可以显式 skipped，但不能借此绕过核心必填字段。可选 pending 任务本身不阻塞。拒绝一个无关 patch 不会使原本合法的计划失效，拒绝情况始终在 reverse_task_json 与 human_report 中显示。

## 运行环境策略

| 策略 | 检查 |
| --- | --- |
| local_t8 | 每次选择最多 9 图片、3 视频、3 独立音频；启用的视频配对音轨不消耗独立音频计数；视频实际输入 24fps、48–360 帧 |
| cloud_strict | 默认本次所选视频时长之和 ≤15 秒、所选音频时长之和 ≤15 秒；启用的视频音轨也计入音频时长；可通过 profile_limits 显式调整 |

local_t8 来源为本地 `comfyui-minimax-h3-audio-T8/conditioning.py` 的 `build_conditioning`：396–397 行计数检查，454–458 行 `official_2_to_15s` 分支；`core.py:20` 定义 FPS=24。T8 后续还会按目标帧数裁剪并对齐 17n+5，本阶段记录/校验传入帧数，不把这些后续处理冒充已完成的切片。其 first_frame/last_frame 与参考图分支分开处理；这里的 9 张是本计划输入策略上限，暂不声称覆盖 T8 所有扩展组合。

**cloud_strict 是部署端配置名和保守策略，不是从官方提示词文档推断出的限制。** 不把原型的“所有 H3 素材总是最多 15 秒”当作模型通用事实。

原素材长度不触发这些输入上限；真正选中并送入模型的窗口才受限制。未启用分段时使用资产的 selected/selected_window；启用分段时每段 selections 是参与权威来源，资产库顶层 selected 标记不再决定分段参与，按每段单独检查。

## 分段契约

`strategy=none` 时无分段内容；uniform_edit 需要非空 global_prompt；narrative 要求每段非空 local_prompt，global_prompt 可承载共享风格/身份要求。共享锁通过 shared_lock_paths 指向真实 plan.locks。

所有段使用 `clock=source_seconds` 和同一 clock_id。各段包含稳定 id、order、source_window、local_prompt、selections；选择项包含 asset_id、window、model_input 和 timing。

- timing=synchronized：素材窗口 + source.clock_offset_seconds 必须映射到该段全局源时间窗，视频和音频共享同一个时钟。
- timing=reference：固定图片、短音色参考等可以跨段复用自己的局部窗口。
- 段起点和终点都必须向前推进，允许重叠，不允许空洞；覆盖的源时钟跨度等于 duration_seconds。变速/跳切后重排的时间映射超出 v1。
- 同次调用每个物理资产只选一个窗口，当前版本不自动为同一文件的多窗复制创建新标签。

final_prompt 是完整目标计划的标准 H3 提示，不是已经生成的逐段执行脚本。分段共享/局部提示单独留在 normalized_plan_json.segmentation，并在 validation_report_json.segment_prompt_layers 中给出标签规范化后的内容。后续执行适配器应从这些层构造逐段 H3 输入，按实际准备后的媒体再次验证；阶段 1 不输出、也不执行逐段采样任务。

## 安全与保存

计划只保存结构化来源、秒/帧/采样窗口和模型输入元数据。没有 command、cut_command、shell_command、API key 或翻译密钥字段。未知字段和常见凭据/命令载荷被拒绝；畸形 JSON、重复 JSON 键与非有限数字返回明确报告。结构失败时节点输出 `{}`，不会回显被拒绝的 payload。自由文本不会送进 eval、exec、subprocess 或网络调用。

此约束是数据契约和执行边界，不是通用秘密识别器。未来执行器必须用可信句柄解析、参数数组和服务端媒体检查实现切片；不得把提示词当命令，也不得仅因本计划 ready=true 就跳过实际媒体核验。

## 原型复核与来源

检查的用户原型为 `h3-builder-v8.html`（103875 字节；SHA256 `1ABE00BAB781FF69FB56357E3103A766F1134CACDE76DAB3160EC322A034FD45`）。其 22 个配方覆盖人物替换、换装、动作迁移、产品替换、背景替换、风格迁移、动作改写、视频续写、中段补全、音轨替换、台词重配、多人物替换、表情替换、发型发色、年龄变化、季节天气、日夜光照、动漫化、材质替换、机位重剪、场景扩展、运镜迁移。阶段 1 不搬运配方文本或单文件 DOM；角色和补槽契约可供下一阶段重新实现配方。

已确认的原型风险：

1. `labelOf` 按数组位置编号，删除/重排会改变语义；新契约持久编号。
2. Subject 混入资产数组，许多 Subject 没有真实 Picture 来源；新契约分离并验证来源。
3. `baseState`/`buildPlanJSON` 只在 Ref2VA 持有/导出 assets；基础模式现全部保存物理素材。
4. FL2VA 首行误把最后 Shot 写成 `[Shot N]`；部分配方使用 `00:00:02.000`，不符合 MM:SS.mmm。
5. 反推任务只有展示文本，没有 exact path、授权范围或真正可执行的字段锁；原型中的 N/A 三态不等于锁。
6. 单端窗口被补成 0 或源时长；新契约要求两端明确，禁止猜测。
7. JSON 含 cut_command，源文件名直接拼入 shell 字符串；本阶段完全移除可执行命令输出。
8. 无槽位时 UI 可以显示“可直接生成”，但其他校验仍有告警；ready 现在统一派生。
9. 视频和音频使用独立分段计算器，且说明要求每段重编号、共用同一提示；新契约共享音画源时钟并区分叙事局部提示。
10. 原型将 translation key 保存在 localStorage，并存在免费翻译回退请求；本模块不包含这些字段或请求。

H3 格式依据本地 `h3-prompt-writing/SKILL.md`、`references/base-en.txt`、`references/ref-en.txt`，未复制其长示例。GPL 项目 `ComfyUI-MiniMaxH3-TimelineDirector` 只参考 README 中的媒体探测、选择范围、音轨跟随和长素材分段概念；未复制其 Python/JS/CSS/文案实现，也未修改该仓库。已有 JS 修改的 SHA256 始终为 `A7101DF603BD916804A77BC857B6F36831925D3778FD396FF20C7D528EB35FBA`。

## 验证和后续边界

开始时目标仓库 HEAD 为 `accce6a8b85733debf0763d2ae44a48eb8f75408`，git status/diff 干净。默认 `python -m pytest -q tests` 在收集时把插件根 __init__.py 当作无父包模块，导致 57 个 setup 错误；使用下面的隔离收集方式后，原有 57 项全部通过，不需要安装 ComfyUI 或改旧测试。

```powershell
python -m pytest -q --rootdir=tests --confcutdir=tests --import-mode=importlib tests
python -m compileall -q h3_focus tests/test_h3_focus.py
git diff --check
```

本次执行结果：基础模式同行格式复核修正后，完整测试 **126 passed**（既有 57 项 + H3 新增 69 项，含四种基础模式完整提示词的逐字符断言）；compileall 和 diff --check 通过。此前已使用环境中安装的 jsonschema 额外核验 Draft 2020-12 资源及全部 7 个示例的输入/归一化输出，全部通过；该库没有加入运行依赖。另对 98 个畸形顶层字段变体执行校验，均返回结构化报告，没有崩溃。

新增 H3 测试覆盖五模式首行/heading、原语言保护、标签持久性、Subject 来源、基础模式素材序列化、锁/授权/类型/旧绑定补槽拒绝、required gap、切点与窗口错误、两种 profile、实际输入帧数、配对音轨、统一分段时钟、共享与局部提示、危险字段拒绝以及最小节点六路输出。已有测试还通过轻量 ComfyUI stub 加载真正的 nodes.py，验证原节点回归。

下一阶段建议先做小型采访字段编辑与 22 配方到新契约的映射，始终回存 normalized_plan_json；然后接入可信媒体探测/准备服务，最后再设计大型时间轴和模型补槽调用。本阶段没有进入这些开发，没有重启运行中的 ComfyUI，没有提交或推送。
