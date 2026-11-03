# 本机 MCP Apps 宿主接线

这是平台私有宿主包，不是另一个 Agent Runtime，也不是已交付员工格式。
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
其他 Runtime、复杂表单／权限申请、其他平台和正式安装仍待验，见实施清单。

当前接线从已经取得的完整员工发布版本内读取技能附件 `mcp/employee.mcpb`，不接受网页
提交任意执行路径。M06 的新源码构建从技能 `mcp/` 目录生成这一附件，开发说明见 `runteams_creator_dev/MCP_AUTHORING.md`；不宣称安装版已换版。
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

`tests/test_employee_mcp.py` 使用临时目录和官方 SDK 服务端工程夹具。
`runteams_official/devtools/preview_employee_mcp.py --node /absolute/prepared/node --output /absolute/new/preview`
使用真实 MCP 和原生私有传输生成隔离预览配置，可配合
`tests/fixtures/creator-native/MCPPreview.swift` 检查当前 WebView 接线。
不使用真实账号／员工／模型／业务数据，不替代产品正式导入与发布。

## 当前明确限制

只接 MCPB 0.3 的 Node 固定入口和随包 binary。额外启动参数、用户配置插值、
环境凭据、运行时版本声明或其他清单版本会明确拒绝，留待可信连接／附件接线，
不会偷偷忽略。平台／CPU／最低系统及完整原生依赖闭包还需正式发布检查。
当前 UI 只协商 inline 呈现和服务端工具，不宣称支持消息发送、采样、交互式
作者后台主动发起的 elicitation、摄像头／麦克风或完整视图切换；未授权功能明确不可用。
已接的是 Codex 官方工具审批事件，不把它算作任意作者交互表单已经接通。
Node 本机代码以普通用户执行，不是强沙箱，不能承诺只能访问当前工作目录。

产品实施和未完成项见 [MCP Apps 实施清单](../../design/MCP_APPS_IMPLEMENTATION_CHECKLIST.md)。
