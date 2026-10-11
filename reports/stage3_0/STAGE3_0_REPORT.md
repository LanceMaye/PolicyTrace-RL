# PolicyTrace-RL Stage 3_0 验收报告

执行日期：2026-10-11。状态：**PASS_OFFLINE；人工验收 PENDING**。

已真实跑通固定 Fork Orchestrator 驱动的离线闭环，Student 和 User 均为确定性脚本，工具和评分器为原生实现。最终 **47 项 Harness 测试 + 164 项范围内回归通过，0 失败、0 错误、0 跳过**；10 项历史用例因本阶段数据边界明确未运行，见下文。7 条演示 Episode 全部实际执行并调用官方评分适配器。

这些结果只证明协议、数据隔离和日志接线成立，不是 Qwen Base、真实模型 Benchmark 或正式 Pass^1/Pass^4。未调用付费 API、下载权重、租 GPU、进行真实 Student 前向、训练或进入 Stage 3_1。

## 1. 固定来源与工程复用

开始前阅读了 Stage 0、Stage 1、Stage 2 原始报告、最新 `STAGE2_COMPLETION_REPORT.md`/验收状态、多工具专项与勘误，以及相关 Task/DB/评分/模板/Parser 源码。Stage 2 当前有效决定保持：Policy 不变，隔离当前多工具或文本与工具混合 Target，SFT Main **8652 Train / 967 Val**。原始和隔离视图、Token、RL Train 394 / Dev 84 / Test 85、Pass4 子集 50 均未改变。

