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
  addCard(slide, 0.75, 1.42, 3.55, 4.45, "普通文生图的限制", "• 输出通常是 raster image\n• 结构不可编辑\n• 很难做安全检查\n• 失败原因不可追踪\n• 不适合展示图形规则约束", C.red, C.white);
  addCard(slide, 4.85, 1.42, 3.55, 4.45, "选择 SVG 的原因", "• XML + 矢量 primitives\n• 可缩放、可编辑\n• 可检查 viewBox / 标签 / 属性\n• 可转 PNG 预览\n• 适合 UI icon 场景", C.green, C.white);
  addCard(slide, 8.95, 1.42, 3.55, 4.45, "Agent 化的价值", "• 把创意生成拆成多个职责\n• 多候选 + 多角度 critique\n• 显式 diagnosis 和 repair route\n• 运行过程可视化\n• 结果与失败都可复盘", C.blue, C.white);
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
  addCard(slide, 5.25, 3.0, 3.0, 1.75, "Web UI", "输入 prompt\n预览 SVG / PNG\n查看 DAG 当前节点\n展开 raw LLM response", C.purple, C.white);
  addCard(slide, 8.7, 3.0, 3.0, 1.75, "CLI", "批量 prompts\n手动 --text\ncase-id 筛选\n可调模型、tokens、repair rounds", C.orange, C.white);
  addBullets(slide, ["所有 Agent 使用 LLM，不再用本地模板冒充生成", "本地工具只做机械检查、渲染和文件导出", "失败时记录原因，不静默切回规则 fallback"], 1.05, 5.35, 11.2, 0.78, 10);
  addFooter(slide, 3);
  addNotes(slide, "系统目标是输入一句英文描述，输出一套完整的图标生成产物。除了 SVG 本身，还会导出 PNG 预览、HTML gallery、metrics、trace 和 raw response。这样答辩时不只是展示最后图片，也可以展示模型到底做了什么、哪个 Agent 参与了、失败是怎么被修复的。");
}

