---
name: policytrace-stage0
description: 为 PolicyTrace-RL 执行 Stage 0 环境与 AReaL Retail 数据兼容性验证；仅在项目初始化、验证 τ²-bench Fork、自定义数据库、任务解析、官方评测与 User Simulator 时使用。通过严格测试及人工确认后再进入后续阶段。
---

# PolicyTrace-RL · Stage 0：环境与数据兼容性验证

> **角色**：你是本项目的工程实施助手 Codex。你的任务是建立一套可重现、可测试的 τ²-bench Retail / AReaL 数据兼容环境，并客观报告证据。**不要在本阶段实现 SFT、OPD、GRPO、完整 Agent Harness 或自定义 Reward。**
>
> **预计时间**：项目 Day 1–3；本地优先使用 Windows + WSL2（Ubuntu 22.04、Python 3.11），CPU 即可完成绝大多数测试。
>
> **工作方式**：检查已有仓库 → 简述执行方案 → 小步实现 → 执行测试 → 留下可复现实验记录 → 停止并等待用户人工验收。不要用未执行的测试、模拟输出或推断代替验证。

## 0. 本阶段唯一目标与边界

基于下列上游源，证明 **AReaL 的 Retail SFT/RL 数据能够被正确读取，RL Task 能在指定数据库状态下执行，且官方评分器能用与 Rollout 一致的任务初态进行评分**：

- τ²-bench 适配 Fork：`https://github.com/dhh1995/tau2-bench`，优先分支 `dhh/async-and-custom-completion`。
- AReaL 官方 τ² 示例：`https://github.com/areal-project/AReaL/tree/main/examples/tau2`；仅作为接口、依赖与流程参考，不安装整个 AReaL 训练框架。
- 数据集：`https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data`；关注 `tau2_sft_train.jsonl`、`tau2_rl_train.jsonl` 与 `tau2_rl_database/`。
- 项目总体要求以仓库内《项目计划.docx》或用户提供的 PolicyTrace-RL V4.0 计划为准；**本 Skill 仅覆盖其中 Stage 0**。

明确不做：训练模型、下载 3B/7B/14B 权重、设计新的 RL 奖励函数、正式划分/清洗训练集、跑 Base 成绩、搭建 TRL、接入 vLLM、引入 Ray/verl、大规模任务遍历、宣称基准得分。需要编写的代码以**可独立测试的最小适配层**为限，不能改造为完整 Harness。

## 1. 执行原则（必须遵守）

1. **先检查现有项目**：查看目录、Git 状态、当前环境和已有文件。不得覆盖用户的工作；如发现未提交的修改，避免破坏性操作。
2. **实际源码优先**：本文中的 API 名称、路径、示例只是候选。必须阅读**所选 Commit** 下的真实 Python 类、函数签名和测试，再调用；不可凭旧文档臆造接口。
3. **冻结来源**：记录 Fork 完整 40 位 Commit SHA、数据集 Revision SHA、Python 版本、依赖版本和下载文件 SHA256。仅记录分支名不算版本锁定。
4. **区分三类事实**：`PASS`（执行并留下可核查证据）、`FAIL`（执行后失败）、`NOT_RUN/BLOCKED`（尚未执行或条件缺失）。任何模拟或跳过测试都不能记为 PASS。
5. **用户授权优先**：安装包与下载公开数据可按用户当前指示执行；涉及付费 API、云 GPU、长期服务、写入外部仓库、提交或推送 Git，先征得用户同意。不得输出或提交 API Key。
6. **最小侵入**：尽量在本项目新建兼容层，不直接修改 `site-packages` 或上游 Fork。确实需要补丁时，以单独 patch / subclass / adapter 实现，写清作用并添加回归测试。
7. **官方评分不变**：确保调用官方 Evaluator 的实际实现与语义；只能修复数据库初态传递等兼容问题，不能为了让测试通过而直接返回自定义分数或修改评分规则。
8. **避免泄漏**：`user_scenario` 只提供给 User Simulator，`evaluation_criteria` 仅供评分与本阶段验证，不得进入未来 Student 可见 Prompt。
9. **结果可重现**：所有测试设置固定 seed、明确 Task ID、源代码 SHA、数据 SHA，报告失败样本和错误栈，避免静默跳过异常。

## 2. 工作顺序与具体任务

### Step A：环境预检、Fork 安装及版本锁定

