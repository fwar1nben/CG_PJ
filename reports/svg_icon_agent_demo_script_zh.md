# SVG Icon Agent 中文演示讲稿

总时长建议：约 10 分钟。语速按正常中文答辩控制，每页不要逐字死读，重点跟着图讲。

## 1. 标题页，约 45 秒

大家好，我汇报的项目是 **SVG Icon Agent**，副标题是“多 Agent 协同的可编辑 SVG 图标生成”。这个项目面向 Computer Graphics Project 3，目标不是训练一个新的图像模型，而是用大模型 Agent 工作流，把一句英文描述转换成可编辑、可检查、可导出的 SVG 图标。

这里有四个关键词：LLM Agents、Editable SVG、RAG Memory 和 Self-Repair。代码仓库链接是 `https://github.com/fwar1nben/CG_PJ`。右侧展示的是实际从 SVG 导出的 PNG 结果，不是额外找的图片素材。

## 2. 问题与动机，约 1 分钟

我先说为什么不直接做普通文生图。普通 text-to-image 模型可以生成很好看的 bitmap，但是对于图标场景有几个问题：第一，输出通常是像素图，不方便继续编辑；第二，内部结构不可检查，很难知道它有没有满足尺寸、安全标签、颜色约束；第三，失败原因不透明，只能重新生成。

所以我选择 SVG。SVG 是 XML 形式的矢量图，天然可缩放、可编辑，也可以用程序检查 `viewBox`、标签、属性和外部引用。这样更贴近计算机图形课程里“结构化图形生成”的主题。

Agent 化的价值在于：把一个复杂生成任务拆成目标管理、规划、候选生成、评价、选择、验证和修复。最后不只是给一张图，而是给一套可追踪的生成过程。PPT 下方这一行是项目定位：这是生成式 AI workflow 实践，不是本地 SVG 模板库。

## 3. 项目目标，约 1 分钟

系统输入可以是一条英文 prompt，比如 “A steaming cup of coffee”。输出不仅包括 SVG，还包括 PNG 预览、HTML gallery、metrics、`llm_trace.json` 和脱敏后的 raw response。页面下方列出的 `generation_goal.json`、`failure_taxonomy.json`、`repair_routes.json` 都是为了让运行过程可复盘。

项目支持两种使用方式：第一是 CLI，可以批量跑本地 prompt，也可以用 `--text` 做单条输入；第二是 Web UI，可以输入 prompt，实时看 Agent DAG 的当前状态，预览 baseline 和 refined 图像，还可以展开模型返回内容。

这里强调一个边界：所有命名为 Agent 的组件都调用大模型，本地代码只做工具层工作，比如输入加载、SVG 机械检查、PNG 渲染、日志和导出。失败时也不会静默切回本地模板生成。PPT 里只展示短日志摘录，完整日志保存在 `llm_raw_responses.jsonl`。

## 4. 总体架构 DAG，约 1 分 20 秒

这一页是系统的核心架构。它不是完全线性的流水线，而是一个有向无环图加条件修复回路。这里我把箭头重新画成分层结构：主干在中间，两个 Critic 是并行分支，下面是条件修复分支。

前半部分从 Memory Retrieval Tool 开始，检索历史运行经验；然后 Goal Manager 生成结构化目标；Prompt Rewriter 改写输入；Planner 生成图标计划；Multi-Candidate Generator 生成多个 SVG 候选。

候选生成之后，Semantic Critic 和 SVG Quality Critic 从两个角度评价。Semantic Critic 关注语义匹配和小图标可读性，SVG Quality Critic 关注 SVG 是否安全、可编辑、可渲染。Consensus Selector 汇总两个 Critic 的意见，选择 winner。

后半部分是 Optimizer 和 Validator。如果 Validator 判断没有阻塞问题，就直接导出。如果有问题，就进入 Failure Taxonomy、Repair Router 和 Refiner，再回到 Validator 重新检查。Web 前端显示的 runtime DAG 也是同一套依赖关系，只是会把节点标成 waiting、active、done、skipped 或 error。

## 5. 核心 Agent 职责，约 1 分钟

这里把 Agent 分成四组。注意这一页下方的边界原则：Agent 等于一次具有明确角色的大模型调用；Tool 等于确定性的解析、检查、渲染和导出。

第一组是目标与上下文：Goal Manager、Prompt Rewriter 和 Memory Curator。它们负责把用户输入、历史经验和验收标准整理清楚。

第二组是图标生成：Planner 和 Multi-Candidate Generator。Planner 给出结构化 plan，Generator 根据 plan 生成多个 SVG draft。

第三组是评价与选择：Semantic Critic、SVG Quality Critic 和 Consensus Selector。它们让模型不是只生成，而是先评价、比较、再选择。

第四组是优化与修复：SVG Optimizer、Validator、Failure Taxonomy、Repair Router 和 Refiner。它们负责把发现的问题转成可执行的修复策略，并返回完整 SVG。

