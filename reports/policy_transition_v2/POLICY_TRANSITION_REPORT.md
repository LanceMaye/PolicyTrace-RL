# 自定义 Retail Policy 迁移与离线复验

执行日期：2026-10-11。状态：**PASS_OFFLINE：迁移完成，225 项测试通过，等待用户审查**。本次是用户明确批准的 Stage 2 / Stage 3_0 设置变更，不进入 Stage 3_1 或训练。

## 1. 当前决定与准确差异

采用 **areal-retail-sft-v1**：从冻结 AReaL Retail SFT System 的 `<policy>` 中逐字提取业务文本，保留首尾换行，替换固定 Fork 的 Retail policy.md。原业务文本、旧配置与旧实现均备份；历史 Stage 0–3_0 报告不覆盖。

- 基础 Fork：`e33e9511e4f51e5cfa16e12b02d0e4ab327b5887`，仅 policy.md 存在已批准改动，**工作区不再是 clean**。
- 当前 Policy SHA256：`efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936`。
- 原 Policy 字节 SHA256：`4313d3fef8acf919f555fa17fbce929cc3ed1cef2dd8f0d35ff5c8c3364de176`。
- 业务差异：移除单回合最多一个工具调用限制；通用写操作确认措辞从 must / explicit confirmation (yes) 改为 SFT 的 you'd better / explicit confirmation。各操作章节原有的确认、订单状态与单订单修改次数限制保留。
- 文本与工具调用混合仍禁止；主运行配置保持 `validate_communication=True`。False 分支只用于原生路由边界诊断。

版本与完整文本：[custom_retail_v1.json](../../configs/policy/custom_retail_v1.json)、[retail.sft_v1.md](../../configs/policy/retail.sft_v1.md)。原件：[retail.e33e9511.original.md](../../configs/policy/backups/retail.e33e9511.original.md)。逐行差异：[retail_policy.diff](retail_policy.diff)。

## 2. 数据视图与恢复数量

当前入口：[sft_main_view.json](../../configs/data/sft_main_view.json)；稳定版本配置：[sft_mixed_only_v2.json](../../configs/data/sft_mixed_only_v2.json)。新数据目录：`data/processed/stage2/policy_sft_v2/`。

| Split | 原质量合格池 | 旧 Main | 恢复纯多工具 Target | 新 Main | 混合隔离 |
|---|---:|---:|---:|---:|---:|
| Train | 10148 | 8652 | 1055 | **9707** | **441** |
| Val | 1139 | 967 | 113 | **1080** | **59** |
| 合计 | 11287 | 9619 | **1168** | **10787** | **500** |

恢复的 Target 中，914 条不修改数据库，254 条包含写入。没有拆分专家动作、删除混合正文、重写原始样本或移动 split。原质量隔离 108 条不恢复。保留全部质量合格来源对话：Train 889 / Val 103；来源对话不跨 split。

| Train 工具调用数（当前 Target） | 旧 Main | 新 Main | 当前混合隔离 |
|---|---:|---:|---:|
| get_order_details | 92 | **2294** | 224 |
| get_product_details | 93 | **229** | 523 |

完整工具分布、样本数与审计见 [data_results.json](data_results.json)。统计字段 multi_targets / both_reasons 描述源 Target 的输出形态及交集；v2 的实际隔离原因只有 `text_and_tool_calls`，不把纯多工具视为违规。

## 3. Token、Policy 与 Context 对齐

**不需要重新 tokenize。** 原 SFT 已使用本次采用的业务 Policy；Qwen Tokenizer、Chat Template、格式转换、专家 Target 与历史均未改变。新 gzip 是新视图，解压后的每个原始 token 行逐字节复用。

- 全量 11287 条 Loss Mask 检查通过；System/User/Tool/历史 Assistant 为 -100，当前 Target 含 EOS 受监督。
- 全量 11287 个 SFT System 的业务文本与当前 Runtime Policy 完全一致；共享 Qwen 包装完全一致。
- 新 Main 10787 条 Target 均通过真实 Tokenizer 解码和严格 Parser，校验全部 **6551 次**工具调用的名称、参数、顺序与数量，Schema 未放宽。
- 两个 split 各抽文本、单工具、多只读、多写入四类，共 8 条重新编码，结果与原记录一致。再通过实际 ContextBuilder 对比 Runtime Prompt IDs，与 SFT Prompt IDs 相等。
- 最大完整样本长度：Train 14332 / Val 13838，小于 16384；未截断。
- 主视图输入 Token 合计 74249779，受监督 Token 合计 1312257。

必要的 Harness 调整：`student_system` 精确保留业务 Policy 的首尾换行，再调用既有 qwen_messages；避免 Fork SYSTEM_PROMPT 在标签内添加额外换行。ModelClient、Parser、Orchestrator 和 Tool Schema 继续复用。

## 4. 版本检查、轨迹与官方评分

[policy.py](../../src/policytrace/policy.py) 校验基础 commit、备份、当前 Policy 精确 SHA、已修改路径、未跟踪文件和暂存改动。只接受当前批准的 policy.md；工具/Evaluator 改动、额外文件、错版本或 Policy 漂移会拒绝。

