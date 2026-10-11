---
name: policytrace-stage3-1
description: 在既有 PolicyTrace-RL 工程和 areal-retail-sft-v1 Policy 上，先本地完成真实 Qwen/DeepSeek 适配、下载及 E0 评测脚本与离线验收并暂停，等用户自行推 Git 并配置 SSH 后再 clone 到 AutoDL 进行只读/最小部署验证并暂停；用户手动下载模型与运行 Dev/Test。
---

# PolicyTrace-RL · Stage 3_1 Skill（v2，先开发，用户推送，后部署验收）

> **给 Codex 的执行指令。** 必须在用户现有 PolicyTrace-RL 仓库中增量开发，不能另建项目。此次明确分成两个**独立会话/阶段**：①本地开发全部脚本并离线验证，之后**停止，等待用户自行 Git Commit/Push**；②用户明确告知 GitHub 已推送且提供可用 SSH Host alias 后，登录其 AutoDL 实例，clone 对应 Commit，检查环境和数据/Policy，执行无权重、无付费 API 的离线预检，然后**立即停止**。下载 Qwen Student、调用 DeepSeek、Dev Smoke 和 E0 正式 Test-85 全部由用户本人后续手动运行。
>
> **版本状态：** `areal-retail-sft-v1` 自定义业务 Policy；Stage 3_0 Harness 已完成；本阶段不得修改数据划分、工具 Schema、DB、官方 R0 或另写一套 Agent Loop。**特别禁止未经用户明确许可进行 Git commit/push、GitHub 仓库操作、模型权重下载、真实模型推理、付费 API、Test-85。**

## 0. 立即遵守的分阶段门禁

**PHASE_LOCAL（用户第一次启动 Skill，默认且唯一可自动执行阶段）：**

1. 读取已有工程/版本；检查代码与私有数据的实际依赖。
2. 实现 Stage 3_1 所需真实适配器、Student 下载/校验、Dev Smoke、Test-85 启动、结果汇总和部署/数据清单脚本。
3. 在本机使用 Mock/Fixture + 真实固定 Qwen Tokenizer + 已有 Fork Orchestrator 离线测试，不加载模型权重、不发网络付费请求、不读冻结 Test 隐藏正文。
4. 做 Git 安全审计；给用户一份**仅供本人执行**的 Git 提交/推送清单。可以列出建议的 `git add <精确文件>` / `git commit` / `git push` 命令，但**绝不执行**任何上述命令，不要创建 GitHub 仓库，也不要改 remote、push、force push。
5. 产出 `STAGE3_1_LOCAL_PREP_REPORT.md` 和 Runbook，**停止**。不得自行进入下一阶段。

**PHASE_REMOTE（必须等用户明确消息“我已推送 Git，SSH 配置好了，请开始远程部署检查”才可执行）：**

1. 从用户已配置好的 SSH Host alias 连接其指定实例，确认目标主机身份。先检查环境和目录是否有冲突。
2. 经用户授权，在指定新目录执行 `git clone`（或按既有项目工作树判断，禁止覆盖）；检查实际 Commit 与 PHASE_LOCAL 交接的 Commit 一致。
3. 配置隔离 Python 环境（会安装/写入时先征得用户同意），恢复固定 Fork Commit 与版本化自定义 Policy，验证 SHA；执行 Linux 无权重、无付费 API 的代码/协议自检。
4. 根据本地生成的精确数据依赖清单核查 RL Dev/Test manifest、任务载荷与所需四份 DB 快照；缺少则输出 **BLOCKED_DATA + 用户可执行的同步方案**，禁止擅自重建数据或查看 Test 隐藏内容。若用户明确允许单独同步私有数据，仅经 SSH/SCP/rsync 安全传输并校验哈希，不上传 GitHub。
5. 产出 `STAGE3_1_REMOTE_CHECK_REPORT.md` 和用户手动操作命令，**停止**。不能自动下载 Student、调用 DeepSeek、跑 Dev Smoke、跑 Test、跑训练。

**用户运行阶段（本 Skill 不代执行）：** 用户手动下载并校验模型 → 真实 Dev Smoke 3–5 条 → 根据实测确认 GPU/API 费用 → 冻结共同协议 → 用户确认后手动 E0 Test-85 → 汇总。没有真实 Episode 前，状态只能是 `READY_FOR_USER_RUN` 或 `BLOCKED_*`，绝不能标为 E0 PASS。

