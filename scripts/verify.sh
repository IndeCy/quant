#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/Users/admin/recommend_analysis/.venv/bin/python3}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

cd "$ROOT"

"$PYTHON_BIN" scripts/check_architecture.py
"$PYTHON_BIN" scripts/check_generated_artifacts.py
"$PYTHON_BIN" scripts/check_strategy_boundaries.py
"$PYTHON_BIN" scripts/check_protected_changes.py
"$PYTHON_BIN" scripts/check_secrets.py
"$PYTHON_BIN" -m pytest -q

cd "$ROOT/frontend"
npm test
npm run build:pre

echo "全部开发围栏验证通过"