| 来源 | 实际接口与复用位置 |
|---|---|
| 固定 Fork | `dhh1995/tau2-bench` / `dhh/async-and-custom-completion`，commit `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`；工作区 clean |
| AReaL | revision `86971dc03da6e7c1a7933295e05b84aab8215386`，现有本地冻结数据 |
| Qwen Tokenizer | `Qwen/Qwen2.5-3B-Instruct`，revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`，现有 Rust Tokenizer + Jinja；无权重 |
| Task/DB | [task_loader.py](/D:/Codes/policytrace/src/policytrace/stage0/task_loader.py:27)、[db_adapter.py](/D:/Codes/policytrace/src/policytrace/stage0/db_adapter.py:48)：原始 Task 解析、快照 SHA、深副本环境；`initialize=False`，由 Orchestrator 初始化一次 |
| 冻结数据入口 | [RLTaskPool](/D:/Codes/policytrace/src/policytrace/data/task_pool.py:11)：沿用 Task payload、revision、snapshot 校验；新 DevTaskPool 仅调整读取范围，避免旧 records 属性提前加载全部 Task |
| Context/Token | [QwenTokenizer](/D:/Codes/policytrace/src/policytrace/data/sft_tokenize.py:44)、`qwen_messages`：沿用实际模板、工具标签与 EOS；没有重建 SFT Token |
| Parser | [parse_completion](/D:/Codes/policytrace/src/policytrace/compatibility/multi_tool.py:23)：整批 JSON/Schema 检查、原生 ToolCall、唯一 ID、保留混合正文以供 Fork 校验 |
| Run/Trial/评分 | Stage 1 `RunContext`、`EvaluationPlan`、`EpisodeRecord`、`ToolStatistics`；[evaluate_r0](/D:/Codes/policytrace/src/policytrace/rewards/official.py:10) → Stage 1 official_adapter → Stage 0 快照绑定 → 官方 ALL |

新增核心为 [model_client.py](/D:/Codes/policytrace/src/policytrace/harness/model_client.py)、[agent_adapter.py](/D:/Codes/policytrace/src/policytrace/harness/agent_adapter.py)、[context.py](/D:/Codes/policytrace/src/policytrace/harness/context.py)、[runner.py](/D:/Codes/policytrace/src/policytrace/harness/runner.py)。fixtures 仅为合成脚本，verification 与 regression_scope 仅用于验收边界。没有重写 Orchestrator、工具、数据库或奖励算法，没有引入训练/Agent 框架依赖。

## 2. 原生执行的源码证据

| 固定 Fork 源码位置 | 本阶段依赖的事实 |
|---|---|
| [BaseAgent:44](/D:/Codes/policytrace/external/tau2-bench/src/tau2/agent/base.py:44) | `generate_next_message(message,state)`、`get_init_state(history)` 原生接口；103 行默认 `is_stop=False` |
| [LLMAgent:105](/D:/Codes/policytrace/external/tau2-bench/src/tau2/agent/llm_agent.py:105) | 多返回展开进入 Agent 历史；新适配器沿用这一方式，模型调用改用 Token-first ModelClient |
| [Orchestrator:574](/D:/Codes/policytrace/external/tau2-bench/src/tau2/orchestrator/orchestrator.py:574) | run 是唯一交互循环；636 行 arun 也通过离线适配器实际验证 |
| [Orchestrator:555](/D:/Codes/policytrace/external/tau2-bench/src/tau2/orchestrator/orchestrator.py:555) | 严格通信拒绝混合消息；752 行顺序遍历全部调用，764 行封装 MultiToolMessage；无批次事务回滚 |
| [Environment:390](/D:/Codes/policytrace/external/tau2-bench/src/tau2/environment/environment.py:390) | 实际 get_response，异常生成 error=True 返回，ID/requestor 对应调用；296 行开始重放历史结果与工具执行 |
| [UserSimulator:95](/D:/Codes/policytrace/external/tau2-bench/src/tau2/user/user_simulator.py:95) | 原生场景包装和历史初始化；122 行 STOP/TRANSFER/OUT-OF-SCOPE 停止规则 |
| [Evaluator:ALL](/D:/Codes/policytrace/src/policytrace/stage0/evaluator_adapter.py:15) | 仍由原适配器调用未改动的官方评分，不增加 Policy 奖励或改写参考操作 |

ScriptedUser 继承 UserSimulator，仅替换生成方法，保留其初始化和停止契约。ObservedEnvironment 为单实例组合包装，在原生 get_response 前后记账，不另建路由循环。Agent/User 不接收彼此的私有系统提示；Student 不接收 Task、user_scenario 或评分参考 actions。

## 3. 7 条真实离线闭环演示

均为 `source=mock, purpose=diagnostic`，属于合成动作在已暴露 Dev 快照上的协议测试。脚本动作从快照选取现存业务对象，**没有使用评分 reference actions 生成 Student 答案**。这些脚本不证明认证、确认或真实用户意图忠实度。

| 已暴露 Dev / 路径 | Student 决策 | User 消息 | 实际 Tool 返回 | 终止 | 官方诊断 R0 |
|---|---:|---:|---:|---|---:|
| retail_152 / 单只读 | 2 | 2 | 1 | user_stop | 1 |
| retail_131 / 单只读 | 2 | 2 | 1 | user_stop | 0 |
| retail_152 / 读→确认→写→读 | 5 | 3 | 3 | user_stop | 0 |
| retail_152 / 同回合写→错误取消→读 | 2 | 2 | 3 | user_stop | 0 |
| retail_152 / 混合消息，严格 True | 1 | 1 | 0 | agent_error | 0 |
| retail_152 / 混合消息，非严格 False | 2 | 2 | 1 | user_stop | 1 |
| retail_152 / 同回合两个独立只读 | 2 | 2 | 2 | user_stop | 1 |

合计 **16 次 Student 决策、14 条 User 消息、11 个真实 Tool 返回**；加上 7 条 Fork 默认 greeting，共 23 条 assistant/14 条 user/11 条 tool 原生消息。12 个工具尝试中，1 个因严格通信未执行，另有 1 个原生 execution error。调用数量/状态是工程诊断，不把不同配置 Episode 合并为模型成功率。

`retail_131` 的只读脚本没有达到其数据库修改目标，因此正常停止也得 0；`retail_152` 的合成写入偏离其原任务数据库目标，因此得 0。只读 retail_152 得 1 仅说明官方 DB 检查满足；空 COMMUNICATE 条件不证明请求已被完整理解或服务行为合规。

状态修改演示的真实顺序为：Fork greeting → User 提出修改 → Student 查订单 → 原生工具返回 → Student 请求确认 → User 确认 → Student 修改地址 → 原生写入结果 → Student 再读 → 原生结果 → Student 文本结束 → User STOP。五次实际 Prompt Token 数为 **4782 / 5095 / 5118 / 5482 / 5795**，每一步都有独立 Context 与 Completion 记录。

详见 [offline_demo_results.json](/D:/Codes/policytrace/reports/stage3_0/offline_demo_results.json)。本次私有演示根目录为 `data/private/stage3_0/offline_6a1ab58433be/`；重跑使用新 run-id，拒绝覆盖既有 Trial 证据。

## 4. Context、Token 与工具关联

- Context 保存允许字段的 ordered messages、完整 Tools、实际渲染文本、Prompt IDs/长度/hash、Policy/Template/Projection 版本、历史条数、角色跨度、逐工具 raw/model hash 与内容 token 数。
- 使用现有 Qwen Tokenizer 实际编码。Prompt/Completion 分开保存，当前 Completion 的相对和拼接后动作 span 与 role_mask 可追溯；全部历史包括先前 Student 输出都是当前决策的条件输入。没有把 SFT `labels=-100` 当成在线 RL Mask。
- Mock Completion IDs 标注 `mock_encoded`；客户端返回的 IDs 通过 decode 与文本核对，不重新编码替换。logprob/provider billed usage 为 null。真实 generate IDs/Logprob/learner 接线仍未验收。
- 真实冻结 SFT Main 单工具样本经 ContextBuilder 转换后的 Prompt IDs，与已有 Token 文件中的 Prompt 前缀完全一致；已有受监督 Target 解码后被同一 Parser 正确解析。此测试保留源 SFT Policy，不声称它与运行时业务 Policy 相同，更不声称源 SFT 数据库完整重放。
- Qwen 模板本身不表示调用 ID 或 Tool Response 的工具名；结构化账本和原生轨迹保留唯一 episode/turn/index ID、name、requestor、返回顺序。缺失、错 ID、乱序及错 requestor 均实测拒绝。
- `identity-v0` 保留完整 Observation，不摘要、不裁剪、不滑窗。Prompt 加 512 generation reserve 超过 16384 上限即 context_overflow；保存完整溢出快照/原始工具结果，不调用下一次 Mock Student。
- Tool 内容、Policy/Schema standalone token 数是固定 tokenizer 的真实编码长度；后两者及其相对 Prompt 比例明确标为 standalone、非可加贡献。完整渲染 System 与总 Prompt 另记，不能将 standalone 比例当成实际模板区段的可加占比。7 条演示的 Prompt 最大为 **7377**，加 reserve 为 **7889**；不据此估计真实最长任务、模型显存或推理吞吐。

每个 Episode 私有文件包括 `simulation_run.json`（完整时）、`episode_metadata.json`、`episode_record.json`、`plan.json`、`decision_trace.jsonl`、`tool_trace.jsonl`、`user_trace.jsonl`、`reward_info.json`。Decision 的 native_simulation_id/native_trajectory_index 与 Tool IDs 关联两个表示；原生 UUID 和应用 episode_id 在 metadata 中显式映射。

## 5. Policy 与失败语义

原版 Policy 文件 SHA：`4313d3fef8acf919f555fa17fbce929cc3ed1cef2dd8f0d35ff5c8c3364de176`。环境读入文本的 SHA 为 `2c9652afbce57d6e087768d37cda64d31c53d50b3e3225cfdb791bac66466467`；文件 CRLF 与 Python 文本换行处理使二者不同，两者都记录，文件未改动。

默认项目诊断配置为 `validate_communication=True`，Fork 默认为 False。实测 True 在工具执行前拒绝混合消息；False 执行工具但不会把同回合正文送给用户。多工具批次仍按列表顺序执行，记录 multiple_tool_calls Policy 违规，未拆分/过滤动作。认证、确认与完整业务合规为 `not_evaluated`；Simulator fidelity 为 unknown。

工具批次先完整解析和校验 Schema；任何成员无效都不执行。被整批取消的尝试归入 parse_errors，并注明 atomic_batch_validation_rejected，不解释为每个成员都非法。原生 ToolMessage.error、未执行的通信/框架拒绝分别记 execution_errors/framework_errors，类别互斥。无法确定嵌套/模糊标签的真实尝试总数时，保留下界及 missing_reason，完整错误率为 null。

原生执行异常不会自动回滚：写入成功、取消错误、后续读取仍执行且读到写入结果；max_errors=1 也先完成整批再停止。max_steps 检查同样保留原生 ENV 队列行为，不把路由 step 当成模型回合。

Parser/Context/框架异常时 Fork.run 抛出，保存 partial_native_trace 与已执行工具事件。原生 SimulationRun 不支持 framework_error，未伪造该类型的完整 SimulationRun；Stage 1 EpisodeRecord 保留已启动事实、framework_error + 具体诊断 code、reward=null。评分异常独立保存 scoring_error/null。正常停止但官方 0、官方 1、原生提前终止 0、parser_error、context_overflow、framework_error 和 scoring_error 均有实测。

普通 Agent 不因 `###STOP###` 文本自动停止；原生 User 停止规则已验证。agent_stop 由显式合成子类验证，正式 Student 的停止方案仍需下一阶段审查。上下文恢复和原生数据库重放已验证；跨进程 cursor/RNG/checkpoint、部分批次 exactly-once 恢复未实现。

