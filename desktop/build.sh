#!/bin/bash
# 构建自包含 RunTeams.app —— 内含 Python 后端(PyInstaller onedir),不依赖系统 Python。
# 关键:macOS 26 对未签名 Mach-O 首次加载做很慢的安全评估 → 必须给所有 .so/.dylib/exe ad-hoc 签名。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/desktop/RunTeams.app"
APP_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
case "$APP_VERSION" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "VERSION 必须是 x.y.z 格式" >&2; exit 1 ;;
esac
PY="${PY:-/opt/homebrew/opt/python@3.12/bin/python3.12}"   # 用干净(homebrew)python,别用 Xcode Framework 版
VENV=/tmp/runteams_build
SIGN_IDENTITY="${RUNTEAMS_CODESIGN_IDENTITY:-}"
if [ -z "$SIGN_IDENTITY" ]; then
  SIGN_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/.*"\(Apple Distribution: ALPHABEAT LIMITED [^"]*\)".*/\1/p' | head -n 1)"
fi
if [ -z "$SIGN_IDENTITY" ]; then
  SIGN_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/.*"\(Apple Development: [^"]*\)".*/\1/p' | head -n 1)"
fi
if [ -z "$SIGN_IDENTITY" ]; then
  SIGN_IDENTITY="-"
fi
cd "$ROOT"

echo "[1/6] 构建资源查看器"
(cd "$ROOT/frontend/resource-viewer" && npm ci --silent && npm run build)

echo "[2/6] 准备 venv + 运行依赖 + pyinstaller"
if [ ! -x "$VENV/bin/python" ] || [ ! -x "$VENV/bin/pip" ]; then
  rm -rf "$VENV"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" -q install -r "$ROOT/requirements.txt" pyinstaller

echo "[3/6] PyInstaller onedir 打包后端"
rm -rf /tmp/runteams_od_build "$ROOT/dist_build"
"$VENV/bin/pyinstaller" --noconfirm --onedir --name runteams-server \
  --add-data "$ROOT/web:web" \
  --add-data "$ROOT/VERSION:." \
  --hidden-import encodings.idna \
  --hidden-import capability_launcher \
  --hidden-import runteams_core.protocol \
  --distpath "$ROOT/dist_build" --workpath /tmp/runteams_od_build --specpath /tmp/runteams_od_build \
  app.py >/tmp/runteams_build.log 2>&1
PYZ_TOC=/tmp/runteams_od_build/runteams-server/PYZ-00.toc
if grep -Eq "\\('(acceptance|agent_sessions|artifacts|assistant_drafts|card_inputs|collaboration|contract|credential_requirements|maintenance_agent|pipeline|protocol_mcp|quota_windows|runtime_dependencies|runtime_failures|skill_runtime|store|task_checks|task_runtime|task_seeds|task_tools|work_locations|worker_improvement|worker_programs|worker_retro|workspaces)'" "$PYZ_TOC"; then
  echo "正式桌面包错误地包含旧运行架构模块" >&2
  grep -E "\\('(acceptance|agent_sessions|artifacts|assistant_drafts|card_inputs|collaboration|contract|credential_requirements|maintenance_agent|pipeline|protocol_mcp|quota_windows|runtime_dependencies|runtime_failures|skill_runtime|store|task_checks|task_runtime|task_seeds|task_tools|work_locations|worker_improvement|worker_programs|worker_retro|workspaces)'" "$PYZ_TOC" >&2
  exit 1
fi

echo "[4/6] 组装 .app"
rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"
cp -R "$ROOT/dist_build/runteams-server" "$OUT/Contents/Resources/server"
cp "$ROOT/desktop/RunTeams.icns" "$OUT/Contents/Resources/RunTeams.icns"
mkdir -p "$OUT/Contents/Resources/RunTeamsPicker.app/Contents/MacOS"
cp "$ROOT/desktop/RunTeamsPicker-Info.plist" "$OUT/Contents/Resources/RunTeamsPicker.app/Contents/Info.plist"
xcrun swiftc "$ROOT/desktop/attachment_picker.swift" \
  -o "$OUT/Contents/Resources/RunTeamsPicker.app/Contents/MacOS/RunTeamsPicker" -framework AppKit
