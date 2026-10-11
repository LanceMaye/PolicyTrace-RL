---
name: policytrace-stage3-0
description: 在 PolicyTrace-RL 已完成的 Stage 0–2 基础上，离线搭建并验收轻量、训练感知的 τ²-bench Retail Agent Harness：复用固定 Fork Orchestrator、现有快照/官方 R0/冻结划分与 Qwen Tokenizer/Parser，建立可替换的 Student Model Adapter、完整轨迹和决策级 Token 上下文日志、离线 UserSimulator、工具与策略诊断及 Stage 3_1 GPU 基线接口；不调用真实模型或付费 API，不训练、不跑 E0 真实基线。仅在用户明确要求 Stage 3_0 时使用。
---

# PolicyTrace-RL · Stage 3_0：离线搭建 Agent Harness（不跑真实 Base）

> **执行对象：Codex。** 本文件是需要在用户现有 PolicyTrace-RL 仓库中落地并真实运行测试的工程 Skill，不是建议性说明。**只完成 Stage 3 的第 0 步——Harness 代码、离线交互闭环、日志协议、接口和验收。** 用户尚未租 GPU；**Stage 3_1 才接入真实 Qwen2.5-3B-Instruct + DeepSeek User Simulator，执行 E0 Base Smoke Test、测时和 Dev 基线。** 本阶段结束即停止，等待用户审查。
>
> **核心原则：复用固定 τ²-bench Orchestrator，不重新造一套 Agent Loop；完整保留原始执行轨迹，但模型看到的上下文需通过明确版本化的投影接口生成；为未来 OPD/GRPO 记录逐次决策的 Token 精确信息及来源，不提前实现训练器。** 最小可用、低成本、可追溯胜过过度架构。

## 0. 阶段边界与绝对限制

- 仅使用现有 Windows / WSL2 CPU、已有项目依赖和现有 Qwen Tokenizer（无模型权重）。如本机缺少可用 tokenizer/依赖，先检查原路径及缓存，报告 BLOCKED；不得偷偷安装庞大 CUDA 环境。
- **禁止**新的 DeepSeek 或其他付费模型 API 调用；禁止租用 AutoDL / GPU、下载 Qwen 模型权重、真实 Student 前向、OPD/SFT/GRPO 训练、执行 E0 真正模型基线或正式 Pass^1/Pass^4。
- **不运行或检查冻结的 RL Test 真实任务内容/最终模型轨迹**；不使用原版外部 τ² Retail test 做调试。开发时只使用已暴露 Dev Task、合成夹具和合法的结构化离线脚本；最终 Test ID manifest 仅可用于边界/哈希完整性检查，不得做新的评分、诊断或轨迹暴露。
- 不修改上游 τ²-bench Fork、Retail Policy、工具 Schema、四份原始 DB、User Simulator 原始设定、Evaluator、官方 R0、数据 revision、Stage 2 冻结 Train/Dev/Test、SFT Main 数据及 Token。不得为测试方便放宽业务规则、伪造 Reward 或覆盖历史报告。
- 禁止 `git commit/push`、初始化/改动不必要的 Git 配置；密钥/场景正文/数据库/真实轨迹/含隐私或隐藏评分的数据只存现有 Git 忽略的私有目录。确认 `.env`、JSONL、token/轨迹、manifest 保护有效。
- 凡由 FakeModel / ScriptedUser / synthetic Fixture 产生的 Episode，必须标注 `source=mock|synthetic`、`purpose=diagnostic`；**不能称 E0、Base 推理、真实 Benchmark、正式成功率或 Pass^1**。工具调用和官方 Evaluator 在这些轨迹上得到的值只算协议诊断。
- 当前阶段只提供**调用真实模型的可替换接口与配置草案**。接入 Hugging Face Transformers 的具体 `generate()`、GPU 显存/性能和真实服务连通性在 Stage 3_1 验收，禁止在本阶段把接口存在说成端到端 Base 已跑通。

## 1. 开工必须检查、尊重并复用的既有工程

**先阅读真实仓库、报告和代码，再给出一屏以内实现计划与复用映射表；以仓库实际路径为准，找不到文件就说明，不要假造。**

