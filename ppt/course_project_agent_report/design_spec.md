# SVG Icon Agent 课程项目汇报 - Design Spec

> Human-readable design narrative - rationale, audience, style, color choices, content outline.
> Machine-readable execution contract: `spec_lock.md`. Executor re-reads `spec_lock.md` before every SVG page.

## I. Project Information

| Item | Value |
| ---- | ----- |
| **Project Name** | SVG Icon Agent 课程项目汇报 |
| **Canvas Format** | PPT 16:9 (1280x720) |
| **Page Count** | 10 |
| **Design Style** | B) General Consulting + 技术系统汇报 / 信息密集但克制 |
| **Target Audience** | 计算机图形学课程教师与同学 |
| **Use Case** | 10 分钟中文课程项目汇报 |
| **Created Date** | 2026-06-07 |

---

## II. Canvas Specification

| Property | Value |
| -------- | ----- |
| **Format** | PPT 16:9 |
| **Dimensions** | 1280x720 |
| **viewBox** | `0 0 1280 720` |
| **Margins** | left/right 56px, top 46px, bottom 38px |
| **Content Area** | 1168x636 |

---

## III. Visual Theme

### Theme Style

- **Style**: 技术系统汇报
- **Theme**: Light theme
- **Tone**: 清晰、工程化、可追踪；避免营销感和空泛升华

### Color Scheme

| Role | HEX | Purpose |
| ---- | --- | ------- |
| **Background** | `#F8FAFC` | 全局浅底 |
| **Secondary bg** | `#FFFFFF` | 信息面板与图标卡片 |
| **Primary** | `#1D4ED8` | 标题、主流程、关键节点 |
| **Accent** | `#0F766E` | RAG、记忆、正向指标 |
| **Secondary accent** | `#F59E0B` | 选择、优化、人工反馈 |
| **Body text** | `#111827` | 正文 |
| **Secondary text** | `#64748B` | 注释、页脚 |
| **Tertiary text** | `#94A3B8` | 弱化标签 |
| **Border/divider** | `#CBD5E1` | 分隔线与面板边框 |
| **Success** | `#16A34A` | 通过、有效 |
| **Warning** | `#DC2626` | 失败、修复入口 |
| **Muted blue** | `#DBEAFE` | 浅色节点底 |
| **Muted teal** | `#CCFBF1` | 记忆/工具底 |
| **Muted amber** | `#FEF3C7` | 选择/优化底 |
| **Muted red** | `#FEE2E2` | 失败/修复底 |

---

## IV. Typography System

### Font Plan

**Typography direction**: CJK-first technical sans, with monospace for code paths and JSON artifacts.

| Role | Chinese | English | Fallback tail |
| ---- | ------- | ------- | ------------- |
| **Title** | `"Microsoft YaHei", "PingFang SC"` | `Arial` | `sans-serif` |
| **Body** | `"Microsoft YaHei", "PingFang SC"` | `Arial` | `sans-serif` |
| **Emphasis** | `"Microsoft YaHei", "PingFang SC"` | `Arial` | `sans-serif` |
| **Code** | - | `Consolas, "Courier New"` | `monospace` |

**Per-role font stacks**

- Title: `"Microsoft YaHei", "PingFang SC", Arial, sans-serif`
- Body: `"Microsoft YaHei", "PingFang SC", Arial, sans-serif`
- Emphasis: `"Microsoft YaHei", "PingFang SC", Arial, sans-serif`
- Code: `Consolas, "Courier New", monospace`

### Font Size Hierarchy

**Baseline**: Body font size = 20px.

| Purpose | Size | Weight |
| ------- | ---- | ------ |
| Cover title | 68px | 800 |
| Chapter / section opener | 44px | 800 |
| Page title | 34-38px | 800 |
| Hero number | 44px | 800 |
| Subtitle | 24-28px | 600 |
| Body content | 20px | 400 |
| Annotation / caption | 14-16px | 400 |
| Page number / footnote | 12px | 400 |

Formula rendering policy: `text-only`. The deck contains no complex formulas; keeping text editable is preferred.

---

## V. Layout Principles

### Page Structure

