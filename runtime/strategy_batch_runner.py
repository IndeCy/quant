"""动态策略实例批量运行器。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys
from typing import Any

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from strategies.factor_topn_runner import run_factor_topn_monthly_instance


COMPAT_ADAPTER_COMMANDS: dict[str, list[str]] = {
    "quality_overlay": [sys.executable, "examples/run_quality_overlay_paper.py", "--skip-update"],
    "mainline_chain_b": [sys.executable, "scripts/run_mainline_chain_daily.py"],
}


def run_enabled_strategy_instances(paths: RuntimePaths | None = None) -> dict[str, object]:
    """运行所有启用的策略实例，并记录每个实例的运行结果。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    repository = SystemRepository(runtime_paths.system_state_path)
    instances = repository.list_strategy_instances(enabled_only=True)
    trade_date = datetime.now().strftime("%Y%m%d")
    results = [_run_instance(instance, runtime_paths, repository, trade_date) for instance in instances]
    return {
        "trade_date": trade_date,
        "enabled_count": len(instances),
        "success_count": sum(1 for item in results if item["status"] == "SUCCESS"),
        "failed_count": sum(1 for item in results if item["status"] == "FAILED"),
        "results": results,
    }


def _run_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    repository: SystemRepository,
    trade_date: str,
) -> dict[str, str]:
    strategy_id = str(instance["strategy_id"])
    command = COMPAT_ADAPTER_COMMANDS.get(strategy_id)
    if command is None and instance.get("template_id") == "factor_topn_monthly":
        try:
            result = run_factor_topn_monthly_instance(instance, paths)
            return {"strategy_id": strategy_id, "status": "SUCCESS", "message": f"selected {result['selected_count']} symbols"}
        except Exception as exc:
            message = str(exc)
            repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
            return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    if command is None:
        message = f"unsupported_template: {instance.get('template_id')}"
        repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
        return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, check=False)
    status = "SUCCESS" if result.returncode == 0 else "FAILED"
    message = _last_message(result.stdout, result.stderr) if result.returncode == 0 else result.stderr[-500:]
    repository.record_strategy_run(strategy_id, trade_date, status, paths.runs_dir / trade_date, message)
    return {"strategy_id": strategy_id, "status": status, "message": message}


def _last_message(stdout: str, stderr: str) -> str:
    text = stdout.strip() or stderr.strip()
    if not text:
        return "strategy instance completed"
    return text.splitlines()[-1][-500:]