| 来源 | 必须复用的事实与组件 |
|---|---|
| Stage 0 | `reports/stage0/`、`src/policytrace/stage0/`：真实 Task 解析、四份 db_path 快照环境工厂、用户模拟器边界、官方 evaluator adapter、独立环境状态、历史 Mock 及 DeepSeek 预算适配。 |
| Stage 1 | `reports/stage1/STAGE1_REPORT.md`、`docs/evaluation_protocol.md`、`src/policytrace/evaluation/`、`rewards/`：`RunContext`/`EvaluationPlan`/`EpisodeRecord`、R0 的官方语义、完整性指标、工具错误和 token/cost 缺失值规范。 |
| Stage 2 | `reports/stage2/STAGE2_REPORT.md`、`STAGE2_COMPLETION_REPORT.md`（真实位置按仓库检查）、`src/policytrace/data/`、`configs/data/sft_main_view.json`、`data/splits/stage2/`：冻结划分、SFT Qwen Template 与 Tokenizer、原始 vs 经过隔离的 Main 视图。 |
| 多工具专项 | `reports/stage2/MULTI_TOOL_COMPATIBILITY_REPORT.md`、勘误文件及 `src/policytrace/compatibility/multi_tool.py`（按实际位置）：原生支持多 ToolCall、ID/顺序/结果关联、严格 Parser、混合文本的通信路由风险。 |
| 上游 Fork | `external/tau2-bench`，固定 `dhh1995/tau2-bench` `dhh/async-and-custom-completion`，Commit `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`；优先复用其 Orchestrator、Agent/UserSimulator 接口、ToolCall/MultiToolMessage、Environment、SimulationRun、原生终止语义。 |
| AReaL | 固定 revision `86971dc03da6e7c1a7933295e05b84aab8215386`；Retail 563 Task，4 个快照，RL Train 394 / Dev 84 / Test 85；SFT Main Train 8652 / Val 967；默认 `configs/data/sft_main_view.json`。 |
| Qwen | `Qwen/Qwen2.5-3B-Instruct` Tokenizer revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`；保持 Stage 2 的工具调用标签、模板与 EOS 规则，禁止随意新增互不一致的消息协议。 |

确认与锁定的边界：

1. Stage 2 当前有效结项：**原版 Retail Policy 不变，隔离当前 Target 多工具或文本+工具的 SFT 样本；原始及隔离视图保存、token 不重建**。SFT Main **8,652 Train / 967 Val**；没有改 RL 集合。Stage 3_0 不能逆转该决策。
2. Fork **运行时**可顺序执行多个 ToolCall；但 Retail **Policy**要求单回合最多一个，混合普通文本与工具在严格通信下可能直接拒绝、非严格模式下文本可能不会递交模拟用户。执行、符合 Policy、官方 R0 成功是三个独立概念。
3. RL 任务的 `user_scenario` 属 UserSimulator 私有信息，`evaluation_criteria`/参考 actions 只供 Evaluator / 离线审计；**Student 的输入和模型调用日志绝不能包含这些私有字段**。UserSimulator 可按其合法职责接收场景，但不得拿到 evaluator 私有参考目标。
4. `retail_131`、`retail_152` 等 Stage 0/1 已用任务进入 Dev；优先使用这些已暴露 Dev fixture。只有确认在 Dev 的 Task 才能在离线集成测试使用。
5. 当前 563 条 COMMUNICATE 评分条件为空；官方 R0 对正常停止的任务主要反映 DB 终态，不证明流程合规。不要以 R0 代替 Policy/Simulator 审查。

**必须先调查的实际代码接口**（不可臆造方法签名）：`Orchestrator.run/step/astep`、Agent 的生成消息抽象接口、`LLMAgent` 消息整理、`UserSimulator` 的停止条件、`Environment.get_response` 和 `MultiToolMessage` 的 flatten、`SimulationRun`/`TerminationReason` 的用法；已有 `compatibility/multi_tool.py` Parser 与阶段 0/1 的 API。确定最少扩展点。若 Orchestrator 某些状态必须定制，不更改 Fork，而是薄 Adapter/Wrapper，说明每处理由。

## 2. 目标架构与最小交付

总体调用：

```text
Stage 3_0 Driver (Dev-only, deterministic)
     |-- Run/Trial context + budgets + privacy controls
     |-- Fork Orchestrator (真实循环、路由、环境工具和终止)
           |-- PolicyTrace StudentAgentAdapter
           |     |-- ContextBuilder (Qwen 模板与显式 ContextPolicy)
           |     |-- ModelClient Protocol (Stage3_0: deterministic Mock)
           |     `-- ResponseParser (复用多工具专项的 Parser)
           |-- Fork UserSimulator interface (Stage3_0: scripted Mock)
           `-- Stage 0 db-bound Environment per Episode/Trial
     |-- Episode/Decision/Tool telemetry (私有、含 raw+projected)
     `-- Stage 0/1 official R0 adapter (仅 mock 诊断)
```

