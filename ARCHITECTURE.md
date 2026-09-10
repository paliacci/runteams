# RunTeams.ai 核心架构 v3

RunTeams.ai 是完整 Agent Runtime 之上的员工与工作协议层。Codex、Claude Code 等负责单个
Agent 如何思考和使用原生工具；RunTeams 负责员工身份、能力组合、发布、派工、交接、恢复和审计。

## 一、四个核心单位

| 单位 | 产品含义 | 稳定性 |
|---|---|---|
| Employee | 用户创建、理解和复用的 AI 员工 | 草稿可编辑 |
| Employee Skill | 员工可以整体使用的一项专业工作能力 | 草稿只引用稳定身份 |
| Package | 员工技能的内部存储、分发和来源单位 | PackageRevision 不可变 |
| EmployeeRelease | 真正参与工作的员工版本 | 发布后不可变 |

Employee Skill 不单独建业务表，一项 Package 就是一项用户可见的完整员工技能。Employee 草稿只引用
`package_id`；包内的 Skill 文档、脚本和确定性工具属于不可变 PackageRevision 的内部资源，不能独立绑定。
渠道原生扩展作为员工工作工具时整体引用 `provider + plugin_id`。两种引用继续共用 Employee 内部的
`capabilities` 数组，不增加绑定表或第二套依赖模型。

流水线中的岗位不是员工副本。岗位只表达“这名员工在这条流程中的位置”，同一名员工可以被多个
流水线复用。

## 二、十张核心表

```text
packages              能力包的稳定身份与来源
package_revisions     内容寻址的不可变包版本
employees             员工身份与当前草稿
employee_releases     不可变员工发布版本
pipelines             岗位和交接关系组成的完整定义文档
tasks                 一件需要处理的工作
workflow_runs         一次任务执行及其冻结快照
employee_runs         一名员工处理一个岗位的一次尝试
artifacts             员工或 Agent Chat 组织的不可变文档与产物
events                所有进展、步骤、能力调用和状态变化
```

不因为一个概念有名字就为它建表。岗位、边、工作单、工作结果、阻塞和人工请求分别是完整文档或
运行事件，不额外拆表。兼容性、就绪度和“已验证”是根据不可变清单与当前环境计算出的结果，不作为
可漂移的业务事实保存。

关系型字段只承担身份、关联、查询和强约束；内部结构高度内聚、通常整体读写的内容使用 JSON 文档。

## 三、五份稳定契约

- `runteams.package/v1`：包格式、文件摘要和包内能力声明。
- `runteams.employee-draft/v1`：职责、固定程序、能力引用和 Agent Channel 选择。
- `runteams.employee-release/v2`：员工语义、完整员工技能与渠道工具版本的不可变编译结果。
- `runteams.work-order/v1`：目标、上下文、输入、预期输出和验收标准。
- `runteams.work-result/v1`：状态、摘要、结构化输出、产物和问题。

用户和 UI 操作 Employee；运行器只接受 EmployeeRelease 与 WorkOrder。上游聊天记录不是下游接口，
员工之间只能通过 WorkOrder、WorkResult 和显式产物交接。

文档是结果层，不另建一套“Agent 文档”数据库。员工运行产物继续以 `employee_run_id` 归属运行；
Agent Chat 组织的文档使用同一 `artifacts`/revision 链，但 `employee_run_id` 为空，并在 `meta_json`
中记录稳定的 `document_key`、`source=agent_chat` 和可选的命名数据视图。正文由 Agent 组织，事实
由内核提供：数据视图只能引用产品已命名的投影（当前为 `opportunities`），禁止 SQL、任意文件路径
或第二事实源。读取通过 `runteams_list_documents` / `runteams_get_document`，变更先由
`runteams_propose_document` 形成提案，普通对话确认后应用；自动化在其授权运行内自动应用。
所有变更仍走不可变 artifact revision，因而文档列表、历史版本、导出和回收站保持同一套行为。

文档之间的引用使用稳定的应用内链接：Agent 工具返回 `internal_link=runteams://document/<id>`，正文渲染
时转换为 `/docs?document=<id>` 并在新窗口打开；旧的 `artifact://<id>` 仍兼容。打开文档会同步地址栏，
目标不存在或已进回收站时只提示并回到文档目录，不把内部引用交给外部站点。

## 四、两次编译

### 发布员工

