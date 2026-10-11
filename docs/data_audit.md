# Stage 2 全量数据审计

本次实际遍历本地原始 JSONL，未引用 Stage 0 的前 100 条抽检充当全量验证。可执行入口为 `scripts/stage2_audit.py`，结构化结果为 `reports/stage2/source_audit.json`。源文件均与 Stage 0 固定 revision 的字节数和 SHA256 一致；原件没有修改。

| 数据 | 实读数量 |
|---|---:|
| 全领域 SFT 行 | 33,531 |
| Retail SFT assistant target | 11,395 |
| Retail 原始来源对话 | 1,000 |
| Retail RL Task | 563 |
| Retail 快照 | 4 |

SFT 的 `source_dialog_id`、`scenario_id`、`turn_index`、`reason_for_call`、`correct`、`reward` 在全部 Retail 行中存在且非空；数值 0 不作为空值。每个对话对应一个 scenario_id，但没有证据把 scenario 的编号直接映射成 RL Task 编号。`messages` 是历史，`answer` 是当前一个 assistant target；不是每行一条完整独立任务。

源标记成功的 992 段对话共有 11,287 行；8 段失败对话共有 108 行，按预先定义的 `correct=1 AND reward=1.0` 质量门槛隔离，原件及规范化副本保留。全部行均通过角色、非空目标、工具 JSON 格式和固定 Fork 参数 Schema 校验，没有格式或工具 Schema 错误。这里的“通过”是结构性质量，不等于每个动作都符合当前业务政策。

同一来源的历史前缀一致，没有重复 turn_index 或跨对话的完全相同完整轨迹，也没有完全重复的监督样本。95 段来源对话存在 turn_index 缺口：已有样本是完整历史的前缀，缺少的监督目标不臆造，合法现有样本保留。对话 assistant target 数最少 6、p50=11、p90=16、p95=17、p99=20、最多 22。这些来源对话的回合数与以后 Student 的 Episode 长度不是同一个量。

所有目标都有非空 `thinking`，历史中还有 `reasoning`。它们仅私有保存，不加入 Qwen 非推理模式的 Student 输入或标签；保留全部合法目标的文本和工具动作。模型无关表示、原始行号及行哈希可回溯到不可变原件，转换不是不可逆删除原字段。

RL 全部复用 Stage 0 解析器：先解码 evaluation_criteria JSON 字符串，再执行真实 Task 校验；快照使用真实 RetailDB 校验。563 个 ID 唯一，没有参考工具 Schema 错误，没有 initial_state。548 条含状态修改参考动作，15 条没有。参考动作数 p50=8、p90=10、p95=11、p99=12，范围 0–14；不能称作已测 Student 长轨迹。

**563 个 RL 任务的 COMMUNICATE 条件全部为空。** 因而当前声明的 DB×COMMUNICATE 在正常终止时，通信分项恒为 1。尤其不能仅凭只读任务的数据库奖励推断认证、确认或拒绝解释正确。

分类为参考动作导出的多标签；主标签按固定名称顺序选择，不假设所有任务只有一个目标。RL 主标签中 account_address 为 172/563，而 SFT 来源对话只有 1/1,000；SFT 主要为取消、改商品、换货等。此分布来自源数据，本阶段没有人为削弱 SFT 来制造 RL 优势。

SFT 短/中/长按来源 target 数 ≤9、10–13、≥14；RL reference proxy 按参考动作数 ≤6、7–9、≥10。阈值固定在配置中，分布为 SFT 330/416/254 段、RL 139/331/93 条，不声称三个桶等大，也不以模型测试得分调阈值。真实 tokenizer 长度另外见 `sft_preprocess.md`。

实际发现两项政策差异：SFT 源政策对修改前确认使用较弱措辞；当前固定 Fork 改为强制明确确认。SFT 源政策未限制一次一个工具调用，当前 Fork 添加了这个限制。原始目标有 1,489 行一次包含多个调用（2 个 647 行、3 个 830 行、5 个 12 行）。它们没有因为这个差异被删除，也没有被假称为当前政策全部合规。训练前需审查政策及动作协议对齐。

私有证据在 `data/private/stage2/`：行级质量、完整规范化源、来源对话、初态观测、实体候选和历史暴露定位均可审查；公开报告只保存统计、规则及哈希。