建议在 `src/policytrace/harness/` 创建职责小而清晰的子模块（如已经有等效实现则复用或扩展；不要因目录结构形式而重复造轮子）：

- `model_client.py`：最小协议 `generate(request) -> response`，显式传 Prompt Token IDs、Chat Template/工具 Schema/采样及停止配置；返回 Assistant 当前目标文本/结构、生成 Token ID（真实生成时）、停止原因、可用的 usage、provider/latency 与是否 Mock。Stage3_0 的 DeterministicMock 严格标记合成；RealQwenClient 可以定义接口/配置契约但**不下载权重、不执行真实推理**。
- `agent_adapter.py`：实现固定 Fork 的 Agent 接口，按其消息类型构造模型输入、将 ModelResponse 转为原生 AssistantMessage（正文或 ToolCall），管理 `requestor`、工具 ID、消息顺序与多返回。禁止绕过 Fork 自己做第二层 Agent-Tool 循环。
- `context.py`：明确 Raw Episode History 与 Model-visible Context 的分离。构建时只接收获许可的 Policy/Tools/User/Assistant/Tool Observation；与 Stage 2 Qwen Formatter 使用同一版本 Chat Template，防止 SFT/推理 Protocol Drift。
- `projection.py`：版本化 `ObservationProjector` 接口，默认 `identity-v0` 完整返回原始观察，不做任意字符串/JSON 截断、总结、滑动窗口、KVCache 假复用；为将来 schema-aware Projection 留扩展点，**当前不开发所有工具的压缩策略**。
- `trace.py` / `telemetry.py`：完整原生 SimulationRun 及私有原始 Observation，另加每次 Student 决策的实际可见 Context、投影版本、Token IDs、调用路由/解析失败、工具结果与角色用量；通过轻量 Observer/Callback/Wrapper 接入，不破坏 Fork 终止语义。
- `runner.py` / `config.py`：Dev-only 离线 Driver、显式步数/错误/上下文上限、Trial ID/seed/快照/运行版本，恢复语义和异常上报；连接 Stage 1 的 EpisodeRecord/R0。禁止复制另一个 EvaluationPlan 或 reward 实现。

这些名称只是建议。**越少新增重复组件越好**；若适配现有模块可少于上述文件。不要引入 LangChain、LangGraph、veRL、Ray、vLLM、外部多智能体框架或训练依赖；Stage 3_0 不做产品 UI。

## 3. 架构与行为的具体工程契约

### A. Agent Loop：以 Fork 为唯一执行内核

