# Stage 0 验收报告

## 结论

**PASS：Windows CPU 验证、真实双向交互与 WSL2/Ubuntu 小规模 CPU 复验均完成。用户本轮明确接受“复验跑通即结束 Stage 0”，该条件已满足；Stage 0 结束，未进入 Stage 1。**

44 项自动化测试全部通过，固定 8 个 Retail 任务完成快照加载、真实工具、官方目标状态和评分检查；另完成 2 条 DeepSeek 真实 Episode。未实现训练或进入 Stage 1。参考动作测试通过不是模型成功率；真实两条任务得分分别为 0 和 1，均如实保留。

Linux 增量复验使用 Ubuntu 22.04.5 / WSL2、独立 `.venv-linux` 和 Python 3.11.15：123 项锁定依赖一致性检查通过，3 项隔离/Mock 路由测试通过，2 个不同快照上的状态修改任务通过工具与官方评分检查。本轮 API 调用和费用均为 0。AutoDL/GPU/训练尚未验证，按用户本轮确定的范围不作为 Stage 0 收尾阻塞项。

## 固定版本

- tau2 Fork：`https://github.com/dhh1995/tau2-bench`，分支 `dhh/async-and-custom-completion`，SHA `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`。
- Dataset：`https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data`，Revision `86971dc03da6e7c1a7933295e05b84aab8215386`。
- AReaL 示例参考：`01de0a83e17cb12c918fc791466138ddbd4168c9`，未安装训练框架。
- Python 3.11.15 / Windows 11；核心库包括 tau2 0.2.1.dev0、Pydantic 2.14.0、LiteLLM 1.104.2、pytest 9.1.1。
- 依赖：`requirements-stage0.lock`；全部版本、项目文件与上游资源 SHA：`versions.json`。
- 数据文件和 4 份快照 SHA256：`data_manifest.json`；全部已核对下载尺寸及远端 LFS SHA256。
- DeepSeek 服务配置、返回 fingerprint 与费用：`deepseek_results.json` / `user_simulator.md`。服务别名不等于不可变模型权重。

## 测试执行结果

| Test ID | 验证内容 | 状态 | 证据 |
|---|---|---|---|
| A1 | Python 3.11 独立环境、tau2 导入、默认 Retail、15 个工具 | PASS | environment.md、environment.json |
| A2 | 依赖一致性及固定 Fork 工作区 | PASS | uv pip check；versions.json |
| A3 | WSL2/Ubuntu CPU 小规模复验 | PASS | linux_revalidation.json、linux_pytest.xml、linux_smoke_results.json、linux_packages.txt |
| A4 | AutoDL/GPU/训练目标环境 | NOT_RUN（后续阶段） | 本阶段未租卡、未安装训练框架 |
| G1 | Fork、Dataset、Python/依赖与文件版本固定 | PASS（本机） | versions.json、data_manifest.json、依赖锁 |
| G2 | 563 条 Retail RL 解析、ID、路径、动作参数 Schema；100 条 Retail SFT 抽检 | PASS | data_audit.json、data_schema.md |
| G3 | 4 份快照隔离、重复初始化、源文件不变、错误路径拒绝 | PASS | tests/stage0/test_db_isolation.py、pytest.xml |
| G4 | 8 个固定样本真实工具及官方评分，正确/错误数据库对照 | PASS | smoke_results.json、test_evaluator_integration.py |
| G5a | 官方双向 Orchestrator、Mock 路由、私有字段隔离 | PASS(mock) | user_sim_results.json、test_user_simulator.py |
| G5b | 2 条真实 User Simulator Episode 与可解释终止 | PASS（链路）；质量局限已记录 | deepseek_results.json、user_simulator.md |
| G6 | 44 项 pytest + Audit + Smoke + Mock 脚本真实执行 | PASS | check_results.json、pytest.xml、私有 UTF-8 日志 |
| E1 | 请求预算、限长、超时、失败不重试与累计账本 | PASS | test_deepseek_budget.py，5 项测试 |
| E2 | 真实失败任务的终态差异与离线反事实诊断 | PASS（诊断） | real_diagnosis.json；不改变真实得分 |
| G7 | 用户逐阶段人工验收 | PASS | 用户本轮条件验收：“如果这个可以跑通……完成了这个 stage0 就算结束了”；条件已满足 |

确定性样本（seed=42，先按 Task ID 排序，再按快照/是否修改状态选取）：`retail_245`、`retail_8`、`retail_454`、`retail_293`、`retail_479`、`retail_325`、`retail_65`、`retail_339`。覆盖全部 4 份数据库，6 条修改状态、2 条只读；8 条均无工具错误、参考 DB match，错误默认 DB 对照均拒绝回放。

## 已确认的兼容点

1. 563 条 Retail 的字符串化 evaluation_criteria 可转为当前 Fork 的 Task/EvaluationCriteria；全部数据库引用存在、符合 RetailDB。
2. SFT 全文件 33,531 条，其中 Retail 11,395 条、来自 1,000 个原始对话。完整下载，抽检未代替正式清洗。
3. Retail 工厂支持 `db` 注入，但顶层评分通过 registry 新建环境；只给 Rollout 注入 DB 不够。本适配为快照建立独立注册项，让官方预测环境与参考环境都从相同快照构造。
4. 不替换默认 retail 注册项、不修改上游文件或评分函数；官方 ALL 聚合、通信条件和提前终止逻辑保留。
5. 真实用户流程使用原始全局用户规范和任务说明，Agent 不获取 evaluation_criteria 或私有场景。

