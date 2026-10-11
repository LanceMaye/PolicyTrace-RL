---
name: policytrace-stage2
description: 为 PolicyTrace-RL 执行 Stage 2「跨源数据审计、无泄漏划分与 SFT/RL 数据组织」。在已验收的 τ²-bench Retail / AReaL Stage 0、统一评测 Stage 1 之上，审计 SFT 原始对话与 RL Task 的来源和具体案例重叠，冻结可追溯的 Train/Dev/Test 划分，谨慎构造节省在线训练成本的 RL Train 去重视图，准备 Qwen2.5 SFT 监督数据与评测任务清单。仅在用户明确要求进入 Stage 2 时使用。
---

# PolicyTrace-RL · Stage 2：跨源审计、数据隔离和训练数据组织

> **执行对象：Codex。** 这不是讨论提纲，需要实际阅读现有工程与原始数据、编写小而可复用的数据处理代码、运行真实数据审计和测试，交付可复现的数据版本、划分清单与阶段验收报告。
>
> **决策原则：最大限度保留高质量 SFT；严格杜绝训练/最终测试的具体任务泄漏；只对证据充分、与 SFT 训练轨迹几乎同一具体案例的 RL *训练* Task，建立可逆的成本过滤视图。绝不能为了放大 RL 相对 SFT 的提升而故意削弱 SFT。**
>
> **环境与阶段边界：** Windows 或 WSL2 Ubuntu CPU；优先 WSL2 的 Linux 文件系统。可以使用已有依赖、标准库及合理的轻量数据处理库；如需取得 Qwen2.5-3B-Instruct 的 tokenizer / chat template，可单独下载体积较小的 tokenizer 配置并固定 revision，不得下载模型权重。无需 AutoDL / GPU；**禁止新的付费模型 API 调用**。不做真实 Agent Rollout、不训练 SFT/OPD/GRPO、不实现 R1、不修改官方 Evaluator、不提交或推送 Git，完成后等待人工验收。
>
> **先审计再拍板：** 70/15/15、SFT 验证集约 10%、85 Task Pass^1 和 50 Task Pass^4 子集都是已讨论的**目标**，不是为了凑整数而牺牲分组隔离的硬约束。先给出审计证据，再冻结实际整数、任务 ID 和哈希。如果关键来源关联无法判定，保留歧义并审慎隔离；不编造已去重或已验证的结论。

## 0. 必须先核对项目事实和现状

执行前阅读并定位真实文件（以当前仓库布局为准，缺失即说明，不自行臆造）：

- `reports/stage0/STAGE0_REPORT.md`、`data_schema.md`、`user_simulator.md`、`docs/stage0_walkthrough.md`，尤其是原始 SFT/RL Schema、四份快照和历史使用过的 Task。
- `reports/stage1/STAGE1_REPORT.md`、`docs/evaluation_protocol.md`、`docs/reward_analysis.md`；`src/policytrace/evaluation/` 与 `rewards/`、Stage 1 `RunContext`、`EvaluationPlan` 和 Task Hash 的约束。
- 现有 `src/policytrace/stage0/`、`scripts/stage0_*`、`tests/stage0/`、`tests/stage1/`、`.gitignore`、`requirements-stage0.lock`、数据清单、版本锁、测试入口。
- 固定 τ²-bench Fork：`https://github.com/dhh1995/tau2-bench`，branch `dhh/async-and-custom-completion`，Commit `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`。
- 固定 AReaL 数据集：`inclusionAI/AReaL-tau2-data`，Revision `86971dc03da6e7c1a7933295e05b84aab8215386`。
- 原始总体证据：Retail RL **563** 个 Task；Retail SFT **11,395** 个 Assistant Turn，来自 **1,000** 个原始对话；四份 Retail DB 快照。上述是 Stage 0 历史证据，Stage 2 应从本机**实读数据**核对并报告，不把历史结果当新执行。
- Stage 0/1 已在日志/报告中使用过的诊断 RL Task：`retail_245`、`retail_8`、`retail_454`、`retail_293`、`retail_479`、`retail_325`、`retail_65`、`retail_339`、`retail_131`、`retail_152`。发现其他历史使用过的 Task 也应加入 `known_exposed` 清单。**这些任务及其同源变体不得进入冻结的最终测试集**；可以进入 Dev 或单独 Diagnostic，不冒充未见任务。参考轨迹的确定性工具评分测试不等于真实模型测试，但已经暴露了隐藏目标和数据情况，故保守隔离。

