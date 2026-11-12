# 架构与目录

免费本机版的正式入口是 `runteams_core.application.community`，安装后命令为 `runteams-community`。HTTP 宿主、资料存储和同一套业务界面共同提供对话、员工、流水线与文档功能。

| 路径 | 职责 |
| --- | --- |
| `runteams_core/` | 本机业务、身份、存储、HTTP 接线与文档模型 |
| `runteams_core` 内的业务分包 | 模型、对话、员工、流水线、文档、配置、存储与工作执行按真实职责归类，见[核心模块目录](core-domains.md) |
| `runteams_creator_dev/` | 独立 SDK 开发工程的命令实现 |
| `sdk/` | 公共 SDK、MCP 宿主、合同和消费者测试 |
| `web/` | 两版共用的业务 UI 与随包静态资源 |
| `frontend/` | 富文档编辑器、资源查看器的前端源码与构建工程 |
| `contracts/` | 业务合同、资源清单和运行时锁 |
| `desktop/` | macOS 壳、自包含打包与签名 |
| `agent_skills/`、`builtin_skills/` | 产品技能与保留原许可的内置技能 |
| `runtime/` | 原生辅助运行时源码 |
| `tests/` | 自动检查使用的测试和确定性夹具 |
| `tooling/` | 工具清单及检查所需的 JavaScript 锁 |
| `requirements/` | Python 运行与构建依赖 |
| `docs/legal/` | 许可解释、第三方说明与清单 |

## 运行与资源

开发源码、已安装 wheel、原生 App 都从自己的明确资源根读取 UI 和合同。wheel 将资源放在 `runteams_core/_resources`；App 携带自己的 Python、Node 和编译器。用户资料位于安装目录之外。

文档使用 React／BlockNote 编辑器、本机内容模型和不可变修订。编辑器前端在 `frontend/rich-document`，发布静态资源在 `web/rich-document`。

员工的采样数量、请求预算等执行策略由脚本维护。配置页只呈现需要使用者提供或决定的项目资料与外部接入项。内部候选记录和巡检台账由员工通过 `runteams_employee_document` 按稳定文档标识创建、读取和修订，不要求使用者选择集合或存储位置。文档归属由宿主绑定的员工身份决定，跨对话和源码更新保持；更新使用原文档修订，冲突须重读合并。跨岗通过真实文档链接与工作汇报交接，各岗只修改自己的文档。

侦察、巡检等工作正常完成但没有可推进的产出时，可以将对应完成位置设为 `records_only: true`。看板不显示该完成列与已完成卡片，执行记录、报告和结构化提交仍保留；普通完成、失败、等待处理和已放弃的任务不应因此消失。此设置只适用于 `kind: done`，属于流水线定义，不依赖窗口的隐藏分组偏好。已有候选的证据不足或否决结果应保留其处理路径，不能混入无候选的记录位置。

共用业务与 UI 只在本仓库维护。官方账号、云服务与收费代码不进入免费源码依赖；私有工程通过精确固定的核心 wheel 组合官方扩展，不复制共用实现。

共享 UI 通过通用宿主接口接入身份、设置和页面扩展，不判断发行版，也不内置隐藏的商业页面。代码归属、接口及源码／产物检查见[界面宿主边界](ui-host-boundary.md)。

## 仓库边界

源码、锁文件、必要的编译后静态资源和测试夹具进入 Git。Python／Node 安装目录、构建缓存、App／DMG、个人数据库、凭据和单次验收记录留在 Git 之外。生成的静态资源必须与其前端源码及许可一起更新。

不要为一次性的截图或调试记录添加新的正式命令。维护者工具归 `runteams_core.devtools`，修改后更新 `tooling/commands.json`。目录调整必须同时更新真实调用者，不保留旧路径转发。仓库根目录保留项目文档和构建配置；核心包根只保留公开类型入口，业务模块按领域维护。仓库检查拒绝在仓库根或核心包根新增散落的业务文件。

返回 [项目首页](../README.md)。

Task-specific application identifiers and client settings belong to the task detail panel, never a shared pipeline employee configuration. Non-secret pipeline parameters with `source: user` and `display: setup` form this task configuration. Values stay in the native task input, obey declared position visibility, and survive subsequent visits. Saving uses the exact frozen task revision, does not run or resume work, and cannot rewrite an admitted run or a completed task. Shared configuration is reserved for team service connections and credentials.

Task configuration sections use the parameter definition’s optional `group` title and the same configuration section/field components as pipeline settings. Do not replace meaningful group titles with a fixed “Task configuration” wrapper. Frozen tasks retain their field/value contract; a missing presentation group may use a current declaration with the same key and type.

Configuration field markers and information hints come from declarations (`required`, conditional `required_when`, `note`, and `constraints`). Conditional markers explain when a field is needed and allow staged setup; they must not turn an unused integration into a mandatory dependency. Task configuration edits validate declared value limits in the native save API and show field errors without echoing submitted values. Missing legacy field metadata can inherit from a matching current declaration; the effective declarations participate in the save revision to reject concurrent rule changes.

员工设置、岗位设置、流水线设置与任务详情的同类元素必须只有一个实现。抽屉头部与折叠组使用 `employee-drawer-header.js/css`，配置字段、说明图标、必填标识、限制及字段错误使用 `configuration-fields.js/css`，配置组、表单、保存栏、草稿比较和保存／回执状态使用 `configuration-form.js`。普通字段默认使用同一说明图标；通用字段样式不得放回员工或任务专用样式表。面板只适配字段定义、作用域、权限、存储、API 和专有业务；不得复制公共 HTML、CSS 或另写一份保存状态流程。任务值仍归当前任务，团队凭据仍归团队配置，凭据入口及资源授权保留专用处理。修改公共组件必须通过 `tests/configuration_form.test.cjs` 的四入口一致性与异常恢复检查，以及任务保存协议检查；两项已纳入核心 CI。

流水线面板不使用浏览器原生 `details/summary` 三角折叠。错误信息直接显示在相关状态旁；岗位下游、流转规则与交接字段按标题分组直接展示。需要折叠的内容分组继续复用公共抽屉组件。
