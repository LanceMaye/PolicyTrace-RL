# Stage 3_1 复用映射（PHASE_LOCAL）

|现有实现|新增调用点|离线验证|
|---|---|---|
|`harness/model_client.py` 的不可变 Request/Response|真实 Transformers 客户端，保留 generate 返回的 token IDs|注入模型桩，验证 prompt 前缀及 completion 切片|
|`harness/agent_adapter.py`、`context.py`|同一个 StudentAgentAdapter；补充采样、来源及遥测字段|真实 Tokenizer、Parser、Mask、历史关联回归|
|`compatibility/multi_tool.py`|继续解析纯多工具；原生严格通信检查拒绝混合|原生 Orchestrator 离线闭环|
|`harness/runner.py:ObservedEnvironment`|新真实运行入口复用工具记录；旧离线 Driver 不放宽|隔离数据库、Observation、评分回归|
|Fork `UserSimulator`|只替换 completion callback，保留原生 scenario/历史/stop|HTTP 桩、原生消息转换、预算及失败持久化|
|`stage0/deepseek_client.py:BudgetedDeepSeek`|继承持久化账本方法；单独配置新运行预算|零重试、预留金额、错误脱敏|
|`data/task_pool.py:RLTaskPool.load`|按授权任务加载；准备期只校验字节哈希和 manifest|不反序列化 Test 正文；缺文件/篡改阻断|
|`rewards/official.py:evaluate_r0`、Stage 1 EvaluationPlan/aggregate|正式 Episode 记录及汇总；不另写评分器|缺失槽位 Pass¹=null、重复 trial 阻断|
|`policy.py:verify_fork`|每次检查固定 Fork 和唯一获批 Policy 补丁|Policy SHA、Fork dirty 范围检查|

新增模块统一放在 `src/policytrace/stage3_1/`。真实驱动仅负责装配、运行原生 Orchestrator 和封存结果；不增加另一个 Agent Loop。Stage 0～3_0 报告、数据、评分器、冻结划分及历史账本保持原样。