## 1. 锁定已完成项目的事实（先核实源代码，不能只信本指令）

依次阅读实际仓库中：`STAGE0_REPORT.md`、`STAGE1_REPORT.md`、`STAGE2_REPORT.md`、`STAGE2_COMPLETION_REPORT.md`、`STAGE3_0_REPORT.md`、`POLICY_TRANSITION_REPORT.md`、`docs/evaluation_protocol.md`、`docs/harness_protocol.md`、`docs/stage3_1_handoff.md`、相关源代码、最新配置与测试。文件不存在时报告，不凭想象补造模块接口。

- **正式 Policy**：`areal-retail-sft-v1`，取自 AReaL Retail SFT System；当前 Policy SHA256 `efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936`，原 Fork SHA256 `4313d3fef8acf919f555fa17fbce929cc3ed1cef2dd8f0d35ff5c8c3364de176`。允许单回合多个工具调用，仍禁止混合文本与工具，正式 `validate_communication=True`。不能恢复原单工具 Policy；业务写入确认采用该版本文本、具体条款照旧。
- **Fork**：`dhh1995/tau2-bench`，分支 `dhh/async-and-custom-completion`，基础 Commit `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`。原工作区因**唯一允许的 `retail/policy.md` 修改**有意 dirty；`git reset --hard`、`git clean` 等破坏性操作禁止。应在新的 clean Fork checkout 上用项目现有 Policy Bootstrap 安装上述自定义 Policy；校验只有预期文件存在差异。不得更改 Fork Orchestrator、Tool Schema、Evaluator、DB。
- **数据**：AReaL revision `86971dc03da6e7c1a7933295e05b84aab8215386`；RL Train **394**、Dev **84**、Test **85**（冻结、不重划、不泄漏）。最新 SFT Main **9707 Train / 1080 Val**，当前 `configs/data/sft_main_view.json` 指向 `policy_sft_v2`，纯多工具监督保留、混合 Target 隔离；旧 `policy_main_v1` 不是默认训练视图。
- **Student**：`Qwen/Qwen2.5-3B-Instruct`；既有 Qwen tokenizer revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`，模型权重 revision 待用户下载前解析并锁定，不可假装与 tokenizer 自动一致；7B Teacher 不下载。
- **Stage 3_0 Harness**：复用 `src/policytrace/harness/{model_client,agent_adapter,context,runner}.py`、Stage 2 Qwen Tokenizer/Parser、Stage 0/1 Task+DB+R0、原生 Fork Orchestrator；`identity-v0` Observation Projection；Context 预算约 16K + 生成 reserve（以当前配置为准）；Stage 1 完整 Episode/Trial、Pass^1/Pass^4 统计语义不可改。
- **冻结资产**：Stage 2 的 Task/split、DB snapshot、Tokenizer、SFT 原始/Token/Main/quarantine 等历史事实与 SHA；Stage 3_0 的 47 项 Harness 测试与范围内回归结果为历史离线证据，不能充当真实 Student 验收。

开始编码前写一张**复用映射**（现有真实模块/调用点 → 新增最小代码 → 测试证据）；既有能力优先复用，不能新建第二套评分器、Agent Loop、数据拆分器。

## 2. PHASE_LOCAL：完成全部脚本（本地优先，不等待服务器）

### 2.1 实际代码与数据依赖盘点

不要只依赖文档猜测目录。沿实际导入链（Evaluation Runner → RLTaskPool/DevTaskPool → Task Loader → DB Adapter → Evaluator）识别 E0 真正需要哪些文件。

创建可运行的**只读依赖清单/校验入口**，例如 `scripts/stage3_1_data_inventory.py`，要求：

- 能列出**最小 E0 实验数据依赖**：已冻结 Dev/Test manifest 与 Task payload 所需源文件、对应四份 DB 快照、必要的配置/索引/Tokenizer 资产；不需要训练用的完整 SFT Token 数据才可运行 E0。不能只复制 manifest 而缺少 Task 内容或评分所需初态。
- 分类为 `GIT_TRACKED_CODE`、`GIT_IGNORED_PRIVATE_REQUIRED_E0`、`GIT_IGNORED_PRIVATE_OPTIONAL_STAGE4`、`DOWNLOAD_ON_REMOTE_BY_USER`（3B 模型）、`RUNTIME_SECRET_MANUAL` 等。打印公开报告时只输出类型、数量、大小、Hash/摘要；若路径/任务 ID 含隐私则保留在私有清单。
- 每个必需文件使用既有 Manifest/SHA 或新增 SHA256 做内容核验，绝不可在服务器重新 `random_split`、重生成 Test、重新抽 85 个任务或替换 DB 快照。Test 准备期不反序列化隐藏测试任务正文，不打印 `user_scenario`/`evaluation_criteria.actions`；只检查存在性、大小、哈希、总数。
- 生成用于用户操作的**精确同步清单/传输说明**。如实现打包脚本，只能依据严格 allowlist 创建本地私有归档、打包后校验；禁止把所有 `data/` 盲目打包或将归档保存进 Git tracked 目录。打包和上传必须由用户单独触发，不属于自动 PHASE_LOCAL。
- 后续 Stage 4 的 `data/processed/stage2/policy_sft_v2/` 和最新 SFT 主视图可按需同步，**当前 E0 不把全部 SFT 数据上传作为前置条件**。如果某项既有离线测试确实依赖 SFT 数据，区分“完整回归可选数据”与“真实 E0 必需数据”，不要为了让单测通过迫使用户传整包 SFT。

**重要 Git 解释：** `git clone` 在远程新目录创建一份**只含版本控制内容**的工程；它不会把你本地 `.gitignore` 排除的文件同步过去，也不会凭空恢复私有 `data/processed`、冻结 Test Manifest、数据库快照或模型权重。`git pull` 同样不负责这些资产。这不是 Git 覆盖数据，而是**未被追踪的本地文件不会随 Git 迁移**。如果目标目录已有数据，clone 到另一新目录；禁止用 reset/clean 覆盖数据。`configs/data/sft_main_view.json` 即使被 Git 追踪，它引用的 `policy_sft_v2` 文件可能不在 Git 中，必须明确标记缺失而不是用旧视图替代。

### 2.2 真实 Student ModelClient（本地开发、离线测试）

基于现有 Stage 3_0 `ModelClient/AgentAdapter/ContextBuilder` 最小实现 `TransformersQwenModelClient` 或当前项目合理等价物，支持真实 GPU 上加载 `Qwen2.5-3B-Instruct` 的本地路径，但本阶段**不执行真实模型加载**。

必须做到：

- 使用已有 Qwen Chat Template/Tokenizer 与多工具 Parser，不修改 System/Tools 包装；输入 Student 的仅为 Policy、Tool Schema 与已授权可见历史，不含私有 Task/Scenario/参考评分答案。
- `generate()` 后**直接保存模型实际生成的 Token IDs** 与输入 `prompt_ids`，分离 prompt/completion/EOS/停止符；不得通过 `decode` 然后重新编码伪造原始 completion IDs。Mock 测试结果明确标为 `mock_encoded`，真实 `model_generated` 留待用户运行验收。
- 保持 ToolCall 批次 ID、顺序、关联返回；允许纯多工具，不把它标为违规；拒绝文本+工具混合（`validate_communication=True`），记录失败原始输出。
- Model dtype、device、max context、生成 reserve/max_new_tokens、temperature/top_p/top_k/seed/EOS、版本/hash 全部显式配置且记录；`identity-v0` 默认不摘要、不裁剪，超限保留可追溯事件并停止这一 Trial，不能默默截断。
- 保存 Student 每个动作的真实生成 Token Span 及 Role/Response Mask，Tool/User 消息仅属于条件上下文，不属于当前动作。只做数据记录，不实现 RL Trainer、GRPO Loss、OPD Teacher。

### 2.3 DeepSeek User Simulator Adapter（开发与 Stub 测试）

复用 Stage 0 已有 Provider/账本，保留 τ² 原生 UserSimulator Scenario 包装和停止语义。支持服务器运行时通过 `DEEPSEEK_API_KEY` 环境变量或**Git 忽略的私有配置**取 Key。请提供仅含占位符的 `.env.example`/Runbook；不得读取、复制、打印、提交本地真 Key，不得写入客户端调用参数/日志/tracebacks。只记录“配置是否存在”，不回显其值。

超时、限流、重试、异常、Provider Model ID、temperature、可用的 seed、请求/输出 token 使用量、API calls、费用真实/估算/未知状态都应能记录；不可获得的费用写 `null`，不假设为 0。UserSimulator 不收到奖励/参考动作等隐藏评分信息；Student 不收到完整 `user_scenario`。本阶段只使用 Fake/Stub API Response 验证路径，不能实际调用 DeepSeek。

### 2.4 Student 下载/验证脚本（写好，不下载）

实现类似 `scripts/stage3_1_download_student.py`：固定默认 Model ID `Qwen/Qwen2.5-3B-Instruct`，支持 `--local-dir`、固定 `--revision`、`--source`（HF / 可选 ModelScope）、`--dry-run`、`--verify-only`，根据下载 SDK 实际能力支持恢复/校验。下载地址必须由用户在服务器运行时指定数据盘目录，避免硬编码假定 AutoDL 每台均有 `/root/autodl-tmp`。包含空间预检、模型/Tokenizer revision 与模板/EOS 一致性核验、下载中断处理、基本文件完整性检查。不要下载 7B Teacher，也不要在本地测试中下载任何权重；不得把模型数据加入 Git。

### 2.5 三类手动 CLI 与统计脚本

根据项目习惯实现最小的 CLI，入口可合并但语义必须分明：

**`env-check` / `dry-run`（Codex 可运行）：** 不能加载真实模型权重、调用付费 API、泄漏 Test 隐藏内容；核对运行环境、Policy SHA、Fork 基础 Commit 和唯一批准改动、Dev/Test manifest 哈希及 84/85 数量、DB 快照、Stage 2/3 共享配置、数据盘路径、模型目录存在、环境变量 Key 是否存在（布尔值）、日志目录写入安全、计划/输出重名风险，输出 `READY / BLOCKED_DATA / BLOCKED_MODEL / BLOCKED_API_KEY / BLOCKED_POLICY / BLOCKED_ENV` 等具体状态。模型未下载/API 未配置时可单独通过代码/数据检查，但**完整运行就绪必须 BLOCKED**。

**`dev-smoke`（只能用户日后手动运行）：** 3–5 个事先固定的 Dev 任务、真实 Qwen + DeepSeek UserSimulator + Fork 环境/DB + 官方 R0；记录协议正确性、Token、工具、Context 增长、费用/延迟/显存。标注 `purpose=diagnostic`，不使用冻结 Test 调试。

**`e0-test`（只能用户日后手动运行）：** 必须具备真实 Dev Smoke 证据、共享协议冻结文件、显式 `--split test --confirm-frozen-test` 等双重门禁；运行**Test-85 × 每 Task 一次独立 Trial**，保持 Stage 1 `policytrace-eval-v1` 分母与 `reward=null` 区分，R0 只由官方 Evaluator 产生。未来 E1/E2/E3/E4 只切换 checkpoint，沿用相同用户、工具、Policy、预算、评测协议；不能写死只服务 E0 的第二套 Loop。正式 Test 一旦运行，不能依据 Test 结果修改 Prompt/Decoder/Policy/模型选择后重试并冒充第一次结果。

用户可分批手动执行，共享一个明确冻结的 85 Task 评测计划，每个 `(task_id,trial_id)` 只运行一次且结果 append-only；若无法安全实现断点恢复，明确只支持保留部分结果并由用户决定后续重新规划，绝不覆盖旧记录或丢失败任务。用户应能设置预算/最多 Episode 数、最大 User+Student 调用数和停止条件；遇到 DeepSeek API error/模型溢出按已开始失败如实记账，不能自动“静默补测”。Dev Smoke 未有成本数据时对 Test 的总费用标 `UNKNOWN` 并阻断盲目启动或要求用户显式成本确认（不能猜测 GPU/API 价格）。

**汇总脚本：** 复用 Stage 0/1/3_0 的原生 SimulationRun、EpisodeRecord、Decision/Tool/User Trace、ToolStatistics 与官方 R0；报告 planned/started/completed、R0=1/0/null、合法/异常停止、Pass^1 成功数/分母、工具次数与 parse/execution/framework 三类错误、multi-tool、mixed reject、Context tokens/max/p50/p95、Student/DeepSeek Token、time、GPU 显存、API 费用（未知置 null）。Test 不齐 85 则 `incomplete`、正式 Test Pass^1=null，不能只根据已完成部分输出完整得分；Pass^4 此阶段 `not_measured`。Raw 轨迹与 User Scenario/DB/hidden criteria 全部私有，公开结果只有脱敏聚合。

### 2.6 完整的离线测试与安全审计

- 本地复用固定 Fork、Policy、Tokenizer、Mock Student/Scripted User 的真实 Orchestrator 离线回归；覆盖 Token 边界、工具调用/返回、混合严格拒绝、独立数据库、官方 R0、故障 `null` 和完整 Episode/Trial 记账。
- 使用离线 Stub 测试 Transformers Client 生成 ID 处理、DeepSeek Adapter 格式/停止/超时/限流、安全日志；不加载任何 3B 模型权重，不产生 HTTP 付费调用。
- 测试 CLI `--help`、`--dry-run`；缺 Secret/缺权重/缺数据阻止真实运行、错误 Policy SHA 阻止启动、重复 ID 与 Test 门禁拒绝启动、部分结果不伪装成功、不能泄漏 Test 正文和 API Key。
- 既有 Stage 0–3_0 相关测试和最新自定义 Policy 61+164 范围内测试尽可能重跑；如果部分因 Test 数据隔离不得重跑，则明确 NOT_RUN 原因，不能通过改变冻结 Split 来“修复”。
- 对**即将由用户推送的 Git 文件**执行敏感信息审计，查看 `git status`、`git ls-files`、`git check-ignore`、`git diff`（输出脱敏）、潜在提交历史泄漏。不要依赖 `.gitignore` 阻止已经 tracked 的敏感文件；发现曾把 DeepSeek Key、PAT、SSH 私钥提交进历史的情况，报告 `BLOCKED_SECRET_HISTORY`，提示用户轮换密钥并修复历史再推送。不要自己读出、回显或复制真密钥。
- 在报告中列出**建议用户 Git 推送的准确文件清单/命令**和必须保留本地或通过私有同步的文件清单。**禁止 Codex 执行** `git add`、`git commit`、`git push`、`gh repo create`、`git remote set-url` 等 Git 发布操作。

**PHASE_LOCAL 最终交付并停下：** `STAGE3_1_LOCAL_PREP_REPORT.md`、`docs/stage3_1_remote_runbook.md`、必要的脚本/配置与测试、一个可核验的 Git 发布清单、Dev/Test 依赖清单及 SHA、尚未实测项。状态为 `LOCAL_PREP_PASS / BLOCKED_*`；用户本人接管 Git 操作与 SSH 配置。不得自行 SSH。

## 3. 用户手动 Git Push 与 SSH 准备（Codex 只给指引）

用户审查本地变更并执行 Git 发布。只有代码、文档、脚本、无密钥配置模板、版本化 Policy Bundle/Bootstrap 等必要文件可入 Git。**原始/处理后 SFT、RL 私有任务清单与隐藏评分、四份 DB 快照、私有审计/日志、DeepSeek Key、SSH Key、模型权重/Checkpoint** 均不入公开 Git；如果 GitHub 是私有仓库，也应优先最小化这些数据的上传。

需要区别三类实际物件：

1. `configs/policy/retail.sft_v1.md`、Policy Bootstrap 等**代码/公开配置**应随 Git 走；服务器 clone 固定 Fork 后通过 Bootstrap 补丁安装，最终 SHA 必须为 `efd7cc...`。
2. `configs/data/sft_main_view.json` 等**可公开的指针配置**可以随 Git 走；其引用的 `data/processed/stage2/policy_sft_v2/` **实际 Token 文件可能是 Git 忽略的私有数据**，clone 后不存在属于正常现象。E0 不使用 SFT Token 时不能把它误判为 E0 缺数据；Stage 4 再同步最新版 SFT 视图，并按 SHA 校验，严禁重新构造一个“差不多”的视图。
3. E0 需要的 **RL Dev/Test 冻结清单、真实任务载荷、DB 快照、评分所需数据** 通常也在 `.gitignore` 路径下。建议依 PHASE_LOCAL 生成的 allowlist，通过用户授权的 `scp`/`rsync` 从本地复制至服务器数据盘或私有目录，再由远程校验 SHA。不要把数据打包提交 Git、不要从 Dataset 重新划分替代冻结版本，也不要用 `git pull` 冒充数据同步。

用户可参考随 Skill 提供的 `references/SSH_SETUP_WINDOWS.md` 自己配置 SSH 公钥；通常在 AutoDL 控制台或第一次通过密码交互登录时安装**公钥**，私钥不出本机。在 Codex 能访问的执行环境下确认 `ssh policytrace-gpu` 可用，之后只提供 Host alias 给 Codex，并明确授权远程只读/最小部署。不在对话中发送 SSH 密码、私钥或 DeepSeek Key；首次确认 SSH 主机指纹由用户本人核对。

## 4. PHASE_REMOTE：用户确认后 SSH、clone、验证、停机

启动前要求用户消息明确包含“已完成本人 Git Push、SSH alias 可用、同意开始远程部署验收”，并确认目标 Git 仓库地址、分支、预期 Commit SHA、SSH Host alias 和是否允许依赖安装/私有数据同步；**绝不推测账号、IP、端口、仓库名或密码**。优先用只读诊断命令，不向报告回显密钥、完整 `env`、私有 Test Task。

1. **连接核验：** `ssh <alias>` 或经授权的非交互诊断命令；核对主机识别信息而不是关闭 HostKeyChecking。若尚须输入密码、首次信任主机指纹，由用户自己在终端操作。确认 OS/Linux、CPU/RAM、GPU/VRAM、`nvidia-smi` 驱动/CUDA 兼容性、Python、pip、PyTorch CUDA build、BF16、磁盘/数据盘、Git/网络、进程/权限、`tmux`。`nvcc` 缺失不单独视作不能运行 PyTorch。
2. **安全目录：** 不覆盖既有数据、权重或已有 Git 工作树；选择用户批准的新项目目录并从用户**已经推送**的仓库 `git clone`（私仓由用户配置只读授权）；`git rev-parse HEAD` 必须与指定 Commit 一致，若不一致停下，不偷偷拉最新版本继续执行。
3. **隔离安装：** 按锁定配置初始化单独 venv/conda（安装依赖/创建文件前先明确征得用户许可）；从固定 `e33e...` 的 Fork 取源码，执行当前仓库的 Policy Bootstrap，将被批准的 `retail/policy.md` 安装为 `areal-retail-sft-v1`，核对精确 SHA 和唯一合法 diff。不能把 Fork dirty 判为失败，也不能 `reset --hard` 使其误回原 Policy。
4. **资产核验：** 按 Phase Local 的私有最小依赖清单，只做存在性、大小、哈希、数量检查；不在终端输出冻结 Test 任务全文、隐藏用户场景或参考操作。未同步则报告 `BLOCKED_DATA`、给用户精确传输命令，**除非另获授权不要私自复制私有文件**。如果用户允许同步，使用 SSH 加密链路与校验、不会覆盖已有文件；与 Git 克隆操作独立。
5. **离线验收：** 执行无需 Qwen 权重、不调用 DeepSeek 的只读环境检测、离线 Parser/Context/Policy/Orchestrator/R0 必需测试；如果依赖数据不全，运行可行的代码预检并标记缺口，不能 Mock 冒充完整真实 E0 运行。不触发模型权重下载，不执行真实 Student、Simulator、Dev 或 Test。核实 `--help`、`--dry-run` 和正式 Test 门禁默认关闭。
6. **结项报告并停止：** `STAGE3_1_REMOTE_CHECK_REPORT.md` 显示 `READY_FOR_USER_MODEL_DOWNLOAD` 或 `BLOCKED_*`、实际远程硬件/依赖、项目与 Fork Commit、Policy SHA、最小数据完整情况、各项检测退出码、用户后续可复制的下载/verify/Dev Smoke/冻结/Test 命令、预算注意事项。必要数据没有到位就明确写“尚未就绪”，不能假报 `READY`。完成后**退出 SSH；不启动 tmux 里的评测、不调用下载脚本。**

## 5. 真实 E0 评测的共同实验约束（Codex 在脚本中保障，用户运行）

- **先 Dev Smoke 再 Test**：先用户自己下载 3B 模型并在 Dev 的 3–5 条任务实测真实 Token ID、Parser、用户模拟、工具执行、R0、上下文、API/GPU 费用；可在 Dev 修复脚本错误。Dev 通过后锁定不可变模型权重 SHA/revision、Tokenizer revision、Policy SHA、Fork Commit、Harness/Tool Schema、Model/Simulator Sampling、`identity-v0`、Prompt/MaxTurns/Budget、Evaluator/DB 配置与 Trial Plan。
- **Test 仅正式评估**：用户自己明确启动冻结 85 任务各 1 Trial 的 E0 测试并封存；E1～E4 后续使用同一自定义 Policy 与可比预算/采样条件。不能用 Test 上失败轨迹来调参数后复考。允许最终五组 Test-85 正式横向比较，禁止把自定义 Policy 的成绩冒称原版 τ² Policy 排行榜成绩。
- **日志隐私与完整性**：记录真实独立 Episode、Role、Tool/Observation、Prompt/Completion IDs 与 Mask、GPU 时间/显存、DeepSeek Token/API/费用（未知 null）、官方 R0 和异常。原始轨迹含私密业务场景/评估参考时必须保持 Git 忽略；报表公开部分只可脱敏。无显式人工批准不得将结果推到 GitHub。
- **分母与异常**：85 槽位未齐 → `incomplete`、最终 Pass^1 为 null；已开始但异常失败纳入正式分母，Reward 原始仍 null；不覆盖已存在 Episode、不挑选成功 Trial、不通过自动重试美化指标；Pass^4 尚未测。
- **费用安全**：AutoDL 只要保持开机通常仍会计费；真实 Test 之前用 Dev 实测 GPU/DeepSeek Token 与时间计算预算。用户可中止后保存结果，Codex 部署结束必须停下等待用户，不留后台收费作业。

## 6. 必须提供的交付物 / 验收状态

**PHASE_LOCAL：**

- 实际工程复用表；Script/Adapter/Config 的代码变更与测试。
- Student `download/verify/dry-run` 入口、真实 Qwen ModelClient、真实 DeepSeek UserSimulator、Dev Smoke / E0 Test-85 / Summarize CLI。
- 依赖清单 / 私有数据最小同步计划 / Frozen Test 哈希验证机制；Policy Bootstrap 和仓库安全审计。
- 用户 Git Push 明细说明与本地测试证据，`STAGE3_1_LOCAL_PREP_REPORT.md`、`docs/stage3_1_remote_runbook.md`。
- **明确停止，未提交/未推送 Git，未 SSH，未下载模型，未实际调用 DeepSeek / E0。**

**PHASE_REMOTE：**

- 已授权远程机器上的 `git clone` 和实际 Commit；当前 Fork + Policy 完整性检查；Linux/GPU/依赖/私有资产的真实状态；离线协议测试实际退出码。
- `STAGE3_1_REMOTE_CHECK_REPORT.md` 与给用户的明确手动运行命令。
- **明确停止，尚未下载权重、尚未运行真实 Dev 或 Test、尚未训练。**

**任何阶段遇到真实阻断**（密钥泄漏、缺少数据、SSH 未授权、远端 Git 未更新、磁盘不足、依赖无法安装、Policy SHA 不符），应准确标出阻断与用户所需操作，不跳过检查、不伪造已通过证据。

## 7. 直接执行方式

- 用户在本地对 Codex 说：`使用 policytrace-stage3-1 Skill。现在只执行 PHASE_LOCAL，把全部脚本和离线测试做好后停下；我会自己 Git Push。`
- 用户手动 Push，配置 SSH 公钥并确保 Codex 的终端 `ssh policytrace-gpu` 可用。
- 用户之后对 Codex 说：`继续 policytrace-stage3-1 的 PHASE_REMOTE。Git 已推送，预期 Commit 是 <SHA>，SSH Host alias 是 policytrace-gpu。只 clone 和验证服务器环境、Policy、数据/离线测试，完成后停止。我会自行下载模型与运行评测。`
