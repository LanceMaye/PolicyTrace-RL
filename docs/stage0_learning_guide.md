# PolicyTrace-RL 项目入门与面试讲解

这份指南讲的是**当前仓库已经做成的 Stage 0**，以及后续模块各自要解决的问题。Stage 0 是环境和数据兼容性验证，不是已经做出一个 RL 客服模型。

## 先用一句话讲清楚项目

PolicyTrace-RL 的目标，是在 τ²-bench 的 Retail 客服环境中，让一个能调用业务工具的语言模型通过交互完成任务，再用任务结果给它评分，并进一步研究如何用强化学习改善它的策略。

目前完成的工作是把这条路的“地基”打通：读取 AReaL Retail 任务和数据库快照，在真实 τ² Retail 工具上执行操作，并让官方 Evaluator 从相同数据库初态评分。项目还用两个真实 DeepSeek 双向对话确认了 Agent、用户模拟器和官方 Orchestrator 能连接起来。**目前没有训练 Student，没有自研 Agent Harness，也没有验证 AutoDL GPU 训练。**

## 需要分清的几个角色

一次客服任务中，程序里有以下角色：

| 角色 | 做什么 | 例子 |
|---|---|---|
| Task | 描述任务背景、用户场景、初始状态和评分条件 | `retail_131`：用户搬家，需要更新默认地址 |
| Agent / 被测模型 | 看公开对话、业务规则和工具说明，决定怎么问、何时调用哪个工具 | 先确认身份，再查询账户、确认新地址，最后调用修改工具 |
| User Simulator | 按隐藏的用户场景扮演客户，逐步回答客服 | 提供身份信息、地址，确认或拒绝操作，并在适当时机结束 |
| Environment | 执行工具并保存本轮运行时的业务状态 | Retail Python 工具访问本轮独立的 RetailDB |
| Orchestrator | 把用户、Agent 和工具连接起来，控制谁在何时收到消息 | 用户话语发给 Agent；Agent 工具调用交给环境 |
| Evaluator | 根据任务的正式评分条件和运行轨迹计算 Reward | 重放工具轨迹，比较实际数据库和参考目标状态 |
| Harness | 实际运行模型评测的工程系统，负责配置、调用、工具路由、日志、终止和故障处理 | Stage 0 用 tau2 官方 Orchestrator；以后计划自行实现 Agent Harness |

Reward 是 Evaluator 输出的分数或分项结果。它不是另一个聊天角色，也不等于用户说“谢谢”。在当前任务中，数据库结果和通信终止等条件参与官方评分；具体哪些分项参与要看任务的 `reward_basis`，不能把每种诊断信息都当成奖励。

## τ²-bench Retail 是什么

它不是一组只要求模型生成文本的问题，而是一个**有状态、可调用工具的模拟业务环境**。Retail 域包含用户、商品、订单、配送等数据和官方业务工具。例如查询账户、查询订单、取消待处理订单、退货、换货、修改地址。工具由 Python 环境执行，返回的观察是真实工具逻辑给出的结果。

Agent 需要理解自然语言任务，并在对话过程中把请求转成合适的工具调用。它还要遵守业务政策，例如先认证、确认用户要修改的内容，以及拒绝不允许的操作。模型输出工具调用，只表示模型提出了一个操作；是否真的改变状态，要看环境执行结果。

一次运行的状态是临时的。每条任务的 `db_path` 指向它的初始 RetailDB 快照。环境从这份快照创建独立副本，工具修改的是 Episode 内的副本，不会把源数据改掉。否则任务之间互相污染，分数就无法比较。

## 当前仓库的一条任务到底怎么跑

1. 从 `tau2_rl_train.jsonl` 读取原始任务记录。兼容层把字符串形式的 `evaluation_criteria` 解析成 tau2 的 Task，并保留任务 ID 与 `db_path`。
2. 安全解析 `db_path`，读取对应 JSON 快照，并校验为 RetailDB。路径越界、缺失文件、错误结构都应明确失败，不能悄悄回退到默认数据库。
3. 用快照的深拷贝创建执行环境。工具调用只修改这份运行时副本。
4. 运行时，Orchestrator 将用户公开发言交给 Agent。Agent 可以发普通文本，也可以发结构化 `ToolCall`。工具调用经环境执行，观察结果再回给 Agent。
5. 对话正常结束或触发停止条件后得到 `SimulationRun`，其中包含消息和工具轨迹。
6. 官方 Evaluator 从同一个初始快照分别建立预测环境与参考环境：前者重放真实轨迹，后者按任务的参考动作构造目标状态。然后依官方规则比较状态和通信等评分项。