- 在真实 Fork `Orchestrator` 中运行一个完整的**离线** Student/ScriptedUser/Environment Episode，不接受只写 Mock 状态机然后称为端到端 Harness 的验收方式。
- 模型输出分为用户可见文本、合法 ToolCall、非法/不完整 ToolCall、文本+工具混合、一个回合多个工具等。复用已验证的非流式 Parser 与 Fork 数据模型；ID 由 Adapter 维护唯一 `(episode, turn, index)` 命名空间，确保 ToolCall ID / ToolMessage ID、顺序、requestor 一致。
- 保留 Fork 原生**顺序执行多 ToolCall**能力作为底层事实，不擅自把它改为并行。原版 Policy 下，多调用记录单回合政策违规，不得把合法 JSON 当作政策合规；**不要为了让 E0 得高分而静默过滤、拆分或改写动作**。
- 混合文本+工具：分别测试 Fork `validate_communication=True` 和 `False` 的确切路由、拒绝/执行结果、用户可见性；不要在非严格模式下丢弃正文而宣称已传达用户。**建议 Harness 项目诊断默认明确配置 `validate_communication=True`，并写明这可能不同于 Fork 默认 `False`；Stage 3_1 的正式配置需用户审查并冻结，不能把不同配置的 E0～E4 结果混报。** 无论如何绝不修改上游 policy 或评分。
- 工具调用 Schema/参数解析失败必须完整记录（包含尝试次数、错误类型、当时状态），不能只统计已成功解析的工具调用。未知工具、参数类型、部分解析成功、工具执行异常、超出错误预算和正常 user_stop/agent_stop 均应有离线测试。
- 工具批次应在执行前完成**语法和 Schema**校验，以避免解析到一半产生副作用；但一旦交给原生执行器，它可能出现前一调用成功、后一调用失败且不回滚，这属于原生行为，禁止隐式事务化。**不做自研全业务 Action Guard**；只记录可机械判定的违反 Policy 项（多工具、混合消息）与工具错误，认证/确认语义在未审核前标 `not_evaluated`。
- UserSimulator 停止必须遵照 Fork 真正的停止机制，不得把单纯 `Agent.is_stop=False` 或工具返回结束冒充任务完成。阶段 0 历史 Mock/真实接线应复用，只替换成**离线脚本实现**且不访问网络。

### B. ContextBuilder：上下文准确性高于早期压缩

- 每条 Episode 保存不可变 Raw Trace；每次模型调用创建当时**实际可见**的 Context Snapshot（ordered messages、tool schema/policy 版本、序列化文本或 canonical 表示、token IDs、长度、hash）。不要把 task 隐藏场景/评分/参考操作拼进 Student；强制 fail-closed 的 canary/redaction 测试。
- **Stage 3_0 只实现 `identity-v0` 观察投影**，明确接入扩展接口。raw observation 用于历史还原/评分，model observation 用于 Student 输入；两者同时留指纹，默认内容完全相同。此时不需要做 Schema-aware 具体工具投影、滑动窗口、Prompt 压缩或 LLM 摘要。
- 精确记录工具返回的逐类 token 数、System/Policy/Tool Schema token 占比、当前完整 Prompt token 数及其增长、历史回合数；离线 Mock 只能测 tokenizer 和协议长度，**不能由此推断 Base 模型真实时延/显存**。输出长度分位统计留给 Stage 3_1 真正测量。
- 上下文上限为显式配置（可先以 16K 作为研究/报警起点，但不假设适用于真实在线最长 Episode）；计算 `prompt_tokens + reserved_generation_tokens` 的窗口预算。超限时明确 `context_overflow` / fail-fast，记录当时长度和预算，**不暗中丢弃旧消息、重要订单字段、用户确认或工具结果**。错误 Episode 不可被聚合器遗漏。
- 不将 `Tokenizer.decode` 后再 `encode` 得到的 token IDs 冒充真实生成的 IDs；Stage 3_0 Mock 的生成 token IDs 可由当前固定 tokenizer 得到，必须标 `provenance=mock_encoded`。Stage 3_1 真 Qwen 推理应**直接保留模型 generate 返回的 token IDs（按 input length 切出 completion）**，并检查它们与线上实际消息解析一一对应；Token 视图和字符视图均需保存。生成时的上下文要能被未来 learner 逐步复用。
- 不把 SFT `labels=-100` 直接解释成在线 RL Mask。在线每次 Decision 必须标识 Student 生成的 token/span；User、Tool、System 历史为条件输入，不作为当前 Student Action 的输出监督。在以后合并完整多步 Rollout 做 GRPO 时，需要单独构建 response/action mask，不能把非 Student token 混入策略更新。
- 如果 Stage 2 的 SFT System Prompt 与真实 Fork Runtime Policy/包装不完全一致，输出**精确 diff/归因报告**，不可静默覆盖 SFT 数据或 Runtime Policy，更不能谎称二者完全一致。固定运行时应使用原版 Retail Policy 且日志记录具体 hash；识别 Stage 2 保留的历史违规风险，不需在本阶段新过滤 SFT。

### C. Decision/Tool Trace：为 OPD/GRPO 留真实接线接口