## 已解决问题与后续验证边界

- **Linux 环境门槛已通过**：此前 Ubuntu 初始化错误已在用户手动安装后消除。本轮 3 项 pytest 通过；`retail_245`（快照 1）和 `retail_8`（快照 2）均实际改变数据库、工具错误为 0、官方 reward=1、DB match=true；错误默认 DB 对照均拒绝。参考动作检查不等于模型任务成功率。
- **跨系统文件兼容**：Windows checkout 的 CRLF 在 WSL 下造成 Git 误报修改；确认 `core.autocrlf=true`、`core.fileMode=false` 后工作区干净，固定 SHA 不变，没有修改上游源码。D 盘挂载上的环境安装/导入较慢，后续建议把 Linux 环境放到 Linux 文件系统。
- **AutoDL 边界**：本次证明 Linux CPU 兼容性，未证明云端 CUDA、GPU 显存、推理或训练链路。租卡后在后续阶段做目标环境 smoke 即可。
- **模拟用户质量**：一条任务存在信息透露时机偏差；另一个地址任务出现国家名称同义表述。两条样本不足以证明正式 RL 所需的稳定性。
- **严格评分差异**：真实地址任务唯一 DB 差异是 `United States` 与 `USA`，官方 reward=0。离线仅规范化 country 后评分为 1，证明确非 DB 初态适配错误。保留失败，不私改评分或原始数据。
- **评测覆盖边界**：本数据默认 DB+COMMUNICATE，部分只读任务通信条件为空；DB match 不能证明行为时序/政策沟通均正确。Stage 1 应明确诊断指标和评测协议。
- **远端可复现性边界**：API 模型别名会变化，且不提供本次使用的 seed 参数；只能固定配置、记录 fingerprint/时间和轨迹，不能承诺未来完全相同输出。

## 修改/新建的文件

- 工程与配置：`.gitignore`、`.env.example`、`pyproject.toml`、`requirements-stage0.lock`、`README.md`。
- `src/policytrace/stage0/`：任务解析、快照隔离、官方评分注入、参考检查、Mock 交互、DeepSeek 有界调用。
- `scripts/`：固定来源 bootstrap、原始数据下载/恢复、审计、Smoke、CPU 检查入口、Mock、真实 DeepSeek Episode、离线诊断、证据记录。
- `tests/stage0/`：Schema、路径、隔离、官方评分、用户路由、付费调用控制。
- `reports/stage0/`：环境、版本、数据统计、逐样本结果、真实调用结果、质量审查和本报告。
- 原始数据、上游 checkout、密钥、完整轨迹与私有日志均排除版本控制；没有提交或推送 Git。

## 复现命令

从项目根目录运行（Windows）：

```powershell
python scripts/stage0_bootstrap.py
.venv\Scripts\python scripts/stage0_fetch.py
.venv\Scripts\python scripts/stage0_check.py
.venv\Scripts\python scripts/stage0_diagnose_real.py
.venv\Scripts\python scripts/stage0_evidence.py
```

前三项不调用模型；离线诊断需要本地保存的真实 Episode。Linux bootstrap 默认使用独立的 `.venv-linux`，本轮已实际验证。Linux 复验（项目根目录，uv 已在 PATH）命令如下：

```bash
python3 scripts/stage0_bootstrap.py
.venv-linux/bin/python scripts/stage0_linux_revalidate.py
```

Linux 结果及实际命令、耗时见 `linux_revalidation.json` 和 `linux_smoke_results.json`；私有日志在 `data/private/stage0/linux/`，保留原 Windows 证据。已增加 `scripts/stage0_replay.py`，两条真实轨迹均已免费回放并离线验证与原评分完全一致；全过程与文件职责见 `docs/stage0_walkthrough.md`。

真实调用入口为 `scripts/stage0_deepseek_smoke.py`，本轮已运行完成。它发现已有报告会拒绝自动重跑，防止再次扣费。累计 23 次请求，74,968 输入 + 1,023 输出 tokens，按高峰 cache-miss 估算 **0.702333 元**；实际账单未读取。

## Stage 1 的依赖与建议

Linux CPU 复验与用户本轮条件验收已完成。后续应固定评测协议、数据分组与最终测试隔离；对 Simulator 行为及字符串规范化做小规模开发集审查，保持官方最终评分不变。AutoDL 到位后检查 GPU/训练环境。暂不开展 SFT/OPD/GRPO，不以这两条真实结果报告 Base 分数。

## 用户验收与阶段收尾

用户明确表示小规模 Linux 复验跑通即可结束 Stage 0，本轮条件已满足，按该指示收尾，无需再次请求相同确认。模拟用户质量及严格字符串评分的局限继续保留。停止在 Stage 0；进入 Stage 1 仍需新的任务指示。

