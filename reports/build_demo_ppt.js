const pptxgen = require("pptxgenjs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "reports", "svg_icon_agent_demo_zh.pptx");

const img = (...parts) => path.join(ROOT, ...parts);

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Zhao Guanjie";
pptx.subject = "SVG Icon Agent Chinese demo deck";
pptx.title = "SVG Icon Agent: 多 Agent 协同的可编辑 SVG 图标生成";
pptx.company = "Fudan University";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "PingFang SC",
  bodyFontFace: "PingFang SC",
  lang: "zh-CN",
};
pptx.defineLayout({ name: "LAYOUT_WIDE", width: 13.333, height: 7.5 });
pptx.layout = "LAYOUT_WIDE";
pptx.margin = 0;

const C = {
  bg: "F7F8FB",
  ink: "172033",
  muted: "667085",
  blue: "2563EB",
  blue2: "DBEAFE",
  green: "16A34A",
  green2: "DCFCE7",
  orange: "F97316",
  orange2: "FFEDD5",
  purple: "7C3AED",
  purple2: "EDE9FE",
  red: "DC2626",
  red2: "FEE2E2",
  line: "D0D5DD",
  white: "FFFFFF",
  dark: "0F172A",
  yellow: "FACC15",
};

function addBg(slide) {
  slide.background = { color: C.bg };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 13.333,
    h: 0.08,
    fill: { color: C.blue },
    line: { color: C.blue },
  });
}

function addTitle(slide, title, subtitle) {
  slide.addText(title, {
    x: 0.55,
    y: 0.35,
    w: 8.8,
    h: 0.42,
    fontFace: "PingFang SC",
    fontSize: 22,
    bold: true,
    color: C.ink,
    margin: 0,
    breakLine: false,
    fit: "shrink",
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.57,
      y: 0.82,
      w: 9,
      h: 0.25,
      fontFace: "PingFang SC",
      fontSize: 8.5,
      color: C.muted,
      margin: 0,
      fit: "shrink",
    });
  }
}

function addFooter(slide, page) {
  slide.addText("SVG Icon Agent | 生成式 AI 与多 Agent SVG 图标生成", {
    x: 0.55,
    y: 7.15,
    w: 6.4,
    h: 0.17,
    fontFace: "PingFang SC",
    fontSize: 6.5,
    color: "98A2B3",
    margin: 0,
  });
  slide.addText(String(page).padStart(2, "0"), {
    x: 12.35,
    y: 7.1,
    w: 0.45,
    h: 0.22,
    fontFace: "Aptos",
    fontSize: 8,
    color: "98A2B3",
    margin: 0,
    align: "right",
  });
}

function addChip(slide, text, x, y, color, fill) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w: 1.65,
    h: 0.32,
    rectRadius: 0.05,
    fill: { color: fill },
    line: { color: fill },
  });
  slide.addText(text, {
    x: x + 0.08,
    y: y + 0.075,
    w: 1.49,
    h: 0.13,
    fontFace: "PingFang SC",
    fontSize: 7,
    bold: true,
    color,
    align: "center",
    margin: 0,
    fit: "shrink",
  });
}

function addCard(slide, x, y, w, h, title, body, accent = C.blue, fill = C.white) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    fill: { color: fill },
    line: { color: "EAECF0", width: 1 },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x,
    y,
    w: 0.08,
    h,
    fill: { color: accent },
    line: { color: accent },
  });
  slide.addText(title, {
    x: x + 0.22,
    y: y + 0.18,
    w: w - 0.35,
    h: 0.22,
    fontFace: "PingFang SC",
    fontSize: 10.5,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  slide.addText(body, {
    x: x + 0.22,
    y: y + 0.52,
    w: w - 0.35,
    h: h - 0.62,
    fontFace: "PingFang SC",
    fontSize: 8.2,
    color: C.muted,
    valign: "top",
    breakLine: false,
    fit: "shrink",
    margin: 0.02,
  });
}

function addEvidenceBox(slide, x, y, w, h, title, body, accent = C.purple) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.06,
    fill: { color: "F8FAFC" },
    line: { color: accent, width: 1 },
  });
  slide.addText(title, {
    x: x + 0.14,
    y: y + 0.12,
    w: w - 0.28,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 7.7,
    bold: true,
    color: accent,
    margin: 0,
    fit: "shrink",
  });
  slide.addText(body, {
    x: x + 0.14,
    y: y + 0.36,
    w: w - 0.28,
    h: h - 0.42,
    fontFace: "PingFang SC",
    fontSize: 7.1,
    color: C.ink,
    valign: "top",
    fit: "shrink",
    margin: 0.01,
    breakLine: false,
  });
}