## 6. SFT/运行时 Policy 的精确比较

全量扫描 **8652 Train + 967 Val** 的 system 文本，只有 1 个源 system 版本。复用 qwen_messages 后，两者的协议包装前缀相同，但业务 Policy 不相同：

| 项目 | 冻结 SFT 源 Policy | 固定 Fork Policy |
|---|---|---|
| 写入确认 | `you'd better` 获取 explicit confirmation | `you must` 获取 explicit confirmation `(yes)` |
| 单回合工具数量 | 未写数量上限 | `You should at most make one tool call at a time` |
| 文本/工具混合 | 禁止 | 禁止 |
| 其他差异 | policy 开头额外空行 | 无该空行 |

没有重写 SFT system、Target、历史、Token 或运行时 Policy。精确 unified diff 与原始 wrapper diff 存私有目录，公开 [policy_diff_results.json](/D:/Codes/policytrace/reports/stage3_0/policy_diff_results.json) 保留数量和哈希。源 policy SHA `efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936`；policy diff SHA `f0b173433ae1280ef36ed93313bee890d2c7dbfde895d0842860599b97fb6005`。Main 保留的历史行为风险沿用 Stage 2，不增加过滤。

## 7. 实际测试、范围与复现

Windows CPU / CPython **3.11.15**，现有 `.venv`；本阶段没有执行 WSL/Linux/AutoDL 验证。最终验收入口为 `scripts/stage3_0_check.py`，退出码 0。

