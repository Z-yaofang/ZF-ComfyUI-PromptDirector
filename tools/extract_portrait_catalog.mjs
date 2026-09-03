import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath || !outputPath) {
  throw new Error("用法：node tools/extract_portrait_catalog.mjs <source.html> <output.json>");
}

const source = fs.readFileSync(sourcePath, "utf8");
const start = source.indexOf("function norm");
const end = source.indexOf("/* ================= 界面构建", start);
if (start < 0 || end < 0) {
  throw new Error("没有在源 HTML 中找到素材定义区。");
}

const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context, { timeout: 5000 });

const cleanLabel = (value) => String(value || "")
  .replace(/（≥18·可手动输入）/g, "（可手动输入）")
  .replace(/（SFW\s*·\s*/g, "（")
  .replace(/SFW强化·/g, "")
  .replace(/NSFW强化·/g, "")
  .replace(/（NSFW·开关启用）/g, "")
  .replace(/NSFW\s*/g, "成人")
  .replace(/\s+/g, " ")
  .trim()
  .replace(/^人种感$/, "人种");

// The source HTML's SFW exposure ladders append policy-like negative clauses.
// Once the full catalog is used as worldview material those clauses can be
// mistaken for global constraints and cancel unrelated adult pose assets.
const cleanOptionText = (value) => String(value || "")
  .replace(/（不露点、避开敏感部位）/g, "")
  .replace(/（避开私处）/g, "")
  .replace(/（仍避开私密部位）/g, "")
  .replace(/（避开私密部位）/g, "")
  .replace(/，仍避开私密部位/g, "")
  .replace(/，仅以贴身内衬保留最后遮挡/g, "")
  .replace(/，仅留极简遮挡/g, "")
  .trim();

const normalizeOption = (item, group = "") => {
  if (typeof item === "string") return { value: item, text: cleanOptionText(item), group };
  if (Array.isArray(item)) {
    return { value: String(item[0] || ""), text: cleanOptionText(item[1] || item[0]), group };
  }
  return {
    value: String(item?.v ?? item?.value ?? item?.id ?? ""),
    text: cleanOptionText(item?.t ?? item?.text ?? item?.label ?? item?.v),
    group,
    risk: Boolean(item?.risk),
    adult: Boolean(item?.nsfw),
  };
};

const flattenPairs = (catalog) => Object.entries(catalog || {}).flatMap(([group, items]) =>
  (items || []).map((item) => {
    const option = normalizeOption(item, group);
    option.value = `${group}｜${option.value}`;
    return option;
  })
);

const flattenPoses = (catalog, categories) => Object.entries(catalog || {}).flatMap(([key, items]) =>
  (items || []).map((item) => ({
    value: String(item?.id || item?.v || item?.t || ""),
    text: cleanOptionText(item?.t || item?.text || item?.id),
    group: String(categories?.[key] || key),
  }))
);

const dynamicOptions = {
  clothItem: flattenPairs(context.CLOTH),
  lingerieItem: flattenPairs(context.LINGERIE_ITEMS),
  sfwSimPick: flattenPoses(context.SFW_POSES, context.SFW_CATS),
  simPick: flattenPoses(context.SIM_POSES, context.SIM_CATS),
};

const optionList = (field) => {
  if (field.range) {
    const result = [];
    for (let value = Number(field.min); value <= Number(field.max) + 1e-8; value += Number(field.step)) {
      const rounded = value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
      result.push({ value: rounded, text: `腿长比例 ${rounded}` });
    }
    return result;
  }
  const raw = dynamicOptions[field.list] || context.OPT?.[field.list] || [];
  return raw.map((item) => normalizeOption(item, item?.group || ""));
};

const adultFieldIds = new Set([
  ...(context.CLOTH_FIELDS?.nsfw || []).map((item) => item.id),
  ...(context.POSE_FIELDS?.nsfw || []).map((item) => item.id),
  "nsfwLowerBody",
  "nsfwBreastDetail",
]);

const field = (item, adult = false) => ({
  id: String(item.id),
  label: cleanLabel(item.label),
  custom: Boolean(item.custom),
  editable: true,
  adult: adult || adultFieldIds.has(item.id),
  options: optionList(item),
});

const OMITTED_FIELD_IDS = new Set([
  // 卡片本身已经支持双击修改，不再保留重复的自由填充页。
  "personCustom", "nsfwCustom1", "nsfwCustom2",
  // 选择与随机直接作用于素材，不再暴露源 HTML 的模式/辅助分类页。
  "sfwSimMode", "sfwSimCoreCat", "sfwSimCat",
  "simMode", "simCoreCat", "simCat",
]);

const POSTURE_GROUPS = [
  ["A", "supine", "仰卧"],
  ["B", "prone", "俯卧"],
  ["C", "side", "侧卧"],
  ["D", "kneeling", "跪姿"],
  ["E", "sitting", "坐姿"],
  ["F", "standing", "站姿"],
  ["G", "squatting", "蹲姿"],
  ["H", "suspended", "悬空"],
  ["J", "special", "特殊姿态"],
];

const SFW_ACTION_GROUPS = [
  ["transition", "姿态转换", (number) => number <= 10 || number >= 26],
  ["walking", "行走与步伐", (number) => number >= 11 && number <= 18],
  ["jumping", "跳跃动作", (number) => number >= 19 && number <= 22],
  ["spinning", "旋转动作", (number) => number >= 23 && number <= 25],
];

const ADULT_ACTION_GROUPS = [
  ["transition", "姿态转换", (number) => number <= 20 || number >= 81],
  ["walking", "行走与步伐", (number) => number >= 21 && number <= 40],
  ["jumping", "跳跃动作", (number) => number >= 41 && number <= 60],
  ["spinning", "旋转动作", (number) => number >= 61 && number <= 80],
];

