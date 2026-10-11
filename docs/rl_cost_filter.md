# 可逆 RL Train 成本视图

本次 `rl_train_full=394`、`rl_train_cost_pruned=394`，排除 0 个 Task；默认选择完整训练池。真实跨源 confirmed_same_instance 为 0，证据不足时视图等于全集就是正确结果，不为了预设的节约成本目标把同业务或相似文本误算成重复。

`data.cost_filter.cost_pruned_view` 只接受同时属于 RL Train 与 SFT Train、classification/confidence 都确认、没有未知关键证据且有私有证据 hash 的关系。probable、pattern、unknown 候选全部保留。`rl_cost_exclusions.json` 保留版本、理由和回退说明，本次 exclusions 是空列表；原始 563 个 Task 始终保留。

恢复或做可选消融只需选择 `rl_train_full.json`，无需重写原始数据。未来若有经人工或严格规则确认的排除，须另存证据、来源、分布变化与规则版本，特别审查稀有任务、快照和长轨迹覆盖；Stage 2 没有启用缩水训练池。

SFT 的专家 teacher forcing 与 GRPO 的模型自生成状态分布不同，同实例也可能有探索、纠错和可靠性训练价值。成本过滤是有机会成本的假设，不能宣称重复任务无 RL 收益。若固定预算只是把 rollout 转投其他任务，总成本也未必下降；后续必须分别记 Episode、Student/User/Teacher token、GPU/API 消耗才能测量节约。

本次没有 API、GPU 或训练成本收益实验，没有为了凸显 RL 效果减少 SFT 专家数据。