开工时先生成不超过一屏的实施计划，明确原始数据在哪里、能否确认文件 SHA、已有可复用模块、预计需要新建哪些脚本。所有统计要注明实际运行还是源报告引用。

## 1. 任务与信息边界（禁止越界）

当前 Retail RL 原始字段已知主要包括 `id`、`description`、`user_scenario`、JSON 字符串形式的 `evaluation_criteria`、`db_path`。SFT 原始字段已知主要包括 `messages`、`answer`、`metadata`（可能包含 `source_dialog_id`、`turn_index`、`scenario_id`、质量字段）。**不要假设每条 SFT 都有 RL 的完整隐藏 `user_scenario`；不要假设 `source_dialog_id` 与 RL Task ID 共享命名空间或有直接映射。先检查真实类型与非空比例。**

区分两套可见性：

- **受控的离线数据审计器/划分器**可在本地访问私有 `user_scenario`、`evaluation_criteria.actions`、数据库快照，以检查重复、任务目标与来源关系、构造分层标签；这些信息只能用于审计、环境评分、User Simulator 的合法职责，不得输入 Student、出现在 Student SFT Prompt 中或公开可提交的文件中。
- **Student 训练/推理侧**只能获得业务政策、工具 Schema、真实对话历史、工具观察，以及由专家 `answer` 转换得到的合法监督目标。RL Task 中隐藏的私有场景和评分答案不能成为 Student 的上下文、监督标签或在线可见诊断提示。

任何哈希/去重识别使用确定性、版本化规范化规则；没有原始敏感文本时使用脱敏 ID、摘要、风险等级和私有证据指针记录依据。`.env`、原始数据库、原始或生成的含私有任务文本的 JSONL、完整轨迹和人工审查样例进 Git 忽略目录。对证据不足的场景标注 `unknown/needs_review`，不宣称独立或精确匹配。

## 2. 工作流程

### Step A：对 Retail SFT / RL 进行完整、可复现审计

必须真实遍历全部 11,395 条 Retail SFT 和 563 条 Retail RL（若数量与历史不同，应先停止并调查），保存代码、审计命令、Schema/质量报告及原始文件 SHA256。不要局限于 Stage 0 前 100 条 SFT 抽检。

**SFT 审计：**

- 检查 `source_dialog_id`、`scenario_id`、`turn_index`、`messages`、`answer`、角色顺序、工具名和参数结构、质量标签、`thinking`/文本字段的有无；统计空值、格式异常、无 assistant 目标、无效工具格式、重复样本、来源对话的 Turn 数和总 Token/字符近似长度（近似值只能用于预估，不冒充真实 tokenizer token）。
- 按**原始完整对话** `source_dialog_id` 分组；若 metadata 有可靠的更上游来源 ID，再研究是否多条原始对话属于同一任务，不可直接假设一对话一任务。
- 明确同一个源对话的全部 Assistant-Turn 样本必须处在同一 SFT split，不允许第 3 回合训练而第 7 回合验证。检查相邻 SFT 样本共享大量 history 的情况，禁止按 11,395 条 Turn 随机切。

**RL 审计：**

- 复用 Stage 0 解析器，先 JSON 解码 `evaluation_criteria` 再调用真实 `Task.model_validate`；验证 `db_path`、初始化、评测条件和参考工具参数 Schema。不为审计重新实现另一套业务工具。
- 统计快照分布、用户目标类别、是否修改数据库、参考动作/工具数、COMMUNICATE 条件是否为空及每类常用工具。
- 分辨真正的任务初始状态、目标实体和参考动作目标；同样客户 ID / 订单 ID 在不同快照中可能对应不同任务，不能简单仅凭 ID 判重复。

**任务类型与长中短分层：**

- 先按实际任务/政策提取粗粒度业务标签（如改地址、取消、退货、换货、只读查询、合规拒绝等；可以多标签），并区分只读/状态修改、快照、沟通条件有无。
- SFT `short/medium/long`：根据完整来源对话的实际回合数、历史长度、工具使用数或真实 tokenizer token（若可用）建立明确定义。RL *还没有 Student Rollout*，不能声称知道真实 Episode 长度；可用参考操作数、任务描述复杂度等标注 `reference_length_proxy` 并定义固定分位阈值/缺失值。该 proxy 不能冒充将来模型轨迹实际长度。
- 输出各分布、分位数、长尾和任务类别稀疏情况，先查看再决定分层约束；563 个 Task 不适合对过多维度做交叉硬分层。保留种子和固定阈值，不按最终测试结果调节分层。

