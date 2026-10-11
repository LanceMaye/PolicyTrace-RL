---
name: policytrace-stage1
description: 为 PolicyTrace-RL 执行 Stage 1「统一评测系统与可扩展 Reward 框架」。在 Stage 0 的 τ²-bench Retail / AReaL 兼容层之上，固定官方评测语义、实现离线评测指标与官方 R0 奖励封装、设计未来 R1 扩展边界，并产出可复现的测试和阶段验收报告。仅在用户明确要求进入 Stage 1 时使用。
---

# PolicyTrace-RL · Stage 1：统一评测系统与可扩展 Reward 框架

> **执行对象：Codex。** 这是需要真正查看仓库、编写少量可复用代码并执行测试的工程任务，不是只讨论方案。项目的核心目标是**提高多轮 Tool-Use Agent 的任务成功率与可靠性**；Benchmark 是验证工具，Reward 是可迭代的训练手段。Stage 1 **不要求设计出最终 Reward 或证明新的算法有效**。
>
> **预计工作量：1–2 天。** 本地 Windows 或 WSL2 / Ubuntu CPU 即可；沿用 Stage 0 现有环境。先做现状审查和简短计划，再小步开发、测试、报告；最后停止，等待用户人工验收。

## 0. 先确认项目状态与任务边界

开工前必须阅读真实仓库代码、已存在的测试和报告，尤其是：

- `reports/stage0/STAGE0_REPORT.md`（名称以仓库实际位置为准）、`data_schema.md`、`user_simulator.md`、`docs/stage0_walkthrough.md`（若存在）。
- `src/policytrace/stage0/`、`tests/stage0/` 中的 Task/数据库快照加载、官方评测适配、轨迹回放代码，以及现有 `pyproject.toml`、依赖锁和 `.gitignore`。
- 已固定的 τ²-bench Fork：`https://github.com/dhh1995/tau2-bench`，Commit `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`。
- 已固定的 AReaL 数据集：`inclusionAI/AReaL-tau2-data`，Revision `86971dc03da6e7c1a7933295e05b84aab8215386`。

**Stage 0 已验收结果（仅作背景，不能伪称本轮重跑）：** Windows 44 项测试通过，Retail 563 条 RL Task 完成 Schema 审计，4 份快照可用；WSL2 完成小规模 CPU 复验；两条 DeepSeek 真实 Episode 的官方 Reward 分别为 0、1。WSL2 并未完整复跑 Windows 全部 44 项；AutoDL/GPU 训练环境尚未验证。具体细节以当前仓库最新报告为准。

**本阶段允许：** 阅读业务政策与上游 Evaluator；实现官方 R0 封装、评测结果统一结构、离线聚合指标、少量可控的诊断接口、文档与单元测试；在需要时复用 Stage 0 回放证据。

**本阶段不允许：** 新的正式数据划分/清洗、实现 Agent Harness 主循环、跑 Base 模型基线、下载模型或执行 SFT/OPD/GRPO、安装 GPU 训练栈、调用付费 API、创建或实际启用 R1 数值公式、重写 Retail 业务逻辑或官方 Evaluator、为提高分数调整 Benchmark、擅自提交/推送 Git。

Stage 1 只**规定数据隔离和评测协议的规则**。训练集/开发集/测试集的实际 Task ID 划分及排重由 Stage 2 完成，当前不可自行拍定最终测试集。

## 1. 不可妥协的执行原则

1. **阅读实际实现，不猜 API。** 先定位锁定 Fork 的 `Evaluator`、`RewardInfo`、`EvaluationCriteria`、`DB`、`COMMUNICATE`、`reward_basis`、任务终止与聚合逻辑。记录代码路径/函数和真实语义；不从通用 τ-bench 文章想当然推断。
2. **复用 Stage 0。** 既有快照感知评分适配已经解决「Rollout 与参考状态评分使用不同初始 DB」问题；直接复用或小范围提炼，避免复制出第二份 Evaluator。
3. **官方评分是不可变真值。** `official_reward` 必须来自真实官方评分路径，不准重算为某个自定义猜测值；保留原始 RewardInfo、终止原因、组成项与版本证据。未来训练 Reward 可以有 R1/R2，但官方评测永远独立、不被污染。
4. **公平对照。** 统一模型输入协议、环境版本、Task、用户模拟器配置、试验重复次数、最大步数/上下文限制和聚合算法。任何后续变化必须作为实验配置显式记录。
5. **没有日志就不造指标。** 未记录的 Token、耗时、GPU 时间、Teacher 成本等保留 `null` / `not_available` 并标注原因；不得用字符数代替真实 Token，不得将 LiteLLM 默认的零费用当作真实账单。
6. **安全与隐私。** 不打印/提交密钥、私有 `user_scenario`、`evaluation_criteria`、完整含敏感信息的用户 Prompt、未脱敏轨迹或数据库快照。原始完整日志可在 Git 忽略的私有目录中使用；提交可审计的脱敏指标、哈希和统计即可。
7. **实证标记。** `PASS`、`FAIL`、`NOT_RUN`、`BLOCKED` 明确区分。禁止用人工构造的四次成功记录宣称已有 Pass^4 实验成绩。遇到上游不支持的字段或接口，解释并提出最小兼容方案，不静默补默认值。
8. **小步实现。** 优先标准库、pytest、已有依赖；不要为这个阶段引入大规模训练框架、数据库服务或仪表板。