| 最终命令（省略同一 Python 前缀） | 结果 | 外层实际耗时 |
|---|---|---:|
| `-m pytest tests/stage3_0 -q` | 47 passed / 0 failed / 0 skipped | 106.672 s |
| `-m pytest -p policytrace.harness.regression_scope tests/stage0 tests/stage1 tests/stage2 tests/multi_tool_compatibility -q` | 164 passed / 10 deselected / 0 failed / 0 skipped | 205.892 s |
| `scripts/stage3_0_offline_demo.py --mode offline --split dev` | 7/7 mock Episode，真实 Fork + 官方评分，PASS_OFFLINE | 42.936 s |
| `scripts/stage3_0_policy_diff.py` | 9619 Main system 实际扫描，差异记录 | 6.807 s |

所有命令退出码均为 0；完整 argv、测试源码 hash、每个 testcase 耗时、私有日志 SHA 见 [check_results.json](/D:/Codes/policytrace/reports/stage3_0/check_results.json)、[pytest.xml](/D:/Codes/policytrace/reports/stage3_0/pytest.xml)、[regression.xml](/D:/Codes/policytrace/reports/stage3_0/regression.xml)。公开 XML 去除 traceback/客户文本，完整原件在私有验收目录。首轮开发断言和接线问题已修正并复测，旧失败日志保留私有证据，不计入最终通过结果。回归有 1 条第三方 Pydantic ReadOnly 提示，无失败。

回归分组：Stage 0 **43**、Stage 1 **48**、Stage 2 **48**、多工具专项 **25**。Stage 0/1 历史参考/真实轨迹仅离线回放，未产生新的真实 API Episode。新 Harness 的写入、评分与隐私验证全部为明确标注的 Mock/合成夹具。

