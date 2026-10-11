# PolicyTrace-RL

面向多轮业务任务的 Tool-Use Agent 后训练项目。Stage 0–2 工程已完成，Stage 3_0 已完成离线 Mock Harness 验收。当前采用 **areal-retail-sft-v1 自定义 Policy**：精确复用冻结 SFT 业务规则，允许纯多工具调用，继续隔离文本与工具混合 Target。当前主视图 Train **9707** / Val **1080**，入口为 [sft_main_view.json](configs/data/sft_main_view.json)。

目前验证了任务解析、数据库隔离、原生工具、官方评分与离线交互闭环。尚未接入真实 Student 或执行 SFT/OPD/GRPO。当前版本变更见 [Policy 迁移报告](reports/policy_transition_v2/POLICY_TRANSITION_REPORT.md) 和 [Stage 3_1 接入清单](docs/stage3_1_handoff.md)。

## Stage 1：评测与奖励接口

- [评测协议 v1](docs/evaluation_protocol.md)：Pass^1、同 Task 四次全成功的 Pass^4、失败分母、配置一致性和缺失值规则。
- [官方 Reward 审计](docs/reward_analysis.md)、[研究候选与待验证假设](docs/reward_backlog.md)。
- `src/policytrace/evaluation/`：冻结的 Run/Task/Trial 记录、官方适配和离线统计。
- `src/policytrace/rewards/`：R0 原样调用官方评分，未来训练奖励的独立插件契约；R1 未实现。
- [Stage 1 报告](reports/stage1/STAGE1_REPORT.md)：实际测试、源码版本和回放证据。

从项目根目录使用现有 CPU 环境：

```powershell
.venv\Scripts\python -X utf8 scripts/custom_policy_check.py
.venv\Scripts\python scripts/stage1_eval_offline.py --input tests/stage1/fixtures/pass4_synthetic.json --output reports/stage1/synthetic_summary.json
```

第二条命令使用明确标注的 synthetic 夹具，只演示指标语义，不是模型成绩。当前检查入口免费执行 Mock Harness 与限定已暴露 Dev 的回归，不调用模型 API。正式 Task 划分仍冻结，真实四次重复评测和训练尚未执行。历史 stage1/stage2/stage3_0 check 属于旧原版 Policy 设置，避免对当前环境重跑并覆盖旧报告。

## 当前证据

- [Stage 0 验收报告](reports/stage0/STAGE0_REPORT.md)
- [版本与源码哈希](reports/stage0/versions.json)、[数据文件哈希](reports/stage0/data_manifest.json)
- [数据审计](reports/stage0/data_schema.md)、[固定任务检查](reports/stage0/smoke_results.json)
- [模拟用户验证与质量边界](reports/stage0/user_simulator.md)

## CPU 复现

需要 Git、uv，以及能够访问 GitHub、PyPI、Hugging Face 的网络。从项目根目录执行：

```powershell
python scripts/stage0_bootstrap.py
.venv\Scripts\python scripts/stage0_fetch.py
.venv\Scripts\python -X utf8 scripts/custom_policy_check.py
```

Linux/AutoDL 的 bootstrap 默认另建 `.venv-linux`，使用 `.venv-linux/bin/python`，避免误用同目录的 Windows `.venv`。小规模 Linux CPU 复验命令如下，实际结果见 `reports/stage0/linux_revalidation.json`；AutoDL GPU/训练检查留待后续阶段。

```bash
python3 scripts/stage0_bootstrap.py
.venv-linux/bin/python scripts/stage0_linux_revalidate.py
```

复验只执行两个参考任务和三项隔离/Mock 路由测试，不调用付费 API。先确保 `uv` 已在 PATH 中。WSL 中建议把虚拟环境放在 Linux 文件系统内，以减少 `/mnt/d` 上大量小文件的访问开销；可用 bootstrap 的 `--venv` 指定路径。

单独复现指定任务（不调用模型）：

```powershell
.venv\Scripts\python scripts/stage0_smoke.py --task-id retail_245 --seed 42 --output reports/stage0/single_smoke.json
```

阅读 [Episode 逐步示范与项目结构说明](docs/stage0_walkthrough.md)，或免费回放已保存的真实对话并离线重新评分：

```powershell
.venv\Scripts\python -X utf8 scripts/stage0_replay.py --task-id retail_131 --validate
```

## 少量真实交互

将 `.env.example` 复制为 `.env` 并在本地填写 `DEEPSEEK_API_KEY`。用户已授权的本轮模型为 `deepseek-v4-pro`，人民币预算上限 5 元。

```powershell
.venv\Scripts\python scripts/stage0_deepseek_smoke.py
```

此命令会产生费用。最多两条 Episode，单条最多 16 步；每次输出最多 512 tokens；不自动重试。请求前预留费用，内部预算 4 元，另留 1 元余量；使用累计账本，已有真实运行报告时拒绝直接重复运行。客户端估算不是服务商账单，实际扣费以服务商为准。

原始任务、数据库、完整轨迹、私有提示词和 API 费用明细保存在被 Git 忽略的 `data/` 下。`.env` 同样不进入版本控制。公开报告不应成为未来 Student 的输入。

## 工程边界

- 使用上游 `RetailDB`、工具、`Orchestrator` 和官方 Evaluator。用户已批准唯一 Fork 改动：Retail policy.md 替换为 SFT 业务 Policy；原件备份在 configs/policy/backups。工具、Schema、评分代码和原始数据库不变。
- `TAU2_DATA_DIR` 指向 `external/tau2-bench/data`，用于政策、默认数据库和用户规范；AReaL 快照单独由任务的 `db_path` 加载。
- 评分通过快照绑定的注册项调用原始 `evaluate_simulation(..., EvaluationType.ALL)`；默认 `retail` 注册项保持原样。
- 参考动作回放是有特权的测试夹具，不是模型表现，不得宣传为 Benchmark 成功率。
- 后续所有 Base/SFT/RL 和评测沿用同一自定义 Policy，日志绑定版本/SHA；指标不能与原 Policy 设置混报。Stage 3_1、真实模型和训练尚未开始。

## Stage 2 数据准备

Stage 2 已生成全量审计、分组划分、SFT 规范化与实际 token labels。当前数据选择见 [SFT 主视图](docs/sft_policy_main_view.md)，基础规则见 [数据划分](docs/data_split_protocol.md) 和 [SFT 预处理](docs/sft_preprocess.md)。旧 Stage 2/3_0 报告及 token 完整保留；新视图原样复用既有 token，不修改冻结划分。

```powershell
.venv\Scripts\python -X utf8 scripts/custom_policy_check.py
```

