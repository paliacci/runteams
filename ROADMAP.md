# RunTeams.ai Roadmap

最后更新：2026-08-23

产品边界以 [`PROJECT_MEMORY.md`](PROJECT_MEMORY.md) 为准，数据与运行契约以
[`ARCHITECTURE.md`](ARCHITECTURE.md) 为准。本文件只记录尚未完成的产品优先级，不重复保存实现细节。

## 唯一成功标准

> 用户把真实任务交给 RunTeams 后，系统能在无人盯守时到达最终交付，或停在一个原因明确、可以继续的人工决策点。

员工是用户组织和复用能力的主要单位；员工技能是整体选用的专业工作资产，Package 只负责内部存储与分发；EmployeeRelease 和 WorkflowRun
分别保证员工行为与一次工作的可复现性。

## 已完成的产品骨架

- [x] Package、PackageRevision、Employee、EmployeeRelease、Pipeline、Task、WorkflowRun、
  EmployeeRun、Artifact、Event 十个核心业务实体
- [x] Agent Skills 目录导入、内容寻址、不可变对象存储和真实 healthcheck
- [x] Employee 草稿整体选择员工技能，发布时冻结精确 PackageRevision、digest 和全部内部资源
- [x] 图式 Pipeline 编排、条件分支、汇合、返工环与启动时不可变 Workflow 快照
- [x] 人工审批环节、流水线暂停/恢复、运行前检查和任务级交付文件聚合
- [x] `runteams.work-order/v1`、`runteams.work-result/v1` 和 MCP 交接协议
- [x] 进程组取消、超时、崩溃恢复、有界重试和稳定岗位工作区
- [x] `needs_human`、`blocked`、`failed` 派生的统一“待你处理”
- [x] 正式团队、流水线、任务、员工技能和运行 UI 接入核心事实源
- [x] Prompt-first 自动化，通过正式核心动作合同创建和运行任务
- [x] Codex 与 Claude Code Agent Channel，以及渠道原生插件、Skill、MCP 资产盘点
- [x] 员工技能与渠道扩展分层：Chat 只用渠道扩展，员工整体绑定技能并显式绑定工作工具
- [x] 移动端核心 Workflow 投影、加密同步、通知和白名单控制
- [x] 旧 Worker/Card 运行时、数据库、协议、UI 和兼容测试物理删除

## P0：员工与能力组合闭环

这是当前最优先的产品工作。完成它之前，不扩张更多 Agent Runtime 或扩展格式。

### P0.1 凭据合同

目标：用户能清楚看到某项能力需要什么凭据，并显式绑定；没有绑定时不能误报为可运行。

- [x] Package tool Capability 使用最小 `credentials: [Key]` 合同，不增加映射表或重复元数据
- [x] EmployeeRelease 冻结凭据 Key 声明，不保存凭据值
- [x] 发布和任务启动前验证必需凭据；缺失时明确指向设置 → 凭据
- [x] 运行时只向声明该 Key 的冻结能力注入对应值，并在能力结果入库前脱敏
- [x] UI 显示能力所需 Key、缺失/就绪状态，以及已发布员工和待发布员工的使用关系
- [x] 删除凭据后，受影响的能力立即显示缺失，员工不能重新发布或启动新任务

### P0.2 员工技能真实性与透明度

目标：UI 中出现的每个 RunTeams Package 工具都能在当前桌面运行环境中执行。

- [x] 零外部依赖 Python 工具使用 RunTeams 自带 Runtime
- [x] 导入时拒绝路径越界、符号链接、缺失入口和无 healthcheck 的可执行工具
- [x] 发布 Employee 时重新验证并冻结精确能力包版本
- [x] 运行时只从不可变 PackageRevision 物化能力
- [x] 在正式 UI 展示每次验证的时间、结果、运行器和失败证据
- [x] 对运行环境变化提供“重新验证”，不修改原 PackageRevision 内容
- [x] 导入一个真实公开 Agent Skill 仓库作为首个外部兼容样本，并固定回归夹具
- [x] 明确区分渠道原生插件/Skill 与 RunTeams Package；不能把“发现”显示成“已绑定”

### P0.3 员工组合体验

目标：普通用户只操作员工，就能理解这名员工会什么、为什么能运行、当前发布与草稿有何差异。

