#!/usr/bin/env bash
# 启动本地量化系统：API、调度器、前端。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/Users/admin/recommend_analysis/.venv/bin/python3"
NODE_BIN="/opt/homebrew/opt/node@22/bin/node"
VITE_BIN="$PROJECT_ROOT/frontend/node_modules/vite/bin/vite.js"
API_PLIST="$HOME/Library/LaunchAgents/com.quant.api.plist"
SCHEDULER_PLIST="$HOME/Library/LaunchAgents/com.quant.scheduler.plist"
FRONTEND_PLIST="$HOME/Library/LaunchAgents/com.quant.frontend.plist"
FRONTEND_PORT="5173"
FRONTEND_LOG="$PROJECT_ROOT/logs/frontend.log"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/state"

is_launchd_running() {
  launchctl print "gui/$(id -u)/$1" >/dev/null 2>&1
}

bootstrap_service() {
  local label="$1"
  local plist="$2"
  if is_launchd_running "$label"; then
    echo "$label 已运行"
    return
  fi
  if [[ ! -f "$plist" ]]; then
    echo "缺少 launchd 配置: $plist" >&2
    exit 1
  fi
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "$label 已启动"
}

start_frontend() {
  if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "frontend 已运行: http://127.0.0.1:$FRONTEND_PORT/"
    return
  fi
  if [[ ! -x "$NODE_BIN" ]]; then
    echo "缺少 Node: $NODE_BIN" >&2
    exit 1
  fi
  if [[ ! -f "$VITE_BIN" ]]; then
    echo "缺少 Vite，请先在 frontend 目录安装依赖: $VITE_BIN" >&2
    exit 1
  fi
  write_frontend_plist
  bootstrap_service "com.quant.frontend" "$FRONTEND_PLIST"
  sleep 2
  if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "frontend 已启动: http://127.0.0.1:$FRONTEND_PORT/"
  else
    echo "frontend 启动失败，查看日志: $FRONTEND_LOG" >&2
    exit 1
  fi
}

write_frontend_plist() {
  cat >"$FRONTEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.quant.frontend</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NODE_BIN</string>
    <string>$VITE_BIN</string>
    <string>--host</string>
    <string>127.0.0.1</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT/frontend</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>QUANT_HOME</key>
    <string>$PROJECT_ROOT</string>
    <key>PATH</key>
    <string>/opt/homebrew/opt/node@22/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$FRONTEND_LOG</string>
  <key>StandardErrorPath</key>
  <string>$FRONTEND_LOG</string>
</dict>
</plist>
EOF
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "缺少 Python 环境: $PYTHON_BIN" >&2
  exit 1
fi

bootstrap_service "com.quant.api" "$API_PLIST"
bootstrap_service "com.quant.scheduler" "$SCHEDULER_PLIST"
start_frontend

echo "服务就绪:"
echo "- 前端: http://127.0.0.1:$FRONTEND_PORT/"
echo "- API: http://127.0.0.1:8765/api/health"
echo "- 调度: http://127.0.0.1:$FRONTEND_PORT/scheduler"
