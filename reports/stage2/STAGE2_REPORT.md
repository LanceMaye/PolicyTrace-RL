# Stage 2 验收报告

执行日期：2026-10-10。状态：**PASS_WITH_RISKS（数据工程与测试完成；人工验收 PENDING）**。

按 `policytrace-stage2` Skill 完成真实全量审计、跨源关系分析、全局分组与边际分层、SFT 标准化和实际 Qwen token/labels、成本视图、Stage 1 计划接口及外部 Test 候选审计。本轮实际执行 44 项 Stage 2 测试、83 项 Stage 0/1 回归，共 **127 项通过，无失败、错误或跳过**。所有正式模型效果、训练与四次重复评测均未执行。

原始数据和完整训练池保留。跨源没有经证据确认的同实例重复，成本视图没有删除任何 Task。默认 16K SFT 数据保留所有合法专家回合，没有为凸显 RL 效果减少专家数据。

## 1. 固定来源与实际审计

开始前已阅读 Stage 0/1 最新验收报告、原始 Schema/User Simulator 说明、walkthrough、评测/奖励协议以及现有 Task、快照、R0、EvaluationPlan 和测试代码。复用已有模块，没有另写业务数据库、工具或官方评分器。

| 来源 | 固定版本 |
|---|---|
| tau2 Fork | `dhh1995/tau2-bench`，`dhh/async-and-custom-completion` |
| Fork commit | `e33e9511e4f51e5cfa16e12b02d0e4ab327b5887` |
| AReaL Dataset | `inclusionAI/AReaL-tau2-data` |
| Dataset revision | `86971dc03da6e7c1a7933295e05b84aab8215386` |
| Qwen tokenizer | `Qwen/Qwen2.5-3B-Instruct` |
| tokenizer revision | `aa8e72537993ba99e69dfaafa59ed015b17504d1` |

实际 Windows CPU / CPython 3.11.15 执行，未使用 GPU。四份快照和两个原始 JSONL 的字节数/SHA 均复核，所有 raw 文件在执行前后不变；Fork 工作区干净。Stage 0 Linux 已有历史验证，但本轮没有运行 Stage 2 WSL/Linux 或 AutoDL 验证。

| 原始数据 | 实读结果 |
|---|---:|
| RL 全领域 | 1,982（Retail 563 / Airline 1,148 / Telecom 271） |
| SFT 全领域 | 33,531 |
| Retail SFT | 11,395 个 assistant target |
| Retail 原始来源对话 | 1,000 |
| Retail RL 唯一 Task | 563 |
| Retail DB 快照 | 4 |

SFT metadata 六个字段在全部 Retail 行中存在且非空；source_dialog_id、scenario_id 和 RL ID 不做未经证实的编号映射。源对话、真实角色、tool JSON/参数、当前 target、完整历史前缀、源质量全部实际检查。格式错误、工具 Schema 错误、空 target、重复 turn_index、完整重复监督行/对话均为 0。

95 段来源存在监督 turn_index 缺口，但已有历史前缀一致；作为 warning 保留，不整段删除、不编造缺失标签。源质量失败为 **8 段 / 108 个回合**，按 correct=1 且 reward=1.0 的门槛隔离；原件与规范化副本保留。合法来源为 992 段 / 11,287 个回合。

RL 全部经真实 Task 校验、db_path 校验与工具 Schema 校验；563 个没有 initial_state。548 个含状态修改参考动作、15 个只读；参考动作数 0–14、p50=8、p90=10、p95=11、p99=12。这里是 reference_length_proxy，不是已测 Student Episode 长度。

**全部 563 个 RL 任务的 COMMUNICATE 条件为空。** 在正常终止下，通信分项恒为 1，官方奖励主要检查数据库终态；不能据此保证认证、确认和业务解释正确。原始 R0 规则保持不变。

## 2. 真实重复与跨源关系

“重复”需要同一客户、业务对象、目标及参数、关键约束、结束条件和相关初态等价。缺失字段不是相等；同类业务、同一商品、单个 ID、相似文本均不作为删除依据。

