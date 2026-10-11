# Stage 3_1 PHASE_LOCAL 验收报告

状态：**LOCAL_PREP_PASS（本地离线准备）**。真实运行仍 **BLOCKED_MODEL / BLOCKED_ENV / BLOCKED_PRICE**；API Key 仅检查当前进程是否配置，不读取 `.env`。E0、真实 Qwen forward、云端部署与依赖解析全部 **NOT_RUN**。

执行 Skill：`.agents/skills/policytrace-stage3/stage3_1.md`。参考并保持 Stage 0、Stage 1、Stage 2、Stage 2 completion、Stage 3_0、Policy transition 最新报告。没有进入 PHASE_REMOTE 或训练。

## 实际变更及复用

- `src/policytrace/stage3_1/`：本地真实 Qwen 客户端、DeepSeek 原生 UserSimulator callback、共享预算、冻结资产检查、按授权 Task 加载、原生 Orchestrator 装配、协议冻结/复核和汇总。
- `scripts/stage3_1_*.py`：下载/验证、只读 inventory、允许清单打包/解包、Policy 验证/安装、Dev Smoke、E0 Test-85、汇总、安全审计与离线验收入口。
- `configs/harness/stage3_1.example.json` 和 `stage3_1_assets.lock.json`：无密钥配置、现有资产字节哈希。
- `requirements-stage3_1-candidate.txt`：独立云端候选依赖；不是已解析的 Linux lock。
- `tests/stage3_1/`、`docs/stage3_1_reuse_map.md`、`docs/stage3_1_remote_runbook.md`。

既有文件只改动两个：`harness/model_client.py` 增加可选 telemetry；`harness/agent_adapter.py` 从客户端取采样、转交 seed、如实保存来源/遥测和 logprobs 缺失原因。原始文件在 `data/private/stage3_1/original_files/` 保存，未放宽旧 Stage 3_0 offline Driver。

继续复用 Stage 2 Qwen Tokenizer/Chat Template、多工具 Parser、ContextBuilder、ObservedEnvironment、RLTaskPool 的载荷/快照验证、Stage 1 EvaluationPlan/EpisodeRecord/aggregate 与官方 evaluate_r0。交互唯一循环来自固定 Fork Orchestrator，没有另写 Loop 或评分器。

## 固定实验事实

|项目|本轮核验|
|---|---|
|Fork base|`e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`|
|唯一允许的 Fork 修改|Retail `policy.md`|
|自定义 Policy|`areal-retail-sft-v1`，SHA `efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936`|
|AReaL revision|`86971dc03da6e7c1a7933295e05b84aab8215386`|
|RL 划分|Train 394 / Dev 84 / Test 85，未重划|
|SFT 默认视图|`policy_sft_v2`，9707 Train / 1080 Val，纯多工具保留、混合 Target 隔离|
|Tokenizer|Stage 2 原文件；revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`|
|Student 权重|Qwen2.5-3B-Instruct；权重 revision 待用户下载前锁定，未下载|
|评分|官方 R0 不变；不代表完整业务 Policy 合规评估|

## 实际离线测试

|测试范围|结果|
|---|---|
|Stage 3_1 新增测试|65 passed|
|现有 Stage 3_0 / 自定义 Policy Harness|61 passed|
|Stage 0 / 1 / 2 / 多工具范围内回归|164 passed，10 项按既有冻结 Test 隔离规则 deselected|
|合计|290 passed，0 failures / 0 errors|

实际命令、退出码、日志 SHA、时间及冻结检查保存在 `check_results.json`；公开 XML 已去掉 traceback/assert 正文，完整日志/XML 在忽略的 `data/private/stage3_1/`。

复现完整本地验收：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_check.py
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_data_inventory.py
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_git_audit.py
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_run.py env-check --config configs/harness/stage3_1.example.json
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_run.py dev-smoke --split dev --config configs/harness/stage3_1.example.json --dry-run
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_run.py e0-test --split test --confirm-frozen-test --config configs/harness/stage3_1.example.json --dry-run
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_download_student.py --local-dir data/private/stage3_1/models/unused --revision 0000000000000000000000000000000000000000 --dry-run
```

最后一条全零 revision 仅是离线测试占位，不能用于真实下载。`env-check` 未就绪返回 2 是预期阻断；`--dry-run` 返回 0 表示预览执行成功，不代表真实运行 READY。

新测试用真实固定 Tokenizer 与 Dev 隔离快照执行 Fork 闭环，Student 为注入的 generation 桩，User 为 HTTP MockTransport。实测纯多工具完整关联及下一轮 Context、混合严格拒绝、部分写入后工具错误、原始 DB 未变、官方评分与原生 SimulationRun 序列化。HTTP 桩测试了 401、429、timeout、缺 usage、截断响应和坏 JSON；没有真实付费请求。