| 强制离线检查 | 代表实测用例（tests/stage3_0/test_harness.py） | 预期与实际 |
|---|---|---|
| 原生循环 | `test_native_orchestrator_is_execution_kernel`、`test_native_arun_with_mock_adapters_is_exercised` | 真正调用 run/arun，user_stop、工具返回与官方诊断成立 |
| Context/Token/ID | `test_context_exact_observation_order_and_token_boundary`、`test_real_frozen_main_prompt_tokens_and_target_parser_match` | Prompt/Completion 解码相等、边界/Mask 对齐、真实 SFT 前缀等于冻结 Token |
| 多/混合/副作用 | `test_one_turn_two_calls_native_multi_return_and_policy_flag`、`test_mixed_strict_rejects_or_native_nonstrict_hides_text`、`test_partial_execution_error_does_not_rollback_or_skip_later_call` | 两次调用未丢失；两种通信分支正确；写入不回滚 |
| Parser/Schema | `test_parser_failures_preserve_started_trial_and_attempts`、`test_entire_batch_schema_validation_precedes_any_write` | JSON/未知工具/错类型/截断/无效 envelope/空输出拒绝，整批无副作用 |
| 预算/停止 | `test_error_budget_is_checked_after_entire_batch`、`test_native_max_steps_finishes_queued_environment_batch`、两个 context_overflow 用例、User/Agent Stop 用例 | 原生预算语义不改；真实 Observation 导致溢出时完整保存；两类停止真实区分 |
| 异常/评分/隔离 | write replay、framework/scoring failure、wrong IDs、generation overflow 用例 | 新 DB 副本互不影响、原生重放一致、真实失败保留 null/partial，而非冒充 0 |
| 隐私/复现 | Canary/raw_data、非 Dev manifest、真实 client 拒绝、网络禁用、seeded reproducibility、覆盖拒绝用例 | 未泄漏私有系统字段；无付费接线；消息/Token/调用/DB/score 结构可重现 |

10 个历史用例明确 **NOT_RUN**：1 个全量 563 Task Schema；5 个通过 shared prepared fixture 加载全体 RL/Test 特征的审计/重划分/质量用例；3 个旧 TaskPool Train/任意 Dev 选择或损坏 Train snapshot 用例；1 个外部 Test 候选审计。不是跳过后算通过。测试专用 regression_scope 把旧 raw iterator 限制为已有 exposed Dev，保持 Stage 0 原始 8 fixture 顺序，未修改旧源码/测试文件。新 Dev-only 集成、源码/数据 SHA、SFT Loss Mask 与 Token 分区回归替代当前所需检查。完整名单与原因在 [regression_scope.json](/D:/Codes/policytrace/reports/stage3_0/regression_scope.json)。

```powershell
.venv\Scripts\python -X utf8 scripts/stage3_0_check.py
.venv\Scripts\python -X utf8 scripts/stage3_0_offline_demo.py --mode offline --split dev
.venv\Scripts\python -X utf8 -m pytest tests/stage3_0 -q
```

默认 pytest 搜索路径仍为历史 Stage 0–2，未改 pyproject；Stage 3_0 使用上述显式入口。冻结起始 inventory 已存在，不能重建以掩盖变更。

## 8. 不变性与隐私证据

执行前后 **623 个文件 SHA 全部不变**，含旧源码/测试/报告、数据原件和快照、SFT 完整/Main/隔离 Token 与 manifest、RL 划分/Pass4、Tokenizer、历史付费账本、锁文件、Fork tracked files。文件清单存私有 `immutable_inputs.json`，inventory SHA 为 `a40cf42978d4e2cea98f3137da1af987926952db23ab1b6929d035bc18d2f8d5`。没有覆盖 Stage 2 原始结论或勘误。

