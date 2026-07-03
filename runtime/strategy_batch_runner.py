"""动态策略实例批量运行器。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys
from typing import Any

from backtest.notifier import NotificationMessage, build_notifier
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.notification_config import resolve_bark_url
from runtime.repository import SystemRepository
from strategies.factor_topn_runner import run_factor_topn_monthly_instance
from strategies.mainline_chain_factor_runner import run_factor_chain_rotation_instance


COMPAT_ADAPTER_COMMANDS: dict[str, list[str]] = {
    "quality_overlay": [sys.executable, "examples/run_quality_overlay_paper.py", "--skip-update"],
}


def run_enabled_strategy_instances(paths: RuntimePaths | None = None, push: bool = False) -> dict[str, object]:
    """运行所有启用的策略实例，并记录每个实例的运行结果。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    repository = SystemRepository(runtime_paths.system_state_path)
    instances = repository.list_runnable_strategy_instances()
    trade_date = datetime.now().strftime("%Y%m%d")
    bark_url = resolve_bark_url() if push else ""
    results = [
        _run_instance(instance, runtime_paths, repository, trade_date, push=push, bark_url=bark_url)
        for instance in instances
    ]
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
    push: bool = False,
    bark_url: str = "",
) -> dict[str, str]:
    strategy_id = str(instance["strategy_id"])
    command = COMPAT_ADAPTER_COMMANDS.get(strategy_id)
    if command is None and instance.get("template_id") == "factor_topn_monthly":
        try:
            result = run_factor_topn_monthly_instance(instance, paths)
            message = f"selected {result['selected_count']} symbols"
            _send_native_notification(instance, message, push, bark_url)
            return {"strategy_id": strategy_id, "status": "SUCCESS", "message": message}
        except Exception as exc:
            message = str(exc)
            repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
            _send_native_notification(instance, f"FAILED: {message}", push, bark_url)
            return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    if command is None and instance.get("template_id") == "factor_chain_rotation":
        try:
            result = run_factor_chain_rotation_instance(instance, paths)
            message = f"selected {result['selected_count']} symbols, nav {result['nav']:.6f}"
            _send_native_notification(instance, message, push, bark_url)
            return {"strategy_id": strategy_id, "status": "SUCCESS", "message": message}
        except Exception as exc:
            message = str(exc)
            repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
            _send_native_notification(instance, f"FAILED: {message}", push, bark_url)
            return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    if command is None:
        message = f"unsupported_template: {instance.get('template_id')}"
        repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
        return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    command = _with_push_args(command, push, bark_url)
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


def _with_push_args(command: list[str], push: bool, bark_url: str) -> list[str]:
    """按需给兼容策略脚本追加统一通知参数。"""
    result = list(command)
    if not push or not bark_url:
        return result
    result.append("--push")
    result.extend(["--bark-url", bark_url])
    return result


def _send_native_notification(instance: dict[str, Any], message: str, push: bool, bark_url: str) -> None:
    """原生模板策略统一用运行中心发送 Bark 通知。"""
    if not push or not bark_url:
        return
    title = f"{instance.get('name', instance.get('strategy_id'))}运行结果"
    try:
        build_notifier("bark", bark_url).send(NotificationMessage(title=title, body=message))
    except Exception:
        return