Harness 版本为 `policytrace-harness-offline-v2-sft-policy`。Policy 版本/SHA 进入配置 hash、Episode ID、RunContext 的 harness_version、Decision 与 Context 元数据。`protocol_features.multiple_tool_calls` 记录形态，对应 Policy 违规标记为 false；混合仍标为违规。认证和确认语义保持 `not_evaluated`。

实际使用原生 Orchestrator、独立 DB 副本、原生 ToolCall/ToolMessage/MultiToolMessage 与唯一官方 R0 适配器。工具批次顺序执行、错误后继续/错误预算、无自动回滚、结果关联、下一轮完整 Context、原生序列化与 DB 重放均由 Harness 测试覆盖。官方 Evaluator、参考 actions、R0 代码和数据库原件不改。

bootstrap 已接入保留的 Policy bundle，后续新机器在固定 checkout 上安装自定义 Policy。已验证该模块仅依赖标准库，以及当前已安装补丁的幂等校验；本轮未重建 Linux/AutoDL 环境或真实验证全新 checkout 的 bootstrap 安装过程。

## 5. 实际执行与复现

```powershell
.venv\Scripts\python.exe -X utf8 scripts/custom_policy_prepare.py
.venv\Scripts\python.exe -X utf8 scripts/custom_policy_check.py
```

prepare 已执行，耗时 **113.491 秒**。该入口拒绝覆盖已存在的新版本目录；日常复验运行 check，重新构建应使用干净副本。

| 验证 | 实际结果 |
|---|---|
| 数据处理、全量 Mask、严格 Parser、8 条代表样本编码与 Prompt IDs | PASS；113.491 秒 |
| Harness 与自定义 Policy 测试 | **61 passed，0 failed/errors/skipped**；135.524 秒 |
| Stage 0/1/2/多工具兼容性范围内回归 | **164 passed，10 deselected，0 failed/errors/skipped**；221.308 秒 |
| 历史报告、原始数据、旧 token 与冻结 split 完整性 | PASS；69 份历史报告均未修改 |

验收证据：[check_results.json](check_results.json)、[Harness XML](harness.xml)、[回归 XML](regression.xml)、[回归范围](regression_scope.json)。执行前记录 1680 个既有文件，除 15 个有原件备份的获准实现/文档/配置/Policy 改动外，1665 个原文件不变；测试期间代码与配置指纹不变。冻结 RL/SFT 划分、原始数据库、Tokenizer、旧数据视图和 API 账本保持原指纹。

回归仍使用已暴露 Dev 边界，不用冻结 Test 调试；范围外项目明确列在 regression_scope.json，不能计为通过。公开 XML 仅保留名称/状态/耗时，完整日志与 traceback 存私有目录。

首次 Harness 检查为 44 passed / 17 setup errors：新增测试与旧测试的模块级 episodes 夹具共享轨迹目录，触发不覆盖保护。修正新增测试，使 Context 比较直接构造适配器，不重复创建同名 Episode；保留首次日志与结果于 `data/private/policy_transition_v2/development/first_harness_run/`。未修改业务工具或评分来获得通过。

首次历史回归为 163 passed / 1 failed：当前 README 已更新到新入口，旧指纹测试仍指向当前 README。将原文逐字节保留在 `docs/history/README.stage2_original.md`，仅对这项获准文档变更及已备份 Policy 使用历史原件校验，其他冻结输入仍校验原路径。失败日志与 XML 保留于 `data/private/policy_transition_v2/development/first_regression_run/`。最终完整复验如上，存在一个原 Fork Pydantic 弃用警告。

## 6. 历史证据、风险和后续边界

旧 policy_main_v1 数据与全部 Stage 0–3_0 报告保持原版本。旧入口配置字节备份：[sft_main_view.policy_main_v1.json](../../configs/data/backups/sft_main_view.policy_main_v1.json)。此次变更与旧报告中的原版 Policy 结论并列保留；旧 check 的 clean Fork / 原始冻结检查属于旧设置，不应用来重写当前验收。

仍存在的限制：

1. Main 中 Train 1979 / Val 248 条包含历史混合消息，历史保持 -100，但仍可能影响模型。隔离针对当前受监督 Target，不声称整个对话已清除混合内容。
2. 商品查询监督仍偏少，Train 混合隔离保留 523 次商品查询；后续 Dev 应检查这类能力，不能推断模型效果不受影响。
3. 原 SFT 数据库初态与私有源 Task 无法完整重建，未声称真实专家 Episode 全部可重放；没有伪造 Observation。
4. 完整采用 SFT 的较弱通用确认措辞；官方 R0 不全面检测 Policy 合规。纯多工具允许不等于所有写入业务合法。
5. 所有未来 Base/SFT/RL 和评测使用同一自定义 Policy 与预算，明确记录设置；不能将结果混报为原版 Policy 条件下的 Benchmark。

本轮模型 API 调用 0、GPU 租用 0、模型权重下载 0；没有真实 Student forward、Base Baseline、SFT/OPD/GRPO 或 Stage 3_1。真实服务质量、GPU/Linux 新设置、模型输出边界及训练效果仍待后续阶段验证。下一阶段使用更新后的 [stage3_1_handoff.md](../../docs/stage3_1_handoff.md)。