## 2. 工作流程

### Step A：审计上游 Evaluator 并冻结评测协议

先做源码调研和文档，**再决定接口和统计口径**。

必须明确：

- 本项目 Retail Task 当前默认 `reward_basis` 是否为 `[DB, COMMUNICATE]`，两者各如何判断和如何聚合。`evaluation_criteria.actions` 如何用于构造目标数据库，为什么不意味着必须逐步匹配参考轨迹。
- Reward/成功状态返回值的实际类型、区间、空值和异常；成功与工具格式正确、政策合规、用户模拟忠实度之间的区别。
- 必须使用同一任务初始数据库完成预测状态与参考状态比较；保持 Stage 0 快照隔离机制。
- 结束条件：用户结束、Agent 结束、步数上限、工具调用异常、Orchestrator/网络异常；评分未完成与官方判失败应分别记录。
- `retail_131`（`United States` vs `USA`，原官方 Reward=0）与 `retail_152`（原官方 Reward=1，但用户模拟器提前披露信息）的意义：这是诊断与讨论的例子，不允许修改上游评分器以改变原结果。

正式输出 `docs/evaluation_protocol.md`，至少包含：

**主指标：**

- `Pass^1`：在给定任务集合上，每个 Task 运行一次的官方成功比例，分母为按协议纳入的任务数。明确意外执行失败是如何计入、是否允许重试；不能静默丢掉失败任务。
- `Pass^4`：对**每个相同 Task 独立进行四次 Trial**，该 Task 必须四次都官方成功才算通过，然后对 Task 求比例。它**不是**至少一次成功的 `Pass@4`，也不应通过 `(Pass^1)^4` 估计作为正式成绩。
- 如 Trial 缺失、Task 重复、版本/用户模型不一致，要给出明确拒绝汇总或 `incomplete` 状态，不能假装完成四次。
- 后续正式结果需记录 Task 集合版本、每个 Task 的四次结果、环境 Commit、Dataset Revision、模型 Checkpoint、User Simulator 名称/配置、采样参数、Trial ID/Seed、评价时间及协议版本。API 的 seed 若不受支持不能承诺逐 Token 可重现。

**辅助指标及明确分母：**

- Tool Call Error Rate：区分模型 Tool JSON/Schema 解析失败、工具执行返回错误、框架异常；至少提供 `失败调用数 / 尝试调用数`，并保留每 Episode 的分布。
- Episode 异常终止率：异常终止 Episode 数 / 已启动 Episode 数；与“合法结束但任务失败”分开。
- 平均/中位工具调用次数、总调用次数、任务耗时；必要时附成功/失败分组统计。
- Student 生成 Token、User Simulator Token、Teacher Token、API 使用量及成本，尽可能按角色分开。无可靠记录则明确缺失。
- 官方 Reward 分布、分任务/任务类型的结果（若类型标签尚未形成则预留）。
- GRPO 阶段未来记录的 Group Reward 均值、方差、全零组 / 全同奖励组比例、有效组比例、KL、Clip Fraction；本阶段**只定义 Schema 与含义，不假造训练数值**。
- GPU 用时、Teacher 推理成本、训练 Token 与计算效率：只定义报告字段和单位，待训练阶段填充。

明确训练用数据与最终评价任务不能泄漏：Stage 1 不锁最终 Task ID；要求 Stage 2 在训练之前完成来源对话/任务归并、近重复审计和最终测试集合冻结。

### Step B：统一 Episode 结果格式和离线指标聚合

尽量建立一个独立、轻量、可被 Stage 3 Harness 和后续 TRL 训练调用的模块。建议路径（可按真实项目结构调整）：