function addCodeSnippet(slide, x, y, w, h, title, code, accent = C.dark) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.05,
    fill: { color: "111827" },
    line: { color: accent, width: 1 },
  });
  slide.addText(title, {
    x: x + 0.12,
    y: y + 0.11,
    w: w - 0.24,
    h: 0.16,
    fontFace: "PingFang SC",
    fontSize: 6.8,
    bold: true,
    color: "93C5FD",
    margin: 0,
    fit: "shrink",
  });
  slide.addText(code, {
    x: x + 0.12,
    y: y + 0.35,
    w: w - 0.24,
    h: h - 0.42,
    fontFace: "Menlo",
    fontSize: 6.1,
    color: "F9FAFB",
    fit: "shrink",
    valign: "top",
    margin: 0.01,
  });
}

function addNode(slide, id, x, y, w, h, label, fill, line = C.blue, text = C.ink) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.06,
    fill: { color: fill },
    line: { color: line, width: 1 },
  });
  slide.addText(label, {
    x: x + 0.05,
    y: y + 0.09,
    w: w - 0.1,
    h: h - 0.16,
    fontFace: "PingFang SC",
    fontSize: 7.1,
    bold: true,
    color: text,
    align: "center",
    valign: "mid",
    fit: "shrink",
    margin: 0,
  });
  return { id, x, y, w, h };
}

function arrow(slide, from, to, color = C.line) {
  const x1 = from.x + from.w;
  const y1 = from.y + from.h / 2;
  const x2 = to.x;
  const y2 = to.y + to.h / 2;
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color, width: 1.3, beginArrowType: "none", endArrowType: "triangle" },
  });
}

function addLineArrow(slide, x1, y1, x2, y2, color = C.line, dashed = false) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: {
      color,
      width: 1.25,
      beginArrowType: "none",
      endArrowType: "triangle",
      dash: dashed ? "dash" : "solid",
    },
  });
}

function addPlainLine(slide, x1, y1, x2, y2, color = C.line, dashed = false) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: {
      color,
      width: 1.15,
      beginArrowType: "none",
      endArrowType: "none",
      dash: dashed ? "dash" : "solid",
    },
  });
}

function addElbowArrow(slide, points, color = C.line, dashed = false) {
  for (let i = 0; i < points.length - 2; i += 1) {
    addPlainLine(slide, points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], color, dashed);
  }
  const a = points[points.length - 2];
  const b = points[points.length - 1];
  addLineArrow(slide, a[0], a[1], b[0], b[1], color, dashed);
}

function addImageFrame(slide, imagePath, x, y, w, h, caption) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.06,
    fill: { color: C.white },
    line: { color: "EAECF0", width: 1 },
  });
  slide.addImage({ path: imagePath, x: x + 0.16, y: y + 0.12, w: w - 0.32, h: h - 0.48, sizingCrop: false });
  if (caption) {
    slide.addText(caption, {
      x: x + 0.14,
      y: y + h - 0.28,
      w: w - 0.28,
      h: 0.16,
      fontFace: "PingFang SC",
      fontSize: 7.2,
      color: C.muted,
      align: "center",
      margin: 0,
      fit: "shrink",
    });
  }
}

function addBullets(slide, items, x, y, w, h, fontSize = 11) {
  const runs = items.map((item) => ({
    text: item,
    options: { bullet: { type: "ul" }, breakLine: true },
  }));
  slide.addText(runs, {
    x,
    y,
    w,
    h,
    fontFace: "PingFang SC",
    fontSize,
    color: C.ink,
    fit: "shrink",
    margin: 0.02,
    paraSpaceAfterPt: 4,
    breakLine: false,
  });
}

function addNotes(slide, notes) {
  if (typeof slide.addNotes === "function") {
    slide.addNotes(notes);
  }
}

