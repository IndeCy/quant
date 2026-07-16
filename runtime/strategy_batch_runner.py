"""动态策略实例批量运行器。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.notifier import NotificationMessage, build_notifier
from domain.strategy_execution import StrategyExecutionResult, TargetPortfolio
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.local_paper_bridge import load_live_market_for_symbols, sync_strategy_target_to_local_paper
from runtime.notification_config import resolve_bark_url
from runtime.repository import SystemRepository
from runtime.strategy_executor_registry import StrategyExecutionContext, StrategyExecutorRegistry
from strategies.opportunity_observer_runner import run_opportunity_observer_instance
from strategies.factor_topn_runner import run_factor_topn_monthly_instance
from strategies.mainline_chain_factor_runner import run_factor_chain_rotation_instance
from strategies.quality_overlay_runner import run_quality_overlay_instance


def run_enabled_strategy_instances(
    paths: RuntimePaths | None = None,
    push: bool = False,
    trade_date: str | None = None,
) -> dict[str, object]:
    """运行所有启用的策略实例，并记录每个实例的运行结果。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    repository = SystemRepository(runtime_paths.system_state_path)
    instances = repository.list_runnable_strategy_instances()
    target_date = trade_date or datetime.now().strftime("%Y%m%d")
    bark_url = resolve_bark_url() if push else ""
    executors = build_default_strategy_executor_registry()
    results = [
        _run_instance(instance, runtime_paths, repository, executors, target_date, push=push, bark_url=bark_url)
        for instance in instances
    ]
    return {
        "trade_date": target_date,
        "enabled_count": len(instances),
        "success_count": sum(1 for item in results if item["status"] == "SUCCESS"),
        "failed_count": sum(1 for item in results if item["status"] == "FAILED"),
        "results": results,
    }


def _run_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    repository: SystemRepository,
    executors: StrategyExecutorRegistry,
    trade_date: str,
    push: bool = False,
    bark_url: str = "",
) -> dict[str, str]:
    """通过注册表执行任意策略实例，并统一记录状态与发送通知。"""
    strategy_id = str(instance["strategy_id"])
    context = StrategyExecutionContext(paths=paths, trade_date=trade_date, push=push, bark_url=bark_url)
    try:
        result = executors.execute(instance, context)
    except Exception as exc:
        message = str(exc)
        repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
        _send_native_notification(instance, f"FAILED: {message}", push, bark_url)
        return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
    if result.target_portfolio is not None:
        paper_message = _sync_target_portfolio(instance, paths, result.target_portfolio)
        result = replace(result, message=f"{result.message}; {paper_message}")
    repository.record_strategy_run(
        strategy_id,
        result.trade_date,
        result.status,
        paths.runs_dir / result.trade_date,
        result.message,
    )
    notification_message = result.message
    if result.observation_only:
        notification_message = f"{notification_message}\n观察策略，不构成调仓建议"
    _send_native_notification(instance, notification_message, push, bark_url)
    return result.to_summary()


def build_default_strategy_executor_registry() -> StrategyExecutorRegistry:
    """登记内置模板和显式兼容适配器，新增策略不再修改分发分支。"""
    registry = StrategyExecutorRegistry()
    registry.register("factor_topn_monthly", _execute_factor_topn)
    registry.register("factor_chain_rotation", _execute_factor_chain_rotation)
    registry.register("opportunity_observer", _execute_opportunity_observer)
    registry.register("quality_overlay_compat", _execute_quality_native)
    return registry


def _execute_factor_topn(instance: dict[str, Any], context: StrategyExecutionContext) -> StrategyExecutionResult:
    result = run_factor_topn_monthly_instance(instance, context.paths)
    trade_date = str(result.get("trade_date") or context.trade_date)
    portfolio = TargetPortfolio.from_weights(
        str(instance["strategy_id"]),
        trade_date,
        dict(result.get("target_weights") or {}),
    )
    return StrategyExecutionResult.success(
        str(instance["strategy_id"]),
        trade_date,
        f"selected {result['selected_count']} symbols",
        selected_count=int(result["selected_count"]),
        nav=float(result["nav"]),
        target_portfolio=portfolio,
    )


def _execute_factor_chain_rotation(
    instance: dict[str, Any], context: StrategyExecutionContext
) -> StrategyExecutionResult:
    result = run_factor_chain_rotation_instance(instance, context.paths)
    trade_date = str(result.get("trade_date") or context.trade_date)
    portfolio = TargetPortfolio.from_weights(
        str(instance["strategy_id"]),
        trade_date,
        dict(result.get("target_weights") or {}),
    )
    return StrategyExecutionResult.success(
        str(instance["strategy_id"]),
        trade_date,
        f"selected {result['selected_count']} symbols, nav {result['nav']:.6f}",
        selected_count=int(result["selected_count"]),
        nav=float(result["nav"]),
        target_portfolio=portfolio,
    )


def _execute_opportunity_observer(
    instance: dict[str, Any], context: StrategyExecutionContext
) -> StrategyExecutionResult:
    result = run_opportunity_observer_instance(instance, context.paths, trade_date=context.trade_date)
    message = f"observation selected {result['selected_count']} symbols, nav {result['nav']:.6f}"
    return StrategyExecutionResult.success(
        str(instance["strategy_id"]),
        str(result.get("trade_date") or context.trade_date),
        message,
        selected_count=int(result["selected_count"]),
        nav=float(result["nav"]),
        observation_only=True,
    )


