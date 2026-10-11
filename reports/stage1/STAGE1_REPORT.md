# Stage 1 验收报告

## 结论

**PASS：统一评测协议、Episode 结果结构、离线聚合、官方 R0 封装与未来训练奖励接口已实现并实际验证。工程检查全部通过，等待用户人工验收；未进入 Stage 2。**

本轮执行 Stage 1 的 **48 项测试**及 Stage 0 相关 **20 项回归**，无失败、错误或跳过。两条历史 DeepSeek Episode 只做离线重放，完整官方 RewardInfo 与原记录一致：`retail_131=0`、`retail_152=1`。没有新的模型 API 请求；原费用账本哈希未变化。

这证明记录、评分适配和指标实现可用，不证明模型能力提升。没有 Base/SFT/OPD/GRPO 正式 Benchmark、没有新的真实 rollout、没有真实四次重复实验、没有训练或实际 R1 优化、没有正式数据划分。

## 固定来源与执行环境

- Fork：`https://github.com/dhh1995/tau2-bench`，SHA `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`，本轮工作区干净。
- Dataset：`inclusionAI/AReaL-tau2-data`，Revision `86971dc03da6e7c1a7933295e05b84aab8215386`，复用 Stage 0 已下载/校验数据；原文件版本证据在 `reports/stage0/data_manifest.json`。
- Windows 11，现有 `.venv`，Python 3.11.15；tau2 0.2.1.dev0、Pydantic 2.14.0、pytest 9.1.1。OS 的 platform 字符串仍采用 Windows-10 内核兼容标签，见 `check_results.json`。
- 使用既有 `requirements-stage0.lock`，未新增依赖；本轮库版本清单为 `packages.json`，检查运行时 SHA256 为 `check_results.json:source_sha256`。收尾文档及全部交付物的最终 SHA256 另存 `source_manifest.json`，并核对已测试代码没有继续改动。
- Stage 0 的 WSL 通过是历史背景；Stage 1 本轮在 Windows CPU 执行，未伪称 Linux/GPU 复跑。

## 上游官方语义

协议版本 **policytrace-eval-v1**，完整说明在 `docs/evaluation_protocol.md`，Reward 分析在 `docs/reward_analysis.md`。

| 原始实现 | 已确认语义 |
|---|---|
| `external/tau2-bench/src/tau2/evaluator/evaluator.py:evaluate_simulation` | USER_STOP/AGENT_STOP 后才评估；其他 tau2 终止给官方 0；ALL 只乘 reward_basis 里的分项 |
| `.../data_model/tasks.py:EvaluationCriteria` | 默认 DB、COMMUNICATE；Stage 0 审计当前 563 Retail Task 均采用此 basis |
| `.../evaluator/evaluator_env.py:EnvironmentEvaluator.calculate_reward` | 同一工厂建立预测/参考环境，真实轨迹与参考 actions 从同一初态回放，比较 DB 哈希；参考动作异常只警告后继续 |
| `.../evaluator/evaluator_communicate.py:evaluate_communicate_info` | assistant 文本小写化/去逗号后的字符串包含检查；空条件直接 1，不是政策语义评分 |
| `.../evaluator/evaluator_action.py:evaluate_actions` | 动作存在性诊断，不保证顺序；当前 ACTION 不参与最终 R0 |
| `.../domains/retail/tools.py:modify_user_address` 与 policy.md | 政策要求认证和明确确认，但该工具本身只赋值地址，没有通用历史确认判定 |

成功定义严格为官方原始 reward=1；0 为官方失败。暂不支持非二值 reward，不自动裁剪/阈值化。上游抛异常导致无法评分时保留 null 和错误状态；聚合可将该已启动 Trial 按失败计入分母，但不伪造官方 0。

`retail_131` 的国家字符串差异继续保留原 Reward=0，原 Stage 0 离线反事实只用作诊断。`retail_152` 原 Reward=1，但客户过早披露单独保留诊断代码；不因 Simulator 偏差重写 Agent 官方分数。DB 终态、工具成功、政策时序与客户忠实度分别解释。

## 结果格式与聚合协议