// Slide 1
{
  const slide = pptx.addSlide();
  addBg(slide);
  slide.addText("SVG Icon Agent", {
    x: 0.72,
    y: 0.72,
    w: 7.6,
    h: 0.8,
    fontFace: "Aptos Display",
    fontSize: 38,
    bold: true,
    color: C.ink,
    margin: 0,
  });
  slide.addText("多 Agent 协同的可编辑 SVG 图标生成", {
    x: 0.78,
    y: 1.58,
    w: 7.2,
    h: 0.38,
    fontFace: "PingFang SC",
    fontSize: 17,
    color: C.blue,
    bold: true,
    margin: 0,
  });
  slide.addText("生成式 AI 实践 · Computer Graphics Project 3", {
    x: 0.8,
    y: 2.08,
    w: 6.5,
    h: 0.26,
    fontFace: "PingFang SC",
    fontSize: 10,
    color: C.muted,
    margin: 0,
  });
  addChip(slide, "LLM Agents", 0.8, 2.62, C.blue, C.blue2);
  addChip(slide, "Editable SVG", 2.62, 2.62, C.green, C.green2);
  addChip(slide, "RAG Memory", 4.44, 2.62, C.purple, C.purple2);
  addChip(slide, "Self-Repair", 6.26, 2.62, C.orange, C.orange2);
  slide.addText("Zhao Guanjie 23307130127", {
    x: 0.8,
    y: 5.88,
    w: 4.7,
    h: 0.25,
    fontFace: "PingFang SC",
    fontSize: 10.5,
    color: C.ink,
    margin: 0,
  });
  slide.addText("Code: https://github.com/fwar1nben/CG_PJ", {
    x: 0.8,
    y: 6.22,
    w: 5.6,
    h: 0.22,
    fontFace: "Aptos",
    fontSize: 8.6,
    color: C.muted,
    margin: 0,
  });
  addImageFrame(slide, img("outputs/web/1780456947-99997024/png/refined/a-minimal-rocket-launch-icon.png"), 8.1, 1.0, 1.75, 1.85, "Rocket");
  addImageFrame(slide, img("outputs/web/1780457342-7e0b912c/png/refined/a-cute-gray-cat-smiling.png"), 10.1, 1.0, 1.75, 1.85, "Cat");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/refined/a-steaming-cup-of-coffee.png"), 8.1, 3.25, 1.75, 1.85, "Coffee");
  addImageFrame(slide, img("outputs/web/1780719731-76e64787/png/refined/a-clean-line-icon-of.png"), 10.1, 3.25, 1.75, 1.85, "Cloud");
  addFooter(slide, 1);
  addNotes(slide, "大家好，我汇报的项目是 SVG Icon Agent。它不是普通的文生图项目，而是把短文本描述转成可编辑的 SVG 图标。项目重点放在生成式 AI 和多 Agent 协作：每个命名为 Agent 的组件都调用大模型，本地代码只负责检查、渲染、导出和日志。");
}

// Slide 2
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "问题与动机：图标不是只要“好看”", "普通文生图给的是像素图，课程项目更适合展示可检查、可编辑、可修复的图形生成流程。");
  addCard(slide, 0.75, 1.28, 3.55, 3.75, "普通文生图的限制", "• 输出通常是 raster image\n• 结构不可编辑，难以复用\n• 无法直接检查 XML / viewBox\n• 失败后只能重新采样\n• 难展示 Agent 之间的决策证据", C.red, C.white);
  addCard(slide, 4.85, 1.28, 3.55, 3.75, "选择 SVG 的原因", "• XML + 矢量 primitives\n• 可缩放、可编辑、可 diff\n• 可检查标签、属性和安全性\n• 可转 PNG 预览，保留源 SVG\n• 适合 UI icon 和课程图形约束", C.green, C.white);
  addCard(slide, 8.95, 1.28, 3.55, 3.75, "Agent 化的价值", "• 将创意任务拆为明确职责\n• 多候选 + 多角度 critique\n• Selector 给出选择理由\n• Taxonomy / Router 给出修复路线\n• Web DAG 让过程可展示", C.blue, C.white);
  addEvidenceBox(slide, 1.0, 5.28, 11.4, 0.78, "本项目定位", "不是训练大图像模型，而是实践“LLM Agent 协作 + SVG 规则工具 + 可编辑图形产物”。评分重点可落在生成式 AI workflow、Agent 组织方式、可解释修复和 demo 可复现性。", C.purple);
  addFooter(slide, 2);
  addNotes(slide, "这个项目的动机是：图标生成不只是生成一张好看的图片。对于计算机图形来说，我更希望输出本身是结构化的、可编辑的、可检查的。SVG 正好符合这个目标。相比直接让模型画图，这里把生成拆成多个 Agent：有人负责目标，有人负责规划，有人生成多个候选，有人评价，有人修复。这样可以展示一个完整的生成式 AI 工作流。");
}