| SFT ↔ RL 候选分类 | 对数 |
|---|---:|
| confirmed_same_instance | **0** |
| probable_same_instance | **0** |
| same_business_pattern_only | 609 |
| distinct_or_unknown | 90 |
| 合计候选 | 699 |

90 对中有 4 对共享订单标识、但客户/约束/初态无法证实相同，作为高风险未决关系保守分组；其余 86 对没有呈现共同实体及业务的同实例证据。以上是候选对数，不是重复 Task 数；检索涉及 272 个 RL Task。全组合空间为 563,000 对，当前实体及局部文本检索不能证明所有未检出组合都独立。

27 对业务诉求文本归一后完全一致，但实体无交集，属于可复用模板；没有任何跨源候选的写入动作及全部参数完全相同。SFT 不含完整私有任务约束/评分结束条件，写入前完整实体观测也不能绑定到四份 RL 初态，因此没有充分确认依据。

RL 内部实体/相同诉求候选有 470 对，其中 3 对 probable，仍未确认私有约束和相关初态等价；SFT 内部有 815 对候选，无确认重复。精确 RL 实例指纹、完整 SFT 对话及监督行重复组均为 0。内部未决关系依共享实体整体分组，不跨数据分区。

私有 `overlap_candidates.jsonl`、`within_rl_candidates.jsonl`、`within_sft_candidates.jsonl` 保存来源、等级、未知字段、规则和证据 hash；详细文字不进公开报告。真实匿名案例和漏检/误删风险见 [跨源审计](../../docs/cross_source_overlap.md)。**这里的 0 是“已确认数量”，不是已证明整个语义空间没有重复。**

## 3. 最终划分与隔离

seed=42，先全局分组，后按业务主类型、快照、参考长度 proxy、状态修改、通信条件做边际分层。共 1,553 组，7 个非平凡组，最大 4 个节点；1 组跨 SFT/RL。它们按统一角色分配，分组不等于宣称组内每对都是真实重复。

| 数据角色 | Task 数 |
|---|---:|
| rl_train_full | **394** |
| rl_train_cost_pruned | **394** |
| rl_dev | **84** |
| rl_test_frozen | **85** |
| quarantine | 0 |
| 预先选定 Pass^4 子集 | **50** |

原始 563 个 Task 各属于且仅属于一个主分区；cost-pruned 和 Pass^4 是派生视图。此次恰好符合整数目标，代码没有把整数配额置于分组完整性之上。

| 快照 | Train | Dev | Test |
|---|---:|---:|---:|
| 1 | 68 | 14 | 14 |
| 2 | 45 | 10 | 9 |
| 3 | 131 | 27 | 28 |
| 4 | 150 | 33 | 34 |

| 业务主类型 | Train | Dev | Test |
|---|---:|---:|---:|
| account_address | 119 | 26 | 27 |
| exchange | 54 | 11 | 11 |
| cancel | 73 | 16 | 16 |
| items | 64 | 13 | 13 |
| order_address | 36 | 7 | 7 |
| payment | 16 | 3 | 3 |
| return | 16 | 3 | 4 |
| readonly_query | 9 | 3 | 2 |
| human_transfer | 7 | 2 | 2 |

短/中/长参考 proxy 为 Train 99/230/65、Dev 19/51/14、Test 21/50/14；阈值 ≤6、7–9、≥10。只读分别 10/3/2，通信条件全部为空，不能假报非空通信分层。小类别只有少量 Task，分布不能视为精确均衡。

Stage 0/1 十个历史暴露 Task 全部进入 Dev：retail_131、152、245、293、325、339、454、479、65、8。来源定位保留私有；没有进入 Test。同实体关系形成的潜在变体亦整体分组。本轮新增离线接口对照 retail_101（Train）和 retail_115（Dev），不触碰冻结 Test；它们是 reference fixtures，不是 Student 效果实验。

| SFT 角色 | 完整来源对话 | assistant target |
|---|---:|---:|
| Train | **889** | **10,148** |
| Val | **103** | **1,139** |
| 质量隔离 | 8 | 108 |
| heldout_from_sft | 0 | 0 |

