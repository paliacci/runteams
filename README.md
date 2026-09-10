# RunTeams.ai

**让你的 AI，像团队一样工作。**

RunTeams.ai 是建立在完整 Agent Runtime 之上的、本地优先的 AI 团队编排平台。它连接你已经登录的 Claude Code、Codex 等 Agent，为它们安排岗位、流水线、交接、审批和可复用的工作方法。

RunTeams 不提供模型，不转售 Token，也不把成熟 Agent 降级成一个简单的文本 API。它负责把多个 Agent 组织成一条能够持续推进、暂停、恢复和交付结果的工作流。

## 当前状态

RunTeams Desktop 正在公测。核心产品计划以开源软件形式发布；官网提供经过验证的正式发行版、持续兼容维护和 Pro 增值能力。

开源核心保留完整的本地创建、运行、查看和导出能力。官方 Pro 方案计划提供签名发行版、稳定更新、兼容性维护、iPhone/iPad 移动伴侣、加密 Relay、推送和远程审批。移动伴侣与跨端服务不属于本仓库的开源核心。

## 核心能力

- **Agent Channel**：连接官方 Agent CLI，复用用户已有的订阅、登录状态和额度。
- **AI Employee**：为每个 Agent 定义职责、能力、交付物和完成标准。
- **Pipeline**：组织顺序、并行、分支、返工和人工审批。
- **持久运行**：保存任务、员工运行、事件、产物和冻结快照，应用重启后可以恢复。
- **可审查交付**：工作结果、文件、异常和人工请求都有明确的事实来源。
- **可复用资产**：把员工技能和工作流程保存为可迁移的本地资产。
- **本地优先**：凭证、工作区、运行控制和完整工作数据默认留在用户电脑上。

## 运行前提

要让 Agent 真正执行工作，电脑上需要安装并登录受支持的官方 Agent Runtime，例如 Claude Code 或 Codex CLI。RunTeams 会使用这些 Agent 自己的订阅，不要求用户为 RunTeams 另外购买模型用量。

核心运行不依赖 RunTeams 的业务服务器。模型调用仍受对应厂商的订阅、额度和数据政策约束。

## 从源码运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

启动前请确认所需的 Agent CLI 已安装并完成官方登录。桌面窗口和本地数据目录的详细说明见 [`desktop/README.md`](desktop/README.md)。

## 构建 macOS Desktop

```bash
bash desktop/build.sh
open desktop/RunTeams.app
```

构建脚本会生成自包含的 macOS 应用。正式对外分发仍需要 Apple Developer 签名、公证和对应架构的构建流程。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `runteams_core/` | Package、Employee、Pipeline、Task、Workflow 的业务内核 |
| `app.py` | 本地桌面服务与 HTTP 外壳 |
| `runner.py` | Agent CLI 进程生命周期、取消、超时和流式输出 |
| `adapter_claude.py` / `adapter_codex.py` | 官方 Agent Runtime 适配器 |
| `core_protocol_mcp.py` | Employee Workflow 的 MCP 协议入口 |
| `contracts/` | 移动、工作单、工作结果和加密信封契约 |
| `desktop/` | macOS 原生窗口和打包脚本 |
| `web/` | 桌面产品界面资源 |
| `tests/` | 核心协议、运行恢复和产品行为测试 |

更完整的领域边界和数据契约见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 设计原则

1. 接入完整 Agent Runtime，不接裸 LLM API。
2. 保留各家 Agent 的原生工具、技能、权限和订阅能力。
3. RunTeams 只标准化跨 Agent 的岗位、工作单、交接、控制点和审计。
4. 本地运行不依赖云端；跨端服务是可选的控制平面。
5. Free 与 Pro 共享同一套核心协议、数据模型和运行事实源。
6. 付费能力必须是核心能力的自然延伸，不能靠限制导出或制造故障收费。

## 贡献

欢迎围绕核心协议、Agent Channel 适配、运行可靠性、文档和测试提交 Issue 与 Pull Request。提交较大改动前，请先阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)，并说明改动影响的运行契约。

贡献应保持以下边界：不要加入裸模型 API 路径，不要把凭证写入运行快照或日志，不要让云端成为本地核心运行的必需依赖。

## 安全问题

请不要在公开 Issue 中提交凭证、个人数据、工作区内容或未修复的安全细节。安全问题请发送至 `security@runteams.ai`，并尽量提供复现步骤和受影响版本。

## 许可证

核心代码以 Apache License 2.0 发布，见 [`LICENSE`](LICENSE)。第三方依赖和示例资产仍受各自许可证约束。

## 官网

[runteams.ai](https://runteams.ai) · [GitHub](https://github.com/paliacci/runteams)
