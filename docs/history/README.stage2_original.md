# PolicyTrace-RL

面向多轮业务任务的 Tool-Use Agent 后训练项目。**Stage 0** 已完成 AReaL Retail 与 τ²-bench Fork 的兼容性验证；**Stage 1** 提供统一评测协议和官方 R0；**Stage 2** 已完成全量数据工程与测试，待人工验收。

本阶段验证任务解析、自定义数据库隔离、真实业务工具、官方评分初态和双向交互。没有训练模型，也没有实现 SFT、OPD、GRPO 或完整自研 Agent Harness。

## Stage 1：评测与奖励接口

- [评测协议 v1](docs/evaluation_protocol.md)：Pass^1、同 Task 四次全成功的 Pass^4、失败分母、配置一致性和缺失值规则。
- [官方 Reward 审计](docs/reward_analysis.md)、[研究候选与待验证假设](docs/reward_backlog.md)。
- `src/policytrace/evaluation/`：冻结的 Run/Task/Trial 记录、官方适配和离线统计。
- `src/policytrace/rewards/`：R0 原样调用官方评分，未来训练奖励的独立插件契约；R1 未实现。
- [Stage 1 报告](reports/stage1/STAGE1_REPORT.md)：实际测试、源码版本和回放证据。

从项目根目录使用现有 CPU 环境：

```powershell
.venv\Scripts\python scripts/stage1_check.py
.venv\Scripts\python scripts/stage1_eval_offline.py --input tests/stage1/fixtures/pass4_synthetic.json --output reports/stage1/synthetic_summary.json
```

第二条命令使用明确标注的 synthetic 夹具，只演示指标语义，不是模型成绩。检查入口会免费重放已保存的两条 Stage 0 Episode，并聚合为诊断摘要；不运行新模型对话。正式 Task 划分已在 Stage 2 冻结，真实四次重复评测和训练尚未执行。

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
.venv\Scripts\python scripts/stage0_check.py
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

- 使用上游 `RetailDB`、工具、`Orchestrator` 和官方 Evaluator；不重写业务政策或奖励规则。
- `TAU2_DATA_DIR` 指向 `external/tau2-bench/data`，用于政策、默认数据库和用户规范；AReaL 快照单独由任务的 `db_path` 加载。
- 评分通过快照绑定的注册项调用原始 `evaluate_simulation(..., EvaluationType.ALL)`；默认 `retail` 注册项保持原样。
- 参考动作回放是有特权的测试夹具，不是模型表现，不得宣传为 Benchmark 成功率。
- Stage 0/1 后已获用户明确指示执行 Stage 2；本阶段交付后等待人工验收，不自动进入 Stage 3。

## Stage 2 数据准备

Stage 2 已生成全量来源审计、跨源关系与全局分组清单、SFT 规范化/实际 token labels、尚未执行的 Stage 1 评测计划模板。验收结果见 [STAGE2_REPORT](reports/stage2/STAGE2_REPORT.md)，规则见 [数据划分](docs/data_split_protocol.md) 和 [SFT 预处理](docs/sft_preprocess.md)。数据与证据在 Git 忽略目录，本阶段不训练模型。

```powershell
.venv\Scripts\python -X utf8 scripts/stage2_check.py
.venv\Scripts\python -X utf8 -m pytest tests/stage2 -q
```