这里有一个不明显但很关键的坑：只给 Agent 执行环境传对了数据库还不够。如果 Evaluator 重建参考环境时使用 tau2 默认 DB，评分其实比较的是不同初态。本项目在 `evaluator_adapter.py` 中给官方 Evaluator 注册了绑定当前快照的环境工厂。上游评分函数和评分语义没有被改写。

数据字段也要分清：

- `user_scenario` 和用户私有指令给 User Simulator，用来扮演客户。
- `evaluation_criteria` 只给 Evaluator 使用。Agent 不应看到答案或参考条件。
- `actions` 常用于构造评测目标状态，不必然是要求 Agent 逐字逐步照抄的唯一路径。
- Agent 能看到业务政策、工具 Schema、公开对话以及自己真实调用工具得到的观察。

## 一个真实 Episode：retail_131 地址更新

这条真实样本用了 DeepSeek 分别扮演客服 Agent 和 User Simulator。两个角色有各自的系统提示词和对话历史，不能因为调用同一个模型服务就认为它们共享记忆。

```text
官方 Orchestrator 给出问候
  → 客户说自己搬家，要修改默认送货地址
  → Agent 要求先验证身份
  → 客户提供邮箱
  → Agent 调用 find_user_id_by_email
  → Retail 工具从当前快照返回用户 ID
  → Agent 询问完整新地址
  → 客户提供地址
  → Agent 复述地址并请求确认
  → 客户确认
  → Agent 调用 modify_user_address
  → Retail 工具在本轮数据库副本中更新地址
  → Agent 告知完成，用户发送停止标记
  → 官方 Evaluator 评分
```

结果是两次工具调用、零工具错误、正常停止，但官方 Reward 是 0。原因是严格数据库比较发现国家字段为 `United States`，参考目标为 `USA`。这是很好的工程案例：**工具成功、对话看上去完成、最终评分通过，是三件不同的事。** 后续应审查数据规范和模型参数输出，但不能偷看答案后把参考分数改成 1。

另一个任务 `retail_152` 要求客户请求跨品类换货，Agent 按政策拒绝；官方 Reward 为 1。不过用户模拟器在认证前透露了想换货的具体内容，存在时序偏差。分数是 1 不代表对话中的每个细节都理想。

## 参考动作测试与真实模型成绩的区别

Stage 0 的 `stage0_smoke.py` 使用的是**参考动作夹具**，检查任务可否加载、数据库和工具可否运行、预期目标状态能否构造，以及官方评分器会如何评分。它的目的类似于先验证“仪器是否接对、已知标准样品是否读对”。

它不是一个学习出来的 Agent，也不能说明模型解决任务的成功率。Linux 复验中 `retail_245` 和 `retail_8` 都 Reward=1，表示参考轨迹能在对应快照上通过评分；它不能被包装成“我们的模型已能做好客服”。真实模型对话目前只有 `retail_131` 得 0、`retail_152` 得 1 两条，样本太少，不能算模型基准分数。

## 当前数据是什么、还没做什么

仓库下载并审计了 AReaL tau2 数据。统计中有 563 条 Retail RL 任务；SFT 全文件有 33,531 条记录，其中 Retail 约 11,395 条，来自 1,000 段原始对话。SFT 的一条记录通常是对话中的一个 assistant 回合，不等于一个独立任务或独立会话。

Stage 0 **没有**清洗数据、删除重复样本、制作正式 train/validation/test 划分或启动训练。真正划分时要防止同一个原始对话的不同 turn 跑进不同集合，也要防止同一任务模板或相关数据库状态造成泄漏。最终测试集应留到方法和参数都定下来以后再使用。

## 你说的下一阶段工程分别负责什么

**Reward 设计**：先决定要优化什么行为，分析官方 Reward 覆盖了什么、漏掉什么。官方评分适合作为基准结果和比较锚点；若需要训练用辅助奖励，应先做离线轨迹审查与反作弊检查，明确它鼓励了什么，可能被怎样钻空子。奖励如果只看数据库终态，可能忽略认证、确认、解释和礼貌；如果给每句话主观打分，又可能把模型带向迎合裁判的表达。训练奖励和最终报告的官方指标应清楚区分。

