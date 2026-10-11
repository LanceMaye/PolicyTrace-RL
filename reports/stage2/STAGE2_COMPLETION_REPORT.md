# Stage 2 结项补充：policy 不变与 SFT Target 隔离

状态：**COMPLETE_WITH_DOCUMENTED_RISKS**。用户已明确批准“policy 不变，同时隔离多工具与文本/工具混合 Target”的处理决策，本次实际实现并验证通过。Stage 2 到此完成，未进入 Stage 3。

本文件补充历史 [STAGE2_REPORT.md](STAGE2_REPORT.md) 及 [多工具专项报告](MULTI_TOOL_COMPATIBILITY_REPORT.md)，记录当前有效的数据选择与结项状态。两份历史报告保留原文及原 SHA；其 PENDING/未过滤状态是各自执行时的状态。固定 Fork 原生支持多工具的勘误依据继续保留，不将政策限制误写为运行时不支持。

## 已执行的选择

保持 Retail policy、工具 Schema、官方 Evaluator、R0 及数据库原件不变。对既有 SFT Train/Val 的当前 Assistant Target，执行以下规则：

1. 同一 Target 的工具调用数量大于 1，标注 `multiple_tool_calls`。
2. 有工具调用且普通文本非空，标注 `text_and_tool_calls`。
3. 任一标注成立即进入对应 split 的 quarantine；其余进入 main。重复理由不重复计数。

| 冻结来源 | 原条数 | 多工具 | 混合文本 | 两项重叠 | 隔离并集 | 当前 main |
|---|---:|---:|---:|---:|---:|---:|
| Train | 10,148 | 1,329 | 441 | 274 | **1,496** | **8,652** |
| Val | 1,139 | 143 | 59 | 30 | **172** | **967** |
| 合计 | 11,287 | 1,472 | 500 | 304 | **1,668** | **9,619** |

Train 隔离占约 14.74%；Val 隔离占约 15.10%。此前专项的 309 条混合文本仅是原始多工具 Target 的子集，本次规则还包含单工具与文本混合：Train 167、Val 29。既有 source-quality 隔离的 108 条仍独立保留，未重新加入训练或验证。

所有 main/quarantine 都留在原有 split 中，未改冻结划分、未把样本从 Train 移到 Val、未拆分专家动作、未删除原始数据。main 覆盖原有全部质量合格来源对话：Train 889 个、Val 103 个，来源对话不跨 Train/Val。quarantine 是样本子视图，可能与 main 共享同一来源对话，这不是 Train/Val 泄漏。

RL Train/Dev/Test、成本过滤视图、内部 Test 和 Pass^4 子集全部保持不变。原有跨源 confirmed=0、probable 候选及来源证据缺口继续沿用原报告；本次没有用弱相似关系新增 RL 去重或删除 SFT 来制造训练效果。

## Token 处理与验证

**无需重新编码，直接复用现有 token。** 政策和序列化模板都没有更改，仅选择了哪些完整样本进入主视图。规范化样本与 token 的 provenance（sample_id、source_dialog_id、原始行号、源行 SHA、turn_index）逐条一致后，原行原样复制到对应视图。

新 gzip 归档并非原文件的字节切片，压缩 SHA 会变化；但每条解压后的记录与原记录逐字节一致。input_ids、attention_mask、labels、目标 span、EOS 和 max_length=16K 均保留。没有截断或拼接新的专家动作。

| 当前主视图 | 输入 tokens | 受监督 tokens（含 EOS） | 文本 Target | 单工具 Target |
|---|---:|---:|---:|---:|
| Train main | 60,531,425 | 1,083,109 | 5,565 | 3,087 |
| Val main | 6,705,654 | 121,597 | 612 | 355 |
| 合计 | 67,237,079 | 1,204,706 | 6,177 | 3,442 |

实际校验覆盖全部 **11,287** 个既有 token 记录的 Loss Mask；主视图与隔离视图逐行 SHA 都与输入行对应，完整覆盖、无重复、无遗漏。历史、System、User、Tool 和其他 Assistant Token 的 -100 保持原样。

## 当前使用入口与隔离证据

