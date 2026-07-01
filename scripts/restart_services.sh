#!/usr/bin/env bash
# 重启本地量化系统。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PROJECT_ROOT/scripts/stop_services.sh"
sleep 1
"$PROJECT_ROOT/scripts/start_services.sh"
