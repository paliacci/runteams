# RunTeams

本机运行的 AI 员工与流水线工作空间。文档、对话和工作资料保存在本机，模型厂商与 CLI 由你自行配置。

这个仓库包含免费本机版、共用业务 UI 和 SDK。免费版无需 RunTeams 账号或 Supabase，不包含官方市场、订阅和自动更新。

## 从源码运行

需要 Python 3.12。在仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/runteams-community --port 8792 --open
```

资料默认位于用户应用资料目录，独立于安装目录；可用 `--data-dir /absolute/path/to/library` 指定其他资料库。运行已安装的包不需要保留源码。修改源码后重新安装。

macOS ARM64 自包含安装包携带 Python 和运行依赖，最低系统 macOS 13.5。当前原生构建已完成本机验收，正式签名、公证和公开下载尚未发布。免费版通过手动下载安装包升级。

## 开发与扩展

| 入口 | 内容 |
| --- | --- |
| [核心业务模块](docs/core-domains.md) | 应用、对话、文档、员工、流水线、资产与执行的代码归属 |
| [架构与目录](docs/architecture.md) | 模块归属、源码与生成资源的边界 |
| [开发指南](docs/development.md) | 环境、检查、SDK 开发包 |
| [桌面构建与发布](docs/releasing.md) | 自包含构建、签名和发行范围 |
| [SDK](sdk/README.md) | runtime、view、ui 与 MCP 宿主 |
| [贡献指南](CONTRIBUTING.md) | 提交方式、测试与授权约定 |
| [安全报告](SECURITY.md) | 私密漏洞报告渠道 |
| [变更记录](CHANGELOG.md) | 源码版本与发行状态 |

开发工具统一位于 `runteams_core.devtools`，完整命令清单见 [tooling/commands.json](tooling/commands.json)。官方账号、订阅、市场、官网与云服务在独立私有工程维护。

## 许可

RunTeams 产品源码采用 [RunTeams Source Available License 1.0](LICENSE)：允许内部商用和用产品交付付费成果，商业再分发或作为托管产品提供须另行授权。这是源码可用许可，不是 OSI 开源许可。

独立创作的员工、流水线、技能和成果可以商用。`sdk/runtime`、`sdk/view`、`sdk/ui` 保留 Apache-2.0；第三方材料保留各自许可。详情见 [许可说明](docs/legal/LICENSING.md) 和 [第三方声明](docs/legal/THIRD_PARTY_DOCUMENTS.md)。