- 最少包含：`run_id / task_id / trial_id / episode_id / decision_id`，`source=mock`，model/config versions、Fork/Dataset/Tokenizer/Policy/Template/Projection hash、snapshot ID/hash、时间戳与停止原因。
- 每次 Student 决策记 `context_messages`（私有）、`prompt_token_ids`（模型实见）、Prompt length/hash、`generated_token_ids`（mock 需注明来源）、generation stop reason/length、`student_action_token_spans`/所有非 Student role mask 元数据、解析状态、原生 ToolCall/ToolMessage ID 映射、工具调用次数/异常类型/耗时、工具结果的 raw/model 版本与 hash。尽量保留可验证的消息与 Token 边界；如有尚未定义的未来 Trainer 字段，显式 `null + missing_reason`，不能制造 logits/logprob。
- Student、User、Teacher Token 分角色记账。Stage 3_0 User/Student 都是 Mock，不可声称为 provider billed usage；真实 provider usage / API 费用 / Teacher Tokens / GPU seconds / GRPO KL 等保持 `null` 或 `not_applicable`，不可冒充实际 0 成本推理吞吐。
- 轨迹数据保存原生 `SimulationRun`（含消息、工具执行），以及对应 `decision_trace.jsonl`；两个表示**不能相互矛盾**，要有 episode/step/tool ID 关联，异常/中断时保存已启动 Trial 的部分轨迹和错误原因。敏感原文、可能包含客户数据或 task 隐藏信息的记录只写私有目录；公开报告只显示统计、哈希、脱敏 ID。
- 如果真实 Fork API 不允许直接挂 Observer，可做不改其源码的 Wrapper/Composition；明确 hook 的执行时机与 state 所属。不要把评测参考动作作为 Student 的 FakeModel 工具调用参考答案。

### D. 环境、官方 R0 与 Stage 1 完整性协议

- `Task/Trial` 使用 Stage 2 manifest + Stage 0 db_path 工厂绑定**相同任务快照**，每条 Episode 前独立初始化环境；两个 Trial 即便共享 Task 也不能复用上一 Trial 修改过的 DB。检查 raw DB SHA 执行前后不变。
- 调用唯一 Stage 0/1 官方 Evaluator 路径，对**真正经过 Fork Orchestrator 的 mock 轨迹**做诊断评分。不要为方便展示修改 reference、伪造 UserSimulator 成功、将评分异常替换为 0 或写另一套 R0。
- 通过 Stage 1 schema 创建或转换 `EpisodeRecord`：区分 `normal stop/reward=0`、官方 `reward=1`、`termination` 官方 0、`parser_error`、`framework_error`、`scoring_error` 和 `not_run`，分母/缺失语义不变。
- `EvaluationPlan` 的真实基线待 Stage 3_1 执行。Stage 3_0 可以在 Dev/mock fixture 构造 `purpose=diagnostic` 的 1-Trial **合成诊断计划** 来测试连接，但**不要产生正式 Pass^1、Pass^4 或冒充四次真实独立 Trial**；不得运行 rl_test_frozen 任务或用于调参的外部 Test。
- 必须与 Stage 1 统一工具错误率口径：**所有工具调用尝试**作分母，解析/Schema、执行、框架失败互斥或给出可解释的分级归属；错误发生后不能凭空丢掉 attempted call 计数。未知总量时率为 null。

## 4. 可用的离线执行入口和建议落盘

按现有项目风格提供以下最小入口（可重命名，但报告写明）:

```text
src/policytrace/harness/          # 复用旧模块并增量实现；不要生成冗余文件
configs/harness/stage3_0_offline.example.yaml  # 显式 mock/Dev-only/限额
scripts/stage3_0_offline_demo.py  # 真 Fork Orchestrator + mock Student/User
scripts/stage3_0_check.py         # 测试、哈希、归档、无网络安全检查
tests/stage3_0/                 # 单元 + 接口 + 真实 Fork 离线端到端
reports/stage3_0/STAGE3_0_REPORT.md
reports/stage3_0/check_results.json
reports/stage3_0/harness_protocol.md    # 或 docs/ 下

data/private/stage3_0/          # Mock 轨迹、决定级 Token 记录、含实体数据
```

**不要**用重复实现把目录填满。接口/CLI 必须可复现，参数明确 `--mode offline --split dev`，默认网络关闭、真实模型禁用、冻结 Test 拒绝。能够配置匿名 synthetic 任务更好，但不能伪造其作为真实 AReaL Task 的结果。

