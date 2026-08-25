"""Quality Value LowVol V0 的生产候选运行适配器。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.execution_model import ExecutionModel
from backtest.mixed_asset_execution import MixedAssetExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.calendar import TradingCalendar
from data.fund_portfolio import load_fund_portfolio_panel
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    CorporateActionAudit,
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.strategy_comparison_research import build_metrics_table
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_state_writer import StrategyHoldingState, write_strategy_instance_state
from strategies.quality_balanced_value_signal import build_quality_balanced_value_topn
from strategies.quality_fixed_sleeve import (
    append_fixed_sleeve_holdings,
    build_effective_exposure_series,
    build_fixed_sleeve_targets,
    load_fixed_sleeve_latest_prices,
    load_fixed_sleeve_plan,
)
from strategies.quality_universe import apply_quality_universe_filters, load_annual_quality_candidates
from strategies.quality_value_lowvol_signal import build_quality_value_lowvol_topn


STRATEGY_ID = "quality_value_lowvol_v0"
BENCHMARK_SYMBOL = "510300.SH"


@dataclass(frozen=True)
class QualityValueLowVolComputation:
    """纯计算阶段产物，提交阶段再写运行数据库与报表。"""

    result: dict[str, Any]
    holdings: pd.DataFrame
    monitoring_frame: pd.DataFrame
    run: RiskLayerRun
    audit: CorporateActionAudit
    metrics: dict[str, Any]
    latest_prices: dict[str, float]


def compute_quality_value_lowvol_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
    *,
    exposure_controller: Any | None = None,
) -> QualityValueLowVolComputation:
    """按运行日快照重建历史曲线，并生成最新理论目标。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=trade_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = _latest_market_date(connection)
        signal_dates = load_month_end_signal_dates(connection)
        if _is_month_end(latest_date):
            signal_dates = sorted(set([*signal_dates, latest_date]))
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        raw_candidates = load_annual_quality_candidates(connection)
        filtered = apply_quality_universe_filters(raw_candidates)
        with_factors = attach_report_adjustment_factors(connection, filtered)
        candidates, audit = build_quality_value_lowvol_candidates(with_factors)
        selections, holdings = _build_strategy_topn(instance, candidates)
        if not selections:
            raise RuntimeError("quality_value_lowvol_no_valid_selections")
        run, benchmark, targets, risk_exposure = _run_backtest(
            connection,
            paths,
            instance,
            selections,
            holdings,
            latest_date,
            exposure_controller=exposure_controller,
        )
        latest_prices = _load_latest_raw_prices(
            connection,
            latest_date,
            selections[max(selections)],
        )
        latest_prices.update(load_fixed_sleeve_latest_prices(instance, paths, latest_date))
        return _build_computation(
            instance,
            paths,
            latest_date,
            selections,
            holdings,
            run,
            benchmark,
            targets,
            risk_exposure,
            audit,
            latest_prices,
        )
    finally:
        connection.close()


def persist_quality_value_lowvol_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    computation: QualityValueLowVolComputation,
) -> dict[str, Any]:
    """串行保存历史净值、理论持仓和标准每日产物。"""
    result = computation.result
    strategy_id = str(result["strategy_id"])
    trade_date = str(result["trade_date"])
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(computation.monitoring_frame)
    holdings = [
        StrategyHoldingState(
            symbol=str(row.symbol),
            weight=float(row.target_weight),
            last_close=float(computation.latest_prices.get(str(row.symbol), 0.0)),
        )
        for row in computation.holdings.itertuples(index=False)
    ]
    write_strategy_instance_state(
        paths,
        strategy_id,
        trade_date,
        float(result["nav"]),
        holdings,
    )
    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _write_artifacts(run_dir, instance, computation)
    repository = SystemRepository(paths.system_state_path)
    repository.record_run_step(
        strategy_id,
        trade_date,
        1,
        "load_point_in_time_factors",
        "SUCCESS",
        f"checked={computation.audit.checked_rows}, excluded={computation.audit.excluded_rows}",
    )
    repository.record_run_step(
        strategy_id,
        trade_date,
        2,
        "run_m0_backtest",
        "SUCCESS",
        f"rows={len(computation.monitoring_frame)}",
    )
    repository.record_run_step(
        strategy_id,
        trade_date,
        3,
        "write_artifacts",
        "SUCCESS",
        "daily outputs generated",
    )
    for report_type, path in artifacts.items():
        repository.upsert_report(
            report_type,
            strategy_id,
            trade_date,
            report_type,
            path,
            tags=["strategy_instance", strategy_id],
        )
    return {**result, "run_dir": str(run_dir)}