- [x] Employee 原地编辑草稿并显式发布不可变版本
- [x] 同一 Employee 可复用于多条 Pipeline，岗位不复制员工身份
- [x] 草稿用同一内部数组整体选择员工技能或当前渠道工作工具，不增加绑定表
- [x] 发布时冻结 Agent Channel、程序与能力版本
- [x] 员工详情同时展示职责、固定程序、能力、渠道、当前发布和待发布变化
- [x] 员工技能更新后明确提示哪些员工可升级；不自动改变运行中的 Workflow
- [x] 提供删除/停用 Package 前的影响预览，避免留下不可解释的 Employee 草稿
- [x] 用一个“创建员工→选能力→发布→放入流水线→完成任务”的首次使用流程做可用性验证

## P0：可靠工作与交接

### P0.4 运行可靠性

- [x] Task 只编译一次 WorkflowRun，运行只读取冻结快照
- [x] Employee 间只通过 WorkOrder、WorkResult 和 Artifact 交接
- [x] 应用重启后恢复未完成岗位，不重复已完成上游岗位
- [x] 用户补充信息与阻塞重试只进入对应下一次岗位 WorkOrder
- [x] 取消会终止 Agent 进程树，晚到结果不能覆盖取消状态
- [x] 为 `effect=operation` 的能力完成跨进程 invocation id 幂等验证
- [x] 覆盖“写入已成功但结果回执丢失”的恢复场景，禁止盲目重放副作用
- [x] 建立 Codex、Claude Code 的 CLI 版本兼容测试矩阵
- [ ] 用至少两小时的真实任务验证取消、断网、限额、应用重启和继续执行

### P0.5 人工处理与交付

- [x] Workflow 和 Automation 的待处理事项都由底层事实派生，不新增 intervention 表
- [x] 用户可以补充信息、重试、终止，并回到原 Workflow
- [x] 运行详情展示岗位、步骤、结果和 Artifact
- [x] 待处理详情统一显示系统已经尝试过什么，以及继续后从哪里恢复
- [x] Artifact 提供一致的打开、预览和导出体验
- [x] 建立失败原因统计，但不新增可由 Event 推导的业务状态字段

## P0 验证门槛

工程完成不等于产品成立。进入 P1 前必须取得以下证据：

- [ ] 选定 3 条真实流程，每条完成至少 30 次端到端运行
- [ ] 至少 95% 的运行到达最终交付或明确人工关口，不静默卡死
- [ ] 应用或 Agent CLI 中断后的可恢复运行成功率达到 99%
- [ ] 因重复领取或重放造成的重复外部副作用为 0
- [x] 所有 UI 中显示“可运行”的 Package 工具都通过当前环境真实验证
- [ ] 新用户能在 10 分钟内完成首次员工发布和第一条任务
- [ ] 20 名目标用户试用 14 天；至少 8 人完成 3 次真实运行，5 人复用同一流程，4 人愿意付费

北极星指标：同一用户每周重复运行、并自动到达交付或明确人工关口的 Workflow 数量。

## 推荐实施顺序

1. 把能力验证证据完整展示到正式 UI。
2. 接入一个公开 Agent Skill 作为唯一外部兼容样本。
3. 打磨员工草稿、发布、能力升级和影响预览。
4. 用 3 条真实 Workflow 持续 dogfood，优先修可靠性问题。
5. 达到 P0 验证门槛后，再决定模板、触发器和更多渠道。

## P1 候选

只根据 P0 真实试用中最常见的阻塞排序：

- 官方与个人 Employee/Pipeline 模板
- Webhook、GitHub、邮箱、Slack、Notion 或文件到达触发
- Pipeline 版本比较和克隆
- Workflow 完成率、人工介入次数和失败原因分析
- 有限、可查看、可编辑、可删除的跨运行员工经验
- 第三个完整 Agent Runtime

## 暂缓

- 裸 LLM API、OpenAI-compatible API 或自建通用 Agent Loop
- 公开社区扩展/流水线商店和 URL 一键安装
- 同时兼容多种外部扩展包格式
- 重度可视化流程画布
- 多用户组织、复杂权限和团队计费
- 自建云端 Agent 执行环境
- 通用知识库、无限记忆和完整 RAG 平台
- 大而全的成本或 BI 仪表盘

## 决策门

横向扩张前必须同时回答：

1. 用户是否反复把真实任务交给 RunTeams？
2. RunTeams 是否显著减少盯守、协调和返工？
3. 跨 Agent Channel 的 Employee Workflow 是否比单一厂商原生能力更有价值？
4. 用户是否愿意为可靠性和复用能力付费？

如果答案还不成立，就继续修员工、能力与交接闭环，不用新功能掩盖核心问题。