请输出一页 Stage 3_1 接入契约文档（例如 `docs/stage3_1_handoff.md`），只写**下一阶段应该填什么**：AutoDL GPU/WSL 环境验证、真实 Qwen weight/checkpoint、Transformers `generate()` 的 Token IDs 接入、DeepSeek API/预算、相同 Context/Parser/Policy、5–10 Dev Smoke、测 Token/耗时/成本、84 Dev Baseline E0 评测、是否需要后续 schema-aware Observation Projection、Stage 4 SFT & Stage 5/6 训练接口。**不执行这些事项，也不承诺 Stage 3_1 真实性能。**

## 5. 强制实测的验收矩阵

每项实测须报告 pytest case/脚本、输入来源（真实 Fork/真实 Dev Task、mock user、synthetic 夹具）、预期/实际、退出码、耗时、证据路径；不允许只有口头检查。

| Gate | 必须通过的实际检查 |
|---|---|
| S3_0-A 工程复用与锁定 | 真实版本/路径/哈希、Stage0–2 组件复用清单、Fork clean，原始资源/报告/manifest SHA 不变；不得改外部源码或 policy。 |
| S3_0-B Orchestrator 离线闭环 | **实际使用固定 Fork Orchestrator** 与 deterministic Student/User 跑一次 User↔Agent↔Tool 的完整诊断 Episode；消息路由、停止机制、顺序和独立环境成立，不是模拟另一个自研 Loop。至少包含一条只读工具路径和一条隔离副本状态修改/错误路径；无法做到需明示 BLOCKED。 |
| S3_0-C Qwen Parser/协议 | Stage 2 真 tokenizer/tool template，正确解析单工具、非工具回复；原生多工具按顺序路由并标违规；混合文本严格与非严格通信行为分别测试；测试 JSON 错误、Schema 未知、ToolCall ID/结果对应、部分批次副作用。 |
| S3_0-D Context 真实可见性 | 完整 Raw Trace 与模型 Context 分离，identity-v0 内容不变，System Policy/Tools + 消息边界正确；使用真实 tokenizer 计算每次输入 token，防止 UserScenario/评价目标泄漏；SFT/RUNTIME wrapper 的差异单独出具事实比较。 |
| S3_0-E Token/动作追踪 | 一次或多次 Student Decision 的 prompt/completion ID、哈希、生成来源、action spans、tool/error timestamps 与实际 Mock 调用对齐；非 Student Role 不被标为当前动作；mock token 不宣称真实模型序列。 |
| S3_0-F 长上下文/Projection | identity-v0 不修改原 Observation；超限 Fail-Fast，包含 Prompt + generation reserve；保存原始长度、工具长度及可复现错误，不随机滑窗、不截断重要字段。 |
| S3_0-G 环境及官方评分 | 同一任务多次环境 reset 独立、原始 DB 不变；Mock 轨迹可通过原生 `SimulationRun` 序列化和 Stage 0/1 官方 R0 回放；R0 仅标诊断；评分异常 null 不冒充官方 0。 |
| S3_0-H Trial/费用/工具诊断 | Stage 1 `RunContext`/`EpisodeRecord` 兼容；包括未解析尝试的全工具分母；单/多/混合 Policy 标记、异常终止、用户忠实度无法判断时标 unknown；role usage/cost 缺失值规范，不虚报费用/收益。 |
| S3_0-I 隐私/冻结 Test 边界 | Student 输入 canary 无 `user_scenario/evaluation_criteria`；拒绝尝试执行 test/外部 test，公开报告无隐私文本；轨迹及机密文件 Git 忽略，未发送付费 API。 |
| S3_0-J 回归/可复现 | 真实运行 `tests/stage3_0` 及被影响的 Stage0–2 CPU 回归；同一 mock 配置/seed 可重现消息、Token/工具/score 关键结构（去除 timestamp/随机 UUID 后），真实 DB、历史日志/冻结 SHA 未改。 |
| S3_0-K 阶段边界 | **没有**实际 Qwen 生成、DeepSeek 真实调用、E0 Base 成绩、Test Episode、AutoDL、SFT/OPD/GRPO 训练、Reward R1、上游源代码修改或擅自 Git push。 |