`RunContext` 固定版本、任务集哈希、模型/checkpoint/采样、User Simulator 配置、Harness 和运行限制。`EvaluationPlan` 显式列出 Task 与一个或四个 Trial；本阶段只有历史两条诊断 Task 与 synthetic 夹具，不是正式 train/dev/test 划分。

`EpisodeRecord` 是冻结的 Pydantic 结构，保留唯一 episode_id、task_id/trial_id、来源、快照 ID/hash、seed、评价时间、执行/评分状态、终止原因、数值官方结果、工具计数、分角色 telemetry 和私有轨迹哈希引用。完整原始 RewardInfo 存在 `data/private/stage1/`，不会复制隐藏 actions/scenario 到公开摘要。

- **Pass^1**：指定一次 Trial 的成功 Task 数 / 全部计划 Task 数；4-Trial 计划固定用第一个 Trial。
- **Pass^4**：每个相同 Task 四次全部成功才通过，再除以计划 Task 数。不同任务不能合成一组，也不能把一段保存 Episode 重标 Trial ID 当四次实验。Pass@4 至少一次成功，含义不同。
- Trial 缺失/显式 not_run：状态 incomplete，正式 Pass 值 null，分母仍为计划 Task 数。重复、未知 Trial、环境/模型/用户配置不一致或同 Task 快照变化均拒绝。
- 已启动的框架/网络/评分失败按失败计入完整试验分母，保留与官方判失败的区别。默认不重试，不静默丢任务。
- 工具完整错误率为 parse/schema、execution、framework 三类互斥失败 / 所有尝试；解析尝试未记录时不造完整错误率。零分母为 null。
- Student/User/Teacher Token 分开，缺值为 null；费用按角色/币种/账单或估算类型分组。耗时、GPU、Teacher 时间、训练 Token 和 GRPO 统计没有记录时不填 0。

## 实际执行证据

完整命令和真实耗时：`check_results.json:commands`。详细日志均在 `data/private/stage1/`。

| 检查 | 状态 | 本轮证据 |
|---|---|---|
| Stage 1 schema、指标、接口、CLI 与官方回放测试 | PASS，48 项 | `pytest.xml`；pytest 16.79 秒，外层进程 18.380 秒 |
| Stage 0 DB 隔离/官方评分相关回归 | PASS，20 项 | `stage0_regression.xml`；pytest 101.53 秒，外层 104.253 秒 |
| 原始真实 Episode 离线 R0 重算 | PASS | `replay_evidence.json`；两条完整 RewardInfo 与原记录一致，provider usage 累计亦一致；8.892 秒 |
| 真实回放记录离线聚合 | PASS（诊断） | `replayed_summary.json`；2 Task/2 Trial，无缺失；0.288 秒 |
| 四 Trial synthetic CLI 示例 | PASS（synthetic） | `synthetic_summary.json`；2 Task/8 Trial，展示 Pass^4 与至少一次成功的区别；0.269 秒 |
| 上游源码与付费账本未改 | PASS | `check_results.json` 的 clean/ledger/hash 证据 |
| 新真实 rollout、真实 Pass^4、GPU/训练 | NOT_RUN | 明确属于后续阶段 |

历史诊断摘要的 Pass^1=1/2 仅是这两个既有样本的离线统计，不是正式模型成功率。Pass^4 未请求且为 null。Synthetic 夹具是人工构造的两个任务各四条记录，不是独立模型实验，不作为能力结论。

原日志有 5 次已解析工具调用、0 次执行错误，执行错误率=0/5；解析失败/框架类别尝试缺失，因此完整 Tool Call Error Rate 为 null。分角色原 usage：Agent（schema 的 student 角色）65,720 输入 + 812 输出，User 9,248 输入 + 211 输出，共 74,968 + 1,023，与 Stage 0 一致。Teacher Token 没有记录，保持 null。

沿用 2026-10-09 已存档价格/usage 的历史上界估计：Agent 0.613404 CNY，User 0.088929 CNY，共 0.702333 CNY；不是本轮新增费用，也不是实际账单。本轮 API 调用/费用为 0。

## R0 接入与扩展接口

`rewards/official.py:evaluate_r0` → `evaluation/official_adapter.py:evaluate_official` → Stage 0 `evaluate_with_correct_initial_state` → 原官方 ALL。没有再实现第二套评分器，也没有规范化 country、增加步数罚分或重新加权。

