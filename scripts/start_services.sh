#!/usr/bin/env bash
# 启动本地量化系统：API、调度器、静态前端。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/.env.properties"
API_PLIST="$HOME/Library/LaunchAgents/com.quant.api.plist"
SCHEDULER_PLIST="$HOME/Library/LaunchAgents/com.quant.scheduler.plist"
FRONTEND_PLIST="$HOME/Library/LaunchAgents/com.quant.frontend.plist"
FRONTEND_PORT="5173"

read_property() {
  local key="$1"
  [[ -f "$CONFIG_FILE" ]] || return 0
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$CONFIG_FILE"
}

resolve_command() {
  local configured="$1"
  local fallback="$2"
  if [[ -n "$configured" && -x "$configured" ]]; then
    printf '%s\n' "$configured"
    return
  fi
  command -v "$fallback"
}

PYTHON_BIN="$(resolve_command "$(read_property PYTHON_EXECUTABLE)" python3)"

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
  if [[ ! -f "$PROJECT_ROOT/frontend/dist/index.html" ]]; then
    local npm_bin
    npm_bin="$(resolve_command "$(read_property NPM_EXECUTABLE)" npm)"
    echo "首次启动，构建静态前端..."
    (cd "$PROJECT_ROOT/frontend" && "$npm_bin" run build:pre)
  fi
  bootstrap_service "com.quant.frontend" "$FRONTEND_PLIST"
  sleep 2
  if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "frontend 已启动: http://127.0.0.1:$FRONTEND_PORT/"
  else
    echo "frontend 启动失败，请查看运行目录 logs/frontend.log" >&2
    exit 1
  fi
}

mkdir -p "$HOME/Library/LaunchAgents"
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/generate_launchd_plists.py" --output-dir "$HOME/Library/LaunchAgents"

bootstrap_service "com.quant.api" "$API_PLIST"
bootstrap_service "com.quant.scheduler" "$SCHEDULER_PLIST"
start_frontend

echo "服务就绪:"
echo "- 前端: http://127.0.0.1:$FRONTEND_PORT/"
echo "- API: http://127.0.0.1:8765/api/health"
echo "- 调度: http://127.0.0.1:$FRONTEND_PORT/scheduler"