xcrun swiftc "$ROOT/desktop/work_location_host.swift" -o "$OUT/Contents/Resources/RunTeamsWorkLocationHost" -framework AppKit
WINDOW_APP="$OUT/Contents/Resources/RunTeamsWindow.app"
mkdir -p "$WINDOW_APP/Contents/MacOS" "$WINDOW_APP/Contents/Resources"
cp "$ROOT/desktop/RunTeams.icns" "$WINDOW_APP/Contents/Resources/RunTeams.icns"
xcrun swiftc "$ROOT/desktop/window_host.swift" \
  -o "$WINDOW_APP/Contents/MacOS/RunTeamsWindow" -framework AppKit -framework WebKit
sed "s/__RUNTEAMS_VERSION__/$APP_VERSION/g" > "$WINDOW_APP/Contents/Info.plist" <<'WINDOW_PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>RunTeams.ai</string>
  <key>CFBundleDisplayName</key><string>RunTeams.ai</string>
  <key>CFBundleIdentifier</key><string>ai.runteams.desktop.window</string>
  <key>CFBundleVersion</key><string>__RUNTEAMS_VERSION__</string>
  <key>CFBundleShortVersionString</key><string>__RUNTEAMS_VERSION__</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>RunTeamsWindow</string>
  <key>CFBundleIconFile</key><string>RunTeams.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
WINDOW_PLIST
sed "s/__RUNTEAMS_VERSION__/$APP_VERSION/g" > "$OUT/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>RunTeams.ai</string>
  <key>CFBundleDisplayName</key><string>RunTeams.ai</string>
  <key>CFBundleIdentifier</key><string>ai.runteams.desktop</string>
  <key>CFBundleVersion</key><string>__RUNTEAMS_VERSION__</string>
  <key>CFBundleShortVersionString</key><string>__RUNTEAMS_VERSION__</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>RunTeams</string>
  <key>CFBundleIconFile</key><string>RunTeams.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$OUT/Contents/MacOS/RunTeams" <<'LAUNCH'
#!/bin/bash
# 启动自包含后端(不依赖系统 python) + 开无边框窗口
HERE="$(cd "$(dirname "$0")/../Resources" && pwd)"
APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${RUNTEAMS_PORT:-8791}"
URL="http://127.0.0.1:${PORT}"
EXPECTED_API_VERSION=14
LAUNCH_LOCK="${TMPDIR:-/tmp}/runteams-${UID}-${PORT}.launch-lock"
LOCKED=0
server_ready() {
  HEALTH="$(/usr/bin/curl -s --max-time 2 "${URL}/api/health" 2>/dev/null || true)"
  case "$HEALTH" in
    *'"app": "RunTeams.ai"'*'"api_version": '"$EXPECTED_API_VERSION"*) return 0 ;;
    *) return 1 ;;
  esac
}
# 后台下载的更新只在本地服务已经完全退出后应用。关闭窗口但任务仍在后台运行时，
# server_ready 为真，因此不会替换正在使用的应用。
if [ "${1:-}" != "--runteams-updated" ] && ! server_ready; then
  set +e
  "${HERE}/server/runteams-server" --runteams-apply-update "$APP_ROOT" \
    >>/tmp/runteams-update.log 2>&1
  UPDATE_STATUS=$?
  set -e
  if [ "$UPDATE_STATUS" = "10" ]; then
    exec "$APP_ROOT/Contents/MacOS/RunTeams" --runteams-updated
  fi