默认 SFT 数据配置：[configs/data/sft_main_view.json](D:/Codes/policytrace/configs/data/sft_main_view.json)。后续训练必须读取该配置所指 main 文件；旧完整文件仍保留作专家资产，不应直接作为本次批准的主训练入口。

- 主训练：`data/processed/stage2/policy_main_v1/sft_train_main.tokenized.jsonl.gz`。
- 主验证：`data/processed/stage2/policy_main_v1/sft_val_main.tokenized.jsonl.gz`。
- 完整规范化及隔离样本、相应 token 和 `manifest.json` 均在同目录。
- 来源 split、样本 ID、SHA 和隔离理由统计：`data/splits/stage2/policy_main_v1/sft_train.json`、`sft_val.json`。
- 全量逐样本原因、历史风险、原始行指纹：`data/private/stage2/policy_main_v1/decisions.jsonl`。
- 输入不变性依据：同私有目录的 `immutable_inputs.json`。
- 可读使用说明及恢复方式：[sft_policy_main_view.md](../../docs/sft_policy_main_view.md)。

本次新增 [sft_policy_view.py](D:/Codes/policytrace/src/policytrace/data/sft_policy_view.py)，只做数据视图，不开发正式 Agent Harness。

## 实际运行与不变性

```powershell
.venv\Scripts\python.exe -X utf8 scripts/stage2_policy_view.py
.venv\Scripts\python.exe -X utf8 scripts/stage2_policy_verify.py
```

| 实际入口 | exit | 耗时 | 实际结果 |
|---|---:|---:|---|
| stage2_policy_view.py | 0 | 25.184 秒 | 冻结源校验、全量视图生成、11,287 个 mask 校验通过 |
| stage2_policy_verify.py → pytest tests/stage2 | 0 | 35.031 秒 | **57 passed，0 failed/errors/skipped**；原 44 项 Stage 2 回归与 13 项新增测试 |

新增测试覆盖目标分类及两原因重叠、历史保留、provenance 错配、损坏 mask、缺 token、重复 ID、真实集合完整性、来源分组隔离、全部输出原行指纹和默认路径。原 Stage 2 的任务池/评测衔接测试也在此次 57 项中执行；本次未重复运行整套 Stage 0/1 的 83 项历史回归。

对照冻结 Stage 2 manifest 及执行前记录核验 **82 个既有输入文件，变化 0**；对照 Stage 0 manifest 校验 raw 文件通过。Fork commit 保持 `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`，工作区 clean。固定 Retail policy SHA256 保持 `4313d3fef8acf919f555fa17fbce929cc3ed1cef2dd8f0d35ff5c8c3364de176`，历史 API 账本和原报告不变。

证据：[policy_view_results.json](policy_view_results.json)、[policy_view_check_results.json](policy_view_check_results.json)、[policy_view_pytest.xml](policy_view_pytest.xml)。全部操作在 Windows CPU 上完成；API 调用、租 GPU、权重下载、模型训练和新正式评测 Episode 均为 0。

## 仍然存在的风险

- 隔离针对当前受监督 Target，并不删除真实历史。main 中 Train **5,570** 条、Val **593** 条的历史含多工具或混合文本动作，已标注且对应历史仍为 -100。历史可以影响模型上下文，因此“当前 Target 符合两条规则”不等于“整段对话完全合规”。
- 没有修改源 SFT system policy 文本，源确认措辞等与固定 Fork 的差异仍在。认证、写入确认和其他业务条件未因这次过滤被宣布全部通过。
- 分布有变化，尤其批量订单查询 Target：Train main 中 get_order_details 调用 92，隔离视图中 2,426；get_product_details 为 93 / 659。完整工具分布公开在 policy_view_results.json。不能只凭保留 85% 左右的 Target 宣称训练能力不受影响；后续需在 Dev 观察单工具查询和多步行为。
- SFT 缺完整可绑定的原始数据库及私有源 Task，因此没有完整源 Episode 重放结论。外部评测仍是来源独立性未证实的候选集，不能混入内部正式指标。
- 正式 Harness 尚未完成；后续必须在输出侧遵守现有 policy 并独立记录政策违规，不能把本次过滤当作 Student 已学会遵守规则。官方 R0 保持原语义。

**用户批准的 Stage 2 修改已全部落地。Stage 2 结项，保留上述风险，不自动进入下一阶段。**