Val 占可用来源约 10.38%，差额来自分组和边际平衡。没有对话被拆到 Train/Val；合法专家回合全部保留。已识别组的 RL 主分区交集、SFT 来源交集、SFT Train↔RL Dev、SFT 模型使用↔RL Test 以及 SFT Val↔RL Train 冲突均为 0。未知共享订单的跨源组整体在训练侧；不是先切分再删除专家行掩盖污染。

集合 ID、快照及 SHA manifest 在 Git 忽略的 `data/splits/stage2/`。Stage 1 Task set hash：

| 清单 | SHA256 |
|---|---|
| rl_train_full / cost_pruned | `ea0a95bbf14c71664ff08750bb1dae294a8e45b73585adfe1a90b38d2edc1be6` |
| rl_dev | `8f8bc4ef239658a7f514a98a8a597935cee0a3b1e4766cdef6ef25b7b5a59fce` |
| rl_test_frozen | `639f6266a127b2e8b625401b52213e66e5b7117209d42b4bf15a2162acb100d5` |
| pass4_subset | `85dfa741bafc83b38da887d796d81d828ec526339e0789c7f359bf1bfc4a83e4` |

实际重算相同输入/seed 后的映射、清单和 hash 一致；不同 snapshot 可以跨分区，共用整个 DB 不当作任务泄漏。仍不能证明不可观测的上游种子关系已全部排除。

## 4. 成本视图与专家保留

排除 **0 个 RL Train Task**，默认完整池。cost-pruned 子集条件、未决候选保留、Train↔SFT Train 限定、证据 hash 和回退均有代码与 synthetic 测试。回退只需选择 rl_train_full，无需恢复被删除原件，因为原件没有删除。

没有因为 SFT 可能较强而减数据；没有认为同实例的 teacher forcing 与 on-policy RL 等价。后续即便确认重复，也可能有探索/纠错收益；固定预算转投其他任务也不等于省钱。本阶段未验证 Episode/Token/GPU/API 成本下降。详见 [成本视图](../../docs/rl_cost_filter.md)。

## 5. 训练格式与实际 Loss Mask

下载的两个 tokenizer 文件合计 7,038,950 字节，没有模型权重。实际执行固定 Qwen Jinja chat template 和 Rust tokenizer，保留模型无关表示，再导出模型输入。flat/function 形式的工具调用转换为 Qwen `<tool_call>` JSON；历史工具返回使用 `<tool_response>`，完整参数及返回边界均校验。

源 agent wrapper 的 valid JSON only 与 Qwen XML/自然语言协议冲突，转换仅调整协议包装，源业务政策原文保留。未来 Harness 应复用同一包装、工具 Schema 和模板；不能把原始 flat JSON 当作自动兼容的推理协议。

模板无 generation mask。实际方法是历史+generation prefill 与完整 answer suffix 的严格边界编码；decode 与完整模板相等，全部 **11,287** 个样本的分段编码亦与整串一次编码完全一致。

| 全量验证 | 结果 |
|---|---:|
| 检查样本 | 11,287 |
| 工具目标 / 文本目标 | 5,110 / 6,177 |
| 数组长度错位 | 0 |
| 空监督 / 全 -100 有效样本 | 0 |
| 历史 assistant/user/tool/system 参与 Loss | 0 |
| 工具 JSON 往返错误 | 0 |
| tokenization 错误 | 0 |
| 默认 16K 长度过滤 / 截断 | 0 / 0 |

仅当前 answer 正文/完整工具调用与 EOS 被监督；prompt、历史 assistant、末尾模板换行和 padding 为 -100。padding 另有 synthetic 正反例测试，真实导出为未 padding 数组。EOS=151645、pad=151643、im_start=151644、tool_call 标签=151657/151658。

模板 hash 为 `2e2d2512cfe46af53dc1eed45368ecaab26ac4461c480e6b69fe571cf0ceaa75`（canonical JSON string SHA256）；文件字节 SHA、序列化 sample hash、完整 artifact hash 另有记录。原始 thinking/reasoning 在私有中间表示保留，当前非推理 Student 标签只用文本与工具动作，没有注入 RL 隐藏答案。

