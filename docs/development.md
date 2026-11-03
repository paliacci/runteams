# 开发指南

使用 Python 3.12。前端／SDK 检查使用 Node 24.22.1，依赖按各工程的 npm 锁安装。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m pip install -r requirements/build.txt
npm ci --prefix tooling/js --ignore-scripts --no-audit --no-fund
```

## 日常检查

在仓库根目录执行源码和仓库检查：

```sh
.venv/bin/python -B -m runteams_core.devtools.check_source
.venv/bin/python -B -m runteams_core.devtools.check_repository --root . --namespace runteams_core
```

仓库检查读取 Git 跟踪文件；新增、移动或删除源码后，先暂存拟提交文件。它检查生成物／私密文件、个人机器路径、目录大小写冲突、文档导航与工具清单。

修改工具后重新生成清单：

```sh
.venv/bin/python -B -m runteams_core.devtools.command_inventory --root . --namespace runteams_core
```

提交源码后运行统一 CI，输出目录使用仓库外的新目录：

```sh
.venv/bin/python -B -m runteams_core.devtools.ci \
  --output /absolute/path/to/new-ci-output \
  --sdk-tsc "$PWD/tooling/js/node_modules/typescript/lib/tsc.js"
```

统一入口覆盖源码边界、仓库卫生、可复现 wheel、独立安装主流程、PDF 附件及 SDK 消费者检查。GitHub 工作流运行相同入口。针对业务变更补充对应的定向测试；一次 CI 通过不表示所有平台、真实模型或长期运行均已验收。

## SDK 开发包

SDK 源码直接在本仓库维护。独立开发包由同源导出器生成，无需第三个仓库：

```sh
.venv/bin/python -B -m runteams_core.devtools.export_creator_devkit \
  --output /absolute/path/to/new-devkit \
  --runtime-root /absolute/path/to/verified-mcp-runtime \
  --libraries /absolute/path/to/verified-author-libraries \
  --esbuild /absolute/path/to/verified-esbuild
```

包内 `runteams.py` 可检查、构建、打包和新建工程；开发机仍需 Python 及声明的依赖。Node 和编译器随开发包提供。macOS ARM64 的 `devkit.yml` 手动工作流从固定锁准备运行资源，再核对原开发主流程。

不要把模型密钥、真实工作资料、浏览器缓存或验收截图提交到仓库。模型调用和对外部署与本机检查分别执行。

返回 [项目首页](../README.md)。