- 确认运行于 WSL2/Linux，获取 `uname`、Python、Git、CPU/RAM/剩余磁盘情况。优先 Python 3.11；如不兼容，先验证并汇报调整理由，不要自行大范围升级系统。
- 建立独立虚拟环境（`.venv`），先安装 Stage 0 所需 CPU 依赖；**不要仅为 Stage 0 安装 CUDA/PyTorch/Transformers/TRL**。
- 获取指定 τ²-bench Fork 并定位分支存在的 Commit；验证其 Retail 环境代码、`Task`、`EvaluationCriteria`、`RetailDB`、工具调用与 Evaluator 实现。
- 检查 `TAU2_DATA_DIR` 的真实用途，按上游实现正确设置路径；执行最小 `import tau2`、Retail 环境构造、默认数据库加载等 Smoke Test。
- 若原 Fork 已删除/更改接口，应查阅其 Git 历史和 AReaL 示例所需接口，选择可解释的兼容 Commit；**不得未经验证自动切换到 τ³ 的最新主干**。

交付：`reports/stage0/environment.md`、`reports/stage0/versions.json`、依赖锁定文件。

### Step B：下载并审计 AReaL 数据格式（此阶段只审计，不清洗）

- 先检查 Dataset Card 与仓库文件列表；记录 Revision 和文件尺寸。只下载所需的原始 SFT/RL JSONL 和 Retail 数据库快照（可先下载 RL + Retail DB，SFT 如网络/磁盘不足可先按流式读取抽样，需如实记录未完整下载）。
- **直接读取原始 JSONL**，不依赖 Hugging Face 网页预览或自动推断出的嵌套 Schema。
- 审计 Retail 的样本数量、Task ID 唯一性、RL `db_path` 分布、关键字段的数据类型、引用文件是否存在、SFT 典型 `messages`/`answer`/`metadata` 结构。对 SFT 仅抽检；不预先训练或重新划分数据。
- 检查典型 RL 字段：`id`、`description`、`user_scenario`、`evaluation_criteria`、`db_path`。注意 `evaluation_criteria` 在 AReaL 中可能为 JSON **字符串**而非字典；字段内 `actions` 是评分期构造参考目标状态的信息，不是强制 Agent 走的唯一动作顺序。
- `db_path` 必须解析为数据集目录下的实际文件，禁止用未校验的路径访问任意文件。记录 snapshot SHA256，检查多个 Retail 快照的加载情况。

交付：`reports/stage0/data_schema.md`，以及只含统计信息、不泄漏隐藏任务条件的 `reports/stage0/data_audit.json`。

### Step C：构建最小任务与数据库兼容层

实现最少量的 Python 代码，允许后续 Stage 1–3 复用：

1. `load_retail_task(raw_record)`：解析并校验 RL 任务；把字符串化的 `evaluation_criteria` 转成 Fork 所需结构，保留原始任务 ID、环境配置和来源索引。
2. `load_retail_db(db_path)`：加载该 Task 的原始 `RetailDB` 快照；校验 JSON 与模型 Schema，不修改磁盘源文件。
3. `make_retail_env(task, initial_db)`：基于所选 Fork 的真实工厂/API 创建隔离环境；Fork 如支持 `get_environment(db=...)`，优先复用它。禁止忽略任务 `db_path` 而偷偷回退到默认 Retail 数据库。
4. `evaluate_with_correct_initial_state(...)`：通过官方 Evaluator 完成评分；需研究它是如何新建环境的，并确保目标状态重放、执行轨迹评分与 Agent Rollout 的初始 DB 完全一致。

接口具体命名可以按已存在的工程风格调整，但必须拥有等效功能、类型注解、错误说明和测试。**不要自己重新实现 Retail 业务工具、政策逻辑或官方评分规则。**

至少覆盖以下单元测试：

- `evaluation_criteria` 字符串 / 字典合法转换；异常 JSON 能明确报错。
- 不存在的 `db_path`、越界路径与结构错误的数据会拒绝加载；不会静默使用默认 DB。
- 相同 `db_path` 读取的两个独立环境具有相同初始内容；一个环境操作后另一个不受影响。
- 同一 Task 多次 reset/重新实例化后的初始数据库内容哈希一致；工具操作不污染原始 snapshot。
- 默认数据库与自定义数据库路径的区别可通过明确测试观察到。

**特别注意**：仅“Agent 执行环境加载了自定义 DB”还不够。要测试“评分器使用的期望目标数据库”是否从**同一自定义初态**构建。若原评分器固定默认环境，应加最小注入/适配并展示修复前后的对照测试。

交付：兼容层实现和 `tests/stage0/` 自动测试。

