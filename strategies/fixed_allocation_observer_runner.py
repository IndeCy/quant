"""固定资产配置的只观察运行器。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.quality_factor_study_support import slice_result
from examples.strategy_comparison_research import build_metrics_table
from factors.etf_momentum import month_end_signal_dates
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.opportunity_observer_runner import save_observation_state


@dataclass(frozen=True)
class FixedAllocationObserverComputation:
    """固定配置观察策略的纯计算产物。"""

    result: dict[str, Any]
    monitoring_frame: pd.DataFrame
    daily_nav: pd.Series
    holdings: list[dict[str, Any]]
    current_prices: dict[str, float]
    metrics: dict[str, float]
    total_cost: float
    failed_order_count: int
    turnover_notional: float


def compute_fixed_allocation_observer(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
) -> FixedAllocationObserverComputation:
    """复用基金标准面板和M0，计算月频固定配置观察净值。"""
    assets = validate_fixed_assets(instance)
    config = dict(instance.get("config") or {})
    observation_start = str(config.get("observation_start") or "20150101")
    panel_start = str(config.get("panel_start") or "20140101")
    benchmark_symbol = str(instance.get("benchmark") or "510300.SH")
    symbols = list(dict.fromkeys([*assets, benchmark_symbol]))
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date=panel_start,
        end_date=trade_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(observation_start)
    ]
    if not signals:
        raise ValueError("固定配置观察策略没有可用月末信号")
    targets = {
        date.strftime("%Y%m%d"): dict(assets)
        for date in signals
    }
    benchmark = panel.adjusted_close[benchmark_symbol]
    run = run_risk_layer_backtest(
        str(instance["strategy_id"]),
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(
            stamp_tax_rate=0.0,
            slippage_bps=float(config.get("execution_slippage_bps", 5.0)),
        ),
    )
    observed_result = slice_result(
        run.result,
        observation_start,
        panel.latest_common_date,
    )
    observed_run = RiskLayerRun(observed_result, run.exposure, run.events)
    daily_nav = (
        observed_result.daily_values
        / float(observed_result.daily_values.iloc[0])
    )
    metrics = _metric_row(observed_run, benchmark)
    monitoring_frame = build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=daily_nav,
        benchmark_values=benchmark,
        exposure=pd.Series(1.0, index=daily_nav.index),
        total_cost=float(observed_result.total_cost),
        failed_order_count=len(observed_result.failed_orders),
        turnover_notional=float(observed_result.turnover_notional),
        benchmark_id=benchmark_symbol,
    )
    latest_date = panel.latest_common_date
    current_prices = {
        symbol: float(panel.adjusted_close.loc[pd.Timestamp(latest_date), symbol])
        for symbol in assets
    }
    names = {
        str(item["symbol"]): str(item.get("name") or item["symbol"])
        for item in _asset_rows(instance)
    }
    holdings = [
        {
            "symbol": symbol,
            "name": names[symbol],
            "target_weight": weight,
            "current_price": current_prices[symbol],
        }
        for symbol, weight in assets.items()
    ]
    result = {
        "strategy_id": str(instance["strategy_id"]),
        "trade_date": latest_date,
        "selected_count": len(holdings),
        "nav": float(daily_nav.iloc[-1]),
        "target_weights": assets,
        "latest_signal_date": max(targets),
    }
    return FixedAllocationObserverComputation(
        result=result,
        monitoring_frame=monitoring_frame,
        daily_nav=daily_nav,
        holdings=holdings,
        current_prices=current_prices,
        metrics=metrics,
        total_cost=float(observed_result.total_cost),
        failed_order_count=len(observed_result.failed_orders),
        turnover_notional=float(observed_result.turnover_notional),
    )


def persist_fixed_allocation_observer(
    instance: dict[str, Any],
    paths: RuntimePaths,
    computation: FixedAllocationObserverComputation,
) -> dict[str, Any]:
    """串行保存观察状态、监控曲线和可再生产物。"""
    result = computation.result
    strategy_id = str(result["strategy_id"])
    trade_date = str(result["trade_date"])
    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    save_observation_state(
        paths,
        strategy_id,
        trade_date,
        dict(result["target_weights"]),
        computation.current_prices,
        float(result["nav"]),
    )
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(
        computation.monitoring_frame
    )
    artifacts = _write_artifacts(run_dir, instance, computation)
    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(
        strategy_id,
        trade_date,
        "SUCCESS",
        run_dir,
        "fixed allocation observation completed; broker disabled",
    )
    for report_type, path in artifacts.items():
        repository.upsert_report(
            report_type,
            strategy_id,
            trade_date,
            report_type,
            path,
            tags=["observation", "allocation", "research"],
        )
    return dict(result)


def validate_fixed_assets(instance: dict[str, Any]) -> dict[str, float]:
    """校验固定资产代码唯一、权重为正且合计为1。"""
    rows = _asset_rows(instance)
    if not rows:
        raise ValueError("construction.assets must be a non-empty list")
    weights: dict[str, float] = {}
    for item in rows:
        symbol = str(item.get("symbol") or "").strip().upper()
        weight = float(item.get("weight", 0.0))
        if not symbol or symbol in weights:
            raise ValueError("fixed allocation symbols must be non-empty and unique")
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("fixed allocation weights must be positive and finite")
        weights[symbol] = weight
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("fixed allocation weights must sum to 1")
    return weights


def _asset_rows(instance: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(instance.get("construction") or {}).get("assets")
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _metric_row(run: RiskLayerRun, benchmark: pd.Series) -> dict[str, float]:
    row = build_metrics_table(
        {str(run.result.strategy): run.result},
        benchmark,
    ).iloc[0]
    annual_return = float(row["年化收益"])
    max_drawdown = float(row["最大回撤"])
    return {
        "annualized_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe": float(row["夏普比率"]),
        "calmar": (
            annual_return / abs(max_drawdown)
            if max_drawdown < 0
            else 0.0
        ),
        "annual_turnover": float(row["年化换手率"]),
    }


def _write_artifacts(
    run_dir: Path,
    instance: dict[str, Any],
    computation: FixedAllocationObserverComputation,
) -> dict[str, Path]:
    strategy_id = str(instance["strategy_id"])
    trade_date = str(computation.result["trade_date"])
    snapshot_path = run_dir / f"{strategy_id}_snapshot.csv"
    nav_path = run_dir / f"{strategy_id}_daily_nav.csv"
    metrics_path = run_dir / f"{strategy_id}_metrics.json"
    report_path = run_dir / f"{strategy_id}_report.md"
    pd.DataFrame(computation.holdings).to_csv(snapshot_path, index=False)
    computation.daily_nav.rename("nav").rename_axis("trade_date").to_csv(nav_path)
    metrics_path.write_text(
        json.dumps(
            {
                **computation.metrics,
                "trade_date": trade_date,
                "strategy_id": strategy_id,
                "nav": float(computation.result["nav"]),
                "trade_policy": "observation_only",
                "paper_broker": "disabled",
                "failed_order_count": computation.failed_order_count,
                "total_cost": computation.total_cost,
                "turnover_notional": computation.turnover_notional,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        _report_text(instance, computation),
        encoding="utf-8",
    )
    return {
        "observation_snapshot": snapshot_path,
        "observation_daily_nav": nav_path,
        "observation_metrics": metrics_path,
        "observation_report": report_path,
    }


def _report_text(
    instance: dict[str, Any],
    computation: FixedAllocationObserverComputation,
) -> str:
    metrics = computation.metrics
    holdings = "\n".join(
        f"- {item['symbol']} {item['name']}：{item['target_weight']:.2%}"
        for item in computation.holdings
    )
    return f"""# {instance['name']} 前瞻观察

- 数据截止：{computation.result['trade_date']}
- 最新月末信号：{computation.result['latest_signal_date']}
- 状态：只观察，不同步 Paper Broker，不创建订单
- 复权/执行：qfq，M0 T+1，基金免印花税

## 固定目标

{holdings}

## 截至当前的同口径历史指标

- 年化收益：{metrics['annualized_return']:.2%}
- 最大回撤：{metrics['max_drawdown']:.2%}
- Sharpe：{metrics['sharpe']:.3f}
- Calmar：{metrics['calmar']:.3f}
- 年化换手：{metrics['annual_turnover']:.2f}x
"""