建议输出 `reports/stage2/source_audit.json` 和 `docs/data_audit.md`；私有细粒度行级数据另存忽略目录。

### Step B：SFT ↔ RL 跨源重合、近重复与来源关系审计（本阶段最高优先级）

**本项目对“重复”的定义比“同一业务类型”严格得多。** 先找到相同来源/事实实体的候选对，再核实是否确为同一具体任务。

证据维度包括：客户身份（如有）、订单或用户等业务对象、数据库快照/相关初始状态、用户目标、目标操作、目标地址/商品/数量/状态等具体参数、业务约束、结束条件、任务实例来源。缺字段即明确标注未知，不能把缺失当相等。对结构化 ID 做精确候选匹配，对文本做确定性规范化和局部相似候选检索；必要时人工复核。允许辅助文本相似度排序，但**绝不因单个相似度阈值自动删任务**。

至少输出四类：

1. `confirmed_same_instance`：多维证据表明具体客户、业务对象、目标操作/结果、关键约束及相关初始状态等价；提供受控审计证据。若缺失关键字段导致无法证明，不得列为 confirmed。
2. `probable_same_instance`：大部分证据一致，但缺少可核验的场景/实体/目标条件；只能候选人工复查。
3. `same_business_pattern_only`：例如两个不同订单的退货、两个不同客户修改地址；**正常共享业务知识，不是需要删除的重复**。
4. `distinct_or_unknown`：已确认不同或证据不足，区分两种状态；unknown 进入待审和保守隔离策略，不自动丢弃。

**重要现实约束：** SFT 的 `messages` / `metadata` 未必包含完整任务私有设定，因此可能只能获得候选相似性而不能验证所有隐藏要求。若无法证明“完全同一任务”，写明证据缺口，不为了执行用户成本过滤要求而假装找到确定重复。不要用大模型 API 充当自动裁判；本阶段无需付费模型调用。

建立跨源关系/重复簇（如可证明），检查 SFT 内、RL 内和 SFT↔RL。对于可能跨 Train、Dev、Test 的同一任务簇，需要**统一分配**，不能把组内样本拆到训练和测试两侧。对于人工认为难以判定的测试侧疑似碰撞，宁愿将受影响任务移到 Dev/Diagnostic 或暂挂，避免声称严格独立；不能根据结果好坏决定去留。

输出 `docs/cross_source_overlap.md`：候选数、经人工或确定性规则确认数、不可判定数、例子（仅脱敏）、误删/漏检风险、证据链、规则和版本；私有 `overlap_candidates.jsonl` 保存候选来源 ID、判断等级与证据哈希。

### Step C：先全局防泄漏，再分层冻结 RL Train / Dev / Test

先把跨源重合簇和 Stage 0/1 已暴露任务视为分组/隔离约束，再考虑数量比例，**不能先随机切完再试图靠删除少量 SFT 行掩盖泄漏**。

约定初始目标（实际规模可因组约束略有偏离）：

| RL 角色 | 初步目标 | 用途 |
|---|---:|---|
| `rl_train_full` | 约 70%，参考约 394/563 | OPD、GRPO 可共同使用的训练任务全集，未执行成本过滤 |
| `rl_dev` | 约 15%，参考约 84/563 | 训练前后调参、Bad Case、方法选择和质量诊断 |
| `rl_test_frozen` | 约 15%，参考约 85/563 | 预先冻结、在定型前不运行模型评分或选超参数的最终测试 |

要求：