**评测搭建**：定义固定任务集合、运行配置、错误分类和结果统计。除成功率/Reward 外，常要报告工具错误、策略违规、超时/提前停止、调用成本、对话长度，并抽查关键轨迹。比较模型或训练步骤时，模拟用户、采样设置、任务初态和停止规则要保持固定。调参集、开发集与最终留出的测试集不能混用。

**数据集划分**：明确训练实际使用哪些 SFT/RL 样本，哪些用于调试，哪些只在最后报告。按原始会话、任务 ID 和任务相似性设计分组规则，保留源索引和清洗日志。不能把 assistant turn 当成互相独立的任务样本来随机打散。

**Agent Harness**：未来 Student 的运行系统。它将模型输出接到 tau2 工具，把工具观察写回上下文，维护轮数/Token/时间上限，处理格式错误和异常，记录可复现轨迹。Harness 负责执行和记录；模型负责决策；Evaluator 负责判分。要避免 Harness 偷看隐藏场景或评分条件。

**训练与 AutoDL**：在 Harness、数据和 Reward 协议固定后，才验证 GPU 模型加载、rollout 吞吐、显存占用、训练更新、checkpoint 保存/恢复。WSL CPU 通过只表明 Linux 依赖、数据和评分链路可运行，不能代替 AutoDL 的 CUDA/GPU/训练验证。

## 面试时可以怎样介绍

简洁版本：

> 我在做一个面向 tau2 Retail 工具型客服任务的 RL 工程项目。Stage 0 的重点不是训练，而是把 AReaL 的任务数据、每条任务对应的 RetailDB 快照、tau2 工具环境和官方 Evaluator 接起来。我发现评分器重建环境时可能使用默认数据库，所以做了快照绑定适配，并验证 Rollout 与参考目标从同一初态评分。Windows 和 WSL Ubuntu 上都跑通了固定任务；还用 DeepSeek 做了两条真实的 Agent/User 双向 Episode，看到地址字段规范差异会造成工具成功但 reward 为 0。当前自研 Harness、训练奖励和 GPU 训练仍是下一步。

如果面试官问“你个人具体做了什么”，你要能说清：

1. 为什么每条 Task 的 `db_path` 必须真正参与环境构建。
2. 为什么数据库必须隔离，以及如何确认原始快照没有被写坏。
3. 为什么 Evaluator 也必须使用同一个初态。
4. 参考动作验证和模型成功率的区别。
5. 为什么真实 `retail_131` 工具无报错仍得 0。
6. 当前框架里哪些使用 tau2 官方代码，哪些是你这边的适配；此时还没有实现哪些部分。

不要声称已实现 GRPO、训练 Harness、提升了模型成功率或完成 AutoDL 训练。诚实说出边界，反而能体现你理解实验结论的适用范围。

## 建议阅读路径

1. 本指南先建立术语和整体流程。
2. 阅读 `reports/stage0/STAGE0_REPORT.md`，确认结论与证据。
3. 用 `docs/stage0_walkthrough.md` 看两条真实 Episode 的消息过程。
4. 阅读 `src/policytrace/stage0/task_loader.py`、`db_adapter.py`、`evaluator_adapter.py`，对应理解任务解析、快照隔离和评分初态。
5. 阅读 `tests/stage0/test_db_isolation.py` 与 `test_evaluator_integration.py`，看工程不变量如何被验证。
6. 最后读 tau2 上游 Retail environment、Task/Snapshot 数据模型和 Evaluator。先能解释调用链，再逐步读每个工具的业务实现。

## 仓库文件夹和模块接口地图

先看工作区根目录：