// Slide 3
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "项目目标：从一句描述到一套可追踪产物", "输入英文 prompt，输出 SVG、PNG、gallery、metrics 和完整 LLM trace。");
  slide.addShape(pptx.ShapeType.roundRect, { x: 0.8, y: 1.45, w: 4.6, h: 0.75, rectRadius: 0.06, fill: { color: C.white }, line: { color: C.line } });
  slide.addText('Input: "A steaming cup of coffee"', { x: 1.05, y: 1.7, w: 4.1, h: 0.2, fontSize: 11, color: C.ink, fontFace: "Aptos", margin: 0 });
  const n1 = addNode(slide, "p", 5.95, 1.52, 1.5, 0.55, "LLM\nPipeline", C.blue2, C.blue);
  slide.addShape(pptx.ShapeType.line, { x: 5.4, y: 1.82, w: 0.52, h: 0, line: { color: C.line, endArrowType: "triangle", width: 1.3 } });
  slide.addShape(pptx.ShapeType.line, { x: 7.48, y: 1.82, w: 0.62, h: 0, line: { color: C.line, endArrowType: "triangle", width: 1.3 } });
  addCard(slide, 8.18, 1.2, 3.9, 1.25, "Outputs", "selected SVG / baseline SVG / refined SVG / PNG previews / gallery / metrics / trace / raw responses", C.green, C.white);
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/baseline/a-steaming-cup-of-coffee.png"), 1.0, 3.0, 1.6, 1.75, "Baseline: 70 invalid");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/refined/a-steaming-cup-of-coffee.png"), 3.0, 3.0, 1.6, 1.75, "Refined: 95 valid");
  addCard(slide, 5.25, 3.0, 3.0, 1.75, "Web UI", "输入 prompt\n预览 SVG / PNG\n查看 DAG 当前节点\n展开 raw LLM response\n完成后可手动反馈再优化", C.purple, C.white);
  addCard(slide, 8.7, 3.0, 3.0, 1.75, "CLI", "批量 prompts\n手动 --text\ncase-id 筛选\n可调模型、tokens、repair rounds\n支持 single/collaborative ablation", C.orange, C.white);
  addCodeSnippet(slide, 1.05, 5.18, 5.2, 0.98, "输出日志文件", "generation_goal.json\nllm_trace.json\nllm_raw_responses.jsonl\nfailure_taxonomy.json / repair_routes.json", C.blue);
  addEvidenceBox(slide, 6.55, 5.18, 5.55, 0.98, "可追踪性", "PPT 中只展示脱敏后的代表性摘录；完整模型返回保存在 llm_raw_responses.jsonl，便于定位 malformed JSON、空回复、repair 失败等问题。", C.green);
  addFooter(slide, 3);
  addNotes(slide, "系统目标是输入一句英文描述，输出一套完整的图标生成产物。除了 SVG 本身，还会导出 PNG 预览、HTML gallery、metrics、trace 和 raw response。这样答辩时不只是展示最后图片，也可以展示模型到底做了什么、哪个 Agent 参与了、失败是怎么被修复的。");
}

// Slide 4
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "总体架构：不是线性流水线，而是 Agent DAG", "候选生成和双 Critic 存在并行关系；Repair 分支是条件触发。");
  const nodes = {};
  nodes.mem = addNode(slide, "mem", 0.35, 2.85, 1.05, 0.54, "Memory\nTool", C.green2, C.green);
  nodes.goal = addNode(slide, "goal", 1.62, 2.85, 1.05, 0.54, "Goal\nManager", C.blue2, C.blue);
  nodes.rew = addNode(slide, "rew", 2.9, 2.85, 1.1, 0.54, "Prompt\nRewriter", C.blue2, C.blue);
  nodes.plan = addNode(slide, "plan", 4.22, 2.85, 0.96, 0.54, "Planner", C.blue2, C.blue);
  nodes.gen = addNode(slide, "gen", 5.42, 2.85, 1.25, 0.54, "Candidate\nGenerators", C.blue2, C.blue);
  nodes.sem = addNode(slide, "sem", 7.1, 1.72, 1.2, 0.54, "Semantic\nCritic", C.orange2, C.orange);
  nodes.qual = addNode(slide, "qual", 7.1, 3.95, 1.2, 0.54, "SVG Quality\nCritic", C.orange2, C.orange);
  nodes.sel = addNode(slide, "sel", 8.82, 2.85, 1.12, 0.54, "Consensus\nSelector", C.blue2, C.blue);
  nodes.opt = addNode(slide, "opt", 10.18, 2.85, 1.05, 0.54, "SVG\nOptimizer", C.blue2, C.blue);
  nodes.val = addNode(slide, "val", 11.45, 2.85, 0.95, 0.54, "Validator", C.blue2, C.blue);
  nodes.exp = addNode(slide, "exp", 12.55, 2.85, 0.95, 0.54, "Exporter", C.green2, C.green);
  nodes.tax = addNode(slide, "tax", 7.05, 5.22, 1.23, 0.54, "Failure\nTaxonomy", C.orange2, C.orange);
  nodes.rou = addNode(slide, "rou", 8.75, 5.22, 1.18, 0.54, "Repair\nRouter", C.orange2, C.orange);
  nodes.ref = addNode(slide, "ref", 10.35, 5.22, 1.0, 0.54, "Refiner", C.orange2, C.orange);
  nodes.cur = addNode(slide, "cur", 12.55, 4.58, 0.95, 0.54, "Memory\nCurator", C.blue2, C.blue);
  ["mem", "goal", "rew", "plan", "gen"].slice(0, -1).forEach((k, i) => arrow(slide, nodes[k], nodes[["mem", "goal", "rew", "plan", "gen"][i + 1]]));
  addElbowArrow(slide, [[6.67, 3.12], [6.88, 3.12], [6.88, 1.99], [7.1, 1.99]], C.orange);
  addElbowArrow(slide, [[6.67, 3.12], [6.88, 3.12], [6.88, 4.22], [7.1, 4.22]], C.orange);
  addElbowArrow(slide, [[8.3, 1.99], [8.55, 1.99], [8.55, 3.12], [8.82, 3.12]], C.orange);
  addElbowArrow(slide, [[8.3, 4.22], [8.55, 4.22], [8.55, 3.12], [8.82, 3.12]], C.orange);
  arrow(slide, nodes.sel, nodes.opt);
  arrow(slide, nodes.opt, nodes.val);
  arrow(slide, nodes.val, nodes.exp, C.green);
  addElbowArrow(slide, [[11.92, 3.39], [11.92, 4.35], [6.7, 4.35], [6.7, 5.49], [7.05, 5.49]], C.orange, true);
  arrow(slide, nodes.tax, nodes.rou, C.orange);
  arrow(slide, nodes.rou, nodes.ref, C.orange);
  addElbowArrow(slide, [[11.35, 5.49], [12.05, 5.49], [12.05, 3.39]], C.orange, true);
  addElbowArrow(slide, [[13.02, 3.39], [13.02, 4.58]], C.green);
  addChip(slide, "蓝色 = LLM Agent", 0.85, 1.28, C.blue, C.blue2);
  addChip(slide, "绿色 = 本地工具", 2.75, 1.28, C.green, C.green2);
  addChip(slide, "橙色 = 修复/评价", 4.65, 1.28, C.orange, C.orange2);
  addEvidenceBox(slide, 6.65, 1.05, 5.85, 0.58, "依赖关系说明", "Generator 扇出到两个 Critic；Selector 汇总后进入 Optimizer。只有 Validator 判定有阻塞问题时，下方 repair branch 才执行。", C.purple);
  slide.addText("Web 前端会把同一张 DAG 按 waiting / active / done / skipped / error 高亮", {
    x: 0.85,
    y: 6.35,
    w: 11.6,
    h: 0.24,
    fontFace: "PingFang SC",
    fontSize: 10,
    color: C.muted,
    margin: 0,
  });
  addFooter(slide, 4);
  addNotes(slide, "这是系统最核心的一页。这里不是完全线性的流程，而是一个 DAG。前半部分从 memory、goal、rewrite、plan 到 candidate generation。生成多个候选之后，Semantic Critic 和 SVG Quality Critic 从两个角度并行评价，再由 Consensus Selector 汇总。右侧的 Validator 如果发现问题，会触发 Failure Taxonomy、Repair Router 和 Refiner，再回到 Validator。");
}