def _execute_quality_native(instance: dict[str, Any], context: StrategyExecutionContext) -> StrategyExecutionResult:
    """运行冻结 Quality 实现，并直接返回正式目标组合。"""
    result = run_quality_overlay_instance(instance, context.paths, context.trade_date)
    trade_date = str(result.get("trade_date") or context.trade_date)
    portfolio = TargetPortfolio.from_weights(
        str(instance["strategy_id"]),
        trade_date,
        dict(result.get("target_weights") or {}),
    )
    return StrategyExecutionResult.success(
        str(instance["strategy_id"]),
        trade_date,
        f"selected {result['selected_count']} symbols, nav {result['nav']:.6f}",
        selected_count=int(result["selected_count"]),
        nav=float(result["nav"]),
        target_portfolio=portfolio,
    )


def _sync_local_paper_from_artifacts(instance: dict[str, Any], paths: RuntimePaths, trade_date: str) -> str:
    """兼容旧调用：把组合文件转换成正式目标组合后同步 Broker。"""
    portfolio = _target_portfolio_from_artifacts(instance, paths, trade_date)
    if portfolio is None:
        return "paper_broker skipped=no_portfolio_snapshot"
    return _sync_target_portfolio(instance, paths, portfolio)


def _target_portfolio_from_artifacts(
    instance: dict[str, Any], paths: RuntimePaths, trade_date: str
) -> TargetPortfolio | None:
    """仅供旧 Quality 适配器使用，原生策略必须直接返回 TargetPortfolio。"""
    strategy_id = str(instance["strategy_id"])
    run_dir = paths.runs_dir / trade_date
    snapshot_path = _portfolio_snapshot_path(run_dir, strategy_id)
    if snapshot_path is None:
        return None
    snapshot = pd.read_csv(snapshot_path)
    if snapshot.empty or "symbol" not in snapshot.columns or "target_weight" not in snapshot.columns:
        return None
    names = {
        str(row["symbol"]): str(row["name"])
        for _, row in snapshot.iterrows()
        if "name" in snapshot.columns and pd.notna(row.get("name"))
    }
    target_weights = {str(row["symbol"]): float(row["target_weight"]) for _, row in snapshot.iterrows()}
    return TargetPortfolio.from_weights(strategy_id, trade_date, target_weights, names)


def _sync_target_portfolio(
    instance: dict[str, Any], paths: RuntimePaths, portfolio: TargetPortfolio
) -> str:
    """把正式目标组合交给唯一 Paper Broker，不再依赖 CSV 作为计算输入。"""
    strategy_id = portfolio.strategy_id
    names = {position.symbol: position.name or position.symbol for position in portfolio.positions}
    symbols = sorted(set(portfolio.weights) | _paper_account_symbols(paths, strategy_id))
    market_data = load_live_market_for_symbols(paths, portfolio.trade_date, symbols, names)
    result = sync_strategy_target_to_local_paper(
        paths=paths,
        strategy_id=strategy_id,
        strategy_name=str(instance.get("name") or strategy_id),
        trade_date=portfolio.trade_date,
        target_weights=portfolio.weights,
        market_data=market_data,
        initial_cash=float((instance.get("config") or {}).get("initial_capital", 1_000_000.0)),
        benchmark_symbol=str(instance.get("benchmark") or "510300"),
        benchmark_name=str(instance.get("benchmark") or "510300"),
    )
    return (
        f"paper_broker created={result.created_orders}, executed={result.executed_orders}, "
        f"rejected={result.rejected_orders}, pending={result.pending_orders}"
    )


def _portfolio_snapshot_path(run_dir: Path, strategy_id: str) -> Path | None:
    candidates = [run_dir / f"{strategy_id}_portfolio_snapshot.csv", run_dir / "portfolio_snapshot.csv"]
    return next((path for path in candidates if path.exists()), None)


def _paper_account_symbols(paths: RuntimePaths, strategy_id: str) -> set[str]:
    if not paths.paper_trading_path.exists():
        return set()
    with sqlite3.connect(paths.paper_trading_path) as con:
        account = con.execute("SELECT id FROM paper_account WHERE strategy_code = ? ORDER BY id LIMIT 1", [strategy_id]).fetchone()
        if account is None:
            return set()
        account_id = int(account[0])
        positions = con.execute("SELECT symbol FROM paper_position WHERE account_id = ?", [account_id]).fetchall()
        pending = con.execute("SELECT symbol FROM paper_order WHERE account_id = ? AND status = 'PENDING'", [account_id]).fetchall()
    return {str(row[0]) for row in positions + pending}


def _last_message(stdout: str, stderr: str) -> str:
    text = stdout.strip() or stderr.strip()
    if not text:
        return "strategy instance completed"
    return text.splitlines()[-1][-500:]


def _with_run_args(command: list[str], trade_date: str, push: bool, bark_url: str) -> list[str]:
    """按需给兼容策略脚本追加统一运行参数。"""
    result = list(command)
    result.extend(["--run-date", trade_date])
    if not push or not bark_url:
        return result
    result.append("--push")
    result.extend(["--bark-url", bark_url])
    return result


def _with_push_args(command: list[str], push: bool, bark_url: str) -> list[str]:
    """兼容旧测试和外部调用，仅追加通知参数。"""
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