| 路径 | 放什么 | 是否属于自己的核心实现 |
|---|---|---|
| `.agents/skills/` | 本项目 Stage 0 执行规范 | 项目流程说明，不是运行时代码 |
| `src/policytrace/` | PolicyTrace 自己的 Python 包；目前内容都在 `stage0/` | **是，Stage 0 适配层** |
| `tests/stage0/` | Schema、路径安全、DB 隔离、评分和 Mock 交互检查 | **是，验证兼容性的测试** |
| `scripts/` | 下载/审计/安装/Smoke/离线回放等可直接执行入口 | **是，操作入口和实验脚本** |
| `data/raw/` | 从固定 AReaL Dataset Revision 下载的原始 JSONL 与 4 个数据库快照 | 输入数据，不直接修改 |
| `data/private/stage0/` | 完整私有轨迹、API 账本、详细测试日志和评分细节 | 本地证据；可能含隐藏任务内容，不能当 Agent 输入或公开提交 |
| `external/tau2-bench/` | 固定 SHA 的第三方 tau2 Fork 源码与它自己的 `data/` | 上游实现；当依赖阅读，不把自有适配混进去 |
| `reports/stage0/` | 人类可读总结、公开统计、固定版本和检查结果 | 项目证据与结论 |
| `docs/` | Episode 流程讲解和本学习指南 | 项目说明 |
| `.venv/`、`.venv-linux/` | Windows、Linux 各自独立的 Python 依赖环境 | 生成环境，不是源代码 |

根目录的 `pyproject.toml` 定义包和依赖入口，`requirements-stage0.lock` 锁定依赖，`.gitignore` 排除虚拟环境、外部 Fork、原始/私有数据和 `.env`。密钥只在 `.env`，绝不复制进报告或提交。

### 自有 Python 模块怎样互相调用

关键调用方向大致是：

```text
stage0_smoke.py
  ├─ task_loader.iter_retail_records() → load_retail_task()
  ├─ db_adapter.load_retail_db() → RetailSnapshot
  ├─ reference_check.reference_fixture() → 用 tau2 工具执行参考动作
  └─ evaluator_adapter.evaluate_with_correct_initial_state()
       └─ tau2 官方 evaluate_simulation(..., EvaluationType.ALL)
```

- `task_loader.py`：`iter_retail_records(data_root)` 逐行读取 RL JSONL；`load_retail_task(raw, source_index)` 做结构转换，返回 `RetailTask(task, db_path, source_index, environment_config)`。
- `db_adapter.py`：`resolve_db_path()` 做路径安全检查；`load_retail_db()` 返回包含文件哈希、内容哈希和 RetailDB 对象的 `RetailSnapshot`；`make_retail_env()` 建一个可供任务执行的独立环境；`snapshot_constructor()` 返回“每次调用都从同一初始快照再建一个环境”的工厂。
- `reference_check.py`：用固定 seed 选取覆盖不同快照、读写任务的样本；`reference_fixture()` 通过上游工具逐条执行 Task 的参考动作。这里是评分链路测试夹具，不是 Student。
- `evaluator_adapter.py`：检查 Task ID 和快照匹配，将 `snapshot_constructor` 注册给官方 Evaluator，再调用官方 `evaluate_simulation`。它不重写 reward。
- `user_sim_check.py`：构造 tau2 官方 Agent、User Simulator 和 Orchestrator，但把 completion 替换成固定 Mock 回复，验证消息路由和隐私隔离；不会联网。
- `deepseek_client.py`：有限额、无自动重试的 DeepSeek API 客户端。真实调用入口在 `scripts/stage0_deepseek_smoke.py`，它把这个客户端注入官方 Agent 和 User Simulator。

建议按“入口 → 函数 → 返回类型 → 下游调用”阅读，而不是从上游 Fork 的几百个文件开始。例如先打开 `stage0_smoke.py`，看到 `load_retail_task` 后跳进 `task_loader.py`，沿着 `RetailTask` 和 `RetailSnapshot` 看下一步。

### 数据库具体放在哪里、如何创建和维护

本项目的四份 AReaL 初始 Retail 数据库是 JSON 文件，不是 SQLite，也不是单独启动的数据库服务器：

```text
data/raw/
└── tau2_rl_database/
    ├── tau2_retail_new_db_1.json
    ├── tau2_retail_new_db_2.json
    ├── tau2_retail_new_db_3.json
    └── tau2_retail_new_db_4.json
```

每条任务的 `db_path` 是**相对于 `data/raw/` 的路径**，例：

```text
tau2_rl_database/tau2_retail_new_db_4.json
```

程序先解析为 `data/raw/tau2_rl_database/tau2_retail_new_db_4.json`，校验它仍在数据根目录内，再用 tau2 的 `RetailDB` 模型校验 JSON。仓库审计确认 4 个快照分别被 96、64、186、217 条 Retail 任务引用。