Student 直接切分桩模拟的 generate sequences，验证 prompt 原 IDs 和 completion 原 IDs；测试显式阻止重新编码。所有这些证据为 `mock` / `mock_encoded`，没有冒充 `model_generated`。Mask 的 prompt 条件为 0、当前 Student 动作为 1，工具/User 仅进条件；EOS 属于当前生成动作，未实现训练 Loss。

门禁测试涵盖缺数据、错误 Policy、缺权重/Key/价格、不可变 revision、协议变更、非真实 Dev 证据、成本超限、重复 task/trial、已有 attempt 拒绝覆写、85 槽位部分结果 Pass¹=null，以及同步路径穿越/不同哈希拒绝覆盖。网络连接由 offline_guard 阻断。

## E0 私有依赖与迁移

最小包：**10 文件，46,809,598 字节**，全部当前哈希已校验，Dev/Test 84/85 数量与 task-set hash 已核验。准备期 Test 正文反序列化次数为 **0**。

- Dev task-set SHA：`8f8bc4ef239658a7f514a98a8a597935cee0a3b1e4766cdef6ef25b7b5a59fce`。
- Test task-set SHA：`639f6266a127b2e8b625401b52213e66e5b7117209d42b4bf15a2162acb100d5`。
- required：两个冻结 manifest、原始 RL 任务文件、四份 DB 快照、三份 Tokenizer 文件。
- optional Stage 4：本轮私有清单列出 16 文件、1,127,031,304 字节（原 SFT/当前默认视图及相关训练清单）；不是整个历史数据仓库，也不作为 E0 前置条件。
- download on remote by user：3B Student 权重、下载 receipt。
- runtime secret manual：用户在云端配置 Key；无密钥进入 Git 或同步包。
- Git code/config：固定 Policy Bundle、Bootstrap、资产锁和其他允许文件随项目 Git 迁移；`external` Fork 单独恢复固定 Commit。

完整允许清单留在 `data/private/stage3_1/sync_allowlist.json`，逐文件 SHA 锁在 `configs/harness/stage3_1_assets.lock.json`。打包器没有自动打包真实数据；单元测试只使用 synthetic archive。用户未来手动 pack→scp→unpack→SHA 校验；不重划数据、不伪造数据库、不重新 Tokenize。

## Git 安全与不可变资产

项目根目录无 `.git`：根 Git status/ls-files/check-ignore/diff/历史审计 **NOT_AVAILABLE_NO_ROOT_GIT**。固定 Fork 的只读 Git 验证已执行且通过。拟发布精确文件清单及敏感字面量扫描见 `git_safety_audit.json` 的 `candidate_files`；它包含代码、文档、公开配置、必要历史报告、脱敏新报告与 CPU/候选依赖清单，不包含原始任务、冻结私有 manifest、DB、Token、日志、密钥或模型。

初始化根 Git 后用户应重跑只读审计，检查 staged/history，再按 Runbook 逐文件暂存并推送；当前报告不能证明不存在尚未建立的 Git 历史泄漏。没有读取 `.env`，扫描发现只输出类型/文件位置，不回显凭据。

开始前 2183 文件哈希基线复核：只有上述两个获批 Harness 文件改变；其他旧报告、冻结划分、原始 DB、SFT 行/Token、Tokenizer、原 Policy 备份、评分代码及历史 API 账本全部未变。证据见 `check_results.json:historical_integrity`。

## 尚未实测与 PHASE_REMOTE 接入清单

1. Linux GPU 候选依赖未安装/解析，PyTorch、Transformers、CUDA、BF16、实际显存及推理速度 **NOT_RUN**。云端先 pip check、保存 freeze 和驱动/硬件信息，再运行无权重离线测试。
2. 真实权重 shard、receipt、模型 forward、实际 `model_generated` IDs、真实停止行为待用户下载后 Dev Smoke。没有宣称 Mock 已证明数值推理可用。
3. 真实 DeepSeek 网络可达性、服务模型版本/价格、User Simulator fidelity 和账单未知。价格模板为 null，必须用户核实；无重试，失败预留不释放，实际账单未知始终 null。
4. 默认 reserve 512、Context 16384、40 steps 需要 Dev 检查；超限不会自动摘要。预算墙钟在调用边界检查，不能硬中断正在执行的 GPU forward。
5. 不支持断点续跑；已有目录禁止复用，已开始失败计入分母，缺失槽位保留。正式 Test 前须用户审核此限制和失败处置。
6. E1～E4 checkpoint receipt 与仅允许 checkpoint 差异的比较门禁未实现，留后续阶段扩展同一驱动；不能手改 E0 receipt/freeze 冒充训练权重。
7. 用户提供 Git 地址/分支/Commit、SSH alias、目标新目录，以及安装/同步授权后，才进入 PHASE_REMOTE。云端检查后再次停止，真实下载、Dev 和 Test 由用户手动运行。

本轮 **0 付费 API、0 模型下载、0 真实评测、0 GPU 租用、0 SSH、0 Git 发布命令、0 训练**。停止，等待用户审查并自行推送 GitHub。
