# RunTeams / 免费本机版

本工程拥有共用本机核心、同一套业务 UI、SDK 源码和免费版桌面构建。免费版无需 RunTeams 账户或 Supabase，不包含订阅、市场和自动更新。模型厂商、CLI 及用户选择的外部服务仍由用户自行配置。

## 独立安装与运行

使用 Python 3.12 创建虚拟环境，在本工程根目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/runteams-community --port 8792 --open
```

默认资料位置在用户应用资料目录，独立于源码和安装目录。使用 `--data-dir /absolute/path` 可以明确指定资料库。SDK 源码和开发工具模块随工程提供；免费版的源码创作与本机构建继续复用同一套 UI。独立开发工具包的导出属于单独的交付流程。

```sh
.venv/bin/python -I -B -m runteams_core.devtools.verify_install
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

安装包内含 Python 代码、共用 UI、业务合同和 SDK 参考资源，运行不回读研发工程。修改源码后重新安装即可；官方工程通过核心 wheel 的摘要和版本固定依赖，不复制共用业务源码。

## macOS 桌面构建

沿唯一入口 `desktop/community/build.py` 构建。构建机需要 Swift/Xcode 工具及 Python 3.12；产出的 App 携带 Python 和运行依赖，用户安装后不需要源码或系统 Python。

```sh
.venv/bin/python desktop/community/build.py --local \
  --creator-builder /absolute/path/to/verified-builder \
  --mcp-runtime /absolute/path/to/verified-mcp-runtime \
  --python-runtime /absolute/path/to/verified-python \
  --output /absolute/path/to/RunTeams-Local.app
```

构建资源沿现有锁和完整性检查准备，缺少可信资源时构建会停止。正式签名公证使用同一入口的 `--sign-identity`、`--dmg` 和 `--notary-profile`；尚未配置的证书与公证凭据以后再配置。免费版只提供手动下载安装包升级。

## 源码归属与发布状态

官方账户、付费权益、市场、云端接口、官网和后台属于独立私有工程。本仓库不提供官方实现的旧路径、转发模块或发行模式切换入口。

源码按 RunTeams Source Available License 1.0 提供：允许使用产品开展商业工作，商业再分发 RunTeams 或其修改版需要另行书面授权。独立创作的员工、流水线、技能和工作成果可以商用。第三方组件保留原许可；这属于源码可用许可，不宣称是 OSI 开源许可。详见 LICENSE、LICENSING.md 和 THIRD_PARTY_DOCUMENTS.md。

SDK 源码直接维护在本仓库的 sdk/；sdk/runtime、sdk/view 和 sdk/ui 三个独立库保留各自 Apache-2.0 许可。开发工具在 runteams_creator_dev/，导出工具为 runteams_core.devtools.export_creator_devkit。开发包是同源交付产物，不需要第三个 Git 仓库。

## 开发工具与 CI

维护者命令在本工程根目录运行，统一归 `runteams_core.devtools`；原根目录 `scripts/` 已删除。完整清单在 `tooling/commands.json`，不提供旧路径转发。

```sh
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python -B -m runteams_core.devtools.ci --output /absolute/path/to/new-ci-output
```

CI 从干净 Git 提交构建 wheel，时间戳取提交时间；相同提交可在官方 CI 重建并逐字节核对核心依赖。GitHub 的 `core.yml` 同时安装锁定 TypeScript 并执行现有 SDK 独立消费者检查，不调用模型、账户或业务调度。

独立 SDK 开发包沿原导出器生成：

```sh
.venv/bin/python -B -m runteams_core.devtools.export_creator_devkit \
  --output /absolute/path/to/new-devkit \
  --runtime-root /absolute/path/to/verified-mcp-runtime \
  --libraries /absolute/path/to/verified-author-libraries \
  --esbuild /absolute/path/to/verified-esbuild
```

开发包携带当前公共 Python 依赖闭包、原合同、UI Kit、Node 和解析器，`runteams.py` 是开发工程的正式入口。包内可检查／构建、运行明确受信任的原模板自测、打包、创建新工程或从源码 ZIP 继续开发，无需产品仓库和 RunTeams 账户。真实模型和发布权益仍由产品原机制管理。

GitHub 的 devkit.yml 是手动运行的 macOS ARM64 构建任务，使用 GitHub 托管的 macos-15，从仓库原有 Node 摘要和 npm 锁准备运行资源，再执行同一 SDK 导出及开发主流程。无需配置本机 runner 或上传个人构建目录。也可以在 macOS ARM64 构建机运行 python -B -m runteams_core.devtools.ci_devkit --output /absolute/path/to/new-output。公共仓库为 https://github.com/paliacci/runteams；本机验证与 GitHub 实际执行分别登记。

后续直接在本仓库维护本机核心、共用 UI 与 SDK；官方业务在私有 runteams-official 维护。旧总工程作为历史工作区保留，不作为当前构建或运行依赖。