def _run_backtest(
    connection: Any,
    paths: RuntimePaths,
    instance: dict[str, Any],
    selections: dict[str, list[str]],
    holdings: pd.DataFrame,
    latest_date: str,
    *,
    exposure_controller: Any | None = None,
) -> tuple[RiskLayerRun, pd.Series, dict[str, dict[str, float]], pd.Series]:
    symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
    stock_bars = load_feature_bars(connection, symbols)
    calendar = load_trading_calendar(connection)
    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        BENCHMARK_SYMBOL,
        end_date=latest_date,
    )
    core_targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }
    config = dict(instance.get("config") or {})
    core_run = run_risk_layer_backtest(
        str(instance["name"]),
        "GRID",
        core_targets,
        stock_bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=float(config.get("execution_slippage_bps", 5.0))),
        vol_window=int(config.get("volatility_window", 20)),
        vol_threshold=float(config.get("volatility_threshold", 0.45)),
        reduced_exposure=float(config.get("reduced_exposure", 0.30)),
        exposure_controller=exposure_controller,
    )
    plan = load_fixed_sleeve_plan(instance)
    if plan is None:
        return core_run, benchmark, core_targets, core_run.exposure
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        plan.symbols,
        start_date="20130101",
        end_date=latest_date,
    )
    if panel.latest_common_date != latest_date:
        raise RuntimeError(
            f"quality_fixed_sleeve_stale:{panel.latest_common_date}!={latest_date}"
        )
    targets = build_fixed_sleeve_targets(instance, core_targets, core_run.exposure)
    bars = pd.concat([stock_bars, panel.bars]).sort_index()
    run = run_risk_layer_backtest(
        str(instance["name"]),
        "FIXED",
        targets,
        bars,
        calendar,
        benchmark,
        MixedAssetExecutionModel(
            set(plan.symbols),
            slippage_bps=float(config.get("execution_slippage_bps", 5.0)),
        ),
    )
    effective_exposure = build_effective_exposure_series(targets, calendar)
    return RiskLayerRun(run.result, effective_exposure, core_run.events), benchmark, targets, core_run.exposure


