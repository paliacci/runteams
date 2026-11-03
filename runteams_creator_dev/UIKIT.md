# MCP Apps 与共用 UI Kit

当前开发工程使用 `runteams.creator-project/2`、依赖锁 `/2` 与完整员工来源 `/3`。
作者页面位于 `source/skills/<技能>/mcp/ui/`，通过官方 MCP Apps 通道调用同一员工程序；
平台控制器及受限 SDK 负责宿主适配、主题、上下文、授权和原请求回执。

`vendor/app.js` 包含固定的官方 MCP Apps 库与 RunTeams UI Kit。
`vendor/theme.css`、`vendor/components.css` 是仓库共用规范的实际分发字节；
不能修改 vendor 来绕过依赖锁。主题、字体、控件与布局使用 `--rt-*` 变量。
UI Kit 不包含员工业务逻辑，可组合现有组件，也可实现自己的完整页面。

源码检查与构建不执行作者程序。自测须明确使用 `test --trust-local-code`；预览明确启用后
才启动同一 MCP 进程。浏览器和桌面共用员工页面、SDK 与运行逻辑。
UI 修改需实际打开预览、操作相关状态并核对截图。

完整命令与当前限制见 [MCP_AUTHORING.md](MCP_AUTHORING.md)。