| 合法样本真实 input tokens | 数值 |
|---|---:|
| p50 / p90 | 6,754 / 9,415.4 |
| p95 / p99 | 10,172.7 / 11,419.12 |
| min / max | 4,800 / 14,332 |
| 全部 input tokens | 77,751,825 |
| 全部受监督 tokens（含 EOS） | 1,383,340 |
| Train input / supervised | 69,950,315 / 1,244,015 |
| Val input / supervised | 7,801,510 / 139,325 |

token 总量包含每行重复的历史/政策/工具，不是独立对话量或 API usage，也不是已执行训练消耗。4K 容纳 0 行，8K 容纳 8,634 行、丢失 2,653 行（约 23.5%），故默认 **16K 完整专家视图**；不因预算随意切掉历史、工具 JSON 或答案。[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)标注 32,768 上下文；16K 的 GPU 显存/吞吐仍待后续实测。

`sft_train.tokenized.jsonl.gz` / `sft_val.tokenized.jsonl.gz` 分别含完整 10,148 / 1,139 行，可读取真实 arrays 和目标 span；oversize 归档为空。模型无关 JSONL、质量隔离文件、源定位和全部思考字段仍保留。格式和掩码通过，但**当前政策与多工具专家轨迹的语义对齐尚未解决，不能直接宣称已具备当前 Fork 的全部政策合规性**。详细规则见 [SFT 预处理](../../docs/sft_preprocess.md)。

## 6. 评测衔接与外部候选

RLTaskPool 实际复用 Stage 0 parser、快照加载和环境工厂；两个 Train/Dev 对照检查初始化、独立副本和官方 R0，工具无错误、官方 DB 匹配。Student context 只返回 policy/tools，不返回 user_scenario、evaluation_criteria、参考 actions 或审计提示。OPD/GRPO 后续可共享任务池定义，但必须分别按当时 Student 真正采集 rollout，不能复用 SFT/旧模型轨迹充当 on-policy。

未执行的 Pass^1/Pass^4 template 已生成；schema 测试填入显式 synthetic 配置后符合 Stage 1 EvaluationPlan，未造 Episode。真实模型、Simulator、采样、服务版本、Harness/上下文等配置仍为空待填。最终预案为 **85 Task Pass^1 + 50 Task Pass^4**，235 Episode/Checkpoint，五个检查点 1,175 条；不同指标注明各自分母，不是 Pass@4，也不是当前成绩。

固定 Fork 的实际 Retail tasks 为 114 条，test split **40 条**；静态任务和工具参数检查通过，当前检索与 AReaL SFT/RL 没有候选命中。但没有可核验的种子生成来源，外部状态为 **EXTERNAL_EVAL_CANDIDATE/CONTAMINATION_RISK**，正式独立泛化评测 **BLOCKED 待来源/协议审查**。未观察到重复不等于已证明独立；它不能混入内部指标分母，也不能无条件对比其他版本的 leaderboard。见 [外部审计](../../docs/external_eval_audit.md)。

## 7. 实际命令、测试与不变性

主命令：`.venv\Scripts\python -X utf8 scripts/stage2_check.py`。以下为本轮完整检查的实际进程结果；数据脚本在 socket connect/create_connection 禁用的 wrapper 下执行，测试也禁止网络。完整 argv、环境、哈希和私有日志定位见 check_results.json。

| 入口 | exit | 耗时秒 | 结果 |
|---|---:|---:|---|
| stage2_audit.py | 0 | 27.054 | 全量 Retail 审计及证据 |
| stage2_split.py | 0 | 1.262 | 全局分组、边际分层、视图 |
| stage2_prepare_sft.py | 0 | 279.931 | 全量真实 tokenizer/labels |
| stage2_external_audit.py | 0 | 1.250 | 真实 Fork test 候选审计 |
| pytest tests/stage2 | 0 | 30.502 | 44 passed |
| 相关 Stage 0 + 全 Stage 1 pytest | 0 | 61.934 | 83 passed |