注意离线 Mock 模型产生的 `completion_ids` 不等于真实 Qwen generate 输出；即便所有 Gate PASS，**正式 Student Prompt ID、Completion ID、Logprob 对齐，仍必须在 Stage 3_1 和后续 RL Trainer 进行真实模型验证。**

## 6. 实际实现建议（避免过度设计）

建议先完成小而稳的 happy path：`dev Task → db-bound environment → Fork Orchestrator → ScriptedUser → MockStudent → 工具 → 回显 → 停止 → 官方诊断 R0`，随后补齐 Parser/Context/Trace/异常/隐私测试。不要以覆盖所有未来 RL edge case 为借口重构固定 Fork；必须遵循已有 Task/工具 API 而非自己复制业务逻辑。

对于 Stage 3_0，观测投影只是 `identity-v0` 接口和 Telemetry；**不需要在没有真实 E0 Token/失败分布之前设计 schema-aware 压缩规则**。Action Guard 亦只保留可验证的 Schema 检查和可审计的政策违反标记；不额外开发零样本业务权限引擎。允许附上后续设计建议，但不要把建议冒充本阶段已经上线的功能。

若有部分接口需要 80GB GPU 或真实 UserSimulator 才能验证，标为 `DEFERRED_TO_STAGE3_1`；这不自动导致离线 Harness 验收失败，只要离线可测的关键契约已全部落实。**如果无法接入真实 Fork Orchestrator、无法生成真实 Qwen Tokenizer Input ID、或无法保存可追溯的 Decision Trace，则必须 PARTIAL/BLOCKED，不可为赶进度硬报 PASS。**

## 7. 报告、停工和人工验收

最终生成 `reports/stage3_0/STAGE3_0_REPORT.md`，报告中必须用实际证据回答：

1. **到底复用了哪些已有源代码？** 每个 Stage 0–2 与上游 Fork 对应真实路径、版本、接口，列出真正新增的最小 Harness 代码；是否出现重复 Orchestrator/数据库/评分器。
2. **有没有真实跑通 Fork Orchestrator 驱动的离线多轮 Episode？** 报告模拟 User/Agent/Tool 数量、终止原因、调用/轨迹/DB/官方 R0 结果及其**mock/synthetic 身份**，不得报告为模型能力。
3. Context Snapshot 包含什么？真实 Qwen Tokenizer 如何编码、Prompt/Completion 边界如何保证？怎么存储每次 Student 的动作与 User/Tool 的非动作角色信息？是否含隐藏私有评分字段？
4. Policy 原版哈希、`validate_communication` 的两种分支实测与推荐配置；多工具/混合文本行为如何分类、如何记录、何时会实际执行；没有实现的业务合规审查明确写 `not_evaluated`。
5. 工具完整尝试及分级错误、Role token/费用、异常与终止、Context 长度预算、冻结 Task/Trial/快照、SimulationRun 及官方 Adapter 的一致性验证结果。
6. 全量 Stage0–2 影响回归中的实际通过数、失败/跳过、未运行原因；Stage 2 SFT Main、RL split/Pass4 hash 和 Fork 原件的 SHA 校验；新增文件、私有目录和配置入口。
7. 哪些功能**尚未执行**：真实模型、DeepSeek、GPU、E0 Baseline、正式 Pass^1/Pass^4、SFT、OPD、GRPO、R1；下一阶段需要什么硬件/费用/接口，以及哪项已记录风险必须到 Stage 3_1 复测。

结果状态使用 `PASS_OFFLINE / PARTIAL / BLOCKED` 加逐 Gate 事实，不要以 CPU 的 Mock 日志造 GPU/模型结论。写出实测命令、环境、退出码、真实耗时、哈希证据、简短复现说明。最后**停止在 Stage 3_0，等待用户明确批准开始 Stage 3_1**；不自动租卡、不自动跑付费 API、不执行 Base。

### 面向用户的最后摘要格式

只需清楚说明：已复用的 Fork/Stage0–2、离线交互是否真实跑通、Context/Token Trace 是否就绪、已解决/待决的协议风险、Stage 3_1 接入清单和未执行事项。不要因为篇幅长而把未验证事项写成成功。