// Slide 4
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "总体架构：不是线性流水线，而是 Agent DAG", "候选生成和双 Critic 存在并行关系；Repair 分支是条件触发。");
  const nodes = {};
  nodes.mem = addNode(slide, "mem", 0.45, 3.0, 1.15, 0.55, "Memory\nTool", C.green2, C.green);
  nodes.goal = addNode(slide, "goal", 1.85, 3.0, 1.15, 0.55, "Goal\nManager", C.blue2, C.blue);
  nodes.rew = addNode(slide, "rew", 3.25, 3.0, 1.15, 0.55, "Prompt\nRewriter", C.blue2, C.blue);
  nodes.plan = addNode(slide, "plan", 4.65, 3.0, 1.15, 0.55, "Planner", C.blue2, C.blue);
  nodes.gen = addNode(slide, "gen", 6.05, 3.0, 1.3, 0.55, "Candidate\nGenerators", C.blue2, C.blue);
  nodes.sem = addNode(slide, "sem", 7.75, 2.2, 1.2, 0.55, "Semantic\nCritic", C.orange2, C.orange);
  nodes.qual = addNode(slide, "qual", 7.75, 3.8, 1.2, 0.55, "SVG Quality\nCritic", C.orange2, C.orange);
  nodes.sel = addNode(slide, "sel", 9.35, 3.0, 1.15, 0.55, "Consensus\nSelector", C.blue2, C.blue);
  nodes.opt = addNode(slide, "opt", 10.75, 3.0, 1.15, 0.55, "SVG\nOptimizer", C.blue2, C.blue);
  nodes.val = addNode(slide, "val", 12.05, 3.0, 1.0, 0.55, "Validator", C.blue2, C.blue);
  nodes.tax = addNode(slide, "tax", 9.35, 5.1, 1.15, 0.55, "Failure\nTaxonomy", C.orange2, C.orange);
  nodes.rou = addNode(slide, "rou", 10.75, 5.1, 1.15, 0.55, "Repair\nRouter", C.orange2, C.orange);
  nodes.ref = addNode(slide, "ref", 12.05, 5.1, 1.0, 0.55, "Refiner", C.orange2, C.orange);
  nodes.exp = addNode(slide, "exp", 11.1, 1.2, 1.1, 0.55, "Exporter", C.green2, C.green);
  nodes.cur = addNode(slide, "cur", 12.55, 1.2, 1.05, 0.55, "Memory\nCurator", C.blue2, C.blue);
  ["mem","goal","rew","plan","gen"].slice(0,-1).forEach((k,i)=>arrow(slide,nodes[k],nodes[["mem","goal","rew","plan","gen"][i+1]]));
  arrow(slide, nodes.gen, nodes.sem, C.orange);
  arrow(slide, nodes.gen, nodes.qual, C.orange);
  arrow(slide, nodes.sem, nodes.sel, C.orange);
  arrow(slide, nodes.qual, nodes.sel, C.orange);
  arrow(slide, nodes.sel, nodes.opt);
  arrow(slide, nodes.opt, nodes.val);
  slide.addShape(pptx.ShapeType.line, { x: 12.55, y: 3.0, w: -2.05, h: 2.1, line: { color: C.orange, endArrowType: "triangle", width: 1.3 } });
  arrow(slide, nodes.tax, nodes.rou, C.orange);
  arrow(slide, nodes.rou, nodes.ref, C.orange);
  slide.addShape(pptx.ShapeType.line, { x: 12.52, y: 5.1, w: 0, h: -1.55, line: { color: C.orange, endArrowType: "triangle", width: 1.3 } });
  slide.addShape(pptx.ShapeType.line, { x: 12.55, y: 3.0, w: -0.45, h: -1.25, line: { color: C.green, endArrowType: "triangle", width: 1.3 } });
  arrow(slide, nodes.exp, nodes.cur, C.green);
  addChip(slide, "蓝色 = LLM Agent", 0.85, 1.28, C.blue, C.blue2);
  addChip(slide, "绿色 = 本地工具", 2.75, 1.28, C.green, C.green2);
  addChip(slide, "橙色 = 修复/评价", 4.65, 1.28, C.orange, C.orange2);
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
    ["目标与上下文", "Goal Manager\nPrompt Rewriter\nMemory Curator", "把用户输入、历史记忆和验收标准显式化", C.purple],
    ["图标生成", "Planner\nMulti-Candidate Generator", "从意图到结构化 icon plan，再生成多个 SVG draft", C.blue],
    ["评价与选择", "Semantic Critic\nSVG Quality Critic\nConsensus Selector", "分别看语义、SVG 质量，再给出 winner 和 repair brief", C.orange],
    ["优化与修复", "SVG Optimizer\nValidator\nFailure Taxonomy\nRepair Router\nRefiner", "把反馈转化为完整 SVG 修改，并形成可审计修复路线", C.green],
  ];
  stages.forEach((s, i) => {
    const x = 0.75 + i * 3.1;
    addCard(slide, x, 1.35, 2.65, 4.6, s[0], `${s[1]}\n\n${s[2]}`, s[3], C.white);
  });
  slide.addText("关键边界：Agent = 调用 LLM；Tool = 本地确定性检查/渲染/导出", {
    x: 1.05,
    y: 6.25,
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
  addImageFrame(slide, img("outputs/web/1780456947-99997024/png/refined/a-minimal-rocket-launch-icon.png"), 0.85, 1.25, 1.45, 1.6, "Final");
  slide.addText("Prompt\nminimal rocket launch icon", { x: 0.65, y: 3.18, w: 1.9, h: 0.45, fontFace: "Aptos", fontSize: 8.5, color: C.muted, align: "center", margin: 0, fit: "shrink" });
  const c1 = addNode(slide, "c1", 3.1, 1.25, 1.55, 0.55, "Candidate 1\nTool 100", C.blue2, C.blue);
  const c2 = addNode(slide, "c2", 3.1, 2.35, 1.55, 0.55, "Candidate 2\nTool 100", C.blue2, C.blue);
  const c3 = addNode(slide, "c3", 3.1, 3.45, 1.55, 0.55, "Candidate 3\nTool 100", C.blue2, C.blue);
  const sem = addNode(slide, "sem", 5.7, 1.65, 1.75, 0.7, "Semantic Critic\n85 / 92 / 70", C.orange2, C.orange);
  const qual = addNode(slide, "qual", 5.7, 3.05, 1.75, 0.7, "SVG Quality Critic\n90 / 88 / 95", C.orange2, C.orange);
  const sel = addNode(slide, "sel", 8.35, 2.35, 1.8, 0.72, "Consensus Selector\nWinner: Candidate 2", C.green2, C.green);
  const opt = addNode(slide, "opt", 10.9, 2.35, 1.55, 0.72, "SVG Optimizer\n修正细节", C.purple2, C.purple);
  [c1,c2,c3].forEach(c => {
    arrow(slide,c,sem,C.orange);
    arrow(slide,c,qual,C.orange);
  });
  arrow(slide,sem,sel,C.orange);
  arrow(slide,qual,sel,C.orange);
  arrow(slide,sel,opt,C.green);
  slide.addText("Selector rationale：Candidate 2 在语义清晰度、动态火焰和小尺寸可读性之间最平衡。", {
    x: 2.9,
    y: 5.35,
    w: 8.2,
    h: 0.32,
    fontFace: "PingFang SC",
    fontSize: 10,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  slide.addText("这里的创新点不是“多调用几次模型”，而是让不同 Agent 给出可比较、可记录的理由。", {
    x: 2.2,
    y: 5.92,
    w: 9.8,
    h: 0.26,
    fontFace: "PingFang SC",
    fontSize: 9.5,
    color: C.muted,
    align: "center",
    margin: 0,
  });
  addFooter(slide, 6);
  addNotes(slide, "协同生成这一页用 rocket run 举例。模型先生成三个候选，三个候选都通过了本地工具检查，但语义和 SVG 质量分不同。Semantic Critic 更喜欢 candidate 2，SVG Quality Critic 更喜欢 candidate 3。Selector 最后选择 candidate 2，因为它在 prompt 对齐、动态火焰和小尺寸可读性上最平衡。这个过程让选择有理由，而不是随机取第一张。");
}

// Slide 7
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "自我修复：把失败拆成 taxonomy 和 route", "真实 coffee 案例：baseline 70 invalid，经一轮修复到 refined 95 valid。");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/baseline/a-steaming-cup-of-coffee.png"), 0.95, 1.35, 1.7, 1.95, "Baseline: 70 / invalid");
  addImageFrame(slide, img("outputs/web/1780459805-0420b72d/png/refined/a-steaming-cup-of-coffee.png"), 10.75, 1.35, 1.7, 1.95, "Refined: 95 / valid");
  const v = addNode(slide, "v", 3.1, 1.52, 1.5, 0.62, "Validator\n发现问题", C.red2, C.red);
  const t = addNode(slide, "t", 5.1, 1.52, 1.65, 0.62, "Failure Taxonomy\n分类根因", C.orange2, C.orange);
  const r = addNode(slide, "r", 7.25, 1.52, 1.55, 0.62, "Repair Router\n选择路线", C.orange2, C.orange);
  const f = addNode(slide, "f", 9.3, 1.52, 1.25, 0.62, "Refiner\n重写 SVG", C.green2, C.green);
  arrow(slide,v,t,C.orange);
  arrow(slide,t,r,C.orange);
  arrow(slide,r,f,C.orange);
  slide.addShape(pptx.ShapeType.line, { x: 9.92, y: 2.14, w: -6.05, h: 1.65, line: { color: C.orange, width: 1.2, endArrowType: "triangle", dash: "dash" } });
  addCard(slide, 1.05, 4.0, 3.1, 1.45, "Taxonomy", "semantic_mismatch\nconstraint_violation\n\n根因：蓝色杯体不符合咖啡色 palette；steam opacity 违反约束", C.orange, C.white);
  addCard(slide, 4.55, 4.0, 3.1, 1.45, "Route", "semantic_recompose\n\n策略：替换为 brown / cream palette，移除 opacity，更新 metadata", C.purple, C.white);
  addCard(slide, 8.05, 4.0, 3.1, 1.45, "Result", "1 repair round\nbaseline_valid 0 -> refined_valid 1\nscore 70 -> 95", C.green, C.white);
  addFooter(slide, 7);
  addNotes(slide, "自我修复机制用 coffee 案例说明。优化后的 baseline 因为颜色不符合计划，被 Validator 判为 invalid，分数 70。Failure Taxonomy 把问题归类为 semantic mismatch 和 constraint violation，Repair Router 选择 semantic recompose 路线，要求把蓝色杯体替换回咖啡色 palette，并去掉 opacity。Refiner 根据这个 brief 返回完整 SVG，最后验证分数提升到 95。");
}

// Slide 8
{
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "目标管理与记忆：让系统从历史经验中生成", "RAG 记忆来自本地历史 runs，不使用外部数据集，也不保存 API key。");
  addCard(slide, 0.9, 1.35, 3.45, 4.25, "GenerationGoal", "objective\nvisual_requirements\nconstraints\nacceptance_criteria\nstyle_preferences\navoid_patterns", C.blue, C.white);
  addCard(slide, 4.95, 1.35, 3.45, 4.25, "Memory Retrieval", "检索相似历史 runs\n读取 success_patterns\n读取 failure_patterns\n读取 user_feedback\n返回 top-k snippets", C.purple, C.white);
  addCard(slide, 9.0, 1.35, 3.45, 4.25, "Memory Curator", "run 结束后总结经验\n保存可复用设计策略\n保存失败模式\n为下一次 prompt 提供上下文", C.green, C.white);
  slide.addText("例：rocket 相关记忆会提醒“居中火箭 + 分层扫掠火焰 + 简化圆形窗口”。", {
    x: 1.3,
    y: 6.05,
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
  addCard(slide, 7.15, 1.18, 5.25, 1.9, "主结果", "Baseline valid: 3 / 4\nRefined valid: 4 / 4\nAverage score: 91.25 -> 97.50\nMax repair rounds: 1", C.green, C.white);
  addCard(slide, 0.85, 3.65, 3.45, 1.55, "候选生成", "每个 prompt 生成 3 个候选\n共 12 个 candidate SVG\nSelector 选出 4 个 winner", C.blue, C.white);
  addCard(slide, 4.95, 3.65, 3.45, 1.55, "修复收益", "Coffee case: 70 -> 95\n后续 dog case: 65 -> 100\n说明 repair loop 能处理真实失败", C.orange, C.white);
  addCard(slide, 9.05, 3.65, 3.0, 1.55, "可展示性", "SVG / PNG / gallery\nllm_trace.json\nraw responses\nDAG runtime states", C.purple, C.white);
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
  addCard(slide, 0.85, 1.35, 3.65, 4.0, "创新点", "• LLM-backed Agent DAG\n• 多候选竞争 + 双 Critic\n• Failure taxonomy + Repair router\n• 本地历史 RAG memory\n• Web runtime 可视化", C.blue, C.white);
  addCard(slide, 4.85, 1.35, 3.65, 4.0, "局限性", "• 免费模型速度和稳定性有限\n• SVG renderer 支持的是实用子集\n• 视觉质量评价仍偏规则化\n• 实验规模还可以扩大", C.orange, C.white);
  addCard(slide, 8.85, 1.35, 3.65, 4.0, "下一步", "• 更大 prompt set\n• 人类偏好评价\n• 更强 perceptual critic\n• 消融实验：single vs collaborative\n• 更细的 SVG grammar", C.green, C.white);
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
