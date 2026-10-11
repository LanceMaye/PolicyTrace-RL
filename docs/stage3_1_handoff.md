# Stage 3_1 接入清单（未执行，待人工批准）

2026-10-11 用户批准切换为 **areal-retail-sft-v1 自定义 Policy**。业务文本逐字复用冻结 SFT；允许纯多工具回合，禁止文本与工具混合。当前 SFT 主视图为 Train **9707** / Val **1080**，入口仍为 `configs/data/sft_main_view.json`。旧 Stage 2/3_0 报告记录的是原 Policy 设置，保留历史证据；当前复验见 [Policy 迁移报告](../reports/policy_transition_v2/POLICY_TRANSITION_REPORT.md)。

| 接口/配置 | 下一阶段需要填写与实际验证 |
|---|---|
| 运行环境 | AutoDL GPU 型号/显存、Linux/Python/CUDA/PyTorch/Transformers 版本及锁文件；现有 Windows Mock 结果不证明 GPU 环境就绪。先验证文件路径、Pinned Fork + 已批准 Policy patch、四个快照、冻结 manifest 与 tokenizer SHA。bootstrap 自动安装保留的 Policy bundle；verify_fork 只允许该 policy.md 改动，其他代码或额外文件仍拒绝。 |
| Student 模型 | `Qwen/Qwen2.5-3B-Instruct` 的确切 weight/checkpoint revision、权重来源、dtype/device、加载日志与显存；本阶段没有权重、Transformers generate 实现或真实前向。 |
| ModelClient | 实现 `generate(ModelRequest) -> ModelResponse`，将现成 Prompt IDs 原样送入模型，按 input length 切出 generate 返回的 Completion IDs；保存原始 IDs，解码文本进入同一个 Parser，校验 EOS/length stop、特殊 Token、文本与解析对应。不能 re-encode 冒充原始生成序列。 |
| 来源与用量 | 将离线 Driver 限制替换为经过审核的真实 client 接线，并在真实记录中使用真实 provenance/source；当前日志和 Driver 专用于 mock，不能只换一个模型名。接入 actual model token/latency；缺失 logprob、provider usage 必须继续标 null。 |
| User Simulator | 沿用 Fork 原有场景包装和停止规则，接入现有 DeepSeek 预算适配；确认实际服务 model ID、API 参数、费用上限、最大请求和上下文预算。密钥仅本地 .env，不进轨迹。Scripted User 不证明 DeepSeek 的场景忠实度和信息透露时机。 |
| Context/协议 | 同一 tokenizer/template、identity-v0、areal-retail-sft-v1、工具 Schema、Parser；默认 validate_communication=True。审核并冻结 max_steps/errors、工具总量与 Token 预算、采样/seed 支持。所有 Base/SFT/RL 及评测使用相同 Policy；不得混用不同配置的 E0–E4。 |
| Policy 版本与风险 | Policy SHA `efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936`；SFT 与当前 Harness 的业务文本、共享 Qwen 包装一致。完整采用 SFT 意味着通用确认措辞为 you'd better，不再指定字面 yes，具体操作确认规则仍在。历史混合消息保持 masked，源数据库缺失，不能宣称全业务合规；商品查询监督仍因混合隔离而偏少。指标应标为自定义 Policy 设置。 |
| Dev Smoke 与基线 | 先用 5–10 个经许可 Dev Task 实际验证模型→Parser→Fork→工具→User→官方评分，再做完整 Dev E0；填真实 checkpoint、Simulator 版本、Task/Trial/seed 和配置，复用 Stage 1 EvaluationPlan/EpisodeRecord，不改官方 R0。不使用冻结 Test 调试。 |
| 性能与长 Context | 实测 Prompt/Completion 长度分布、工具占比、TTFT/生成耗时、整 Episode 时延、显存和真实费用；根据真实溢出与分布决定是否需要 schema-aware Observation Projection，当前不启用压缩或 KV cache 复用。 |
| 失败与恢复 | 验证真实服务超时/限流/断流、generation length stop、Tool error、Parser failures；保持所有已启动 Trial 和完整 attempts。跨进程 checkpoint、RNG/client cursor、部分批次 exactly-once 尚未验证，不能自动无痕重试。 |
| 后续训练 | Stage 4 才开始 SFT；以后 OPD/GRPO 单独接入 learner/action mask、真实 logprob/Teacher/rollout group/KL 等；当前 decision span 只提供边界证据，不证明 trainer 接口、数值或学习效果。 |

尚未验收：真实 Student Prompt/Completion/Logprob 对齐、DeepSeek 连通性与质量、GPU/AutoDL、真实 E0、正式 Pass^1/Pass^4、训练、R1、外部 Test 独立性、全业务 Policy Guard、流式 Parser，以及参数字符串含协议分隔符等真实输出边界。Stage 3_0 完成后停工；上述内容需要用户批准 Stage 3_1 后再执行。
