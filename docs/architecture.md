# 架构与目录

免费本机版的正式入口是 `runteams_core.community`，安装后命令为 `runteams-community`。HTTP 宿主、资料存储和同一套业务界面共同提供对话、员工、流水线与文档功能。

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

共用业务与 UI 只在本仓库维护。官方账号、云服务与收费代码不进入免费源码依赖；私有工程通过精确固定的核心 wheel 组合官方扩展，不复制共用实现。

## 仓库边界

源码、锁文件、必要的编译后静态资源和测试夹具进入 Git。Python／Node 安装目录、构建缓存、App／DMG、个人数据库、凭据和单次验收记录留在 Git 之外。生成的静态资源必须与其前端源码及许可一起更新。

不要为一次性的截图或调试记录添加新的正式命令。维护者工具归 `runteams_core.devtools`，修改后更新 `tooling/commands.json`。目录调整必须同时更新真实调用者，不保留旧路径转发。仓库根目录保留项目文档和构建配置；核心包根只保留公开类型入口，业务模块按领域维护。仓库检查拒绝在仓库根或核心包根新增散落的业务文件。

返回 [项目首页](../README.md)。