### Step D：官方 Reward / 参考动作的可验证性测试

- 阅读实际 Fork 中 Task、工具调用、模拟器、参考动作回放、Evaluator 的代码路径，绘制简短数据流说明。
- 从 Retail RL 任务中按**固定 seed 和确定性 Task ID 排序**选择 5–10 个用于 Stage 0 的任务。尽量覆盖多个 `db_path`、至少一种数据库变更操作和一种其他任务类型；若样本不适配，如实列出原因并补充候选。
- 使用上游提供的**参考动作/任务状态构造机制**检查期望目标状态是否能形成，并验证读取的快照与评分环境一致。不能假设 `evaluation_criteria.actions` 总能无条件逐条当成 Student 工具调用执行；如需用户参与或执行前置条件，按官方数据结构处理。
- 执行少量合法与非法工具调用，确认 Observation/错误处理符合 Fork 规范。合法调用不代表最终任务必定成功。
- 最少对 2 个涉及 DB 状态修改的任务验证：参考目标状态与真实工具执行后的终态比较逻辑能够正常工作；同时针对不同初始 DB 做防误配测试。
- 对每个样本保存 Task ID、快照文件、操作/预期、官方 Evaluator 原始输出或异常、复现命令及耗时。**不把参考动作完全一致作为唯一成功标准。**

结果中应区分：`task_loaded`、`db_loaded`、`tool_executed`、`evaluator_invoked`、`evaluation_validated`、`task_success`。评分正确调用和 Agent 成功完成任务不是一个概念。

交付：`scripts/stage0_smoke.py`、`reports/stage0/smoke_results.json`、对应 pytest 测试。

### Step E：User Simulator 的最小真实交互检查

Retail **不支持 `solo_mode`**。要先确认 Fork 中官方双向交互流程、所需 Simulator 接口和结束条件。

1. 测试本地模拟接口层的参数与消息路由：Agent 可见历史与用户私有指令严格分离；用 Mock 用户回复测试状态机，不调用付费 API。
2. 在用户提供**且同意使用** API/服务的前提下，固定 Simulator 的提供方、精确模型名/版本、采样设置和主要参数，真实运行至少 1–2 条简单 Retail Episode，记录工具调用、终止状态、API 费用或 Token 消耗。
3. 若目前没有 API 或网络服务，Mock 测试只能记为 `PASS(mock)`；**真实双向 Episode 验收必须记为 `BLOCKED`，Stage 0 不得宣称完全通过**。同时给出最少配置步骤与预计验证范围，不要求用户交出明文密钥。
4. 不要使用 `solo_mode=True` 绕过 Retail 限制，也不要私改 Simulator/Benchmark 以制造成功记录。

交付：`reports/stage0/user_simulator.md`；可选 `scripts/stage0_user_sim_smoke.py`。

## 3. 期望项目结构（允许尊重已有结构做小范围调整）

```text
PolicyTrace-RL/
├── .gitignore
├── pyproject.toml                # 仅 Stage 0 必需依赖；或 requirements-stage0.txt
├── uv.lock / requirements-stage0.lock
├── src/policytrace/stage0/
│   ├── task_loader.py
│   ├── db_adapter.py
│   └── evaluator_adapter.py
├── scripts/
│   ├── stage0_smoke.py
│   └── stage0_user_sim_smoke.py   # 条件允许再添加
├── tests/stage0/
│   ├── test_task_schema.py
│   ├── test_db_isolation.py
│   └── test_evaluator_integration.py
├── reports/stage0/
│   ├── environment.md
│   ├── versions.json
│   ├── data_schema.md
│   ├── data_audit.json
│   ├── smoke_results.json
│   ├── user_simulator.md
│   └── STAGE0_REPORT.md
└── data/raw/                    # 数据缓存，必须被 .gitignore 忽略
```

- 上游 Fork 推荐置于 `external/tau2-bench/` 或单独目录，以 editable 安装方式引用；避免把上游完整历史混入业务源码。
- `.gitignore` 应覆盖 `.venv/`、`data/raw/`、数据库快照、本地密钥、`.env`、大日志与缓存；提交的仅是轻量统计/测试报告及必要的适配代码。
- 保证本地无 GPU 时也能运行全部**不依赖真实模型**的自动测试。
- 所有脚本统一使用从项目根目录运行的明确命令；CLI 参数如 `--task-id`、`--limit`、`--seed`、`--data-root` 应合理提供，不强制绑定开发者个人绝对路径。

