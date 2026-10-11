# Stage 1 官方奖励审计

固定 Fork：`e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`。以下“源码确认”针对这一 Commit 和当前 AReaL Retail 数据；没有推广为所有 tau-bench 版本的行为。具体统计协议见 `evaluation_protocol.md`。

## R0 真正在奖励什么

正常 `user_stop`/`agent_stop` 后，官方 ALL 只对 reward_basis 中的分项相乘。当前 563 条 Retail Task 的 basis 都是 DB、COMMUNICATE，所以 R0 是它们的乘积；任一失败得到 0。其他 tau2 结束原因提前返回 0，没有继续计算分项。

DB 奖励比较从同一初态重建出的数据库终态哈希。参考环境执行 evaluation_criteria.actions，预测环境重放实际工具消息；两侧数据库一致给 1。这允许与参考查询动作不同、但终态相同的轨迹。来源：`evaluator/evaluator.py:evaluate_simulation`、`evaluator/evaluator_env.py:EnvironmentEvaluator.calculate_reward`。Stage 0 适配保证两侧工厂绑定同一 AReaL 快照；不能只让 Rollout 正确而让目标环境回退默认 DB。

COMMUNICATE 在 assistant 文本中查找所需字符串（小写化、移除消息逗号），所有字符串都找到给 1；没有 communicate_info 时给 1。它不是语义裁判，也没有通用“先认证再写入、先确认后更新”的时序逻辑。来源：`evaluator/evaluator_communicate.py:evaluate_communicate_info`。

ActionEvaluator 会计算动作匹配诊断，ALL 也保留 action_checks，但 ACTION 不在当前 basis 中，因此缺少只读参考查询未必扣分。其动作匹配采用存在性查找，不保证顺序。来源：`evaluator/evaluator_action.py:evaluate_actions`、`data_model/tasks.py:Action.compare_with_tool_call`。

## 评分与业务质量的边界

| 行为 | 当前 R0 覆盖 | 证据状态与说明 |
|---|---|---|
| 最终地址/订单/支付状态符合参考目标 | DB 检测状态差异 | 源码确认，Stage 0 真实/参考回放验证 |
| 国家字段同义字符串不同 | 严格终态可能给 0 | 已观察：retail_131 原值 United States、参考 USA；原 R0=0 保留 |
| 只读任务中的拒绝/解释质量 | DB 保持不变且 COMMUNICATE 为空时覆盖有限 | 已观察：retail_152 reward=1；合理拒绝来自轨迹人工审查，不能由分数单独推出 |
| 写入前认证与明确确认 | 政策要求，但并无通用轨迹顺序奖励 | 源码确认其未全面自动检查；尚未观察到本项目 Agent 绕过确认拿高分的真实例子 |
| 工具参数解析/执行错误 | 可使轨迹重放异常、终态失败或提前终止，但 R0 没有统一逐次错误罚分 | 源码确认；独立 tool telemetry 区分原因，评分抛异常保持 null |
| 重复只读动作、冗长无益对话 | 可能最终仍成功；达到 max_steps 时官方 0 | 源码确认边界；过度重复的本项目实证统计尚缺 |
| Simulator 忠实度与披露时机 | 没有直接的 Simulator 质量分项 | 已观察：retail_152 的客户提前披露；单独诊断，不篡改 Agent 分数 |
| 长轨迹最后一步失败的因果责任 | 终局二值 R0 不提供逐步 credit assignment | 设计判断；中间状态只定位疑点，唯一因果责任需要反事实等额外证据 |

Retail policy 要求身份认证、单一客户、修改前列明细并确认、遵守订单状态和商品规格规则。工具会实现部分状态约束，但例如 `RetailTools.modify_user_address` 只读取用户并赋值地址，不读取对话历史检查客户是否确认。源码：`data/tau2/domains/retail/policy.md`、`domains/retail/tools.py:modify_user_address`。因此工具返回 error=false 不能自动等同政策合规。

上游参考动作执行异常会记 warning 然后继续。这是官方行为，Stage 1 不改它；未来应将参考数据有效性诊断与 Agent 失败分开。部分任务的初始 message_history/初始化动作也应由同一官方状态机制处理，不自行重复应用。

## 训练奖励如何扩展

R0 通过 `rewards/official.py:evaluate_r0` 原样调用 Stage 0 官方路径；原始 RewardInfo 留在私有证据中，公开 Episode 只保存数值分项与哈希。评分异常由调用方记录，不用造出的 0 代替上游结果。

未来可研究 `R_train = R_official + λ × R_verified_aux`，这里只是示意，λ 未设置，R1 没有实现和启用。插件必须独立命名、配置和版本记录，只看到经过审计的数值/终止信号，不能拿隐藏 scenario/actions 作为 Student 的在线提示。`select_training_reward` 默认是 R0；测试替身的任意数值仅验证接口隔离，不是候选 R1 的实现或收益。

官方评测始终只读取 immutable official_score，不能以 training_reward 替代。SFT 使用监督目标，OPD 使用教师分布/轨迹等目标，二者不直接以 R0 作为监督标签；GRPO 初始可用 R0，之后的辅助奖励取决于真实开发集证据。

全零组也可能来自任务过难、采样不够多样、模型未学会工具格式或 simulator 偏差，不能直接证明 R0 错了。应先看组均值/方差、全同组比例、错误类型与实际轨迹，再判断采样/难度调整还是奖励扩展。GPU、训练组、KL、Clip Fraction 在本阶段都未测量。
