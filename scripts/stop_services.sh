#!/usr/bin/env bash
# 停止本地量化系统：前端、调度器、API。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_PORT="5173"

stop_launchd_service() {
  local label="$1"
  local plist="$2"
  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    echo "$label 已停止"
  else
    echo "$label 未运行"
  fi
}

stop_frontend() {
  local stopped=0
  if launchctl print "gui/$(id -u)/com.quant.frontend" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.quant.frontend.plist" >/dev/null 2>&1 || true
    stopped=1
  fi

  local port_pids
  port_pids="$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    # 端口兜底，避免上次不是由脚本启动时 pid 文件不存在。
    kill $port_pids >/dev/null 2>&1 || true
    stopped=1
  fi

  if [[ "$stopped" == "1" ]]; then
    echo "frontend 已停止"
  else
    echo "frontend 未运行"
  fi
}

stop_frontend
stop_launchd_service "com.quant.scheduler" "$HOME/Library/LaunchAgents/com.quant.scheduler.plist"
stop_launchd_service "com.quant.api" "$HOME/Library/LaunchAgents/com.quant.api.plist"
