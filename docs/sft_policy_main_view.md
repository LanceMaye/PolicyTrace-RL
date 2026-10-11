# Stage 2 当前 SFT 主视图

2026-10-11 用户批准完整采用冻结 AReaL SFT 的业务 Policy，版本为 `areal-retail-sft-v1`。允许纯多工具回合，仍隔离普通文本与工具调用混合的当前 Assistant Target。当前入口为 [sft_main_view.json](../configs/data/sft_main_view.json)，稳定版本配置为 [sft_mixed_only_v2.json](../configs/data/sft_mixed_only_v2.json)。这是一份可逆选择视图，冻结 Train/Val 划分未变。

| 文件（位于 data/processed/stage2/policy_sft_v2/） | 用途 |
|---|---|
| sft_train_main.jsonl / sft_train_main.tokenized.jsonl.gz | 当前主训练数据，9,707 条 |
| sft_val_main.jsonl / sft_val_main.tokenized.jsonl.gz | 当前主验证数据，1,080 条 |
| sft_train_quarantine.jsonl / 对应 tokenized 文件 | Train 混合 Target，441 条 |
| sft_val_quarantine.jsonl / 对应 tokenized 文件 | Val 混合 Target，59 条 |
| manifest.json | 原始 split、样本 ID、规则版本、文件 SHA、token 数量与来源对话 |

后续训练入口应读取 `configs/data/sft_main_view.json` 指向的 main token 文件。直接读取上一级原始 `sft_train.tokenized.jsonl.gz` 会绕过这次隔离；原文件仍保留作完整专家池和恢复依据。暂无训练器，因此本轮只设置明确的数据入口，没有启动训练。

规则只作用于当前 `answer`：存在工具调用且 content.strip() 非空，即隔离。恢复纯多工具 Target 共 1,168 条（Train 1,055 / Val 113）。历史 Assistant、User、Tool 和 System 原样保留，混合历史另行标注，历史对应 labels 仍为 -100；这不代表历史不影响模型，也不等于整段对话已通过业务政策审核。

无须重新 tokenize：原 SFT 已包含本次采用的精确业务 Policy，Qwen 模板与 Tokenizer 未变。规范化行与 token 行按完整 provenance 配对，原样写入新视图。解压后的逐样本 token 记录、input_ids、attention_mask、labels、EOS 均不变。全量 11,287 条重验 Loss Mask，新 Main 的 10,787 条解码后通过严格 Parser；代表性的文本、单工具、多只读、多写入样本重新编码并对比 Runtime Prompt IDs。

Fork 的 Retail policy.md 已替换为 SFT 业务文本，唯一获准的 Fork 改动是该文件。通用确认措辞完整采用 SFT 的 you'd better、不指定字面 yes，具体操作确认要求仍保留。认证、确认、用户私有约束和源数据库完整重放未被宣称全部通过。纯多写入交给原生顺序执行，无自动回滚。

复现命令，在仓库根目录使用现有 CPU 环境：

```powershell
.venv\Scripts\python.exe -X utf8 scripts/custom_policy_check.py
```

当前检查入口复验数据、Harness 和限定已暴露 Dev 的历史回归，证据另存 reports/policy_transition_v2。构建入口为 scripts/custom_policy_prepare.py，拒绝覆盖已存在的版本目录；重新构建应在干净副本中使用固定输入。旧检查脚本属于历史原版设置，不应在当前设置下重跑并覆盖旧报告。

原 policy_main_v1、完整专家池、冻结划分、历史报告保留。原 Policy 的字节备份位于 configs/policy/backups/retail.e33e9511.original.md，旧入口配置备份在 configs/data/backups/sft_main_view.policy_main_v1.json。原有 source-quality 隔离的 108 条保持原样。所有未来 Base/SFT/RL 与评测使用同一自定义 Policy，并记录版本/SHA。

当前变更与验收见 [POLICY_TRANSITION_REPORT.md](../reports/policy_transition_v2/POLICY_TRANSITION_REPORT.md)；[STAGE2_COMPLETION_REPORT.md](../reports/stage2/STAGE2_COMPLETION_REPORT.md) 保留历史原版设置的证据。