- RL Task 全部且仅属于一个主分区或显式 `quarantine`；所有 Task 的 provenance/重合簇具有统一分区决策，精确检查交集为空，并为所有差额给出原因。
- Stage 0/1 已暴露 RL Task（前述 10 条及新发现历史暴露）不得放入 `rl_test_frozen`，优先 Dev/Diagnostic。完整排查已有脚本、fixtures、任务 ID 白名单及人工日志中的历史暴露事实；不能单凭用户说“没训练过”就把诊断任务重新视为未见测试。
- 尽量按业务主类型、快照、只读/修改状态、COMMUNICATE 是否为空、`reference_length_proxy` 的 short/medium/long 进行**粗粒度分层**；类别太小时进行合并或标记不可平衡，不牺牲重合簇完整性。不使用 RL Student 的最终输出或测试 Reward 选择划分。
- 相同数据库快照在训练和测试两侧出现**不自动视为泄漏**，因为多个任务共用快照本是 Benchmark 设定；真正要隔离的是具体任务实例和目标事实。记录同实体跨快照疑似重合，但不把整份 DB 快照直接划到单个分区（会使分布极端失衡）。
- 测试任务不能与任何用于**模型训练或模型选择**的 SFT 样本、RL Train、历史诊断答案发生已确认具体任务级重合；无法确保时应报告限制并隔离冲突样本，不夸称“完全排除一切相似性”。Dev 可用于调参但不得混入训练。与 RL Dev 重合的专家答案不得进入 SFT Train；是否用于 SFT Val 要明确标记其 Dev 用途，不能间接用于训练更新。
- 使用固定 RNG 种子、版本化特征规范、分组策略与实际整数输出，不要求强行凑成 394/84/85。生成 **Task ID 清单**和 SHA256，供 Stage 1 的 `EvaluationPlan` / `RunContext.task_set_sha256` 使用，并运行实际兼容性检查。

**最终测试预算预案：** 暂定在最终 RL Test（约 85 个）上报告所有五个检查点的 Pass^1；预先从其中按业务类型/复杂度分层选定约 50 个 Task 作为 Pass^4 重复可靠性子集。每个 Task 计划四次真实独立 Trial；不复用同一历史轨迹冒充四次。85 + 50×3 = 235 Episode/Checkpoint，五个约 1175 条（实际数字以冻结集合为准），仅是**预算计划，不是已执行实验**。Stage 3 可根据 **Dev 实测时延和预算**、在尚未观察 Test 模型分数前进行一次显式版本化的预算修订；不能事后挑选有利任务。Pass^1 和 Pass^4 报告必须标明不同分母。允许补充四次 Trial 平均的单次成功率；`Pass@4` 与 `Pass^4` 明确区分。

所有最终 Test Task 的原始 `user_scenario` 和隐藏评分条件仍由环境/User Simulator/Evaluator 在将来合法读取；本阶段清单只包含可审计 ID、快照标识和哈希。**Stage 2 不运行真实 Test Episode，不根据其得分修剪任务**。

### Step D：在隔离约束内整理 SFT Train / Validation（不要故意削弱 SFT）

- 以完整 `source_dialog_id` 及已发现的更高层重合簇为分组单位划分，不拆同一对话的不同 Turn。
- 在与 RL 最终 Test（以及不可用于训练的 Dev）冲突的专家案例被隔离后，尽量保留所有合法、正确、可复现的 SFT 专家数据供训练；对于质量筛选只根据预先定义的明确错误（空目标、无法序列化、工具参数不合规、明显重复错误、来源质量标签等），不可因为 SFT 可能过强而剔除。
- 目标将**可使用的 SFT 来源对话**约 90% 用作 `sft_train`、约 10% 用作 `sft_val`，结合可用对话簇及与 RL 分区的关系微调。Val 应与 SFT Train 来源对话分组隔离；尽可能让 SFT Val 不与 RL Train 的具体任务实例重合，以保证监督验证指标可解释。SFT Val 是早停/超参数选择集合，因此不能把与最终测试完全相同的专家轨迹放在 Val；可将对应专家轨迹彻底隔离在 `heldout_from_sft`。
- **SFT Train 与 RL Train 可以共享同一具体任务实例**：这是正常的阶段式后训练，不构成 Train↔Test 泄漏。不能仅因为训练池中 SFT/RL 相似就删掉 SFT 专家对话。也不要求 SFT 与 RL 业务类别分离。
- 若某个 RL Dev/Test 任务与 SFT Train 碰撞，优先通过全局重合簇重分配或隔离少数冲突样本保护最终评测；不能一边保留泄漏 SFT 标签，一边宣称 Dev/Test 是未见任务。
- 统计 SFT 训练/验证的来源对话数、Assistant Turn 数、业务类型、长中短、工具出现率、样本 token 长度分布、被排除的具体原因和数量。绝不把 11,395 个 Assistant Turn 当成 11,395 个独立任务。

**为何不另建独立 SFT Test？** 当前五检查点的最终业务效果统一使用冻结的 Retail 交互式测试。SFT Val 用于监控 teacher-forcing cross-entropy，独立 Agent Dev/Test 用于验证真实多轮能力。Stage 2 仅准备数据与协议，Stage 4 才实测 SFT loss、assistant-token 准确率（若支持）和 E1 官方任务成功率；不能把 Validation Loss 当成 Pass^1。