// Slide 5
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "核心 Agent 职责：把大任务拆成可解释的小任务", "每个 Agent 负责一个语义明确的判断或生成动作。");
  const stages = [
    ["目标与上下文", "Goal Manager\nPrompt Rewriter\nMemory Curator", "输入：prompt + goal + memory\n输出：GenerationGoal、rewritten prompt、可复用经验", C.purple],
    ["图标生成", "Planner\nMulti-Candidate Generator", "输入：rewritten prompt + plan\n输出：3 个不同 SVG draft，全部走 SvgCheckTool", C.blue],
    ["评价与选择", "Semantic Critic\nSVG Quality Critic\nConsensus Selector", "输入：候选 SVG + tool report\n输出：语义分、质量分、winner 与 repair brief", C.orange],
    ["优化与修复", "SVG Optimizer\nValidator\nFailure Taxonomy\nRepair Router\nRefiner", "输入：反馈和失败证据\n输出：optimized baseline、taxonomy、route、refined SVG", C.green],
  ];
  stages.forEach((s, i) => {
    const x = 0.75 + i * 3.1;
    addCard(slide, x, 1.35, 2.65, 4.6, s[0], `${s[1]}\n\n${s[2]}`, s[3], C.white);
  });
  addCodeSnippet(slide, 1.05, 5.86, 11.2, 0.55, "边界原则", "Agent = LLM call with explicit role; Tool = deterministic SVG parse / safety check / render / export. No local SVG template fallback.", C.dark);
  slide.addText("关键边界：Agent = 调用 LLM；Tool = 本地确定性检查/渲染/导出", {
    x: 1.05,
    y: 6.48,
    w: 11.2,
    h: 0.32,
    fontFace: "PingFang SC",
    fontSize: 13,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  addFooter(slide, 5);
  addNotes(slide, "这一页解释为什么叫多 Agent。每个 Agent 的职责都很窄，比如 Goal Manager 只负责把目标和验收标准写清楚，Critic 只负责评价，Router 只负责把问题转成修复策略。这里我特别区分 Agent 和 Tool：Agent 必须调用大模型；本地 XML 检查和 PNG 导出只是工具。这样项目主体仍然是生成式 AI，而不是本地规则模板。");
}

// Slide 6
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "协同生成：多候选 + 双 Critic + 共识选择", "同一个 prompt 不只生成一个 SVG，而是让模型团队先竞争再优化。");
  addImageFrame(slide, img("outputs/web/1780456947-99997024/png/refined/a-minimal-rocket-launch-icon.png"), 0.72, 1.28, 1.3, 1.5, "Final rocket");
  addCodeSnippet(slide, 0.58, 3.1, 2.3, 1.05, "Prompt Rewriter 原始摘录", "A minimal, upright rocket icon\ncentered on a 256x256 canvas...\ndynamic, layered flame...", C.blue);
  const c1 = addNode(slide, "c1", 3.35, 1.25, 1.42, 0.52, "Candidate 1\nTool 100", C.blue2, C.blue);
  const c2 = addNode(slide, "c2", 3.35, 2.25, 1.42, 0.52, "Candidate 2\nTool 100", C.blue2, C.blue);
  const c3 = addNode(slide, "c3", 3.35, 3.25, 1.42, 0.52, "Candidate 3\nTool 100", C.blue2, C.blue);
  const hub = addNode(slide, "hub", 5.35, 2.25, 0.75, 0.52, "score\nfan-out", "F8FAFC", C.line, C.muted);
  const sem = addNode(slide, "sem", 6.75, 1.55, 1.75, 0.64, "Semantic Critic\n85 / 95 / 90", C.orange2, C.orange);
  const qual = addNode(slide, "qual", 6.75, 3.0, 1.75, 0.64, "SVG Quality Critic\n85 / 95 / 90", C.orange2, C.orange);
  const sel = addNode(slide, "sel", 9.2, 2.25, 1.8, 0.68, "Consensus Selector\nWinner: Candidate 2", C.green2, C.green);
  const opt = addNode(slide, "opt", 11.55, 2.25, 1.3, 0.68, "SVG\nOptimizer", C.purple2, C.purple);
  [c1, c2, c3].forEach((c) => addElbowArrow(slide, [[c.x + c.w, c.y + c.h / 2], [5.05, c.y + c.h / 2], [5.05, 2.51], [5.35, 2.51]], C.line));
  addElbowArrow(slide, [[6.1, 2.51], [6.38, 2.51], [6.38, 1.87], [6.75, 1.87]], C.orange);
  addElbowArrow(slide, [[6.1, 2.51], [6.38, 2.51], [6.38, 3.32], [6.75, 3.32]], C.orange);
  addElbowArrow(slide, [[8.5, 1.87], [8.82, 1.87], [8.82, 2.59], [9.2, 2.59]], C.orange);
  addElbowArrow(slide, [[8.5, 3.32], [8.82, 3.32], [8.82, 2.59], [9.2, 2.59]], C.orange);
  arrow(slide, sel, opt, C.green);
  addCodeSnippet(slide, 3.22, 4.6, 4.7, 0.95, "Selector 原始摘录", "Candidate-2 has the highest semantic\nand SVG quality scores (95 each),\nwith a strong rocket shape...", C.green);
  addEvidenceBox(slide, 8.25, 4.6, 4.1, 0.95, "为什么这是协同？", "三个候选不是平均投票，而是由两个 Critic 给出可记录分数和理由，再由 Selector 写出 winner rationale 与 repair brief。", C.purple);
  addFooter(slide, 6);
  addNotes(slide, "协同生成这一页用 rocket run 举例。模型先生成三个候选，三个候选都通过了本地工具检查。这里我放了脱敏日志里的两段摘录：Prompt Rewriter 把原始 prompt 扩写成 256x256、居中火箭、分层动态火焰；Selector 的原始输出说明 candidate 2 同时有最高语义分和 SVG 质量分。这个过程让选择有证据，而不是随机取第一张。");
}

