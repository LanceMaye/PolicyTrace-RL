# PolicyTrace evaluation protocol v1

协议版本：`policytrace-eval-v1`。适用固定 tau2 Fork `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887` 与 AReaL 数据版本 `86971dc03da6e7c1a7933295e05b84aab8215386`。本协议规定评价规则；最终训练/开发/测试 Task ID 清单由 Stage 2 冻结。Stage 1 的两个历史 Episode 回放是诊断证据，不是正式 Benchmark。

## 官方真值与成功

`R0 = official_reward`，只从 Stage 0 快照感知适配调用原始 `evaluate_simulation(..., EvaluationType.ALL)` 获得。成功定义为官方原始 reward 精确等于 1；0 为官方失败。本阶段仅支持该锁定 Retail 的二值奖励，遇到非二值/NaN/无穷官方输出明确拒绝，不能自行阈值化或裁剪。评分异常时 reward 和 success 为 null，不冒充官方 0。

源码依据（均相对于 `external/tau2-bench/src/tau2/`）：

- `evaluator/evaluator.py:evaluate_simulation`：仅 `user_stop`、`agent_stop` 可继续评分，其他 tau2 终止原因直接产生官方 0，且分项可为空；无 evaluation criteria 时返回 1。ALL 会计算各诊断器，但仅将 Task 声明的 reward_basis 分项相乘。
- `data_model/tasks.py:EvaluationCriteria`：默认 reward_basis 为 DB、COMMUNICATE。Stage 0 对当前 563 条 Retail Task 的审计确认全部采用这两个分项。
- `evaluator/evaluator_env.py:EnvironmentEvaluator.calculate_reward`：从同一环境工厂创建预测和参考环境；重放真实消息构成预测终态，参考 actions 构成目标终态。比较 Agent/User DB 哈希，均一致时 DB=1，否则 0。参考动作异常会被上游警告后继续，不能把它当成正确参考已保证的证明。
- `environment/environment.py:Environment.set_state`：应用 initialization data/actions 并重放历史工具调用，核对工具响应。错初态、轨迹重放不一致等可能抛异常，应归类为 scoring_error。
- `evaluator/evaluator_communicate.py:CommunicateEvaluator.evaluate_communicate_info`：对 assistant 的文本做小写化，在去逗号后的消息里查找所需字符串。空 communicate_info 直接给 1；不证明认证、确认、礼貌或政策推理全部正确。
- `evaluator/evaluator_action.py:ActionEvaluator.evaluate_actions`：检查每个参考动作是否在预测工具调用中出现，不要求严格顺序；当前 ACTION 不在 reward_basis 中，诊断失败不能私自加到 R0。
- `data_model/simulation.py:RewardInfo/TerminationReason`：保留官方 float、分项和终止原因，原始 RewardInfo 含隐藏 action/沟通条件，完整 JSON 只能存私有目录。
- `orchestrator/orchestrator.py:Orchestrator.run`：返回六类 tau2 termination_reason；部分网络/框架异常可能直接抛出而没有 SimulationRun。未来 Harness 需单独记录启动事实和异常，不能丢记录。

每条任务必须使用它的 AReaL db_path 初态。复用 `stage0.evaluator_adapter`，不替换默认 retail 注册项，不改变业务字段或上游评分。`retail_131` 原始 country 字符串差异仍得 0；`retail_152` 仍得 1，用户过早披露信息作为单独诊断保留。

## Run、Task、Trial 与完整性

一个 EvaluationPlan 显式声明 RunContext、Task ID 清单以及 1 或 4 个有序 Trial ID。Task 与 Trial 清单必须无重复；记录的 task_set_sha256 应匹配排序后 Task ID 清单的规范 JSON SHA256。每条 Episode 唯一键为 `(task_id, trial_id)`，并须与计划中的环境、数据、模型/checkpoint/采样、User Simulator 配置、Harness 和步数/上下文限制一致。同一 Task 的各 Trial 必须使用相同快照 ID/hash；各 Task 可以有各自快照。

`episode_id` 在计划内唯一，避免同一已保存 Episode 被改标 Trial ID 充当独立试验。RunContext.purpose 区分 diagnostic 和 benchmark；synthetic/reference/mock 不能声明为正式 benchmark。聚合只能检查记录身份和元数据，不能靠 ID 单独证明独立运行，后续 Harness 仍须保存每次实际执行的证据。

跨 run/config/协议/模型/User 混合，重复 Trial、未知 Task/Trial 均拒绝汇总。真实、参考、Mock、synthetic 来源不能混在同一计划。Trial 的 seed 可以不同或 null；seed 来源与服务是否支持 seed 要独立记录，不能把 Orchestrator seed 当成 API 的逐 token 复现承诺。