def _build_computation(
    instance: dict[str, Any],
    paths: RuntimePaths,
    latest_date: str,
    selections: dict[str, list[str]],
    holdings: pd.DataFrame,
    run: RiskLayerRun,
    benchmark: pd.Series,
    targets: dict[str, dict[str, float]],
    risk_exposure: pd.Series,
    audit: CorporateActionAudit,
    latest_prices: dict[str, float],
) -> QualityValueLowVolComputation:
    selection_date = max(selections)
    selected = holdings[holdings["signal_date"].astype(str).eq(selection_date)].copy()
    target_date = max(date for date in targets if date <= latest_date)
    target_weights = dict(targets[target_date])
    selected["target_weight"] = selected["symbol"].astype(str).map(target_weights).fillna(0.0)
    selected["reason"] = _selection_reason(instance)
    selected["sleeve"] = "quality_core"
    selected = append_fixed_sleeve_holdings(
        selected,
        target_weights,
        instance,
        selection_date,
    )
    exposure = float(sum(target_weights.values()))
    core_exposure = float(risk_exposure.loc[:pd.Timestamp(latest_date)].iloc[-1])
    action_required = _target_changed(paths, str(instance["strategy_id"]), target_weights)
    monitor = build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=run.result.daily_values,
        benchmark_values=benchmark,
        exposure=run.exposure,
        total_cost=run.result.total_cost,
        failed_order_count=len(run.result.failed_orders),
        turnover_notional=run.result.turnover_notional,
        benchmark_id="510300",
    )
    latest = monitor.iloc[-1]
    metric_row = build_metrics_table({str(instance["name"]): run.result}, benchmark).iloc[0]
    metrics = {
        "strategy_id": str(instance["strategy_id"]),
        "trade_date": latest_date,
        "selection_date": selection_date,
        "nav": float(latest["nav"]),
        "daily_return": float(latest["daily_return"]),
        "cumulative_return": float(latest["cumulative_return"]),
        "annualized_return": float(metric_row["年化收益"]),
        "max_drawdown": float(metric_row["最大回撤"]),
        "current_drawdown": float(latest["drawdown"]),
        "sharpe": float(metric_row["夏普比率"]),
        "excess_return": float(metric_row["超额收益"]),
        "volatility_20": float(latest["volatility_20"]),
        "target_exposure": exposure,
        "core_risk_exposure": core_exposure,
        "risk_state": "REDUCED" if core_exposure < 1.0 else "NORMAL",
        "selected_count": len(selected),
        "action_required": action_required,
        "corporate_action_checked": audit.checked_rows,
        "corporate_action_changed": audit.changed_rows,
        "corporate_action_excluded": audit.excluded_rows,
        "corporate_action_missing": audit.missing_rows,
        "corporate_action_threshold": audit.materiality_threshold,
        "total_execution_cost": float(run.result.total_cost),
        "failed_order_count": len(run.result.failed_orders),
        "trade_count": len(run.result.trades),
    }
    result = {
        "strategy_id": str(instance["strategy_id"]),
        "trade_date": latest_date,
        "selection_date": selection_date,
        "selected_count": len(selected),
        "target_weights": target_weights,
        "action_required": action_required,
        "nav": float(latest["nav"]),
        "message": _notification_message(metrics),
    }
    return QualityValueLowVolComputation(result, selected, monitor, run, audit, metrics, latest_prices)