// Slide 7
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "自我修复：把失败拆成 taxonomy 和 route", "真实 coffee 案例：baseline 70 invalid，经一轮修复到 refined 95 valid。");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/baseline/a-steaming-cup-of-coffee.png"), 0.65, 1.25, 1.45, 1.65, "Baseline: 70 invalid");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/refined/a-steaming-cup-of-coffee.png"), 11.2, 1.25, 1.45, 1.65, "Refined: 95 valid");
  const v = addNode(slide, "v", 2.55, 1.42, 1.35, 0.6, "Validator\ninvalid", C.red2, C.red);
  const t = addNode(slide, "t", 4.45, 1.42, 1.55, 0.6, "Failure Taxonomy\n分类根因", C.orange2, C.orange);
  const r = addNode(slide, "r", 6.55, 1.42, 1.45, 0.6, "Repair Router\n选择路线", C.orange2, C.orange);
  const f = addNode(slide, "f", 8.55, 1.42, 1.25, 0.6, "Refiner\n完整 SVG", C.green2, C.green);
  const ok = addNode(slide, "ok", 10.15, 1.42, 0.78, 0.6, "valid", C.green2, C.green);
  arrow(slide, v, t, C.orange);
  arrow(slide, t, r, C.orange);
  arrow(slide, r, f, C.orange);
  arrow(slide, f, ok, C.green);
  addElbowArrow(slide, [[9.18, 2.02], [9.18, 2.92], [3.22, 2.92], [3.22, 2.02]], C.orange, true);
  slide.addText("re-validate", { x: 5.6, y: 2.72, w: 1.2, h: 0.18, fontFace: "Aptos", fontSize: 7, color: C.orange, align: "center", margin: 0 });
  addCodeSnippet(slide, 0.95, 3.55, 3.7, 1.35, "failure_taxonomy.json 摘录", 'failure_types: [\n  "semantic_mismatch",\n  "constraint_violation"\n]\nroot_cause: blue cup != coffee palette', C.orange);
  addCodeSnippet(slide, 4.95, 3.55, 3.7, 1.35, "repair_routes.json 摘录", 'route: "semantic_recompose"\nordered_actions:\n- replace #4a90d9 -> #6F4E37\n- remove opacity from steam lines', C.purple);
  addCard(slide, 8.95, 3.55, 3.25, 1.35, "Result", "1 repair round\nbaseline_valid 0 -> refined_valid 1\nscore 70 -> 95\n完整 SVG 重新导出 PNG", C.green, C.white);
  addEvidenceBox(slide, 1.0, 5.45, 11.2, 0.55, "日志证据说明", "这些片段来自脱敏后的 failure_taxonomy.json 与 repair_routes.json；完整模型调用、usage 和响应保存在 llm_raw_responses.jsonl / llm_trace.json。", C.blue);
  addFooter(slide, 7);
  addNotes(slide, "自我修复机制用 coffee 案例说明。优化后的 baseline 因为颜色不符合计划，被 Validator 判为 invalid，分数 70。PPT 中放了日志摘录：Failure Taxonomy 把问题归类为 semantic mismatch 和 constraint violation；Repair Router 选择 semantic_recompose，并给出替换颜色、移除 opacity 的 ordered actions。Refiner 根据这个 brief 返回完整 SVG，然后 re-validate，最后分数提升到 95。");
}

