# 本机 MCP Apps 开发

当前开发格式为 `runteams.creator-project/2`、`runteams.dependencies/2` 与 `runteams.release/2`。
完整员工仍使用原员工／技能随包格式，原源码 ZIP、修订、权限及正式发布回执继续复用。

`source/` 是作者可编辑源码。`skills/<技能>/mcp/manifest.json` 是 MCPB 0.3 清单，
`server.cjs` 是可直接运行的 Node 程序，`ui/` 是可选的 MCP Apps 页面。
`vendor/` 提供精确锁定的官方 MCP／Apps 库与原 UI Kit；修改依赖时须更新完整字节与锁，
不能只写包名、浮动版本或等待使用者安装。生成的 `mcp/employee.mcpb` 是构建产物，不写回源码。

这是 JavaScript 首批交付。检查／构建不会运行作者代码：构建使用平台固定 Node 做语法检查，
固定解析器核对静态导入的完整闭包，再确定性打包完整资源。动态路径仍是作者行为，不能静态证明所有运行分支。程序入口须是已准备好的 JS／CJS／MJS；本轮不自动执行 npm／pip 脚本，
不承诺 TypeScript、其他语言／原生附件和未验证系统的自动转换。技能员工可以不包含程序或界面。

可直接使用既有 Python 环境运行 `runteams.py`，依赖版本见 requirements.txt：

```sh
python runteams.py doctor
python runteams.py check
python runteams.py build
python runteams.py test --trust-local-code
python runteams.py preview
python runteams.py pack --output dist/employee-source.zip
python runteams.py inspect dist/employee-source.zip
python runteams.py init ../another-employee --key another-employee --name 新员工
python runteams.py open /absolute/employee-source.zip ../continued-employee
```

自测和预览会实际执行作者程序，以普通用户身份访问本机和网络。只对可信源码使用
`--trust-local-code`；浏览器预览在明确勾选启用后才启动。检查、构建、打包、导入不授予运行权限。
预览目录保存的是开发过程，不是正式员工工作或平台业务账本；本段未验收预览文件的完整备份／换机恢复。
自测须提供非空 `runteams.mcp-dev-tests/1` 案例，断言实际工具 structuredContent；从产品导出的
任意项目不继承示例断言。未知调用不能用换键或重开当作成功，不把本机输出当平台业务回执。

源代码变更后重新检查、构建，只补受影响自测。UI 改动须打开真实预览、操作相关状态并查看截图；
组件和主题继续使用 UI Kit，不重做平台布局。固定工具与 Runtime、技能、插件和 MCP 保持完整，
不引入裸模型 API，不修改开发者全局 Agent 配置。Skill 是可选指引，不参与员工运行。

产品普通对话中发送完整源码文件夹，由 Agent 使用当前附件编号导入；Agent 与编辑器编辑同一修订，构建与试运行采用同一格式。
正式发布仍由原产品发布入口校验当前权限、精确版本及可信构建签名，并以原请求回执确认。
本工具不提供直接写数据库、发布、部署或安装命令。完成本机自测不代表正式交付或供应商业务成功。

平台维护者准备新开发包时，复用 `runteams_core/devtools/export_creator_devkit.py --profile mcp`，
提供已核验的 `--runtime-root`、`--libraries` 和固定 `--esbuild`，不提供模型或供应商凭据。
`prepare_creator_builder.sdk_archive(..., profile='mcp', runtime_root=..., libraries=...)`
生成独立分发的开发包 ZIP 与摘要；产品不提供临时开发包下载入口。

可信发布 worker 使用 `runteams.creator-release-builder/3`：`runtime` 包含平台资源绝对
`root` 和 `manifest_sha256`，`esbuild` 包含解析器绝对 `path` 和 `sha256`，
另有 `signing_key_file` 与原 `trusted_keys`。配置和签名私钥须是仅维护者可读的文件；
这些路径／钥匙属于可信构建服务，不进入作者源码、开发包或客户端。实际密钥、正式资源
签名、托管 worker、部署与发布仍需单独准备和确认，不用示例密钥开放正式门禁。
