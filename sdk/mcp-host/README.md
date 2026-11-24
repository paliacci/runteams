# 本机 MCP Apps 宿主接线

这是随 Core 源码提供、由平台构建的本机 MCP Apps 宿主包。
复用官方 MCP 客户端 2.4.0、MCP Apps 2.0.3 和当前 UI Kit。版本及依赖字节由
`package-lock.json` 固定；开发构建阶段使用 Node/npm/esbuild，用户安装和工作阶段
只使用平台预备的 Node 和离线单文件资源，不运行 npm、pip 或编译器。

当前源码提供：

- MCPB 0.3 的 Node／随包二进制执行资源检查与只读展开，检查不运行作者代码。
- 一次工作一个进程组，官方 SDK 处理 stdio／协商／工具及 UI 资源；关闭可打断等待。
- 启动前及每次调用由可信宿主校验账户、员工、发布、工作和启用授权。
- 官方 AppBridge 接现有 CreatorWebHost。作者页面在独立的 opaque iframe 中运行，
  没有平台凭据或原生桥；工具调用经原生宿主检查。普通页面脚本不是用户同意。
- 工具超时／断连后保留未知结果，不自动重发；关闭进程不承诺回滚外部效果。

原员工入口已增加本机版本的明确启用／停用、同一工作 MCP 进程、Codex 官方审批往返、
App 直接操作确认与工作恢复。一次真实官方订阅模型和独立 Apps 页面已做本段隔离验收；
实际员工／资产输入是一次性工程资料，不能当作正式发布、安装或真实用户业务验收。
其他 Runtime、复杂表单／权限申请、其他平台和正式安装仍待验。

当前接线从已经取得的完整员工发布版本内读取技能附件 `mcp/employee.mcpb`，不接受网页
提交任意执行路径。M06 的新源码构建从技能 `mcp/` 目录生成这一附件，开发说明见[本机 MCP Apps 开发](../../runteams_creator_dev/MCP_AUTHORING.md)；不宣称安装版已换版。
平台准备器同时输出 `runtime.sha256`，正式应用需将它和 `mcp-runtime` 资源一并纳入签名；
资源未随应用提供时明确不可启用，不回退用户 PATH 的 Node。

固定员工版本／包的启用授权放在既有 host-credentials 范围；工作备份只保留完整资产与
工作记录，不能继承另一主机的启用或连接授权。关闭不是回滚；未知工具调用不自动重放，
MCP 编号和本机日志不能代替具体业务服务的去重及权威回执。

## 平台开发验证

在本目录执行 `npm ci --ignore-scripts --no-audit --no-fund`，然后执行
`node build.mjs /absolute/new/host-resources`。产物包括两个宿主脚本、两份完整作者库、构建来源和依赖许可。
依赖安装仅发生在平台开发／构建阶段；员工包不触发这些命令。

`runteams_core/devtools/provision_mcp_node.py --cache /absolute/build-cache` 从固定官方版本和摘要
准备 Node，目前只列入实际验证的 darwin-arm64。`runteams_core/devtools/prepare_mcp_runtime.py`
组合既有受信 Node 和宿主资源，返回供平台固定的 manifest 摘要；安装器不能接受作者
自报的摘要作为平台资源信任根。正式打包仍需接应用签名、分发和精确资源清单。

在 Apple Silicon Mac 上安装 Python 3.12、Node 22 或更新版本、npm 和 Xcode 命令行工具。从 Core 仓库根目录运行：

```sh
scratch=$(mktemp -d)
python3.12 -m venv "$scratch/venv"
"$scratch/venv/bin/python" -m pip install -r requirements/runtime.txt
"$scratch/venv/bin/python" -B -m runteams_core.devtools.ci_devkit --output "$scratch/devkit"
```

该命令从公开的固定版本构建宿主，检查 inline／fullscreen 切换与关闭协议，再用桌面的 [CreatorWebHost](../../desktop/creator/CreatorWebHost.swift) 加载同一份宿主脚本。[原生 WebView 测试](../../tests/check_mcp_webview.py)让 iframe 中的 MCP App 向内存测试服务取得随机值并回传，核实消息和回复经过原生桥。各步日志与 `verification.json` 位于输出目录。

同一命令还会构建、自测并打包随附的示例工程。要在浏览器里手动预览示例，可运行以下命令，再打开终端给出的本机地址：

```sh
(cd "$scratch/devkit/workspace" && "$scratch/venv/bin/python" runteams.py preview)
```

## 当前明确限制

只接 MCPB 0.3 的 Node 固定入口和随包 binary。额外启动参数、用户配置插值、
环境凭据、运行时版本声明或其他清单版本会明确拒绝，留待可信连接／附件接线，
不会偷偷忽略。平台／CPU／最低系统及完整原生依赖闭包还需正式发布检查。
当前 UI 支持服务端工具。具备原生呈现能力的宿主协商 inline 和 fullscreen，其他宿主使用 inline。
消息发送、采样、作者主动发起的 elicitation 以及摄像头和麦克风访问仍未开放。
已接的是 Codex 官方工具审批事件，不把它算作任意作者交互表单已经接通。
Node 本机代码以普通用户执行，不是强沙箱，不能承诺只能访问当前工作目录。

工程格式、技能附件和预览授权见 [MCP Apps 创作规范](../../contracts/creator-system/mcp-v1/AUTHORING.md)。