// Slide 8
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "目标管理与记忆：让系统从历史经验中生成", "RAG 记忆来自本地历史 runs，不使用外部数据集，也不保存 API key。");
  addCard(slide, 0.9, 1.25, 3.45, 3.05, "GenerationGoal", "objective\nvisual_requirements\nconstraints\nacceptance_criteria\nstyle_preferences\navoid_patterns\n\n作用：把“好图标”变成可验证标准", C.blue, C.white);
  addCard(slide, 4.95, 1.25, 3.45, 3.05, "Memory Retrieval", "检索相似历史 runs\n读取 success_patterns\n读取 failure_patterns\n读取 user_feedback\n返回 top-k snippets\n\n作用：让新 prompt 继承历史经验", C.purple, C.white);
  addCard(slide, 9.0, 1.25, 3.45, 3.05, "Memory Curator", "run 结束后总结经验\n保存可复用设计策略\n保存失败模式\n记录 score / tags\n\n作用：形成轻量长期记忆", C.green, C.white);
  addCodeSnippet(slide, 1.0, 4.62, 5.4, 0.9, "GenerationGoal 摘录", "objective: 256x256 rocket launch icon\nacceptance: centered rocket, layered flame\navoid: static-uniform flame shapes", C.blue);
  addCodeSnippet(slide, 6.75, 4.62, 5.4, 0.9, "Memory 摘录", "success_patterns:\n- centered-upright-rocket\n- layered-sweeping-flame-curves\nuser_feedback: simplify-window", C.purple);
  slide.addText("例：rocket 相关记忆会提醒“居中火箭 + 分层扫掠火焰 + 简化圆形窗口”。", {
    x: 1.3,
    y: 6.08,
    w: 10.7,
    h: 0.28,
    fontFace: "PingFang SC",
    fontSize: 12,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  addFooter(slide, 8);
  addNotes(slide, "这一页是目标管理和记忆。Goal Manager 把 prompt 变成显式目标和验收标准，避免模型只凭一句话自由发挥。Memory Retrieval 从本地历史运行中找相似案例，比如 rocket prompt 会检索到以前的成功经验：火箭要居中，火焰要分层扫掠，窗口最好简化成单个圆。Memory Curator 在每次运行结束后再把经验写回 memory index。");
}

// Slide 9
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实验结果：报告快照中的 Web UI 运行", "4 个主要 Web run：12 candidates，4 selected winners，final validity 100%。");
  addImageFrame(slide, img("outputs/web/1780456947-99997024/png/refined/a-minimal-rocket-launch-icon.png"), 0.75, 1.25, 1.35, 1.52, "Rocket 95");
  addImageFrame(slide, img("outputs/web/1780457165-766f9cd2/png/refined/a-minimal-white-rocket-launch.png"), 2.25, 1.25, 1.35, 1.52, "White rocket 100");
  addImageFrame(slide, img("outputs/web/1780457342-7e0b912c/png/refined/a-cute-gray-cat-smiling.png"), 3.75, 1.25, 1.35, 1.52, "Cat 100");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/refined/a-steaming-cup-of-coffee.png"), 5.25, 1.25, 1.35, 1.52, "Coffee 95");
  addCard(slide, 7.15, 1.18, 5.25, 1.9, "主结果", "Baseline valid: 3 / 4\nRefined valid: 4 / 4\nAverage score: 91.25 -> 97.50\nMax repair rounds: 1\nFinal validity: 100%", C.green, C.white);
  addCard(slide, 0.85, 3.55, 3.45, 1.72, "候选生成", "每个 prompt 生成 3 个候选\n共 12 个 candidate SVG\nSelector 选出 4 个 winner\n每个 winner 都有 rationale", C.blue, C.white);
  addCard(slide, 4.95, 3.55, 3.45, 1.72, "修复收益", "Coffee case: 70 -> 95\n后续 dog case: 65 -> 100\nCloud 多轮 repair 提升\n说明 repair loop 能处理真实失败", C.orange, C.white);
  addCard(slide, 9.05, 3.55, 3.0, 1.72, "可展示性", "SVG / PNG / gallery\nllm_trace.json\nllm_raw_responses.jsonl\nDAG runtime states", C.purple, C.white);
  addCodeSnippet(slide, 1.05, 5.55, 11.2, 0.48, "统计口径", "Report snapshot = 4 main Web runs; later outputs/web runs are used only as demo evidence, not mixed into the formal aggregate.", C.dark);
  slide.addText("说明：正式统计采用报告中的 4-run 快照；后续 outputs/web 中还有更多运行，可作为 demo 素材。", {
    x: 1.0,
    y: 6.02,
    w: 11.3,
    h: 0.24,
    fontFace: "PingFang SC",
    fontSize: 9,
    color: C.muted,
    align: "center",
    margin: 0,
  });
  addFooter(slide, 9);
  addNotes(slide, "实验结果按报告快照统计。四个主要 Web run 一共生成十二个候选 SVG，选出四个 winner。优化后的 baseline 中三分之四有效，经过修复后的 refined 四分之四有效，平均分从 91.25 提升到 97.50。其中 coffee 是主要修复案例，后续 dog 和 cloud 运行也显示修复循环能继续发挥作用。");
}