这个设计的重点是职责清晰，每个 Agent 的输入输出都可以记录和检查。所以后面放进 PPT 的 prompt rewrite、selector rationale、taxonomy 和 route 都不是我手写的解释，而是来自运行日志的脱敏摘录。

## 6. 协同生成流程，约 1 分钟

这一页用 rocket run 举例。对于同一个 prompt，系统先生成三个候选 SVG。三个候选都通过了本地工具检查，tool score 都是 100，但两个 Critic 的评分不同。左下角是 Prompt Rewriter 的日志摘录，它把原始输入扩写成 256x256、居中火箭、分层动态火焰等更明确的 SVG prompt。

Semantic Critic 给 candidate 2 最高分，因为它更符合“rocket launch”和“dynamic flame”的语义。SVG Quality Critic 更偏向 candidate 3，因为它在 SVG 结构上看起来更稳定。但 Consensus Selector 最后选择 candidate 2，因为它在语义清晰、动态火焰和小尺寸可读性之间最平衡。

这里的创新点不是简单多调用几次模型，而是把多次生成变成一个有评价、有理由、有记录的协作流程。页面下方的 Selector 摘录说明，candidate 2 同时有最高语义分和 SVG 质量分，因此被选中；Selector 还会写 repair brief，交给后面的 Optimizer。

## 7. 自我修复机制，约 1 分 20 秒

这一页是 coffee 修复案例。baseline 的分数是 70，并且 invalid；修复后 refined 分数是 95，并且 valid。这里的箭头表示完整闭环：Validator 发现问题，Taxonomy 分类，Router 给路线，Refiner 重写 SVG，然后再 re-validate。

为什么会失败？Validator 发现杯子的颜色使用了蓝色，不符合 Planner 设定的咖啡色 palette，同时 steam 里有 opacity，违反了约束。Failure Taxonomy 把这个问题分类为 `semantic_mismatch` 和 `constraint_violation`。

然后 Repair Router 选择 `semantic_recompose` 路线，给出具体动作：把蓝色杯体替换为 brown 和 cream palette，移除 opacity，并更新 metadata。PPT 中的 JSON 片段来自 `failure_taxonomy.json` 和 `repair_routes.json`。Refiner 根据这个 brief 返回完整 SVG，再交给 Validator 检查。

这个例子说明，修复不是泛泛地“再试一次”，而是先诊断，再路由，再生成修复版本。

## 8. 目标管理与记忆，约 1 分钟

目标管理和记忆是我后面增加的创新点。

Goal Manager 会输出 `GenerationGoal`，包括 objective、visual requirements、constraints、acceptance criteria、style preferences 和 avoid patterns。这样后续 Agent 不只是看一句原始 prompt，而是看明确的验收标准。页面下方放的是实际目标和记忆摘录。

Memory Retrieval Tool 会从本地历史 run 中检索相似案例，比如 rocket prompt 会检索到以前成功的策略：居中火箭、分层扫掠火焰、简化圆形窗口。Memory Curator 在每次运行结束后，把成功策略、失败模式、用户反馈和分数写回 memory index。

所以系统具备一种轻量 RAG 记忆能力：它不是外部数据集，而是从自己的历史运行中积累经验。这个设计也能解释为什么后续类似 rocket prompt 会越来越稳定。

## 9. 实验结果与案例，约 1 分 20 秒

实验结果采用报告里的 4 个主要 Web run 快照。四个 prompt 一共生成 12 个候选 SVG，选出 4 个 winner。优化后的 baseline 有 3/4 有效，最终 refined 是 4/4 有效。平均分从 91.25 提升到 97.50，最大修复轮数是 1。这个口径在 PPT 里单独标出来，避免把后续 demo run 和报告统计混在一起。

案例上，rocket、white rocket 和 cat 在优化后就已经有效；coffee 触发了修复流程，从 70 提升到 95。后续 `outputs/web` 中还有 dog 和 cloud 等更多运行，其中 dog 从 65 修到 100，cloud 也有多轮修复提升，可以作为 demo 时的补充材料，但正式统计仍以报告快照为准。

我在正式统计里只使用报告快照，避免混合不同时间的实验口径；但更多运行记录说明这个框架可以继续扩展。

## 10. 总结与展望，约 1 分钟

最后总结一下。这个项目的核心不是一个 SVG 模板库，而是一个面向 SVG 图标生成的 LLM Agent 协作系统。它有目标管理、多候选生成、双 Critic、共识选择、SVG 优化、验证、自我修复和历史记忆。

它的优点是过程可解释、产物可编辑、失败可追踪，并且 Web UI 可以展示 Agent 当前状态。局限也很清楚：免费模型速度和稳定性有限；本地 renderer 支持的是实用 SVG 子集；视觉质量评价还比较规则化；实验规模还可以继续扩大。另一个工程经验是 raw LLM 输出偶尔会 malformed，所以项目里也加入了 retry 和脱敏日志记录。

后续我希望补充更大的 prompt set、人类偏好评价、single workflow 和 collaborative workflow 的消融对比，以及更强的 perceptual critic。我的汇报到这里，谢谢大家。
