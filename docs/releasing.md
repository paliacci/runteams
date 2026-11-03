# 桌面构建与发布

免费本机版的唯一 macOS 构建入口是 `desktop/community/build.py`。构建机需要 macOS ARM64、Swift/Xcode 工具及 Python 3.12。

## 本机验收包

先按仓库内的锁与开发工具准备可信的 Python、MCP Node 运行时和编译器；构建不猜测其他工程或个人安装路径。

```sh
.venv/bin/python desktop/community/build.py --local \
  --creator-builder /absolute/path/to/verified-builder \
  --mcp-runtime /absolute/path/to/verified-mcp-runtime \
  --python-runtime /absolute/path/to/verified-python \
  --output /absolute/path/to/RunTeams-Local.app \
  --dmg /absolute/path/to/RunTeams-Local-macos-arm64-local.dmg
```

输出必须使用新路径。构建检查运行资源、封装清单和签名；App 随包携带 Python、Node、编译器和依赖，安装后不需要源码或系统 Python。当前 ARM64 声明最低 macOS 13.5，旧系统实际执行需在对应系统验证。

`--local` 使用 ad-hoc 签名，只用于本机验收。验证时用 `--data-dir /absolute/path/to/disposable-library` 指定独立资料目录，避免打开现用资料。

## 正式发行

正式包使用同一入口，提供 `--sign-identity`、`--dmg` 和 `--notary-profile`，不使用 `--local`。Developer ID 证书及私钥、公证凭据保存在构建机凭据存储，不能进入 Git。保留运行时、SDK、编辑器和其他依赖的原许可文件。

正式发布前检查 App 与 DMG 签名、公证／装订、实际下载安装及公开校验摘要。当前源码版本为 0.1.2；本机自包含包主流程已经验证，正式 Developer ID、公证和公开下载尚未完成。不要把本机验收包标为正式发行包。

免费版不包含自动更新。升级方式为手动下载并替换安装包，资料目录独立保存。每次涉及资料格式变更时记录支持的版本跨度并验证对应迁移；同版本替换不能证明跨版本迁移。

返回 [项目首页](../README.md)。