// Slide 10
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "总结：可编辑图形 + 可解释 Agent 协作", "项目价值不只是生成图标，而是把生成、评价、修复、记忆做成可追踪系统。");
  addCard(slide, 0.85, 1.25, 3.65, 4.1, "创新点", "• LLM-backed Agent DAG\n• 多候选竞争 + 双 Critic\n• Failure taxonomy + Repair router\n• 本地历史 RAG memory\n• Web runtime 可视化\n• 脱敏 raw response 支持 debug", C.blue, C.white);
  addCard(slide, 4.85, 1.25, 3.65, 4.1, "局限性", "• 免费模型速度和稳定性有限\n• SVG renderer 支持实用子集\n• 视觉质量评价仍偏规则化\n• 实验规模还可以扩大\n• raw LLM 输出偶尔 malformed，需要 retry", C.orange, C.white);
  addCard(slide, 8.85, 1.25, 3.65, 4.1, "下一步", "• 更大 prompt set\n• 人类偏好评价\n• 更强 perceptual critic\n• 消融实验：single vs collaborative\n• 更细的 SVG grammar\n• 对 failure route 做量化评估", C.green, C.white);
  slide.addText("Takeaway: 这是一个面向 SVG 图标生成的“LLM Agent 协作 + 规则工具保底 + 记忆自改进”系统。", {
    x: 1.1,
    y: 6.0,
    w: 11.1,
    h: 0.36,
    fontFace: "PingFang SC",
    fontSize: 13.5,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  addFooter(slide, 10);
  addNotes(slide, "最后总结一下。这个项目的核心创新是把 SVG 图标生成拆成一个可解释的多 Agent 系统：有目标管理，有候选竞争，有双 Critic，有修复路线，也有本地记忆。局限是目前模型速度、稳定性和实验规模还有限，视觉评价也还有提升空间。后续可以做更完整的 ablation 和人类偏好评价。");
}

pptx.writeFile({ fileName: OUT });