```text
Employee Draft
  + active PackageRevision / installed channel extension
  + Agent Channel 配置
  + 结构检查、真实能力自检与本机凭据就绪检查
  → immutable EmployeeRelease
```

发布会重新运行所有 RunTeams 工具的 healthcheck，确认其声明的凭据 Key 已在本机保险箱填写，并解析
员工显式选择的渠道扩展。渠道扩展只冻结 provider、plugin id、版本与内容指纹，不保存本机路径；缺失、
被停用、无法独立加载或与员工渠道不匹配时拒绝发布。相同内容产生相同 digest，凭据值不进入发布快照。

### 启动工作

```text
Pipeline Definition
  + active EmployeeRelease
  + Task Payload
  → compiled WorkflowRun snapshot
```

一次执行周期开始后只读取已编译快照。员工草稿、员工技能新版本、流水线后续修改以及任务编辑都不能
改变正在进行或已经留下的员工运行。只有用户在任务终态后显式“重新运行”时，系统才比较当前 Task 与
该周期的任务快照：没有变化就从失败岗位恢复；任务已修改则只重新编译 Task 部分、记录
`workflow.task_recompiled` 事件，并从起始岗位重新走完整流水线。旧 EmployeeRun、WorkOrder、结果与产物
继续作为真实历史保留，Pipeline Definition 与 EmployeeRelease 仍使用原 WorkflowRun 冻结版本。

## 五、员工技能与内部包格式

首个外部格式只接 Agent Skills：

```text
package/
  SKILL.md
  scripts/
  references/
  assets/
  runteams.json       # 可选：RunTeams 的确定性工具声明
```

`SKILL.md` 是主流兼容入口；`runteams.json` 只补充外部规范没有表达的可执行契约：入口、runner、
effect、healthcheck 和所需凭据 Key 列表。凭据使用同名 Key 绑定，不增加映射表、用途字段或输入类型
副本；厂商特有元数据保留在 `manifest.extensions`，不得污染员工或工作流字段。

导入时拒绝符号链接和越界路径，限制文件数与总大小，计算整棵目录的 digest，复制到内容寻址对象库，
再从该不可变副本执行 healthcheck。首版只接受使用 RunTeams 自带 Python、零外部依赖的确定性工具；
这保证 UI 里显示的工具在桌面 App 环境中确实能运行，不依赖用户 shell、全局 site-packages 或临时
虚拟环境。

以后需要第三方依赖时，只增加一种机制：按 `package digest + platform + runtime version` 构建并缓存
受管环境。安装发生在导入/准备阶段，任务开始时只做确定性命中和预检，绝不在工作过程中临时 pip
install，也不为每名员工复制环境。

## 六、Agent Runtime 边界

核心不包含模型 API 或自建 Agent Loop。运行入口固定为：

```text
EmployeeRelease + WorkOrder
  → Agent Channel adapter
  → Codex / Claude Code 完整 Runtime
  → RunTeams MCP
  → WorkResult + Artifacts + Events
```

Agent 第一项动作必须通过 MCP 读取工作单，按发布程序顺序提交步骤。确定性工具只能通过
`run_capability` 调用；`effect=verifier` 的工具必须在最终内容完成后通过。成功、请求人工和阻塞是
互斥终态。普通最终回复不作为提交结果。

每个岗位必须按 EmployeeRelease 冻结的 `runtime.channel` 选择 Agent adapter；执行器不能为整条
Workflow 预先固定某一家渠道，也不能在额度不足时偷偷切换渠道。Codex 与 Claude Code 共用同一员工
协议，仅使用各自官方 CLI 的 MCP 注入格式。渠道不存在、被停用或协议不兼容时，在 Agent 启动前失败。

员工运行不继承该 CLI 的全部用户扩展。适配器隔离用户配置，只加载 EmployeeRelease 显式冻结的渠道
扩展；每次启动重新解析内容指纹，扩展升级或被替换后要求重新验证并发布。普通 Agent Chat 只继承和选择
当前渠道原生扩展、附件与临时上下文，不能选择、物化或执行 RunTeams 员工技能。员工技能只在发布员工后
进入 Employee Runtime；内部工具统一通过员工协议的 `run_capability` 调用和凭据边界执行。