### Step E：用户提出的唯一变更——可逆的 RL Train 成本去重视图

**用户动机：减少在与 SFT 已充分重合的具体训练任务上反复生成在线轨迹的成本，不是人为压低 SFT 或放大 GRPO 优势。**

但务必写清技术事实：SFT 的专家动作 teacher forcing 与 GRPO 在模型自生成状态分布上的探索/纠错并不等价；即使同一任务，也可能产生 RL 训练价值。故不能直接假设“相同任务必然无 RL 收益”。

具体执行顺序及规则：

1. 必须**先完成跨源重合判断和全局 Train/Dev/Test 隔离**；只在 `rl_train_full` 内寻找与 `sft_train` 的 `confirmed_same_instance`。与 `sft_val`/Dev/Test 碰撞的实例应按数据隔离规则处理，不能作为一般成本去重理由随意转入另一集合。
2. 为每条确认同实例的 RL Train Task 输出证据：对应 SFT 源对话 ID（允许多对一）、同一客户/订单等关键字段比对、目标操作/结果/约束/初态是否等价、审计规则 ID、`confidence=confirmed`、审计人或确定性判定依据。敏感细节仅私有保留。
3. 生成两份**不修改原始数据**的任务视图：`rl_train_full`（全部合规训练任务）与 `rl_train_cost_pruned`（仅剔除已确认同实例重复的 Task）。配套生成 `rl_cost_exclusions.json`（只放任务 ID、分类、证据 hash/来源哈希、版本及原因，敏感证据另存私有）。所有疑似匹配均保留在 cost-pruned 视图中，列入人工审查清单；禁止基于同一业务类型、单一共享 ID 或近似文本分数自动排除。
4. 若删除候选涉及任务稀有类型、特定数据库快照、长轨迹任务或数量过多，报告分布偏移、保留率与成本收益不确定性，并在最终将哪份视图设为训练默认之前提出需用户人工核准的建议；不要无说明地让训练池缩水。
5. **除非审计足以确认真实同一实例，否则成本视图等于完整 RL Train，这仍是合格结果。** 不伪造重叠数来满足预设想法。不需要为了在 Stage 2 宣称省钱而对每个任务执行一次真实 RL。
6. 后续 OPD/GRPO 可以以 `rl_train_cost_pruned` 作为初步的节约成本训练池，但必须记录训练是否真的减少 Episode / Token / GPU/API 消耗。如果预算固定且只是把 Rollout 转投其他任务，总成本并不一定下降；不虚报节省金额。保留完整池为回退和可选消融，不强制为了成本复跑所有任务。

此设计需以 `docs/rl_cost_filter.md` 写明：已确认重复与待复核的数量、训练池变化、任务类型分布变化、真正的成本假设、潜在机会成本、如何回退，以及为什么这不是“让 RL 更容易显著超越 SFT”的实验操作。

### Step F：SFT 样本标准化与 Qwen2.5 监督 Token Mask

不开始训练，但交付 Stage 4 能直接读入、可查证的规范化样本格式。优先保留一份模型无关、无损的中间表示，再导出模型相关格式，避免过早绑定训练器和以后重复清洗。

