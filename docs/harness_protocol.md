# PolicyTrace 离线 Harness 协议 v2（SFT 自定义 Policy）

当前仅用于 `source=mock`、`purpose=diagnostic`。唯一执行内核是固定 τ²-bench Fork 的 Orchestrator；没有第二套 Agent Loop、业务工具或评分器。

当前 Policy 为 `areal-retail-sft-v1`，见 `configs/policy/custom_retail_v1.json`。Fork 基础 commit 不变，仅 Retail policy.md 是获准的改动；工具、Schema、Evaluator 与原始数据库保持冻结。版本检查按路径与精确 Policy SHA 验证该改动，绝不把 dirty Fork 描述为 clean。原 Stage 3_0 报告和旧代码备份保留；复验入口是 `scripts/custom_policy_check.py`。

```text
offline_demo -> DevTaskPool -> Stage 0 独立环境
                    |
             Fork Orchestrator
              /      |       \
  StudentAgentAdapter |    ScriptedUser(UserSimulator)
      |               |       原生场景包装/停止规则
  ContextBuilder      |
  QwenTokenizer    ObservedEnvironment -> 原生 get_response
  ModelClient         |
  strict Parser       |
              SimulationRun
                    |
       Stage 1 evaluate_r0 -> Stage 0 快照适配 -> 官方 ALL
```

## 输入、Context 与动作

`DevTaskPool` 继承 Stage 2 `RLTaskPool` 的 manifest、Task payload 和 DB SHA 校验；只允许固定 `rl_dev.json` 中已暴露的 `retail_131/152`。扫描原始 RL 文件时仅从其他行识别根 ID，只有选中 ID 才反序列化正文。拒绝 Train、Test、外部任务入口；不通过泛化的旧 `records` 属性加载所有 563 个 Task。

Student 适配器实现原生 `LocalAgent` 接口。收到 MultiToolMessage 时按原顺序展开全部结果。ContextBuilder 仅投影原生 User/Assistant/Tool 的允许字段，剥离时间戳、usage、raw_data 等 provider 元数据；不接受 Task。业务 Policy 来自原生 `environment.get_policy()`，`student_system` 精确保留该文本的首尾换行，最终包装和渲染复用 Stage 2 `QwenTokenizer.render/qwen_messages`。避免 Fork SYSTEM_PROMPT 添加额外换行，使 SFT 与实际 Runtime 的 Prompt IDs 一致。

`identity-v0` 原样保留每条 Observation。原始轨迹用于官方重放；模型 Context 是新建的允许字段快照。两者的内容、调用 ID、结果 ID、requestor 和顺序须一致，缺结果、乱序、重复 ID 或越权消息立即失败。Canary 出现在可见正文时，禁止调用 ModelClient；raw_data 内 Canary 经白名单剥离。此机制检查工程边界，不替代真实模拟用户信息披露质量审核。

ModelRequest 含实际 prompt 文本、Prompt ID 元组、结构化 Context JSON、完整工具 Schema JSON、版本信息、sampling JSON、EOS ID 和 generation reserve。ModelResponse 必须提供文本与 Token IDs；适配器检查解码一致性，不用重新编码结果替换客户端返回的 IDs。当前 Mock 的 IDs 由固定 tokenizer 编码，注明 `mock_encoded`，没有真实模型 forward/logprob。

每次 Decision 的全部 Prompt Token 都是条件输入，包括过去的 Assistant 动作。当前 Completion 单独保存 ID、长度、相对 span 和与 Prompt 拼接后的 span；role_mask 用两段长度及值 0/1 表示，不是 SFT labels，也不是未来拼接完整 rollout 的 RL mask。模板角色跨度与原始消息角色同时保存：Qwen 把 Tool Results 渲染成含 `<tool_response>` 的 user 段，不能据此把它当成真实用户发言。

Qwen 文本不携带 Call ID，也不在 Tool Response 包装中携带工具名称。ID 在结构化 Context、原生 SimulationRun、Decision/Tool ledger 中维护；命名空间为 episode/decision/index。工具名与参数仅由已验证的严格非流式 Parser 转成原生 ToolCall。

## 执行与错误