```text
src/policytrace/evaluation/
    schema.py             # Episode/Trial/Run 元数据与官方评分结果结构
    metrics.py            # Pass^1 / Pass^4 及工程指标的纯函数聚合
    official_adapter.py   # 复用 Stage 0 的官方评分适配，仅负责统一输出
src/policytrace/rewards/
    official.py           # R0: official reward 的无损包装
    interface.py          # 后续实验奖励插件接口/配置契约（不实现 R1）
configs/evaluation/
    protocol.example.yaml # 可参考配置，不含密钥、真实私有任务内容
tests/stage1/
    ...
docs/
    evaluation_protocol.md
    reward_analysis.md
    reward_backlog.md
reports/stage1/
    STAGE1_REPORT.md
```

最小 Episode/Trial 记录建议包含：`task_id`、`trial_id`、`model_id/checkpoint`、`domain`、`environment_sha`、`dataset_revision`、`db_snapshot_id/hash`、`simulator_config_id`、`seed`（可为空）、`termination_reason`、`official_reward`、`reward_components`（上游有则存）、`success`（定义须按官方语义）、工具尝试/错误计数、耗时、Student/User/Teacher Token usage（允许为空）、API 费用统计（明确币种和估算/实账类型）、轨迹定位 ID、时间戳和数据版本。

要求：

1. 定义结构化对象（现有项目已采用 Pydantic 则可继续使用）和 JSON/JSONL 序列化；完整轨迹不必复制到汇总结果，可用私有路径或哈希引用。
2. 建立离线聚合入口，读取多条 Episode 结果、校验重复/缺失/版本不一致，输出 Task 级与整体 Summary JSON；按需提供短的 Markdown 表格或 CSV。
3. `Pass^4` 必须显式分组 `(task_id, trial_id)` 并验证四个完整 Trial；不允许把不同任务的四条轨迹归一组。
4. 非成功的基础设施异常、确实失败、无法评分、未运行，应分别在原始记录中保留；聚合策略公开且可审计，默认不能悄悄删掉对模型不利的 Trial。
5. 该模块不依赖 TRL/GPU，也不依赖完整 Stage 3 Harness；支持将来从实际 Rollout 日志构造 EpisodeRecord。

### Step C：建立 R0 与未来 R1 的扩展契约

**R0 = 官方原始 Reward。**

- 奖励函数通过 Stage 0 的快照感知官方评测路径取得官方结果；暴露 `official_reward` 和可用的官方分项信息，不私自加权、不规范化业务字段、不加入步数罚分。
- 未来训练 R1 应是**单独命名、配置可选、带版本与分量记录**的 `training_reward`；定义接口允许使用 `Episode` 的可验证、非隐藏泄漏信号，但默认不会自动启用任何 R1。
- 官方评测指标永远调用 R0 / 官方 Evaluator；严禁将 R1 的数值写回 `official_reward`，严禁根据隐藏 `evaluation_criteria` 向 Student 泄漏目标答案或作为在线动作提示。
- 明确 SFT 与 OPD 不需要直接使用 R0 作为其监督目标；GRPO 初始训练使用 R0，后续 R1 是条件性研究项目。
- 在文档中写出示意设计（不是实现要求）：`R_train = R_official + λ * R_verified_aux`，`λ` 暂不定值；并注明稀疏奖励/全零组本身不足以证明奖励函数有缺陷，可能需要改采样或任务难度。

`docs/reward_analysis.md` 要用实际 Fork 源码解释已评分和未充分评分的行为，包括 DB、COMMUNICATE、流程合规、工具异常、重复动作、长轨迹和 User Simulator 偏差；每个判断注明源码依据或标为待验证。

`docs/reward_backlog.md` 保留 3–6 个**候选问题/想法**，每项只需写清：

- 可能出现的具体行为问题与证据来源（如果未观察到，明确标为假设）。
- 已有官方 R0 能否检测、缺失的究竟是评分信号还是诊断信息。
- 可验证性和潜在 Reward Hacking / 过度拒绝 / 错误归因风险。
- 需要等待哪一种真实轨迹统计才值得实施。
- 值得后续阅读的论文主题/检索关键词（如 verifiable process reward、step-level credit assignment、trajectory-level reward、DAPO dynamic sampling、GSPO），**不需要在 Stage 1 复现论文或声称这些就是本项目创新**。

对“长轨迹最后失败，哪一步造成失败”要特别谨慎：流程检查/中间状态变化可以定位嫌疑步骤，但不能未经反事实或其他证据就声称某一步是唯一因果责任者。

### Step D：测试、样例与回归