- 识别 `messages` 是历史上下文、`answer` 是**当前这个 Assistant Turn 的监督目标**。规范化角色 `system/user/assistant/tool`、工具调用标识与参数、工具返回、文本/非文本字段。`thinking` 若存在，先核实来源和政策，确定是否属于允许监督的目标，不默认把隐藏思维或私有任务说明带入 Student 输出。
- 使用实际 Qwen2.5-3B-Instruct tokenizer/chat template 版本验证格式；合理情况下可以只下载 tokenizer 小文件，**不得在本阶段下载完整模型权重**。存储 tokenizer 名称、revision、special token IDs、模板 hash 和序列化样例的脱敏 hash。不要假设原始 τ²-bench Tool Call JSON 自动与 Qwen 模板兼容，实际比较工具定义、tool_call / tool response 的序列化结果及推理时预期协议。
- **当前 SFT 每行通常仅监督 `answer` 中 Student 应生成的 Assistant 目标片段**：`labels` 只在目标 Assistant 的真实 Token 上启用，其余 `messages` 历史（包含既往 Assistant）、User、Tool observation、System 和 padding 位置一律为 `-100`。对于目标中的工具调用、消息结束 token，需要基于实际模板决定哪些属于应学习的 Assistant 输出。不得仅因历史消息 role=assistant 就错误地一起算 Loss。
- `input_ids`、`attention_mask`、`labels` 真实对齐，逐样本检查 `len` 相等、监督 token 非空、非 Student Token 未受监督。谨慎处理 Chat Template 的 `{% generation %}` 掩码支持与实际返回值：如默认模板不能直接正确输出 assistant mask，应实现**经过样例验证**的目标 span/token 对齐策略，不能把 `assistant_only_loss=True` 视为自动正确。
- 长上下文：统计至少 p50/p90/p95/p99 的真实 token 长度（若已取得 tokenizer）；提出 4K/8K 首轮预算建议，结合工具调用边界及关键约束做截断/过滤，避免截断工具调用 JSON、答案目标或结束标记。处理规则固定并统计被过滤数量，**不为了凑长度切掉必要的用户和工具上下文**。
- 源数据错误或目标不可序列化、超长无法保留有效监督的样本需列入有理由的排除报告；仍保持来源对话和任务关联。完整 Token 数与成本指标不能以字符估计替代。
- 不要求 Stage 2 实现 TRL `SFTTrainer`、训练器的梯度计算、Teacher 概率分布或 GRPO loss。Stage 4 接入时可以复用这些产物并做一次端到端 GPU 冒烟验证。

输出：`docs/sft_preprocess.md`、数据转换代码、测试夹具、私有或被 Git 忽略的 `sft_train`/`sft_val` 规范化及 tokenized 数据；明确哪些是最终可训练数据、哪些仅是待 tokenizer 验证的中间结果。

### Step G：RL 任务加载接口与 Stage 1 EvaluationPlan 集成

OPD、GRPO 共享同一 RL **训练任务池定义**（可基于完整或成本过滤视图），但后续**各自使用当时 Student 策略真正采集的在线 Rollout**，绝不能拿 SFT 专家轨迹或不同模型的陈旧轨迹冒充 on-policy GRPO 采样。

- 输出可读取的 `rl_train_full`、`rl_train_cost_pruned`、`rl_dev`、`rl_test_frozen`、`pass4_subset` ID manifest 及数据库快照引用；由实际 Stage 0 Task 解析和环境工厂加载，先验证少量 Train/Dev Task 的初始化/重置/官方评分接口，但不触发 LLM 调用。
- 生成**尚未执行**的 EvaluationPlan 模板，符合 Stage 1 `policytrace-eval-v1`、Task SHA 和 Trial 身份约束；真实 Pass^4 需要以后四条独立 Episode。Task 集与配置完整一致；缺环境/model/simulator 信息应保留待填项而不是伪造已固定的配置或成绩。
- Test/External Test 任务只在私有 Manifest 中保持任务 ID 与必要哈希，不能将隐藏场景/参考 actions 输出到公开训练数据或 Agent Harness 的可见 prompt。
- 固定映射：Task → Snapshot ID/hash → Task 来源/类型/复杂度 proxy → Split；对 OPD/GRPO 采样期暴露哪些字段、Student 屏蔽哪些字段给出明确机器可测试的边界。

### Step H：外部泛化评测——原版 τ²-bench Retail test

用户已明确同意把原版 τ²-bench Retail test 作为**额外泛化评测候选**，而非拿来混进内部 AReaL 训练池。

- 首先检查当前固定 Fork 实际存在的 Retail test split、文件/任务版本和实际任务数；**不要硬编码“40 条”**，以锁定 Fork 的真实文件为准。
- 审计这些 test 任务与 AReaL SFT/RL 所用种子任务、同客户同订单同目标事实及共享来源是否可能重叠。生成来源关系与泄漏风险清单。AReaL 合成数据可能基于原版任务拓展，不能仅因文件来自另一个 repository 就宣称完全独立。
- 若确认可作为额外评测，输出独立的外部 test manifest/hash，记录环境、政策版本、用户模拟协议和指标的潜在差异。**它不是可混到内部 Pass^1/Pass^4 平均值的额外任务**，报告必须另列，不能无条件与原版 τ²-bench leaderboard 直接比较。
- 若无法证实来源独立或评分兼容，标注 `EXTERNAL_EVAL_CANDIDATE/CONTAMINATION_RISK/BLOCKED`，保留候选并说明证据，不伪称已通过独立性测试。本阶段不运行任何外部测试 Episode。

