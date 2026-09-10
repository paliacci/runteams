# RunTeams.ai 桌面 App（M4 · 已解决 ✅）

`desktop/RunTeams.app` 是一个**自包含**的 macOS 应用：内含 Python 后端、全部前端资源和原生 WebKit 窗口，**别的电脑不用装 Python或 Chrome**。双击即起后端 + 开一个与 Codex/Claude Code 一样隐藏标题文字、内容延伸到交通灯下方的原生应用窗口。

> 唯一前提:要真跑 AI 员工,目标机器得装了某个模型 CLI 并登录(如 `claude` + 你的订阅)——这是 RunTeams.ai "用户自带订阅、零 token 成本" 的设计,不是打包缺陷。UI/编排/导入导出不需要它。

## 重新构建

```bash
bash desktop/build.sh      # 产出 desktop/RunTeams.app
```
默认用 homebrew 的干净 Python（`/opt/homebrew/opt/python@3.12`）。可用 `RUNTEAMS_DATA` 指定数据目录。

## 本地调试登录

需要反复调试账号界面时，可显式开启一个只在本机进程内有效的固定邮箱/验证码：

```bash
RUNTEAMS_ENABLE_DEV_AUTH=1 \
RUNTEAMS_DEV_AUTH_EMAIL=debug@runteams.local \
RUNTEAMS_DEV_AUTH_CODE=654321 \
desktop/RunTeams.app/Contents/MacOS/RunTeams
```

三个变量缺一不可，验证码必须是 6 位数字。该身份不会请求 Supabase、不会签发 JWT，也不能访问云端中转或用户数据；正式启动默认禁用。

**首次启动约 20–30 秒**（macOS 首次评估签名），之后秒开。

关闭桌面窗口只关闭界面，已经启动的本地流水线会继续在后台运行；再次打开 RunTeams
即可查看进度。启动器使用单实例锁和健康检查复用后台服务，不能因为重复打开窗口或一次
短暂健康检查超时而终止正在运行的 AI 员工。

## 踩过的坑（构建原理，改动前必读）

1. **别用 Xcode Framework 版 Python**（`/usr/bin/python3`）打包——PyInstaller 打它连 Python 都进不去(卡在 dyld 加载)。用 `brew install python@3.12`，在 venv 里装 `pyinstaller`。
2. **macOS 26 必须签名所有 Mach-O**。未签名的每个 C 扩展 `.so` 首次加载会被系统做很慢的安全评估，几十个累积起来像"卡死"（其实是极慢）。构建脚本已对所有 `.so/.dylib/exe` 做 ad-hoc 签名 + 对 `.app` 做 `codesign --deep`。这是它能跑起来的关键。
3. 代码里已修 `HTTPServer.server_bind` 的 `getfqdn()` 反向 DNS 卡顿（自定义 `Server` 类跳过）。

## 分发给别人 / 跨平台（还没做）

- **Gatekeeper**：ad-hoc 签名只够本机。发给别人首次打开会被拦，对方可**右键→打开**绕过；要干净分发需 Apple 开发者账号（$99/年）做正式签名 + 公证。
- **跨平台/架构**：Mac 打的包只能在 Mac 跑；Windows/Linux、Intel/ARM 都要各自打（PyInstaller 按机器架构打包）。
- **原生窗口**：使用系统 WebKit + Swift 外壳，不依赖 Chrome；标题栏透明、隐藏标题文字，红黄绿窗口按钮保留。Chrome/Edge 仅作为原生外壳缺失时的兜底。

## 静默更新

正式打包版本启动后会读取 `https://runteams.ai/updates/stable.json`。线上不需要动态
接口或数据库，只维护这一份静态清单。清单版本高于 App 内的 `VERSION` 时，客户端按
`darwin-aarch64`、`darwin-x86_64` 等目标选择资源，在后台下载到用户数据目录并校验
SHA-256。

下载不会重启应用。下一次本地服务已经完全退出后的启动，启动器会先验证 macOS App
签名和系统安全评估并替换应用，再启动新版本；仅关闭窗口、后台任务仍在运行时不会应用更新。失败时
保留旧版本和待更新资源，后续完整启动可重试。

发布新版本：

1. 修改根目录 `VERSION`，执行 `desktop/build.sh` 并完成正式签名、公证。
2. 执行 `desktop/package-update.sh` 生成更新 ZIP 和 SHA-256。
3. 上传 ZIP，把网站 `public/updates/stable.json` 的 `version`、平台 URL 和 SHA-256 改为新值。
4. 部署网站。旧版本随后会自动发现并下载更新。

开发运行默认不访问更新地址；设置 `RUNTEAMS_DISABLE_AUTO_UPDATE=1` 可禁用正式包检查，
`RUNTEAMS_UPDATE_MANIFEST_URL` 可切换测试清单。
