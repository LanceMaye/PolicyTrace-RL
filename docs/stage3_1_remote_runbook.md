# Stage 3_1：用户手动操作 Runbook

当前只完成 PHASE_LOCAL。本文件中的发布、SSH、安装、下载和真实评测命令均留给用户后续操作；本轮没有执行。最新 Policy 为 `areal-retail-sft-v1`；纯多工具允许，文本与工具混合仍拒绝。Test 成绩只代表自定义 Policy，不对应原官方 Policy 的排行榜。

## 1. 本机审查与 Git 发布

项目根目录目前没有 `.git`。固定 Fork 自己的 `.git` 不等于项目已有 Git。发布前审查 `reports/stage3_1/git_safety_audit.json` 的 `candidate_files`，这是逐文件允许清单；不要使用 `git add .`，不要强制加入忽略文件。

下列 PowerShell **只供你本人执行**，地址/分支由你填写；Codex 没有执行初始化、暂存、提交、推送或 remote 修改。

```powershell
# 先初始化，再重新运行只读审计；仅在报告没有 BLOCKED/敏感发现后继续。
git init
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_git_audit.py
$publication = Get-Content -LiteralPath 'data/private/stage3_1/publication_allowlist.json' -Encoding UTF8 | ConvertFrom-Json
foreach ($file in $publication.files) { git add -- $file }
git diff --cached --stat
git diff --cached --name-only
# 人工检查：不得出现 .env、data 下私有数据、external、模型、日志或密钥。
git commit -m 'Prepare Stage 3_1 offline adapters and user-run E0 protocol'
# 在 GitHub 建立你的仓库后，用你自己的实际地址设置 origin。
git remote add origin <YOUR_REPOSITORY_URL>
git push -u origin <YOUR_BRANCH>
git rev-parse HEAD
```

`git_safety_audit.json` 在无根 Git 时只能给出拟发布文件审计；历史状态 `NOT_AVAILABLE_NO_ROOT_GIT`。初始化后需再审计。若发现历史私有数据或密钥，先修复历史及轮换相关凭据，不要推送。

## 2. 私有数据单独迁移

最小 E0 包 **10 个文件、46,809,598 字节（44.64 MiB）**。逐文件路径、大小和 SHA 位于：

- 运行校验锁：`configs/harness/stage3_1_assets.lock.json`，不含 Task 正文或 ID。
- 本地私有完整清单：`data/private/stage3_1/sync_allowlist.json`。
- Stage 4 可选清单：`data/private/stage3_1/optional_stage4_inventory.json`。它不是 E0 运行条件。

E0 需要冻结 Dev/Test manifest、原始 RL 任务载荷、四份数据库快照和三份 Tokenizer 文件。只传 manifest 不够。Fork 内原生代码、用户指南和原生基础数据来自固定 Commit checkout；自定义 Policy 源文件由项目 Git 发布，安装到 Fork 后校验。

原始 SFT、Token 化 SFT、训练视图和历史私有日志不必为了 E0 全部上传。当前 Stage 4 默认指针仍是 `configs/data/sft_main_view.json` → `policy_sft_v2`（9707 Train / 1080 Val），将来按冻结 SHA 单独迁移，不重新生成划分或重做 Token。