缺少任何计划槽位，或者显式 `not_run` 时，Summary 为 incomplete，所有请求的正式 Pass 值为 null，并列出缺失 Task/Trial。空计划返回 empty/null。不能把已完成的一小部分当成完整分母。

## 主指标与失败口径

- **Pass^1**：每个纳入 Task 的一次指定 Trial 官方成功数 / 计划 Task 数。1-Trial 计划使用唯一 Trial；4-Trial 计划使用计划中第一个 Trial，不挑选最好的一次，也不与四次全部通过混称。
- **Pass^4**：每个相同 Task 的四个独立 Trial 全部官方成功才记通过；通过 Task 数 / 计划 Task 数。只有完整 4-Trial 计划才提供此指标。
- Pass@4 至少一次成功，与 Pass^4 全部成功不同。不能用 `(Pass^1)^4` 或从四条不同任务估计正式 Pass^4。
- 官方已评分失败、已启动但框架/网络/评分异常、已启动无法评分，均按失败计入 Pass 分母；原始记录依旧区分错误来源，官方 reward 缺失保持 null。记录完整与评分覆盖分别报告。
- 不允许静默重试，Trial 失败后仍保留原 Trial；若后续设计重试实验，需要新增显式版本、配置和统计协议，不能替换失败记录。

## 工程指标的分母和单位

每 Episode 保存工具尝试数和 parse/schema、execution、framework 三类互斥错误数。完整工具错误率为三类失败和 / 所有尝试数（包含未解析成功的尝试）；记录缺项时为 null。Stage 0 保存的真实轨迹只能可靠数到已解析的 ToolCall 和返回的 execution error，因此标为 parsed_calls 口径，完整错误率不可从它推断。工具执行错误率为 execution errors / 已解析调用尝试数；0 次调用的率为 null。

工具总数、平均、中位数只在记录完整且口径一致时输出总体值；另外保留每 Episode 分布、来源口径和有记录/缺记录数。异常终止率分母为已启动 Episode 数；user_stop/agent_stop 合法结束但 reward=0 不算异常终止。工具错误不必导致 Episode 异常终止。按成功/失败分组统计耗时和调用数，并保留工具失败与框架错误区别。

duration 单位秒，缺失为 null。Student/User/Teacher token 分别保存 prompt/completion provider usage，不能用字符数推断 token，也不能把未记录当作 0。汇总同时提供完整总量、已观察小计和缺失数，完整总量有任一缺项即为 null。成本按角色、币种、actual_bill/provider_estimate/upper_bound_estimate 分组，不混币种、不把估算叫账单。LiteLLM 默认 cost=0 不作为 DeepSeek 账单证据。

未来训练字段：GRPO group_reward_mean/variance、all_zero_group_fraction、all_equal_group_fraction、effective_group_fraction（非零方差可参与组内优势计算的组比例）、KL、clip_fraction；GPU_seconds、teacher_inference_seconds、training_tokens 和计算效率（训练 token/GPU 秒，分母需非零）。本阶段全部保留 null 与 missing_reason，只定义含义，不填训练数值。原始 Reward 分布和 Task 结果单独输出；任务类型 label 允许缺失，待 Stage 2 分类规则形成。

## 公平比较和数据隔离

后续比较 Base/SFT/OPD/GRPO 时，固定任务集合版本、环境 Commit、Dataset Revision、模型 checkpoint、模型输入与工具 Schema 协议、Harness 版本、User Simulator 名称/版本/配置、采样、重复次数、各 Trial ID/seed、最大步数/错误/上下文限制及本协议版本。所有配置变更显式记录，新的 Run 不能与旧配置拼成四次重复。

Stage 2 必须在训练前完成 SFT 原始 source_dialog_id/Task 来源分组和近重复审计，防止同一对话不同 assistant turn 或近重复任务跨集合。最终测试集合须冻结，仅用于最后评测。Stage 1 不制定正式 Task ID 划分。

## 扩展与隐私

`evaluation/schema.py` 定义冻结的 Episode/Run/Trial 结构；`metrics.py` 只读官方结果。R0 无损封装保留原始 RewardInfo 的私有证据，公开汇总只包含数值分项、哈希和私有定位引用，不复制参考动作、用户说明或原始对话。

未来训练奖励通过单独 `TrainingReward` 插件返回 value/name/version/components，不写回 official_reward；插件只收到受控的数值信号和终止原因，不接收 scenario、参考动作、评分私有文本或 prompt。软件接口隔离不能阻止不受信任 Python 代码自行读文件，插件仍须人工代码审查。默认仅 R0；未实现或启用 R1。

EvaluationPlan 和脱敏 Episode JSONL 是离线 CLI 的输入。本协议是评测工程契约，并不证明模型成功率提高。正式 Pass^4 尚无四次独立真实实验。