Employee Bot 会话是持久的员工身份外壳，而不是另一种员工运行器。`chats` 对这类会话长期记录
`subject_type=employee` 和 `employee_id`，不会因员工重新发布而拆分成新会话；每轮使用的
`employee_release_id/digest` 仅作为最近版本摘要，消息和 WorkflowRun 各自保存不可变来源。
会话作用域 `scope_type` 可为 `global`、`pipeline` 或 `run`，只限制可解释的事实集合，不改变核心执行权限。

Bot 收到的是 `runteams.bot-context/v1` 有界只读投影（员工职责、发布版本、流水线运行、员工
结果和已登记产物），并带稳定的 `workflow_run:<id>` 引用。凭据、无关员工、任意文件和隐藏
推理永不进入投影。对话中的“再做一次/修改”必须转成显式 Task 或 WorkflowRun，由现有的
EmployeeRelease + WorkOrder 运行链执行；Bot 对话官方线程与流水线 EmployeeRun 的工作区、
记忆、取消和重试状态彼此隔离。

长期记忆读取不另建向量索引：`runteams_get_bot_context` 只按绑定员工和显式的
`run_id/task_id/pipeline_id/state` 做可复现的结构化筛选，事实来源固定为 WorkflowRun、Task、
EmployeeRun、Artifact 与 Event。返回的 retrieval 元数据记录过滤条件和边界；精确运行需要更深
细节时再沿 `workflow_run:<id>` 使用任务读取工具，避免相似度召回把负相关工作混进上下文。

当用户在 Bot 对话中确认“交给这个 Bot 处理”时，应用层会把最新一条已完成工作从上述有界投影
编译为 WorkOrder 的显式 `context.bot_memory` 交接，并保留 `upstream_position`/
`upstream_output` 信号。新任务的用户输入优先；来源上下文只补齐缺失字段，身份键会重新生成，
避免把新交办错误去重到来源任务。这样员工运行读取的是冻结任务载荷中的平台事实，而不是聊天
线程、全局历史或工作区外文件；没有可用历史时仍按普通新任务运行。