- **Header area**: 46-94px. Title on the left; short page tag or section label on the right.
- **Content area**: 560-600px. Use native SVG diagrams, metric panels, compact callouts, and selected generated icon images.
- **Footer area**: 26-38px. Slide number and concise source/file reference when useful.

### Layout Pattern Library

- Cover: large title + compact project metadata + selected generated icon strip.
- Architecture pages: left-to-right pipeline and feedback loop diagrams, using color-coded node groups.
- Evidence pages: dense panels, small metric blocks, selected examples; one assertion per page.
- Results page: numbers first, then caveat that current samples are Web runs, not a single full batch.

### Spacing Specification

| Element | Current Project |
| ------- | --------------- |
| Safe margin from canvas edge | 56px |
| Content block gap | 28px |
| Icon-text gap | 10px |
| Card gap | 20px |
| Card padding | 22px |
| Card border radius | 8px |
| Diagram node radius | 10px |

---

## VI. Icon Usage Specification

### Source

- **Built-in icon library**: `tabler-outline`
- **Stroke width**: 2
- **Usage method**: SVG placeholder `<use data-icon="tabler-outline/icon-name" .../>`

### Recommended Icon List

| Purpose | Icon Path | Page |
| ------- | --------- | ---- |
| 目标管理 | `tabler-outline/target` | P04, P05 |
| 记忆检索 / RAG | `tabler-outline/database` | P04, P05 |
| 提示改写 | `tabler-outline/wand` | P04, P05 |
| 规划 | `tabler-outline/route` | P04 |
| 候选生成 | `tabler-outline/layout` | P04, P06 |
| 语义/质量评审 | `tabler-outline/search` | P04, P06 |
| 共识选择 | `tabler-outline/check` | P06 |
| 优化 | `tabler-outline/tools` | P06, P07 |
| 验证 | `tabler-outline/shield` | P07 |
| 失败修复 | `tabler-outline/alert-triangle` | P07 |
| 分支回路 | `tabler-outline/git-branch` | P07 |
| 导出 | `tabler-outline/file-export` | P08 |
| 实验指标 | `tabler-outline/chart-bar` | P09 |
| 生成样例 | `tabler-outline/rocket` | P08 |

---

## VII. Visualization Reference List

No external chart template is locked. All diagrams are native SVG:

| Page | Visualization | Purpose |
| ---- | ------------- | ------- |
| P04 | RAG + multi-agent pipeline diagram | 解释从历史记忆、目标管理到生成/验证/修复/记忆沉淀的全流程 |
| P06 | Candidate-Critic-Selector diagram | 解释为什么不是单次生成，而是候选竞争和双路评审 |
| P07 | Validation and repair loop | 解释 Validator、Failure Taxonomy、Repair Router、Refiner 的闭环 |
| P09 | Metric cards + compact bars | 展示当前 Web 样本的有效率和分数变化 |

Runners-up considered:

- `timeline_horizontal` rejected: pipeline has分支与回路，不是线性时间线。
- `grouped_bar_chart` rejected: 指标数量少，用大图表会稀释讲述重点。
- `flowchart_process` rejected: 需要同时呈现 RAG 输入和修复回路，自绘结构更准确。

---

## VIII. Image Resource List

The project generated many SVG icons. The deck uses selected refined outputs that are visually stable and cover different prompt categories.

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Acquire Via | Status | Reference | text_policy | page_role |
| -------- | ---------- | ----- | ------- | ---- | -------------- | ----------- | ------ | --------- | ----------- | --------- |
| gen_rocket.png | 128x128 | 1.00 | Cover accent and object-icon example; selected for clean silhouette and strong color | Generated icon preview | #12 thumbnail grid | user | Existing | refined rocket icon from project output | none | local |
| gen_coffee.png | 128x128 | 1.00 | Object icon example; selected for readable handle/steam details | Generated icon preview | #12 thumbnail grid | user | Existing | refined coffee icon from project output | none | local |
| gen_dog.png | 128x128 | 1.00 | Animal/character example; selected for high recognizability | Generated icon preview | #12 thumbnail grid | user | Existing | refined dog icon from project output | none | local |
| gen_book.png | 128x128 | 1.00 | Education/object example; selected as a course-related artifact | Generated icon preview | #12 thumbnail grid | user | Existing | refined book-pencil icon from project output | none | local |
| gen_landscape.png | 128x128 | 1.00 | Scene example; selected to show non-object prompt handling | Generated icon preview | #12 thumbnail grid | user | Existing | refined landscape icon from project output | none | local |
| gen_cloud.png | 128x128 | 1.00 | UI icon example; selected for app-icon style | Generated icon preview | #12 thumbnail grid | user | Existing | refined cloud-download icon from project output | none | local |
| gen_shield.png | 128x128 | 1.00 | Safety/security UI example; selected for crisp contrast | Generated icon preview | #12 thumbnail grid | user | Existing | refined shield-lock icon from project output | none | local |
| gen_calendar.png | 128x128 | 1.00 | UI/productivity example; selected for polished app-like shape | Generated icon preview | #12 thumbnail grid | user | Existing | refined calendar-check icon from project output | none | local |