fi
stop_stale_server() {
  EXISTING_PID="$(/usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | /usr/bin/head -n 1)"
  [ -z "$EXISTING_PID" ] && return 0
  EXISTING_COMMAND="$(/bin/ps -p "$EXISTING_PID" -o command= 2>/dev/null || true)"
  case "$EXISTING_COMMAND" in
    *runteams-server*)
      /bin/kill -TERM "$EXISTING_PID" 2>/dev/null || true
      for i in $(seq 1 40); do
        /bin/kill -0 "$EXISTING_PID" 2>/dev/null || return 0
        sleep 0.1
      done
      return 1
      ;;
    *)
      echo "端口 ${PORT} 已被其他程序占用：${EXISTING_COMMAND}" >/tmp/runteams.log
      return 1
      ;;
  esac
}
release_lock() {
  if [ "$LOCKED" = "1" ]; then
    /bin/rm -f "$LAUNCH_LOCK/pid" 2>/dev/null || true
    /bin/rmdir "$LAUNCH_LOCK" 2>/dev/null || true
    LOCKED=0
  fi
}
acquire_lock() {
  for i in $(seq 1 160); do
    if /bin/mkdir "$LAUNCH_LOCK" 2>/dev/null; then
      echo "$$" >"$LAUNCH_LOCK/pid"
      LOCKED=1
      return 0
    fi
    server_ready && return 1
    sleep 0.25
  done
  OWNER="$(/bin/cat "$LAUNCH_LOCK/pid" 2>/dev/null || true)"
  if [ -n "$OWNER" ] && /bin/kill -0 "$OWNER" 2>/dev/null; then
    return 1
  fi
  /bin/rm -f "$LAUNCH_LOCK/pid" 2>/dev/null || true
  /bin/rmdir "$LAUNCH_LOCK" 2>/dev/null || true
  /bin/mkdir "$LAUNCH_LOCK" 2>/dev/null || return 1
  echo "$$" >"$LAUNCH_LOCK/pid"
  LOCKED=1
  return 0
}
trap release_lock EXIT INT TERM
if ! server_ready; then
  if acquire_lock; then
    if ! server_ready; then
      # 另一实例可能正在启动或暂时繁忙；先等待健康检查恢复，避免误杀长任务。
      EXISTING_PID="$(/usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | /usr/bin/head -n 1)"
      if [ -n "$EXISTING_PID" ]; then
        for i in $(seq 1 20); do server_ready && break; sleep 0.5; done
      fi
    fi
    if ! server_ready; then
      stop_stale_server || exit 1
      RUNTEAMS_PORT="$PORT" /usr/bin/nohup "${HERE}/server/runteams-server" \
        </dev/null >/tmp/runteams.log 2>&1 &
      # 首次启动 macOS 要评估签名, 给足时间
      for i in $(seq 1 80); do server_ready && break; sleep 0.5; done
      server_ready || exit 1
    fi
    release_lock
  else
    for i in $(seq 1 160); do server_ready && break; sleep 0.25; done
    server_ready || exit 1
  fi
fi
WINDOW_HOST="${HERE}/RunTeamsWindow.app/Contents/MacOS/RunTeamsWindow"
if [ -x "$WINDOW_HOST" ]; then
  "$WINDOW_HOST" "$URL"
elif [ -d "/Applications/Google Chrome.app" ]; then
  open -W -na "Google Chrome" --args --app="${URL}" --user-data-dir="${HOME}/.runteams-window"
elif [ -d "/Applications/Microsoft Edge.app" ]; then
  open -W -na "Microsoft Edge" --args --app="${URL}" --user-data-dir="${HOME}/.runteams-window"
else
  open "${URL}"
  wait
fi
LAUNCH
chmod +x "$OUT/Contents/MacOS/RunTeams"

echo "[5/6] 使用稳定身份签名所有 Mach-O（无开发证书时回退到 ad-hoc）"
find "$OUT/Contents/Resources" -type f | while read -r f; do
  file "$f" 2>/dev/null | grep -q "Mach-O" && codesign --force -s "$SIGN_IDENTITY" "$f" 2>/dev/null || true
done
codesign --force --deep -s "$SIGN_IDENTITY" "$OUT/Contents/Resources/RunTeamsWindow.app" 2>/dev/null || true
codesign --force --deep -s "$SIGN_IDENTITY" "$OUT" 2>/dev/null || true
codesign --verify --deep --strict "$OUT"

echo "[6/6] 完成 → $OUT"
echo "数据目录可用 RUNTEAMS_DATA 自定义"
echo "首次启动约 20-30 秒(系统评估签名), 之后秒开。"