不调用任何付费 API。优先使用 Stage 0 的**可离线回放**证据与脱敏夹具；若真实结果格式不便复用，则构造明确标为 synthetic 的公开测试夹具，不能把它当模型评测结果。

必须测试：

1. R0 调用与 Stage 0 官方评分适配一致；数据初态由指定 `db_path` / snapshot 决定，不回退到默认 DB。至少验证一条正确数据库结果、一条错误数据库结果。
2. `retail_131`：原官方 Reward 仍为 0；离线字符串规范化反事实只能作为诊断另存，不覆盖原分数。`retail_152`：若有可回放证据，原 Reward 仍为 1；Simulator 偏差单独记录而不篡改 Agent 官方得分。
3. `Pass^1` 对 0/1、空集合、重复 Task、异常终止有明确结果或报错；不可静默处理分母。
4. `Pass^4` 对某 Task 全四次成功、一次失败、缺少 Trial、重复 Trial、同 Task 配置不一致分别得到正确结果或清晰报错；至少有一例证明它和 `Pass@4` 不同。
5. 工具异常与工具调用错误率的分母正确；零调用 Episode 可安全处理；Token/耗时未知时输出 `null` 而不是 0。
6. `training_reward` 插件接口不得改变 `official_reward`；无需实现真实 R1，可使用测试替身验证接口隔离。
7. 在 Windows 或 WSL2 当前可用环境运行 Stage 1 pytest，并执行必要的 Stage 0 回归测试，报告实际执行命令、结果、耗时。不要把 Stage 0 的历史通过情况冒充本次结果。

### Step E：文档、可复现入口与验收报告

形成简洁的 `reports/stage1/STAGE1_REPORT.md`，至少汇报：

- 新增/修改的文件以及复用了哪些 Stage 0 模块；为何有这些设计。
- 官方 Reward 的真实组成和上游源码定位；遇到评分与工具/流程合规不一致的边界案例。
- 评测协议版本、指标的分母、Pass^1/Pass^4 定义、任务隔离规则，以及尚未冻结的 Task 划分。
- R0 的接入方式、R1 扩展接口（仅接口）、候选 Reward Idea 的优先级与仍需证据的假设。
- 实际执行的测试命令、测试数量、PASS/FAIL/BLOCKED；如有失败，给出修复或下一步最小验证策略。
- 下一阶段需要 Stage 2 提供的输入（Task 划分清单、来源分组、去重/泄漏审计、SFT 数据组织等）。
- 明确说明本阶段**没有生成 Base/SFT/OPD/GRPO 的正式 Benchmark 分数**、没有大规模真实 Episode、没有训练或实际 Reward 优化。

只提供可以在本地 CPU 重复运行的入口，例如：

```bash
python -m pytest tests/stage1 -q
# 下面的命令只是推荐形式，必须以你最终实际实现的参数和文件为准；不可空造执行成功记录：
python scripts/stage1_eval_offline.py --input <PRIVATE_OR_SYNTHETIC_FIXTURE> --output <LOCAL_REPORT_PATH>
```

如已有等效脚本，不要为了路径一致另建重复工具。

## 3. 验收门槛

| 编号 | 验收项 | 达标标准 |
|---|---|---|
| S1-A | 官方评测语义审计 | 解释 DB、COMMUNICATE、聚合、异常与阶段适用性；标注真实源码位置 |
| S1-B | 指标协议 | Pass^1 / Pass^4 的分组、分母、完整性校验清楚；工程指标有定义与单位 |
| S1-C | 可执行的离线聚合 | Stage 1 Python 模块/CLI 能处理真实或明确标注的合成 Episode 记录 |
| S1-D | 不变的官方 R0 | 接入 Stage 0 快照感知评分；真实回放分数不变；奖励扩展不污染官方结果 |
| S1-E | 可扩展接口与研究记录 | R1 只设计接口，形成有证据状态的候选想法，不拍定权重、不伪造实验收益 |
| S1-F | 测试与复现 | pytest 及必要 Stage 0 回归实际运行通过；报告真实命令和证据 |
| S1-G | 阶段边界 | 无付费 API、无模型下载/训练、无正式数据划分、无越权推送；完成后停止等待人工验收 |

**完成后给用户的最终汇报应回答：**「我们现在用什么标准衡量 Agent 是否进步？官方 Reward 具体在奖励什么、忽略什么？将来加入过程奖励如何不污染 Benchmark？当前代码与测试能够证明什么？还缺少哪些数据？」

**如未全部达标：** 标记 `PARTIAL` / `BLOCKED`，列出最小阻碍，不要为凑齐 PASS 修改官方评分、改动上游工具或假造数据。不得自动进入 Stage 2。