JSON 快照顶层有 `users`、`products`、`orders`。比如其中一份快照包含 1,500 个用户、50 个商品、3,941 个订单。`RetailDB` 被读取成 Python/Pydantic 对象；调用工具时修改的是内存里的**深拷贝**。每个新 Episode 重新从原始 JSON 载入/构建初态，原始下载文件不被回写。文件 SHA256 用来证明源文件没变，内容哈希用来比较环境状态。

另一个容易混淆的目录是 `external/tau2-bench/data/`。`TAU2_DATA_DIR` 指向它，为 tau2 自己提供 Retail 政策、默认数据库、用户模拟规范等上游资源。**它不是** AReaL 任务的 `db_path` 根目录。本项目的 AReaL 快照仍从 `data/raw/` 按每条任务路径读取。

### `db_path` 和 `user_scenario` 原始数据长什么样

每行 RL JSONL 是一条 JSON 对象。以下只展示实际字段形状，所有文本值都替换成占位内容；真实场景可能包括身份信息和隐藏目标：

```json
{
  "id": "retail_示例编号",
  "description": {
    "purpose": "公开任务类别说明",
    "notes": "可选备注",
    "relevant_policies": ["上游政策标识"]
  },
  "user_scenario": {
    "persona": "客户画像或附加信息",
    "instructions": {
      "domain": "retail",
      "reason_for_call": "客户为什么联系商店",
      "known_info": ["客户一开始知道/愿意提供的信息"],
      "unknown_info": ["客户不知道的信息"],
      "task_instructions": ["客户应如何逐步回应、确认或结束"]
    }
  },
  "evaluation_criteria": "{... JSON 字符串 ...}",
  "db_path": "tau2_rl_database/tau2_retail_new_db_4.json"
}
```

几个字段的含义：

- `id`：数据集中任务的唯一标识，例如 `retail_131`。
- `description`：任务描述元数据；`purpose` 解释目标类别。
- `user_scenario`：客户模拟指令。`known_info`/`unknown_info` 和 `task_instructions` 用来控制客户如何透露信息。**它的部分内容是隐藏条件，给 User Simulator，不能整块塞进 Agent prompt。**
- `evaluation_criteria`：这里原始类型是字符串，字符串内部再编码 JSON。`task_loader` 先 `json.loads`，再交给 tau2 的 Pydantic `Task` 校验。解码后的字段有 `actions`、`communicate_info`、`env_assertions`、`nl_assertions`、`reward_basis`。它只供评分/受控验证，不能给 Agent 看。
- `db_path`：告诉系统这条任务该从哪个 Retail 初始状态开始，不是对话文本，也不是数据库内容本身。

对应的 SFT JSONL 记录大致包含 `messages`（历史消息）、`answer`（assistant 本回合的文字或工具调用）和 `metadata`（对话来源、turn 序号等）。SFT 记录多是对话回合；RL 任务记录则是任务、用户场景、评分目标和数据库引用。两者不能把一行简单当成同一种样本。

### 代码和测试怎么配对读

| 先看生产代码 | 再看测试 | 测试要保护什么 |
|---|---|---|
| `task_loader.py` | `test_task_schema.py` | criteria 字符串解码、schema 错误、非法 db_path |
| `db_adapter.py` | `test_db_isolation.py` | 独立副本、reset 后哈希一致、源 JSON 未变、错快照被拒绝 |
| `evaluator_adapter.py` | `test_evaluator_integration.py` | 官方参考/预测环境使用同一快照，错误初态不会被接受 |
| `user_sim_check.py` | `test_user_simulator.py` | 工具观察路由正确，用户私有内容不泄漏给 Agent |
| `deepseek_client.py` | `test_deepseek_budget.py` | 超预算、超时、错误响应不自动重试，费用预留保留 |

入口脚本的定位：`stage0_audit.py` 审计原始数据；`stage0_smoke.py` 跑确定性参考夹具与评分；`stage0_user_sim_smoke.py` 跑 Mock；`stage0_deepseek_smoke.py` 跑已授权的真实模型对话（会收费，当前报告存在时会拒绝重跑）；`stage0_replay.py` 回看已保存真实轨迹并可离线复评；`stage0_linux_revalidate.py` 做本次小规模 Linux CPU 检查；`stage0_bootstrap.py` 建立固定依赖环境。