---

## IX. Content Outline

### Part 1: Problem and Fit

#### Slide 01 - Cover

- **Layout**: Left title, right selected icon strip.
- **Title**: SVG Icon Agent
- **Subtitle**: 可编辑 SVG 图标生成的多 Agent 流水线
- **Core message**: 本项目把图标生成拆成目标、记忆、规划、候选、评审、选择、验证、修复和记忆沉淀。
- **Content**: 课程、项目定位、作者信息占位。

#### Slide 02 - Project Requirement Mapping

- **Layout**: Three columns.
- **Title**: 对齐 Project 3：Agent 不只是一次模型调用
- **Core message**: 项目对应课程中的 2D 生成与多 Agent 协作方向。
- **Content**:
  - 图形学对象：可编辑 SVG icon，而非位图。
  - Agent 任务：从提示词到生成、评审、修复的自治流程。
  - 输出证据：SVG/PNG/metrics/trace/gallery/Web UI。

#### Slide 03 - Problem Definition

- **Layout**: Problem -> constraints -> design choice.
- **Title**: 为什么选择 SVG 图标生成
- **Core message**: 相比文生图模型输出位图，当前方案更适合图标和 UI 资产，因为 SVG 可编辑、可检查、可定位错误。
- **Content**:
  - 输入短，但语义、风格、尺寸约束多。
  - SVG 需要安全、可解析、可编辑、可渲染。
  - 文生图模型适合复杂视觉和写实效果，但图标任务更重视结构化控制。
  - 因此把生成变成带检查点的 Agent 流水线。

### Part 2: Agent Architecture

#### Slide 04 - Overall Agent Architecture

- **Layout**: Full-width RAG + pipeline diagram.
- **Title**: 总体架构：RAG 记忆 + 多 Agent 生成/验证/修复
- **Core message**: 本地历史记忆作为 RAG 上下文进入 Goal Manager；后续 Agent 逐步收窄目标并产生可验证 SVG。
- **Visualization**: RAG + multi-agent pipeline diagram.
- **Content**:
  - Memory Retrieval Tool 从历史运行中检索相似经验。
  - Goal/Rewriter/Planner 明确目标、重写提示、形成结构化计划。
  - Generator/Critics/Selector/Optimizer 形成协作生成。
  - Validator/Taxonomy/Router/Refiner 形成失败修复闭环。
  - Exporter/Memory Curator 输出并沉淀经验。

#### Slide 05 - RAG and Goal Conditioning

- **Layout**: Left narrative, right mini RAG diagram.
- **Title**: RAG 在这里：不是外部知识库，而是本地运行记忆
- **Core message**: 检索增强用于复用项目自己的成功/失败经验，而不是给模型塞无关资料。
- **Content**:
  - `memory_index.jsonl` 记录 prompt、summary、success/failure patterns、score、tags。
  - BM25 检索返回 top-k 经验，拼入 Goal Manager 和后续上下文。
  - Goal Manager 输出 objective、requirements、constraints、acceptance criteria。

#### Slide 06 - Candidate Competition and Critique