const virtualField = (id, label, options, adult = false) => ({
  id,
  label,
  custom: false,
  editable: true,
  adult,
  options: options.map((option) => ({ ...option, adult: adult || Boolean(option.adult) })),
});

const postureFields = (options, adult = false) => POSTURE_GROUPS.map(([letter, id, label]) =>
  virtualField(
    `${adult ? "adultPosture" : "posture"}${id[0].toUpperCase()}${id.slice(1)}`,
    `${label}${adult ? "·扩展" : ""}`,
    options.filter((option) => String(option.value || "").startsWith(letter)),
    adult,
  )
);

const actionFields = (options, adult = false) => {
  const dynamic = options.filter((option) => String(option.value || "").startsWith("I"));
  const groups = adult ? ADULT_ACTION_GROUPS : SFW_ACTION_GROUPS;
  return groups.map(([id, label, matches]) => virtualField(
    `${adult ? "adultAction" : "action"}${id[0].toUpperCase()}${id.slice(1)}`,
    `${label}${adult ? "·扩展" : ""}`,
    dynamic.filter((option) => matches(Number(String(option.value || "").slice(1)))),
    adult,
  )).filter((item) => item.options.length);
};

const sourceSections = context.SECTIONS.flatMap((section) => {
  let fields = section.fields || [];
  if (section.id === "cloth") {
    fields = [
      ...(context.CLOTH_FIELDS?.sfw || []).map((item) => field(item, false)),
      ...(context.CLOTH_FIELDS?.nsfw || []).map((item) => field(item, true)),
    ].filter((item) => !OMITTED_FIELD_IDS.has(item.id));
  } else if (section.id === "pose") {
    const normalOptions = dynamicOptions.sfwSimPick;
    const adultOptions = dynamicOptions.simPick;
    const chain = (context.POSE_FIELDS?.nsfw || [])
      .filter((item) => item.id === "nsfwChain")
      .map((item) => field({ ...item, label: "身体反应" }, true));
    return [
      {
        id: "posture",
        title: "姿态",
        open: Boolean(section.open),
        fields: [...postureFields(normalOptions), ...postureFields(adultOptions, true)],
      },
      {
        id: "action",
        title: "动作",
        open: Boolean(section.open),
        fields: [...actionFields(normalOptions), ...actionFields(adultOptions, true), ...chain],
      },
    ];
  } else {
    fields = fields.map((item) => field(item)).filter((item) => !OMITTED_FIELD_IDS.has(item.id));
  }
  return [{
    id: section.id,
    title: cleanLabel(section.title),
    open: Boolean(section.open),
    fields,
  }];
});

const sourceMap = new Map(sourceSections.map((section) => [section.id, section]));
const fieldsFrom = (sectionId, ids = null) => {
  const fields = sourceMap.get(sectionId)?.fields || [];
  if (!ids) return fields;
  const wanted = new Set(ids);
  return fields.filter((item) => wanted.has(item.id));
};
const section = (id, title, fields, sourceId = id) => ({
  id,
  title,
  open: Boolean(sourceMap.get(sourceId)?.open),
  fields,
});

const PERSON_SUBJECT_FIELDS = [
  "temperament", "age", "race", "face", "skin", "texture", "body",
];
const CLOTHING_FIELDS = [
  "stylePreset", "clothCat", "clothItem", "outerwear", "collarStyle", "topLength",
  "bottomStyle", "splitColor", "bottomLength", "lingerieCat", "lingerieItem",
  "lingerieColor1", "lingerieColor2", "pantyColor", "pantyStyle",
];
const ACCESSORY_FIELDS = [
  "shoes", "sockType", "sockLen", "sockColor", "sockOpacity", "accessory",
];
const CLOTHING_EXPRESSION_FIELDS = [
  "clothMat", "clothPattern", "clothDeco", "clothLayer", "sfwExposure",
  "clothTransparency", "nsfwExposure",
];

const personSubjectSet = new Set(PERSON_SUBJECT_FIELDS);
const sections = [
  section("shooting_light", "拍摄与光影", [
    ...fieldsFrom("camera"),
    ...fieldsFrom("light"),
  ], "camera"),
  section("subject", "人物主体", fieldsFrom("person", PERSON_SUBJECT_FIELDS), "person"),
  section("person_detail", "人物细节", fieldsFrom("person").filter((item) => !personSubjectSet.has(item.id)), "person"),
  section("hair", "发型与头饰", fieldsFrom("hair")),
  section("styling_expression", "妆造表达", [
    ...fieldsFrom("makeup"),
    ...fieldsFrom("expression"),
  ], "makeup"),
  section("wear_state", "穿着状态", fieldsFrom("cloth", ["nsfwState"]), "cloth"),
  section("clothing", "服装", fieldsFrom("cloth", CLOTHING_FIELDS), "cloth"),
  section("accessories", "配饰", fieldsFrom("cloth", ACCESSORY_FIELDS), "cloth"),
  section("clothing_expression", "服装表现", fieldsFrom("cloth", CLOTHING_EXPRESSION_FIELDS), "cloth"),
  section("posture", "姿态", fieldsFrom("posture")),
  section("action", "动作", fieldsFrom("action")),
  section("bg", "场景与道具", fieldsFrom("bg")),
  section("comp", "画面构图", fieldsFrom("comp")),
  section("extra", "风格与质感", fieldsFrom("extra")),
];

const catalog = {
  version: 3,
  source: "人像提示词生成器 v12（获授权参考素材的工程化整理）",
  sections,
  style_presets: context.STYLE_PRESETS || {},
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(catalog)}\n`, "utf8");
console.log(`已生成 ${outputPath}，${sections.reduce((sum, item) => sum + item.fields.length, 0)} 个字段。`);