def _write_artifacts(
    run_dir: Path,
    instance: dict[str, Any],
    computation: QualityValueLowVolComputation,
) -> dict[str, Path]:
    strategy_id = str(instance["strategy_id"])
    plan_columns = [
        "symbol", "name", "sleeve", "rank", "factor_score", "target_weight", "reason",
        "roe", "roa", "ocf_to_or", "earnings_yield", "book_yield",
        "low_volatility_60d",
    ]
    plan = computation.holdings.reindex(columns=plan_columns)
    snapshot = plan[["symbol", "name", "target_weight"]].copy()
    artifacts = {
        "rebalance_plan": run_dir / f"{strategy_id}_rebalance_plan.csv",
        "portfolio_snapshot": run_dir / f"{strategy_id}_portfolio_snapshot.csv",
        "strategy_metrics": run_dir / f"{strategy_id}_strategy_metrics.json",
        "daily_report": run_dir / f"{strategy_id}_daily_report.md",
    }
    plan.to_csv(artifacts["rebalance_plan"], index=False)
    snapshot.to_csv(artifacts["portfolio_snapshot"], index=False)
    artifacts["strategy_metrics"].write_text(
        json.dumps(computation.metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    artifacts["daily_report"].write_text(
        _daily_report(str(instance["name"]), computation.metrics, plan),
        encoding="utf-8",
    )
    return artifacts


def _daily_report(name: str, metrics: dict[str, Any], plan: pd.DataFrame) -> str:
    rows = "\n".join(
        f"| {row.symbol} | {row['name']} | {row.target_weight:.2%} | {row.factor_score:.4f} |"
        for _, row in plan.iterrows()
    )
    return f"""# {name} 日报

- 数据日期：{metrics['trade_date']}
- 选股信号日：{metrics['selection_date']}
- 当前净值：{metrics['nav']:.4f}
- 当日收益：{metrics['daily_return']:.2%}
- 累计收益：{metrics['cumulative_return']:.2%}
- 当前仓位：{metrics['target_exposure']:.2%}
- 20日年化波动率：{metrics['volatility_20']:.2%}
- 风险层状态：{metrics['risk_state']}
- 是否需要调仓：{'是' if metrics['action_required'] else '否'}
- 公司行为门禁：检查 {metrics['corporate_action_checked']}，变化 {metrics['corporate_action_changed']}，重大变化剔除 {metrics['corporate_action_excluded']}，缺失 {metrics['corporate_action_missing']}

| 股票 | 名称 | 目标权重 | 综合得分 |
| --- | --- | ---: | ---: |
{rows}
"""


def _notification_message(metrics: dict[str, Any]) -> str:
    action = "需要生成T+1委托" if metrics["action_required"] else "目标未变化"
    return (
        f"数据{metrics['trade_date']}，仓位{metrics['target_exposure']:.0%}，"
        f"当日{metrics['daily_return']:.2%}，当前回撤{metrics['current_drawdown']:.2%}，"
        f"风险{metrics['risk_state']}，{action}"
    )


def _target_changed(paths: RuntimePaths, strategy_id: str, weights: dict[str, float]) -> bool:
    state = SystemRepository(paths.system_state_path).load_strategy_instance_state(strategy_id)
    previous = {
        str(item["symbol"]): float(item["weight"])
        for item in state.get("holdings", [])
    }
    if not state.get("trade_date"):
        return True
    if set(previous) != set(weights):
        return True
    return any(not math.isclose(previous[symbol], weight, abs_tol=1e-9) for symbol, weight in weights.items())


def _load_latest_raw_prices(
    connection: Any,
    trade_date: str,
    symbols: list[str],
) -> dict[str, float]:
    placeholders = ",".join("?" for _ in symbols)
    frame = connection.execute(
        f"""
        SELECT symbol, raw_close
        FROM features
        WHERE trade_date = ? AND symbol IN ({placeholders})
        """,
        [trade_date, *symbols],
    ).fetchdf()
    return dict(zip(frame["symbol"].astype(str), frame["raw_close"].astype(float)))


def _factor_weights(instance: dict[str, Any]) -> dict[str, float]:
    return {
        str(item["factor_id"]): float(item["weight"])
        for item in instance.get("factors", [])
    }


def _build_strategy_topn(
    instance: dict[str, Any],
    candidates: pd.DataFrame,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按显式评分模式路由，数据、组合、风险和执行层保持共用。"""
    config = dict(instance.get("config") or {})
    mode = str(config.get("score_mode") or "quality_value_lowvol_v0")
    weights = _factor_weights(instance)
    top_n = int(instance["construction"]["top_n"])
    if mode == "quality_balanced_value_v1":
        return build_quality_balanced_value_topn(
            candidates,
            weights,
            top_n=top_n,
        )
    if mode != "quality_value_lowvol_v0":
        raise ValueError(f"unsupported point-in-time value score mode: {mode}")
    return build_quality_value_lowvol_topn(candidates, weights, top_n=top_n)


def _selection_reason(instance: dict[str, Any]) -> str:
    """把评分口径写入每日持仓原因，便于Paper复盘。"""
    mode = str(dict(instance.get("config") or {}).get("score_mode") or "")
    if mode == "quality_balanced_value_v1":
        return "Quality80%+E/P10%+B/P10%综合得分TopN"
    return "五因子综合得分TopN"


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        indicator=paths.fina_indicator_path,
        income=paths.income_statement_path,
        balance=paths.balance_sheet_path,
        cashflow=paths.cashflow_statement_path,
    )


def _latest_market_date(connection: Any) -> str:
    value = connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
    if not value:
        raise RuntimeError("quality_value_lowvol_market_data_empty")
    return str(value)


def _is_month_end(trade_date: str) -> bool:
    current = pd.Timestamp(trade_date)
    next_day = TradingCalendar().next_trading_day(current)
    return next_day is not None and next_day.month != current.month