## 4. 验收门槛（必须逐项给出证据）

| 门槛 | 合格要求 | 失败/未执行时 |
|---|---|---|
| G1. 固定版本 | Fork 全 SHA、Dataset Revision、Python/依赖版本均已记录 | BLOCKED，不能声称可复现 |
| G2. 数据解析 | SFT 基本字段抽检、Retail RL 样本与 DB 路径可解析，非法样本有日志 | FAIL 并列出异常任务 |
| G3. 环境隔离 | 不同任务/同任务重复执行的 DB 初态一致、改动互不污染 | FAIL，必须先修复 |
| G4. 官方评分 | 至少 5–10 个固定样本完成目标状态/工具/评分链路检查；评分器使用正确初态 | FAIL/BLOCKED，逐项标注 |
| G5. 双向交互 | Mock 链路验证通过，并至少 1–2 个真实 User Simulator Episode 完成可解释的终止 | 无 API 则 BLOCKED，不得宣称最终 PASS |
| G6. 自动化 | `pytest` 和 Smoke 脚本有实际运行结果、复现指令和保存的日志 | NOT_RUN 不算 PASS |
| G7. 人工验收 | 编写总结、风险和后续建议，**明确等待用户确认** | 禁止自动进入 Stage 1 |

Stage 0 的最终状态只允许：`PASS`（所有必需门槛已通过）、`PARTIAL/BLOCKED`（确切指出缺失条件）、`FAIL`（已验证存在未解决错误）。**Stage 0 PASS 不代表 SFT/OPD/GRPO 训练链路已经可用。**

## 5. 故障处理规则

- Fork 接口或分支不存在：检查官方 AReaL 示例指向、Git 历史、真实 Commit；记录调查证据，不自行降级到 τ³ 或换用陌生框架。
- 下载失败/带宽不足：记录请求的文件、大小和具体报错；支持恢复下载，优先仅下载 Retail 相关文件；不以伪造数据代替真实兼容测试。
- 数据 Schema 不匹配：保留原始 JSONL，给出字段 Diff，编写最小 adapter 和测试；不得修改原数据来掩盖不兼容。
- DB 正确但 Reward 错误：重点检查默认 DB 与任务 `db_path` 是否被评分器分别使用、参考动作重放起点是否相同、评分所需沟通条件是否缺失；不要直接改分数。
- 评分返回 0：区分“模型确实未完成任务”和“任务/数据库/评分器接口不一致”。参考操作回放与最终对话评分是不同层次的测试。
- Mock 成功、真实 API 失败：记录模型版本、Provider 报错、模拟用户异常/终止情况，停止付费重试并向用户确认。
- 项目已有大量工作：避免覆盖和无关重构；先复用已有模块、提出最小修改范围。

## 6. Codex 结束时必须给我的报告格式

在 `reports/stage0/STAGE0_REPORT.md` 保存并在聊天中简洁汇报：

```markdown
# Stage 0 验收报告

## 结论
PASS / PARTIAL-BLOCKED / FAIL

## 固定版本
- tau2 Fork URL + Branch + 40 位 SHA：
- Dataset URL + Revision：
- Python / OS / 核心依赖：
- 数据文件与快照校验信息：

## 测试执行结果
| Test ID | 验证内容 | PASS/FAIL/BLOCKED | 证据（命令/日志/文件） |
|---|---|---|---|

## 已确认的兼容点
...

## 尚未解决的问题及根因
...

## 修改/新建的文件
...

## 复现命令
...

## Stage 1 的依赖与建议
...

## 需要用户决定的事项
...
```

## 7. 现在立即执行的动作

1. 阅读仓库现状及本 Skill，报告你发现的操作系统、Python 版本和工作目录。
2. 给出 **不超过 10 行的 Stage 0 子任务计划**和预计产生的文件；若仓库已有代码，说明如何避免冲突。
3. **直接开始** Step A → B → C → D；除非需要付费 API、外部写操作、破坏性修改或用户未提供的关键权限，否则不必每个小步骤都等待确认。
4. Step E 若无真实 User Simulator API，可先完成 Mock 与文档，明确 BLOCKED 并询问用户是否配置 API。
5. 运行测试、保存报告、提交执行总结。**然后停止，不进入 Stage 1，不生成训练脚本。**

**成功的核心证据**：给定 AReaL 的 Retail Task 和对应 `db_path`，能从完全隔离的正确数据库状态初始化环境，调用真实工具，使用官方逻辑正确评测，且可复现。其他功能均属于后续阶段。
