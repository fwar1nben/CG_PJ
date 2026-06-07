# 01_cover

这次项目做的是 SVG Icon Agent，一个把短文本提示词转换成可编辑 SVG 图标的多 Agent 系统。我们没有选择直接调用文生图模型输出位图，而是把生成过程拆成目标管理、记忆检索、提示词改写、规划、候选生成、评审、选择、优化、验证、修复和记忆沉淀。右侧这些图标不是装饰图，而是项目实际 refined 输出里挑出的样例，用来说明系统最终产物就是可复查的图标资源。

# 02_requirement_mapping

这个项目和 Project 3 的对应关系主要有三点。第一，图形学对象是 SVG 图标，它要求 viewBox、路径、颜色和可编辑结构都能被检查。第二，Agent 不是一个名字，而是多个 LLM-backed Agent 分工完成窄任务。第三，项目输出不只是一张图片，还包括 SVG、PNG、gallery、metrics、trace、failure taxonomy 和 repair routes，这些文件能支撑复现和分析。

# 03_problem_definition

选择 SVG 图标生成，是因为这个任务更重视结构控制，而不是写实效果。文生图模型适合复杂场景、纹理和真实感输出，但它通常给的是 PNG 或 JPG，局部修改、语法检查和错误定位都不方便。图标和 UI 资产更需要可编辑路径、稳定配色、小尺寸可读性和可验证安全性。当前方案用 SVG Agent 流水线，就是把这些要求拆成可以检查和修复的结构化任务。

# 04_overall_architecture

总体架构可以分三层看。左侧是 RAG 输入，Memory Retrieval Tool 从本地历史运行中检索相似经验，把成功策略和失败模式交给 Goal Manager。中间是主生成链路，Goal、Rewriter、Planner 和 Generator 逐步把用户提示词变成结构化计划和多个 SVG 草稿。右侧是协作和修复链路，两个 Critic 评审候选，Selector 选择 winner，Optimizer 改写 baseline，Validator 发现问题后再进入 Taxonomy、Router 和 Refiner 闭环。

# 05_rag_goal_conditioning

这里的 RAG 不是外部资料库，而是项目自己的运行记忆。每条 MemoryRecord 保存 prompt、summary、成功策略、失败模式、用户反馈、分数和标签。检索时用 BM25 从本地 jsonl 中取 top-k 经验，Goal Manager 再据此生成 objective、visual requirements、constraints 和 acceptance criteria。这样做的价值是让系统下一次生成时能利用已有失败，而不是每次从零开始。

# 06_candidate_critique

生成阶段不是让模型一次性给答案，而是先生成多个候选。Multi-Candidate Generator 通常输出三个 SVG 草稿，Semantic Critic 关注语义对齐和小尺寸识别，SVG Quality Critic 关注可编辑性、安全性和渲染风险，并结合 SvgCheckTool 的机器检查结果。Consensus Selector 不是只给一个分数，它还会给下游 Optimizer 写 repair brief，所以选择过程是可以解释的。

# 07_validation_repair_loop

修复闭环的重点是先诊断，再修复。Validator 给出 score、valid 和 issue list，如果发现 warning 或 error，Failure Taxonomy 会把问题分类到语法安全、渲染、语义偏差、布局等类型。Repair Router 再选择路线，例如 safety rebuild、semantic recomposition 或 simplification。Refiner 最后拿到这些上下文，返回完整修复后的 SVG。现有样本里 coffee 从 70 分到 95 分，dog 从 65 分到 100 分，说明这个闭环不是摆设。

# 08_webui_examples

Web UI 的作用是把 Agent 流程暴露出来。它显示每个节点 waiting、active、done、skipped 或 error 的状态，也显示 prompt rewrite、memory context、候选图、selected、baseline 和 refined 输出。右侧是我从项目生成结果里挑出的八个比较稳定的例子，覆盖对象、动物、场景、安全和 UI 类图标。选择标准不是分数最高就完事，而是轮廓清楚、放大后不乱、能代表不同 prompt 类型。

# 09_results_caveats

当前工作区里有十五个 Web 单 prompt 样本。Baseline 阶段有十三个通过验证，Refined 阶段十五个都通过；平均分从 89.33 到 93.20，最大修复轮数是三轮。这个结果说明修复链路确实能提高有效率，但我不会把它说成完整 benchmark。严格实验还需要固定十二个 prompt 一次性批跑，并和 single workflow 做更系统的对比。

# 10_takeaways

最后总结三点。第一，RAG 记忆让历史经验进入目标设定。第二，多候选、双 Critic 和 Selector 让生成不完全依赖一次模型输出。第三，Validator、Taxonomy、Router 和 Refiner 让失败修复更具体。限制也很明确：系统依赖 LLM 服务质量，SVG 检查覆盖的是实用子集，当前实验规模还不够大。下一步应该做完整批量评测、人类偏好对比，并继续扩展 SVG grammar 和 repair route。
