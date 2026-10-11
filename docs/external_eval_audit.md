# 固定 Fork Retail Test 外部候选审计

来源为固定 commit 的 `external/tau2-bench/data/tau2/domains/retail/`。实际读取 tasks.json 共 114 条，split_tasks.json 的 train 为 74 条、test 为 40 条；这个 40 来自文件，不是硬编码假设。每个 test ID 均能定位，真实 Task 与工具 Schema 静态校验通过。未执行任何外部 Episode。

将全部 40 个 test Task 与 563 个 AReaL RL Task 和 1,000 段 SFT 对话做相同实体、目标和局部文本候选检索，本次没有候选命中，也没有观察到确认同实例重复。这是当前规则可见的结果，不是种子来源独立性的证明；AReaL metadata 没有可核验的 original seed-task lineage，文字/实体变体可能逃过检索。

状态为 **EXTERNAL_EVAL_CANDIDATE/CONTAMINATION_RISK**；正式独立泛化评测在来源与协议审查前保持 BLOCKED。CONTAMINATION_RISK 表示来源证据未完备，不表示已经找到实际污染。候选清单、原 ID 到独立 ID 的映射、Task/Snapshot hash 在 `data/private/stage2/external_test_candidate.json`，私有场景和参考答案不写入公开文件。

这组任务使用固定 Fork 的默认 DB、政策与上游任务版本，将来要单独记录 Simulator、Harness、采样及指标。即使可用，也不能混入内部 85/50 的 Pass^1/Pass^4 分母；该 Fork 的得分不能无条件对比其他版本的官方 leaderboard。当前分支/commit 固定不等于已核对原版最新任务或证明合成训练来源完全独立。

可执行审计入口 `scripts/stage2_external_audit.py`，聚合证据与资产 SHA 在 `reports/stage2/external_eval_audit.json`。