Agent Runtime 保留其原生文件、Shell、搜索和编辑能力。RunTeams 只治理工作目录、进程树、超时、
取消、确定性能力调用与审计，不建立第二套通用工具循环。通用 `runner.py` 只承担 Agent CLI 的进程
生命周期，不解析 Employee、Package、Pipeline 或 Task，也不注入历史 Card 工作区和项目凭据。
Agent CLI 兼容性不按版本号猜测：启动前根据各渠道实际 `--help` 对 RunTeams 使用的命令参数做能力
握手，缺少任一必需能力就标记为不兼容并阻止启动。版本号只用于向用户展示；Codex JSONL 与 Claude
stream-json 的已知事件形态由固定解析矩阵回归，新增事件只能向后兼容，不能静默降低为纯文本成功。
凭据是独立、扁平的本机保险箱。Package 的 tool 能力只声明 Key 名；EmployeeRelease 冻结该声明但
绝不保存值。运行时按工具逐次解析同名 Key，只向该工具子进程注入声明值，去除其他环境秘密，并在
结果进入 Event 或运行记录前替换凭据明文。Skill 不能声明运行时凭据；需要凭据的动作必须是受控 tool。
`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 和 `CODEX_ACCESS_TOKEN` 属于 Agent Runtime 登录边界，能力包
不得声明或注入，避免把订阅 Runtime 偷换成模型 API。

## 七、执行与恢复

`workflow_runs.snapshot_json` 冻结整次工作；`employee_runs` 是唯一员工执行事实。每名员工的输入和
输出都是完整契约文档。步骤、进展、能力调用和终态都进入 Event 流；状态可以由事实推导时不重复
存储。

PipelineDefinition 以 `positions` 保存稳定展示顺序，以 `edges` 保存真实执行路由。边可用 `when` 区分
完成、异常、自定义结果以及审批通过或打回；多个上游可以汇合到同一岗位，边也可以返回上游形成返工环。
WorkflowRun 用持久化 `cursor_key` 记录下一执行环节，审批环节进入 `needs_approval`，流水线暂停后保留
当前位置，恢复时从原处继续。每次运行最多经过 50 个环节，防止错误配置形成无限循环。

同一文档还可保存可选的 `states` 视图列（待定、完成、放弃或自定义状态）。状态列不参与执行路由，
不创建 Node/Card 表，只把 Workflow 的真实结果投影到看板。

应用重启时，从最后一个没有成功终态的 EmployeeRun 恢复；已经完成的上游员工不重跑。operation
能力用 invocation id 幂等，diagnostic/verifier 证据绑定最终工作区内容。

WorkflowRun 由单机执行器用 SQLite 写事务从 `ready/waiting_retry` 原子认领为 `running`；同一 Task
只编译一次 WorkflowRun。失败尝试保留为 EmployeeRun，并以 `available_at` 持久化有界退避；新尝试
收到且只收到最近一次失败的 `recovery_context`。进程异常退出后，启动恢复把仍在 `running` 的尝试
标记为 `interrupted` 并重新入队，继续使用该流水线岗位的稳定工作区。首版只有一个本地执行器，因而
不增加分布式 lease、scheduler 或队列表。

Agent CLI 的限额和瞬时断网属于外部等待，不记为员工业务失败：当前 EmployeeRun 记为
`interrupted`，WorkflowRun 持久化为 `waiting_retry`。可解析的官方额度重置时间直接写入现有
`available_at`；无法解析时使用有界退避。外部等待不消耗业务失败预算，恢复后仍从同一岗位和工作区继续。

取消同时写入 WorkflowRun、Task 和当前 EmployeeRun，并触发 Agent Runtime 的进程树取消信号；运行时
晚到的结果不能覆盖 `canceled`。`completed/blocked/needs_human/failed/canceled` 是 WorkflowRun 终态。
人工重试通过显式状态转换重新进入 `ready`：未编辑 Task 时不改变快照并从失败岗位恢复；Task 已编辑时
按上节的显式重新编译边界从起始岗位重新运行。员工请求人工时，问题留在
该 EmployeeRun 的 WorkResult；用户回复作为 `workflow.human_responded` Event 记录，下一次同岗位
WorkOrder 只接收与该尝试匹配的 `human_response`。阻塞重试同样只接收最近一次阻塞的
`recovery_context`，不新增人工请求表或回复字段。

统一“待你处理”同样只是读模型。核心服务从处于 `needs_human/blocked/failed` 的 WorkflowRun 及其最新
EmployeeRun/WorkResult 派生条目，不创建 intervention 记录；条目消失只意味着底层工作流状态已变化。
自动化失败同样不创建 intervention 记录：正式列表从每项已启用自动化的最新失败 AutomationRun 派生，
重试产生新的 queued run、暂停关闭 schedule 后，条目会随底层事实自然消失。自动化 Agent 只能通过核心
动作合同创建 Task/WorkflowRun，不能创建旧 Card/RunChain。桌面点击核心条目直接打开原 WorkflowRun
详情；移动端通过 `workflow:<id>` 或以失败 run id 组成的 `automation-intervention:<id>` 不透明目标操作，
并在执行前根据当前事实重新校验允许动作。旧 Card 干预不得进入默认产品入口。

移动快照只读取核心库：顶层运行集合是 `workflows`，流水线结构是 `positions → tasks`，员工、岗位与任务
字段使用 `employee/position/task` 语义，不保留 `Worker/Node/Card/RunChain` 兼容字段。手机待办只允许
操作派生的核心 Workflow 或 Automation 条目；运行控制只允许终止 `workflow:<id>`，因为核心没有暂停/
继续语义。移动端不得展示一个服务端无法真实执行的控制按钮。

正式本地外壳由 `product_store.py` 所有，只保存凭据元数据、Agent Channel、通用/Employee 对话和移动
Relay 台账；自动化的 schedule、run、结构化工作记录、恢复和派生待处理统一由 `automation_store.py`
所有。核心业务资产仍只进入独立 core 数据库。所有领域存储只共享 `local_database.py` 提供的单一数据库
路径、事务连接、进程锁和时间函数；该模块不含任何业务表或查询。旧 `store.py`、Workspace 托管层与
Worker/Card 运行时已经从仓库物理删除；生产导入与构建检查必须阻止这些模块名称重新进入桌面进程。

正式桌面进程只启动核心 Workflow 执行器和自动化调度器，不恢复或启动旧 Card 调度器。旧
Worker/Card/Node/Pipeline HTTP 路由及其墓碑响应已经物理删除；未知接口统一按普通 404 处理，不保留
查询参数、隐藏入口或回退逻辑。旧 `_execute_job`、Card `DurableScheduler` 类、聊天 Card 启动回退、
移动数字 intervention/RunChain/Worker proposal 命令、旧运行历史 GET/SSE 以及对应执行测试也已物理删除。
旧 Worker/Card MCP 入口不属于迁移或修复边界，不得打入正式桌面包；员工执行只使用
`--runteams-core-mcp` 和 `runteams_core.protocol`。正式构建必须检查 PyInstaller 模块清单，并在
任何已退役 Worker/Card 运行模块被静态收集时失败。

## 八、UI 透明度

UI 直接展示内核事实，不制造含糊的“可用”状态：

- 能力包：来源、digest、版本、文件、说明、工具入口和最近一次真实验证证据。
- 员工：职责、固定程序、所选能力、当前发布版本和冻结的包 revision。
- 流水线：岗位、员工发布版本和交接关系。
- 运行：每份 WorkOrder、每名员工的步骤/工具/终态、产物和完整事件。
- 追溯：事件账本带全局 hash chain、操作者/请求关联和 before/after；每次 Agent
  EmployeeRun 另留不可覆盖的 transcript 摘要（路径、大小、SHA-256、提示词摘要和可用的
  Provider 用量元数据）。请求 ID 等渠道未提供的字段保持缺失，不由平台猜造。
  /api/core/audit/{pipeline|task|workflow|employee}/{id} 直接从事件源重建时间线，实体
  清理后仍可凭墓碑事件复核。
- 文档：Agent 组织的叙述与数据库事实视图分开呈现；打开文档时重新读取绑定投影，避免把过期
  的机会结果复制进正文。

“已发现、已导入、已验证、已绑定、已冻结、当前环境可运行”是不同事实，界面不得合并成一个绿色
开关。

## 九、切换原则

`runteams_core/` 是业务内核的唯一实现，`product_store.py` 是桌面外壳存储的唯一正式入口。旧
Worker/Card/Pipeline 存储、协议、Workspace、验收、任务工具和维护运行时及其测试已从仓库物理删除；
不为新旧模型编写双向同步、兼容字段、墓碑路由或长期 repository adapter。

## 十、文档编辑器状态边界

文档编辑器也遵循单一事实源，而不是让宿主页面和编辑器各维护一份可写状态：

- ProseMirror 文档与选区是正文、块样式和光标的唯一事实源；段落、标题和列表项的样式进入节点属性并由
  schema 的 `toDOM` 渲染。
- 行左侧菜单只发出 `applyBlockStyle` 命令。宿主页面负责菜单展示、稳定目标签名和持久化回调，不直接改
  `.ProseMirror` 内的 DOM。
- 编辑器控制器统一处理单块、多块和列表项事务，并一次性发出 `onBlockStyleChange` 结果；指针事件只负责
  恢复实际点击的 ProseMirror 选区，不能再通过第二个 MutationObserver 把旧样式刷回去。
- 禁用会抢选区的虚拟光标运行时；菜单关闭、焦点转移和输入前的保护逻辑必须服务于同一个编辑器控制器，
  不得新增宿主级定时器或平行选区状态。
- 旧文档样式只在挂载完成时通过 `hydrateBlockStyles` 迁移一次。兼容代码不得成为常规渲染路径，避免对齐、
  颜色和多选列表在重绘期间互相覆盖。

## 十一、文档格式边界（迁移中的权威规则）

文档阅读器允许打开受支持的原始文本格式，但不再把它们在运行时偷偷改写成 Markdown：

- `artifacts`/revision chain 仍是唯一文档身份和历史来源；每个当前 revision 保留原始 `path`、字节和 `content_model`。
- `markdown` 使用原生富文本编辑模型；CSV/TSV 使用独立的 `table` 网格编辑模型。JSON 使用 `json` 预览，其他文本使用 `text` 预览，尚未接入编辑器的模型保持只读。
- 员工发布、阅读、搜索和下游交接都读取原始文件；格式适配不得出现在每次渲染或自动保存路径上。
- 未接入编辑模型的格式编辑请求在服务端拒绝，不能依靠前端按钮隐藏来保证边界；新增格式只能增加明确的模型读写实现，不能复用 Markdown 转换作为捷径。
- AI 与人类只能通过同一文档服务写入可编辑模型。不得用“同格式最新版”补偿多套事实来源。

这条迁移规则优先保证可追溯和可维护：所有格式都能打开，不代表所有格式都能直接编辑；新增格式必须先定义稳定模型、导入/导出边界和契约测试，再接入编辑器。