输出 `docs/external_eval_audit.md`，以及可用时的独立外部评测任务清单。

## 3. 建议工程产出（可根据现有仓库调整，禁止重复造轮子）

```text
src/policytrace/data/
    source_audit.py          # 真实 Retail SFT/RL 内容、来源和质量审计
    provenance.py            # 任务实体/来源/跨源重复候选的确定性提取与规则
    split.py                 # 簇级、可复现、粗分层的全局划分
    cost_filter.py           # rl_train_full -> rl_train_cost_pruned 可逆过滤
    sft_format.py            # SFT 标准化与角色/Tool Call 映射
    sft_tokenize.py          # Qwen tokenizer + 仅 answer 的 assistant labels
    manifests.py             # 清单、SHA256、Schema、私有证据定位
scripts/
    stage2_audit.py
    stage2_split.py
    stage2_prepare_sft.py
    stage2_check.py
configs/data/
    split_config.yaml        # seed、粗分层字段、目标比例、规则版本
    preprocess_config.yaml   # tokenizer/revision、最长长度、过滤规则
reports/stage2/
    STAGE2_REPORT.md
    source_audit.json
    split_statistics.json
    quality_report.json
    source_manifest.json
docs/
    data_audit.md
    cross_source_overlap.md
    data_split_protocol.md
    rl_cost_filter.md
    sft_preprocess.md
    external_eval_audit.md
data/splits/stage2/         # 可追溯的任务 ID 清单/哈希；无私有场景正文
data/processed/stage2/      # 真实训练 JSONL、tokens、用户私有字段；Git 忽略
data/private/stage2/        # 候选重合证据、人工复核轨迹；Git 忽略
tests/stage2/
    ...
```

如果已有等效文件和路径，优先复用并在验收报告中列出实际产物。不得创建假文件仅为了让目录树看起来完整。公开文件必须不含密钥和用户/任务隐藏参考文本；对训练数据及私有审计证据禁止自动 Git add/commit/push。

## 4. 必须真实执行的测试与证据

测试应使用真实数据的非泄漏聚合统计、具有清晰标注的 synthetic case 和少量离线私有对照；区分**测试程序对 synthetic 夹具通过**与**完成了真实全量审计**。

1. **固定源与全量统计**：锁定数据 SHA，准确读完 Retail SFT/RL；字段缺失、重复、质量/工具 Schema 错误计数可追溯；四份快照按 Stage 0 环境逻辑正确引用。
2. **SFT 来源分组**：同一 `source_dialog_id` 的不同 Turn 永不跨 SFT Train/Val；若有多对话同源簇，整个簇不可跨 Train/Test。
3. **严格重合判定**：同业务不同客户/订单、同客户不同目标、同目标不同相关初态不被自动判为 `confirmed_same_instance`；完整同实例通过；缺关键证据只标候选并保留。不以单一 TF-IDF/embedding 相似度直接删除。
4. **Train/Test 污染检查**：SFT Train、RL Train 与 RL Test 不出现经确认同源的具体任务；RL Dev 不与模型梯度训练数据中同一实例混用；历史暴露 Task 不进入最终 Test。统计高风险未决重合项并呈现真实限制。
5. **粗分层与可重复性**：同样源哈希、配置和 seed 重跑，Task ID 集与 manifest hash 一致；训练/开发/测试 ID 交集为空、重复簇完整、比例和快照/类别/short-medium-long 统计可审计；稀疏类别不报假均衡。
6. **成本过滤**：`rl_train_cost_pruned ⊆ rl_train_full`；每个排除项都有高置信度证据且属于 RL Train 并与 SFT Train 同实例；任何仅类别/单 ID/相似度命中的候选不被剔除；原始 563 条 Task 不丢失，保留完整池和可回退清单。
7. **SFT 格式与 Labels**：测试真实不同 Tool Call 形态及 user/tool/system/history assistant 角色；仅目标 `answer` tokens 参与 Loss；不得出现全 `-100` 仍被当作有效样本、label 长度错位或隐藏评价信息泄漏；验证工具调用边界、特殊 token、截断行为。
8. **Stage 1 集成**：构造未执行的 EvaluationPlan，校验 Task ID / Hash、1 Trial 和 4 Trial 定义，确保每个同 Task 共享快照且不混 run；不产生假 Episode、假 Pass^4、假 Token/GPU 统计。
9. **External Test 审计**：任务数从真实 Fork 读取，检查与本项目数据的重合/来源风险；无法证实时留风险标签，不宣称独立。
10. **Stage 0/1 回归**：执行受影响的 CPU 回归测试，确认数据库快照/官方 R0、已存历史回放分数、EvaluationPlan/metrics 语义均未变化；当前阶段不需要也不得另发付费请求。