- **Layout**: Center branch-merge diagram.
- **Title**: 候选竞争：三个草稿，两路评审，一个可解释选择
- **Core message**: 生成阶段通过多候选与双 Critic 减少单次输出的偶然性。
- **Visualization**: Candidate-Critic-Selector diagram.
- **Content**:
  - Multi-Candidate Generator 生成 3 个不同 SVG 草稿。
  - Semantic Critic 关注 prompt alignment 和小尺寸识别。
  - SVG Quality Critic 结合 SvgCheckTool，关注安全、可编辑和渲染风险。
  - Consensus Selector 选 winner，并给 Optimizer 写 repair brief。

#### Slide 07 - Validation and Repair Loop

- **Layout**: Loop diagram with failure path highlighted.
- **Title**: 修复闭环：先诊断，再选择修复路线
- **Core message**: Refiner 不是盲目重试，而是接收 Validator、工具检查、Failure Taxonomy 和 Repair Router 的结构化上下文。
- **Visualization**: Validation and repair loop.
- **Content**:
  - Validator 输出 score、valid 和 issue list。
  - Failure Taxonomy 分类 root cause 和 failure type。
  - Repair Router 选择 safety rebuild / semantic recomposition / simplification 等路线。
  - Refiner 返回完整修复 SVG；最多迭代 3 轮。

### Part 3: Implementation and Evidence

#### Slide 08 - Web UI and Generated Examples

- **Layout**: Two-column: workflow UI description + selected generated icon gallery.
- **Title**: Web UI：让每个 Agent 节点可见
- **Core message**: 前端不是装饰，而是把运行状态、prompt rewrite、memory context、候选和最终图标暴露出来。
- **Content**:
  - 节点状态：waiting / active / done / skipped / error。
  - 支持 post-run optimizer feedback，不必重跑全流程。
  - 插入 8 个精选 refined 图标：rocket、coffee、dog、book、landscape、cloud、shield、calendar。

#### Slide 09 - Current Results and Caveats

- **Layout**: Metric cards + compact bars + caveat box.
- **Title**: 当前结果：15 个 Web 样本，修复后全部有效
- **Core message**: 现有样本显示修复闭环能提高通过率，但还不是严格完整基准实验。
- **Content**:
  - Web run 样本数：15。
  - Baseline valid：13/15。
  - Refined valid：15/15。
  - Baseline average score：89.33；Refined average score：93.20。
  - 最大修复轮数：3。
  - Caveat：样本来自多次 Web 单 prompt 运行，不等同于一次完整 12 prompt 批量实验。

#### Slide 10 - Takeaways and Limitations

- **Layout**: Left takeaways, right limitations.
- **Title**: 结论：Agent 架构的价值在可控性
- **Core message**: 项目的主要贡献是让 SVG 生成从黑箱输出变成可追踪、可验证、可修复的过程。
- **Content**:
  - 有效点：RAG 记忆、候选竞争、双 Critic、结构化修复、可视化运行状态。
  - 限制：依赖 LLM 质量和 OpenRouter 队列；SVG 渲染器覆盖的是实用子集；当前实验规模有限。
  - 下一步：完整批量评测、更多人类偏好指标、扩展 SVG grammar 和 repair route。

---

## X. Speaker Notes

- Total talk length: about 10 minutes.
- P01: 40s. State project in one sentence.
- P02: 55s. Map to Project 3 requirements.
- P03: 55s. Explain why SVG icon generation is a good graphics-Agent target.
- P04: 90s. Spend the most time on full architecture and RAG diagram.
- P05: 60s. Explain local memory retrieval and goal conditioning.
- P06: 70s. Explain candidate competition and two Critic Agents.
- P07: 70s. Explain validation and repair loop.
- P08: 70s. Show Web UI affordances and selected examples.
- P09: 70s. Present metrics with caveats.
- P10: 50s. Close with concrete takeaways and limitations.

---

## XI. Technical Constraints

- All slide SVG files use `viewBox="0 0 1280 720"`.
- No `<style>`, no CSS classes, no `foreignObject`, no scripts, no external web assets.
- Use raw SVG primitives for architecture diagrams and metric panels.
- Use only approved `tabler-outline` icons.
- Use selected PNG generated examples from `images/`.
- Keep page text concise enough for 10-minute delivery; speaker notes hold details.