回归涵盖 Task/路径、数据库隔离、官方 R0、已保存两条真实轨迹及 EvaluationPlan/metrics 语义。原始 `retail_131=0`、`retail_152=1` 和完整 RewardInfo 保持不变；没有付费重跑。开发中修正了支付 ID 被误当客户候选、turn 缺口不应整段质量排除、审计 set/list TypeError、往返测试不应解析 system 内的协议示例；最终全量脚本与测试均通过，初次开发测试的 1 个失败已修复，保留 pytest-development.xml 而非冒充全程从未失败。

所有 raw 文件执行前后 hash 一致，DeepSeek 历史账本 hash 不变，tested code 执行前后不变，Fork clean。真实 Git check-ignore 检查 .env、raw/private/processed/tokenizer/Test manifest 通过；使用私有临时 git-dir，未初始化项目根 .git、未提交/推送。没有新增付费 API、Student/User 模型调用、真实 Episode、模型权重、SFT/OPD/GRPO、R1 或 Stage 3 Harness。

## 8. 风险与人工验收重点

1. **政策差异与多调用目标**：原始有 1,489 个多调用 target，而当前 Fork 一次只能一个工具调用；源确认措辞也较弱。保留专家动作并标注 REVIEW_REQUIRED，后续训练前需决定如何对齐协议与监督，不能以本次结构性 PASS 代替政策合规审查。
2. **专家初态无法重放核验**：SFT 完整实体观察不能绑定四份 RL 快照，源 metadata 缺少 DB 引用和完整私有约束。本次源质量标签+格式/参数检查不能证明所有专家业务结果可在当前环境重放。
3. **上游关系证据不足**：跨源确认数 0 不等于语义/种子重合绝对为 0；内部 3 对 probable、订单数字复用及实体别名仍有待审空间。可见风险整体分组，未知 lineage 仍公开保留限制。
4. **分布差异**：account_address 在 RL 主标签中为 172/563，SFT 来源仅 1/1,000；未通过删减 SFT 改造此分布。后续模型效果可能受源覆盖差异影响，当前没有效果证据。
5. **官方评分覆盖不足**：全部通信条件为空，只读/确认等政策可能没有全面奖励覆盖；country 严格字符串比较的历史风险仍在，官方规则未修改。
6. **资源与训练器尚未验证**：默认 16K 保留专家但增加未来上下文预算；本轮没有 GPU/Trainer/packing/梯度验证，也没有本轮 Stage 2 Linux 实测。接入时需复核 same template/schema、causal labels 和运行成本。

| Gate | 状态 | 实际边界 |
|---|---|---|
| S2-A 全量审计 | PASS | 源 SHA、全部 Retail 行、质量/字段/Schema |
| S2-B 跨源关系 | PASS_WITH_LIMITATIONS | 699 候选、确认 0、未知依据与私有链 |
| S2-C 分组隔离 | PASS（可见关系） | ID/组/历史暴露隔离；不宣称未知 lineage 已证明独立 |
| S2-D 专家组织 | PASS | 992 合法来源完整分组，保留全部合法 target |
| S2-E 成本视图 | PASS | 394=394，排除 0，可回退 |
| S2-F Qwen 格式/Mask | PASS；政策 REVIEW_REQUIRED | 真实 11,287 行；业务语义非结构校验可替代 |
| S2-G Stage 1 接口 | PASS | manifests/plan schema；正式评测未运行 |
| S2-H 外部候选审计 | PASS；独立性待审 | 40 条实际文件，正式外部评测 BLOCKED |
| S2-I 测试与阶段边界 | PASS | 127 实测通过、原件/R0/账本不变、0 新模型请求 |

主要工程产物为 `src/policytrace/data/`、六个 Stage 2 入口（含仅 tokenizer 文件下载）、`configs/data/`、`tests/stage2/`、六份 docs、聚合 JSON 和本报告。私有清单、完整规范化源、证据与真实数组在 Git 忽略目录；代码/文档/报告及产物指纹见 source_manifest.json。

本阶段不证明 Student 已学会工具、SFT 成功率提升或 RL 成本下降。按 [policytrace-stage2 Skill](../../.agents/skills/policytrace-stage2/stage2.md)：“停止在 Stage 2 等用户人工验收，不自动进入 Stage 3”。本轮停止于此，等待人工验收。