实际执行 `pytest`、脚本入口、检查文件哈希、输出生成过程的 exit code、耗时和失败原因。无法取得 tokenizer/依赖时报告 `PARTIAL/BLOCKED`，仍可先完成数据审计/划分部分；绝不能用字符数或手工标签伪装通过 tokenizer mask 验收。

## 5. 验收门槛

| Gate | 条件 |
|---|---|
| S2-A 原始数据审计 | 真实全量数据、文件/版本、字段和来源统计与质量分布可复现 |
| S2-B 跨源重合审计 | confirmed/probable/pattern/unknown 分类有证据，明确 SFT 与 RL 关联能否被实际证明 |
| S2-C 严格划分隔离 | RL Train/Dev/Test 分组不泄漏；Stage 0/1 已暴露任务排除测试；固定 seed、Task 清单/哈希、真实分层统计 |
| S2-D SFT 数据组织 | 完整原始对话分组、SFT Train/Val、质量过滤有记录，所有训练样本可映射回来源 |
| S2-E 成本过滤视图 | 高置信同实例 RL Train 才可从可逆视图排除；保留完整池和回退方案；没发现重复也视为诚实达标 |
| S2-F Qwen 监督格式 | 用实际 tokenizer/chat template 验证 target-only Assistant Token Mask 和 Tool Call 映射；无法验证则部分完成，不谎报 |
| S2-G 评测协议衔接 | 完整内部 test 和 Pass^4 子集预案；Stage 1 ID/哈希/Trial 兼容，未执行正式 Benchmark |
| S2-H 外部泛化候选 | 原版 Retail test 存在性、来源重合、协议适配风险和独立候选清单已审计 |
| S2-I 测试与边界 | Stage 2 + 必要回归实测；无新 API/训练/GPU/官方 R0 修改/隐私泄漏/未授权 Git 提交 |

## 6. 完工报告和人工验收

撰写 `reports/stage2/STAGE2_REPORT.md`，必须回答：

1. SFT 实际源对话和 Turn 数、RL 实际 Task 数；数据完整性、长度/任务类型/快照分布、清洗了哪些样本、原因与数量。
2. **SFT 与 RL 有没有经证明是“同一个具体业务任务”的跨源重复？** 给出 confirmed/probable/unknown 数、匿名化证据、判定规则与不确定性；不许只有“发现很多相似案例”的泛泛结论。
3. 最终冻结的 Train/Dev/Test 各多少 Task、为什么未必严格 70/15/15；历史暴露 Task 如何处理、跨集合污染检查结果、任务类型与长度分层是否平衡。
4. SFT Train/Val 分了多少原始对话及 Assistant Turn，是否保存专家数据质量，是否存在对话跨集合、最终测试污染、哪些数据被隔离。
5. `rl_train_full` 与 `rl_train_cost_pruned` 差多少 Task，是否真的有可靠排除依据；对未来 RL 效果和成本的潜在影响是什么。**不能宣称已经验证节省 GPU/API 费用或 RL 没必要学重复任务。**
6. Qwen Chat Template、Tokenizer 版本、Tool Call 格式和 Assistant-only Loss Mask 的实际测试证据；如未完成精确 Token 标注，明确标注未完成。
7. 原版 τ²-bench Retail test 是否可作为真正的额外泛化集，其来源独立性风险和不能直接与官方排行榜对比的限制。
8. Stage 1 评测计划文件/哈希是否可读取，最终 Pass^1/Pass^4 预算预案，哪些结果尚未执行。
9. 实际命令、测试 PASS/FAIL/BLOCKED、产出文件清单、Git 忽略检查、未修复风险，以及下一阶段 Harness/GPU 环境所需接口。

完成后只进行小范围可读汇报，**停止在 Stage 2 等用户人工验收，不自动进入 Stage 3**。即使本阶段测试都 PASS，也不能声称 Student 已学会使用工具、SFT 已提高 Pass^1 或 GRPO 的训练成本已经下降。

如证据不支持预想：优先报告事实和不确定性，而非为了赶进度用弱相似匹配凑出 RL 去重结果。用户看重的是**严谨、可复现、没有人为制造的性能优势**。