你可以在 Windows 手动创建一个只包含允许文件的私有压缩包：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_data_inventory.py
.venv/Scripts/python.exe -X utf8 scripts/stage3_1_data_inventory.py --pack data/private/stage3_1/e0-assets.zip
# SSH alias 与目标项目目录由你配置，先自己核对服务器主机指纹。
scp data/private/stage3_1/e0-assets.zip <YOUR_SSH_ALIAS>:<YOUR_PRIVATE_UPLOAD_DIRECTORY>/
```

在服务器项目根目录，用项目环境解包并校验：

```bash
python scripts/stage3_1_data_inventory.py --unpack <YOUR_PRIVATE_UPLOAD_DIRECTORY>/e0-assets.zip
python scripts/stage3_1_data_inventory.py
```

只接受锁中的完整 10 文件集合；拒绝路径穿越、额外文件、重复条目、软链接和哈希不符。已有相同哈希文件跳过；不同哈希文件拒绝覆盖。不要提交压缩包，不要把 `.env` 或 SSH 私钥加入迁移包。路径按项目根目录恢复；本阶段尚未实现任意外部数据根目录映射。

## 3. 后续 PHASE_REMOTE 的启动信息

你完成 Git 推送和 SSH 公钥配置后，再提供：仓库地址、分支、预期 Commit SHA、可用 SSH Host alias、新项目目录，以及是否授权安装依赖和私有数据同步。不要发送密码、私钥或 API Key。

Codex 下一轮只核验和部署离线环境，不替你运行模型下载、Dev Smoke 或 Test。以下安装说明是候选方案；本轮没有安装，也没有验证云端依赖解析。

建议独立 Python 3.11 环境，NVIDIA CUDA，BF16；候选为 PyTorch 2.8.0、Transformers 4.57.1、Accelerate 1.10.1、Tokenizers 0.22.2、HF Hub 0.36.0。Windows CPU 锁中的 HF Hub 1.33.0 / Tokenizers 0.23.2 与该 Transformers 版本要求不同，不能原样当成 GPU 锁。`requirements-stage3_1-candidate.txt` 保留其余旧版本，但它是待 Linux 解析验证的候选清单。

在授权的新目录恢复固定 Fork；切勿 reset/clean 现有 Fork：

```bash
git clone --no-checkout https://github.com/dhh1995/tau2-bench.git external/tau2-bench
git -C external/tau2-bench checkout --detach e33e9511e4f51e5cfa16e12b02d0e4ab327b5887
# 创建独立环境后，先按实际驱动选官方 CUDA wheel；cu128 只是驱动允许时的示例。
python -m venv <YOUR_NEW_GPU_VENV>
source <YOUR_NEW_GPU_VENV>/bin/activate
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements-stage3_1-candidate.txt
python -m pip check
python scripts/stage3_1_bootstrap_policy.py --apply
python scripts/stage3_1_data_inventory.py
python -m pytest tests/stage3_1 -q
```

该离线测试集仅依赖最小 E0 包和固定 Fork，不依赖旧 Stage 3_0 私有审计或完整 SFT。本机已运行的 61+164 历史回归需要更多历史私有资产，最小云端包不承诺能运行全部历史测试。不要在 GPU 环境最后执行 Stage 0 的 `uv pip sync`，它会恢复 CPU 依赖集合并可能移除新增包。

安装/解析后，在私有目录保存 `pip freeze`、Python/PyTorch/CUDA/驱动及硬件信息；先完成离线测试，发现依赖差异时只在 Dev 前修复。云端是否满足 CUDA/BF16/显存、0.22.2 Tokenizer 是否重现协议，均须真实验证。

PyTorch wheel 选择参考[官方历史版本](https://pytorch.org/get-started/previous-versions/)；Qwen 的 SDPA 与 `logits_to_keep` 接口参考[Transformers Qwen2 文档](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/qwen2)。

## 4. 你手动下载 Student

从实际数据盘选目录，不假定服务器一定有某个 AutoDL 路径。只用 `Qwen/Qwen2.5-3B-Instruct`，不下载 Teacher。先由你查明并填写权重的不可变 40 位 Commit revision；不能直接使用 `main`，也不能假定它自动等于 Stage 2 Tokenizer revision。

```bash
# 这条仅查询权重仓库元数据，供你选择并记录 immutable revision。
python -c 'from huggingface_hub import HfApi; print(HfApi().model_info("Qwen/Qwen2.5-3B-Instruct").sha)'
python scripts/stage3_1_download_student.py --local-dir <YOUR_MODEL_DATA_DIR> --revision <WEIGHT_COMMIT_40HEX> --dry-run
python scripts/stage3_1_download_student.py --local-dir <YOUR_MODEL_DATA_DIR> --revision <WEIGHT_COMMIT_40HEX>
python scripts/stage3_1_download_student.py --local-dir <YOUR_MODEL_DATA_DIR> --revision <WEIGHT_COMMIT_40HEX> --verify-only
```

要求下载前至少 10 GB 空闲空间。仅接受 safetensors；核验 shard/index/header/shape/offset/payload、大小和 SHA，架构与 EOS、Tokenizer 文件及 Chat Template 必须匹配 Stage 2。输出权重 receipt；验证不加载权重。若下载中断且没有 receipt，保留目录并选择新目录，本版不自动恢复下载。若 Tokenizer 与冻结版本不匹配则停止，不能替换 Tokenizer。

## 5. 你手动配置、Dev Smoke 与协议冻结

复制模板至忽略的私有目录，修改模型绝对路径、权重 revision、你核实的当前 API 输入/输出保守单价及核实日期、GPU 时租价格。示例预算上限为 5 CNY；金额不足时停止并保存部分结果，不自动加预算。旧 Stage 0 的日期/单价不能当作当前报价。[DeepSeek 官方 API 文档](https://api-docs.deepseek.com/api/create-chat-completion/)说明请求/usage/stop 格式；当前价格由你在运行前确认。

```bash
mkdir -p data/private/stage3_1
cp configs/harness/stage3_1.example.json data/private/stage3_1/run.json
# 用编辑器修改 run.json；密钥只通过运行进程环境传入，不写进 JSON。
read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY
export DEEPSEEK_API_KEY
printf '\n'
python scripts/stage3_1_run.py env-check --config data/private/stage3_1/run.json --check-gpu
python scripts/stage3_1_run.py dev-smoke --split dev --config data/private/stage3_1/run.json --dry-run
python scripts/stage3_1_run.py dev-smoke --split dev --config data/private/stage3_1/run.json --execute --confirm-paid-api --run-id E0-dev-smoke-01 --output data/private/stage3_1/E0-dev-smoke-01
python scripts/stage3_1_summarize.py --run-dir data/private/stage3_1/E0-dev-smoke-01
```

Dev Smoke 的 3 个 ID 事先固定在代码中，不按结果挑选。它检查工程运行是否正常，不要求三个任务 R0 全为 1，也不作为正式 Test 分数。实际 prompt/generation IDs、当前动作 Mask、工具及 Observation、原生 SimulationRun、官方 RewardInfo 和完整日志全保留在私有目录。

检查真实运行来源、官方评分可用、没有 context/transport/parser 故障，查看延迟、上下文 max/p50/p95、API 用量及 GPU 显存。Token reserve 512、总 Context 16384 都是待 Dev 验证的配置；发生溢出时保存原始失败，不摘要/截断后假装通过。正式 Test 前可以根据 Dev 调整并重新运行新命名的 Smoke；一旦冻结 Test 开始，不用 Test bad case 调这些配置。

确认实测预算后，用户手动冻结：

```bash
python scripts/stage3_1_run.py freeze-protocol --config data/private/stage3_1/run.json --smoke-dir data/private/stage3_1/E0-dev-smoke-01 --output data/private/stage3_1/common_protocol.json --confirm-cost
```

冻结包括权重 receipt、Tokenizer、Policy、Fork、数据锁、代码、库版本、采样/seed/停止符、预算和 strict communication。冻结检查真实 Student IDs、真实 User 记录、三条已评分 Dev、原生序列化与原始 DB 未变；Mock 不可用于冻结。API 测算超过当前上限则阻断；GPU 时租未知时仍为 null，`--confirm-cost` 表示你已接受未知部分，必须仔细阅读测算。线性外推不包含安装/下载/空闲计费和任务长尾，不保证完成时间或精确账单。

## 6. 你手动启动 E0 Test-85

```bash
python scripts/stage3_1_run.py e0-test --split test --confirm-frozen-test --config data/private/stage3_1/run.json --protocol data/private/stage3_1/common_protocol.json --dry-run
python scripts/stage3_1_run.py e0-test --split test --confirm-frozen-test --config data/private/stage3_1/run.json --protocol data/private/stage3_1/common_protocol.json --execute --confirm-paid-api --run-id E0-test-01 --output data/private/stage3_1/E0-test-01
python scripts/stage3_1_summarize.py --run-dir data/private/stage3_1/E0-test-01
```

Test-85 每任务一次独立 Trial；没有 Pass⁴。用户必须同时明确 Test split、冻结 Test 确认、执行和付费确认；启动前再次核验冻结 Dev 的文件哈希和协议。修改代码、Policy、数据库、Tokenizer、依赖或采样后不能沿用旧冻结文件。

**本版不支持断点续跑。** 已存在运行目录拒绝启动；每个 episode 先创建独占 started 标记。API 错误、框架错误或评分错误会保存失败并停止后续任务；不会重试。Ctrl+C 尽量封存轨迹；断电/SIGKILL 后由汇总器将已有 started 标记计入已开始失败，R0=null。未开始任务保留缺失槽位，未齐 85 时正式 Pass¹=null，不能把已完成子集冒充 Test-85。

Model/User 调用数、Episode 数、API 账本与墙钟上限会在下一次操作前阻断。HTTP 调用有 timeout；单次 GPU forward 不能被此同步驱动硬中断，预算时间可能超过一个当前调用的时长。不会把 GPU 空闲费用计成 0。实例开机通常仍在计费；运行结束由你保存产物并按平台规则停机。

## 7. E1～E4 接口交接

后续继续复用本版 ModelClient、StudentAgentAdapter、原生 Orchestrator、EpisodeRecord 和官方 R0。正式 Test 共用 Task-85、User 配置、Policy、Tools、采样与预算；只替换 Student checkpoint。

当前 receipt/downloader 与 `e0-test` 门禁严格锁定原始 Qwen 权重。训练 checkpoint 的 receipt、E1～E4 标签及仅允许 checkpoint 差异的比较门禁留给后续阶段；不要伪造 HF revision、手改旧 E0 冻结文件，或重写 Agent Loop。没有真实云端 Smoke 前，不能宣称 Base Baseline 或 E0 PASS。
