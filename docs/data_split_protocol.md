# 数据划分版本 policytrace-data-v1

使用 `configs/data/split_config.yaml`，seed=42。先建立覆盖全部 RL Task 与 SFT 来源对话的全局分组，再分配角色，不按 assistant turn 随机切。共享客户/邮箱/订单的关系做保守分组；精确重复或 probable 关系亦不拆组。相同业务模式不单独连成组，共用同一整个 DB 也不连成组。

全局共有 1,553 组，7 组包含多个节点，最大 4 个节点；其中 1 组跨 SFT/RL。Stage 0/1 的十个历史暴露 Task 来自源码、fixtures、选择算法、公开报告与私有历史证据扫描，强制整个相关组进入 Dev。与合法 SFT 重合或未决共享实体的 RL 组优先 Train，保护专家数据；其余组按总量与业务类型、快照、参考长度、状态修改、通信条件的边际分布贪心分层。没有高维交叉小格硬切，也没有读取 Student Test 成绩。

| RL 主分区 | Task 数 |
|---|---:|
| rl_train_full | 394 |
| rl_dev | 84 |
| rl_test_frozen | 85 |
| quarantine | 0 |

实际本次恰好达到整数目标，但分组约束优先于整数配额。每条原始 RL Task 恰属一个主分区，交集为 0。`rl_train_cost_pruned=394` 是 Train 的可逆视图，不是第四个主分区。

| 快照 | Train | Dev | Test |
|---|---:|---:|---:|
| 1 | 68 | 14 | 14 |
| 2 | 45 | 10 | 9 |
| 3 | 131 | 27 | 28 |
| 4 | 150 | 33 | 34 |

| 参考长度 proxy | Train | Dev | Test |
|---|---:|---:|---:|
| short ≤6 | 99 | 19 | 21 |
| medium 7–9 | 230 | 51 | 50 |
| long ≥10 | 65 | 14 | 14 |

修改状态 Task 分别为 384/81/83；只读为 10/3/2。通信条件在三侧都为空，无法构造非空通信子层。稀有类型、只读 Task 很少，报告真实数字，不声称各子类都有精确比例。

| SFT 分区 | 完整来源对话 | 原始 assistant target |
|---|---:|---:|
| sft_train | 889 | 10,148 |
| sft_val | 103 | 1,139 |
| quality_excluded | 8 | 108 |
| heldout_from_sft | 0 | 0 |

Val 是 992 段可用来源对话中的约 10.38%，偏离 10% 来自分组与边际平衡。合法专家数据全部进入 Train/Val；没有按 SFT/RL 重合而删除 SFT。Train 与 Val 没有来源对话交集，已识别实体/来源组不跨模型训练与最终 Test；RL Dev 不与 SFT 梯度训练案例混用，SFT Val 也不与 RL Train 的已识别组混用。Val 用于模型选择，其专家轨迹不能与最终 Test 共实例。

Task manifest 在 Git 忽略的 `data/splits/stage2/`；Test 只保存 ID、快照、来源行及哈希、粗标签，不复制私有场景或参考动作。Task set SHA 使用 Stage 1 `task_set_hash` 的排序 ID 规范 JSON；完整 manifest 文件另有字节 SHA。相同输入、配置、seed 重算后的映射、ID 清单和 Task hash 已有实际测试。

Pass^1 预案覆盖全部 85 个 Test Task；预先按边际业务/快照/复杂度从中选定 50 个作为 Pass^4 子集。四条真实 Trial 全部成功才算 Pass^4；其余 35 个只做一次。预算是 85+3×50=235 Episode/Checkpoint，五检查点共 1,175 条。均未执行，不是模型成功率或已产生费用。

`pass1_plan_template.json` / `pass4_plan_template.json` 标为 NOT_RUN_UNRESOLVED，保留 Student checkpoint、服务版本、采样、Simulator、Harness、步数和上下文等待填项。用 `data.eval_plan.resolve_plan` 填齐真实配置后才得到 Stage 1 EvaluationPlan。schema 测试使用明确 synthetic 配置，没有生成伪 Episode；空记录的正式 Pass 值仍为 null。

后续训练和测试必须引用此 manifest 版本；预算若需改，只能在看 Test 模型成绩前、依据 Dev 时延与预算显式升版。当前可见分组隔离已验证，不能把它扩大为不可观测的上游种子污染已全部证明排除。
