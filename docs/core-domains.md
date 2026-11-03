# 核心业务模块

`runteams_core` 按业务职责分包。包根只保留公开的 `ContractError`／`DocumentLossError` 类型入口；业务实现直接位于各自目录，子包初始化文件不转发其他模块。

| 目录 | 职责 |
| --- | --- |
| `application/` | 免费版入口、应用组成、原生启动；`http/` 承接本机 HTTP 路由 |
| `agents/` | 模型运行、提示与执行；`adapters/` 归 CLI 适配器，`models/` 归模型渠道，`environment/` 归环境绑定，`tools/` 归工具注册和传输 |
| `assets/` | 资产引用和不可变文件；`skills/` 归技能包，`collections/` 归集合格式 |
| `authoring/` | SDK 创作与定义；`source/` 归源码修订和导入导出，`compilation/` 归依赖与编译，`workers/` 归独立检查／构建子进程 |
| `automation/` | 计划存储、周期规则、调度和到期工作 |
| `configuration/` | 配置消费；`credentials/` 归凭据与脱敏，`connections/` 归连接交换和准入 |
| `conversations/` | 对话执行、附件、工作目录上下文和项目记忆 |
| `documents/` | 富文档、修订、资源、导出与文档工具 |
| `employees/` | 员工定义、上下文、工作约定与记录；`mcp/` 归程序执行和原生展示 |
| `pipelines/` | 流水线定义、依赖绑定、工作区和执行控制 |
| `storage/` | 本机库、SQLite 和持久化组成；`backups/` 归备份、恢复与保留策略 |
| `work/` | 工作账本、输入、资源绑定、报告与结果；`hosts/` 归执行和展示宿主 |
| `foundation/` | 共用类型、哈希、资源定位和列表游标；`identity/` 归身份引用，`transport/` 归本机通信基础 |
| `devtools/` | 工程检查、SDK 导出、编译打包和维护者命令 |

## 导入与入口

直接导入实际拥有实现的模块：

```python
from runteams_core.documents.document_export import export_document
from runteams_core.agents.models import model_channels
from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime
```

免费版命令仍为 `runteams-community`，实际 Python 入口是 `runteams_core.application.community:main`。环境启动器使用 `python -m runteams_core.agents.environment.agent_python`。工具 STDIO 传输使用 `runteams_core.agents.tools.agent_tools_mcp`，冻结产品复用现有的原生桥接模式。

SDK 检查／构建进程由 `authoring/workers/creator_worker_process.py` 中的正式清单定义。编译器来源摘要使用相对于包根的真实分域路径；安装包、SDK 开发包与托管验证准备使用同一批源码，不通过旧路径寻找文件。

## 维护规则

增加模块时选择实际业务所有者，跨业务的纯类型和基础通信才放入 `foundation`。不要把无关实现塞进一个公共工具模块。资源与实现一同放在拥有它们的子包，如 HTTP 资源登记表和员工 MCP 原生连接脚本。

目录归属在 `tooling/core-domains.json` 登记。仓库检查拒绝包根业务文件和未登记子包；源码检查拒绝不存在的限定模块、缺失的包成员和未限定的内部导入。变更目录时直接更新调用者、资源清单、worker 清单和构建来源，不增加模块转发或运行时别名。

参见 [整体架构](architecture.md)、[开发指南](development.md) 和 [发行指南](releasing.md)。