整个工具批次在任何副作用前完成 JSON/Schema 检查。合法批次交给原生 Orchestrator 顺序执行；不并行、不拆分、不自动回滚。`protocol_features.multiple_tool_calls` 记录多个调用这一事实；当前 Policy 下对应的违规标记为 false。混合调用仍为 Policy 违规。认证、确认和完整业务合规为 `not_evaluated`。

项目诊断默认 `validate_communication=True`，不同于 Fork 默认 False。True 拒绝混合消息并终止 AGENT_ERROR，工具尚未执行；False 仅用于诊断原生边界，将该消息路由至 ENV，正文不交给用户，不作为正式设置。纯多调用在当前 Policy 下允许。RunContext 的 harness_version 与 Episode ID 包含离线 config、Policy 版本和 SHA；Decision/Context/Metadata 也保留 Policy SHA，避免跨设置混报。

工具尝试分母包括可识别的 `<tool_call` 开始标签。批次语法/Schema 失败时，整个拒绝批次计入 parse_errors，包括其中被连带取消的合法调用；每条 attempt 注明 `atomic_batch_validation_rejected`，不能解释为每个 JSON 都非法。原生 execution error 和未执行的通信/框架拒绝分别计入 execution_errors/framework_errors，互斥。嵌套/模糊标签只有下界，framework_errors 为 null 且写 missing_reason，Stage 1 完整错误率因此为 null。普通文本输出没有工具尝试，不能给零分母填 0% 错误率。

原生 max_steps/max_errors 检查在一批 ENV 调用结束后进行，可能完成已排队批次后才停止；不会强行把原生 step 解释为一次模型回合。普通 StudentAdapter 继承 `BaseAgent.is_stop=False`，`###STOP###` 文本不会自行终止；正常场景由原生 UserSimulator 停止规则结束。Agent Stop 仅用显式合成测试子类验证，不作为已冻结的真实 Student 停止配置。

Context 上限检查 `prompt_tokens + reserved_generation_tokens`，超限保留完整快照并报 context_overflow，不截断、滑窗或摘要。Policy、Schema 的 standalone token 数是各文本的真实编码结果，受 BPE 和包装影响不能相加还原总数；完整 Prompt/渲染 System 数另存。

## 轨迹、评分、费用和恢复

每 Trial 从 Stage 0 工厂新建数据库深副本，再由 Orchestrator 应用初态，避免重复初始化。ObservedEnvironment 在每次原生 get_response 前后记录调用/返回/时刻/耗时/DB hash；不改变工具内容或评分。完整运行保存原生 SimulationRun，官方 RewardInfo 另存私有文件，再转成 Stage 1 EpisodeRecord。官方 R0 为调用 Stage 1/Stage 0 适配器后的原始值。

Parser/Context/模型适配器异常时 Fork.run 会抛出，保存 partial_native_trace 与已发生 Tool Events；不伪造不支持 framework_error 的 SimulationRun。Stage 1 记录 started/framework_error、诊断 error_code 与 reward=null。原生 AGENT_ERROR/MAX_STEPS/TOO_MANY_ERRORS 可由官方评分得到 0。完整 SimulationRun 的评分异常独立记 scoring_error/null，保留完整轨迹。

Student TokenUsage 的 instrumented 数仅描述 Mock 调用时的 tokenizer 长度；User 仅记录脚本文字输出 token，实际 User 模型 prompt/provider usage 未发生，保持 null。Teacher、真实 provider billed usage、API bill、GPU 时间、训练字段/logprob 都为 null。原生默认 greeting 的 cost=0 是 Fork 的字段，不作为 API 账单证据。

`get_init_state(history)` 与原生重放验证了上下文恢复。跨进程断点恢复、模型 cursor/RNG、部分工具批次的 exactly-once 恢复未实现；禁止把失败 Trial 覆盖成重试成功。Driver 检测目录已存在即拒绝覆盖。

原始 Context、Token、场景、客户信息、RewardInfo、测试 traceback 只存 `data/private/stage3_0/`。公开报告只含统计、哈希和已暴露 Task ID，公开 pytest XML 去掉 traceback/body。Python socket guard 拒绝 DNS/连接/bind，仅允许 Windows asyncio 内部 socketpair 的本机唤醒调用链；这不是针对任意恶意 Python 代码的操作系统网络沙箱。
