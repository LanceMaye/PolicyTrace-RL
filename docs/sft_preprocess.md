# SFT 标准化、Qwen 协议与 target-only labels

原始数据不可变。私有 `normalized_source.jsonl` 保存规范化历史与当前答案、排除的非 Student 字段、完整 metadata、源行号和行哈希；可从原始行恢复全部内容。Student 导出只包含 `messages`、`answer` 和来源定位，不把 metadata.reason_for_call、thinking/reasoning、RL user_scenario 或 evaluation_criteria 加入模型上下文。

原始 flat tool call `{name, arguments}` 和 OpenAI function 形式均映射到结构化 function，JSON 字符串 arguments 先解析成对象，使用实际 Retail Tool Schema 校验。历史工具结果按名字和 pending calls 绑定，补上确定性的调用 ID；孤立响应、未回答调用、非法参数、空 target 会拒绝。源数据允许多调用；中间表示保留原动作和实际返回，不猜测未执行动作。

使用 [Qwen 官方 tokenizer 配置](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/aa8e72537993ba99e69dfaafa59ed015b17504d1/tokenizer_config.json)，revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`。只下载 tokenizer.json（7,031,645 字节）和 tokenizer_config.json（7,305 字节）；没有权重、Torch 或训练器。用已锁定 Rust tokenizers 与 Jinja 执行原模板，JSON filter 与 HF 的 JSON 语义一致。template hash、文件 SHA、special IDs 见 quality_report.json；对象及模板字符串 hash 采用本项目 canonical JSON SHA256，文件 SHA 则是原始字节 SHA256。

Qwen 输出 `<tool_call>` 中的 `{name, arguments}` JSON，工具返回进入 `<tool_response>` 区块。工具 definitions 使用固定 Fork 的 15 个真实 Schema。模板本身没有 `{% generation %}`；不能把 assistant_only_loss 配置视为自动正确。

源 agent wrapper 要求 valid JSON only，与其自然语言答案和 Qwen XML 工具协议冲突。模型导出只改协议 wrapper，保留 `<policy>` 内的源业务政策原文；模板和包装函数需由以后推理 Harness 复用。当前 Fork 政策与源政策确有差异，详情见 data_audit.md。没有偷偷把专家动作改写成参考 actions，也没有删除多调用专家目标。**格式可用于训练，但业务政策与一次一个工具调用的对齐仍需训练前人工审查。**

编码步骤：实际模板先生成历史+generation prompt，再生成历史+answer；验证前者为后者的严格前缀。按真实推理边界分别编码前缀和完整 answer suffix，并检查 decode 后与完整模板逐字符一致。只监督当前 answer 正文、工具调用的完整 JSON/标签和结束 `<|im_end|>`；assistant header、所有历史 assistant/user/tool/system、末尾模板换行、padding 一律 labels=-100。input_ids/attention_mask/labels 等长，最后监督 token 必须是 EOS，不允许空监督。编码结果同时比较完整字符串的一次性编码是否相同；如 BPE 会跨边界合并，分段编码保证不把 prompt 字符混入 Loss，计数另有记录。

| 实际合法样本 token 长度 | tokens |
|---|---:|
| 最短 | 4,800 |
| p50 | 6,754 |
| p90 | 9,415.4 |
| p95 | 10,172.7 |
| p99 | 11,419.12 |
| 最大 | 14,332 |

全部 11,287 行共 77,751,825 个真实 input tokens。这包含每个 turn 重复的历史与工具/政策；不是独立对话总量，也不是 API usage 或已消耗的训练 tokens。

4K 覆盖 0 行。8K 覆盖 8,634 行，会排除 2,653 行（约 23.5%）。**默认 16K 视图保留全部 11,287 行**，没有长度截断或长度过滤，避免降低合法专家数据覆盖。[Qwen 官方 3B 模型卡](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)标注上下文 32,768，支持这个长度上限；实际 GPU 显存和吞吐尚未测量。8K 仅是预算覆盖统计，不是启用的默认训练缩减。

`data/processed/stage2/sft_train.jsonl` / `sft_val.jsonl` 是模型无关 Student 视图；`.tokenized.jsonl.gz` 分别是 10,148 / 1,139 个完整 16K 内样本。tokenized 行含真实数组、目标 span、监督 token 数、序列化 hash、源定位，未 padding。oversize 归档本次为空；失败源对话的 108 行在单独质量隔离文件中。所有产物和原始数据都由 Git 忽略。

全量样本均校验长度、非空监督、历史屏蔽、EOS、字节解码及工具 JSON 往返。synthetic 测试另覆盖历史 assistant、多工具、flat/function 形态、JSON 字符串参数、隐私字段、坏 mask、padding 与孤立结果。尚未执行梯度、SFT loss、assistant accuracy、GPU Trainer 或任何模型效果评测；接入 Trainer 时仍须验证 causal shift、padding/packing 语义与推理协议一致。