| 冻结资产 | SHA256 |
|---|---|
| RL Train full manifest | `dd7d9ba74317de0d930743b80e341189884892a20a005bfd950ec8af51c6fff7` |
| RL Dev manifest | `313428d577b0372616c0c202470449c031e3269c2d15ca9ca6b09a83b498caa0` |
| RL Test manifest（仅字节 SHA） | `2dfcacc7888b046457f89198011198024fbb78546ddbcb77dde7375da77a5902` |
| Pass4 子集（仅字节 SHA） | `e778d38cfd6ee0ee1a0d249a0fb30d78c69eeae4d7ed81ce69a60e1c6e42b354` |
| SFT Main manifest | `7e2fbf1bfcb8497810393d69b7c55165bbffd16b11b5266ae6a31b741369361e` |
| active SFT config | `85844f82e73de13a80fb6ca1aa396343437a73fe4079f12b71a238ecf58dfd9f` |
| 历史付费 ledger | `66aff237194729679ca4c32da6fc959f5ad4da815818eeab19fbf48afb7655ce` |

Driver 仅反序列化 retail_131/152 的正文；旧回归仅选已暴露 Dev。没有新的冻结 Test/外部 Test 评分、诊断或轨迹。git check-ignore 验证 .env、私有轨迹/JSONL/测试 XML、raw 和 Token 路径被忽略；没有读取密钥。socket guard 仅例外允许 Windows asyncio 内部本机唤醒 socketpair，不允许任意 Student/API 连接；这是一项本地测试保护，不是针对恶意代码的系统网络沙箱。

## 9. Gate 与仍待验证事项

| Gate | 结果 | 证据/限制 |
|---|---|---|
| S3_0-A 复用/锁定 | PASS | 623 文件不变、固定 Fork clean、既有评分和数据接口复用 |
| S3_0-B 原生闭环 | PASS | 真 run/arun、7 演示，包含只读、写入、错误路径 |
| S3_0-C 协议 | PASS_OFFLINE | Parser/单工具/多返回/混合两分支/整批校验与副作用实测 |
| S3_0-D Context | PASS_OFFLINE | 真实 tokenizer、源 Main 前缀一致、白名单/Canary、精确 Policy diff |
| S3_0-E Token Trace | PASS_OFFLINE | 实际 Mock 请求 IDs、mock_encoded Completion、span/hash/轨迹关联；真实 model_generated/logprob 未测 |
| S3_0-F 长上下文/投影 | PASS_OFFLINE | identity-v0、reserve 检查、真实工具结果溢出保存；真实最长 Episode/GPU 未测 |
| S3_0-G DB/评分 | PASS | 独立副本、原生 SimulationRun 序列化/DB 重放、唯一官方 R0/null 失败语义 |
| S3_0-H Trial/诊断 | PASS_OFFLINE | Stage 1 schema、全尝试记账、机械 Policy 标注、角色费用缺失值 |
| S3_0-I 隐私/Test | PASS | Dev-only、实际 Test/真实 client 拒绝、私有文件忽略、无场景/参考字段直传 Student |
| S3_0-J 回归/复现 | PASS_SCOPED | 47 + 164 通过、10 项范围外 NOT_RUN；关键结构复现，不声称全量历史审计重跑 |
| S3_0-K 阶段边界 | PASS | 无 API/权重/GPU/真实基线/训练/R1/Fork 改动/Git commit/push |

**DEFERRED_TO_STAGE3_1**：真实 Qwen generate 与 Prompt/Completion/Logprob 对齐；真实 DeepSeek 连通性、预算和场景忠实度；GPU/Linux/AutoDL；E0 Dev smoke/完整 Dev baseline；真实长度/延迟/显存/费用；正式 Pass^1/Pass^4；根据真实分布决定是否做 Observation Projection。

其他未实现：正式跨进程恢复与 exactly-once、副作用批次中断恢复、完整认证/确认 Policy Guard、流式 Parser、参数字符串含协议分隔符等真实输出边界。源 SFT 初始数据库不可完整还原、历史违规与业务 Policy 差异、外部 Test 独立性风险继续保留。当前离线协议通过不能自动解除这些风险。

详细协议见 [harness_protocol.md](/D:/Codes/policytrace/docs/harness_protocol.md)，下一阶段需填写的硬件、权重、generate IDs、DeepSeek 预算和评测设置见 [stage3_1_handoff.md](/D:/Codes/policytrace/docs/stage3_1_handoff.md)。停止在 **Stage 3_0**，等待用户人工审查；未开始 Stage 3_1、SFT/OPD/GRPO 或 R1。