未来插件通过 `rewards/interface.py:select_training_reward` 显式传入，输出独立 name/version/value/components 的 `TrainingReward`。默认返回 R0；官方记录冻结，聚合只读 official_score。插件输入仅数值奖励、终止原因、工具计数和耗时，没有私有 Task/scenario/参考动作或轨迹路径。测试用任意输出的替身证明隔离，不实现 R1 数值公式。trusted Python 插件仍需代码审查，接口不能阻止其自行读文件。

`docs/reward_backlog.md` 的六项候选按先诊断排序：Simulator 稳定性、字段歧义、认证/确认时序、只读拒绝质量、重复与效率、稀疏奖励/全同组。每项标注已观察或假设，定义可验证证据、投机/归因风险和需要等待的开发集统计。没有拍定 λ 或声称算法有效。

## 文件与复用

- 新增 `src/policytrace/evaluation/{schema,metrics,official_adapter}.py` 和 `src/policytrace/rewards/{official,interface}.py`。
- 新增 `scripts/stage1_eval_offline.py`、`stage1_replay_evidence.py`、`stage1_check.py`；`tests/stage1/` 与明确标注 synthetic 的 JSON 示例。
- 新增 `configs/evaluation/protocol.example.yaml`（参考模板，不是已冻结 Task 集合）、3 份协议/Reward 文档和本报告。
- `pyproject.toml` 将 Stage 1 纳入默认 pytest 搜索；README 增加入口。依赖版本和 Stage 0 代码/数据/报告均保留；不提交或推送 Git。
- 原样复用 Stage 0 Task 解析、快照加载/隔离和官方评分适配，不实现 Harness 主循环。

## 可复现入口

从项目根目录使用现有 Windows 环境：

```powershell
.venv\Scripts\python -X utf8 scripts/stage1_check.py
.venv\Scripts\python -m pytest tests/stage1 -q
.venv\Scripts\python scripts/stage1_eval_offline.py --input tests/stage1/fixtures/pass4_synthetic.json --output reports/stage1/synthetic_summary.json
.venv\Scripts\python scripts/stage1_eval_offline.py --input data/private/stage1/episodes.jsonl --plan data/private/stage1/plan.json --output reports/stage1/replayed_summary.json
```

这些命令不调用模型。完整检查依赖本地已保存的两个 Stage 0 私有 Episode；若移到另一台机器没有证据，应明确 NOT_RUN/BLOCKED，不能生成替代“真实”样本。Linux 的 Python 路径可换为独立 `.venv-linux/bin/python`，但本轮没有实际运行该命令，不承诺本轮 Linux Stage 1 已验证。

## 验收门槛与下一阶段

| Gate | 状态 | 依据 |
|---|---|---|
| S1-A 官方语义审计 | PASS | evaluation_protocol.md、reward_analysis.md、固定源码 |
| S1-B 指标协议 | PASS | 分母、Trial 完整性、配置与缺失值规范 |
| S1-C 可执行聚合 | PASS | 真实脱敏回放 JSONL 和 synthetic JSON 的 CLI 输出 |
| S1-D 官方 R0 不变 | PASS | 原分数/完整 RewardInfo 不变；正确/错误 DB 和 snapshot 拒绝测试 |
| S1-E 扩展接口与候选记录 | PASS | 仅接口和测试替身、6 项带证据状态的 backlog |
| S1-F 测试复现 | PASS | 本轮 48+20 项，5 个入口进程成功，非历史冒充 |
| S1-G 阶段边界 | PASS | 无新 API、模型下载、训练、正式划分、R1 或推送；停止在 Stage 1 |

Stage 2 需要提供来源对话/Task 归并、近重复/泄漏审计、冻结的训练/开发/最终测试清单与哈希、SFT 数据组织和任务类型标签。后续 Stage 3 才实现 Student Harness；其日志必须遵守本协议，特别是记录解析失败尝试、真实 usage、Episode 身份和已启动的基础设施失败。

用户人工验收为 PENDING。依据 `.agents/skills/policytrace-stage1/stage1.md`：“最后停止，等待用户人工验收。”完成本阶段工程后停止，不自动进入 Stage 2。
