"""冻结 Quality Alpha V1 的原生策略执行适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backtest.quality_overlay_paper import QualityPaperSnapshot
from backtest.quality_overlay_paper import QualityPaperStore
from runtime.local_paper_bridge import load_live_market_for_symbols
from runtime.paths import RuntimePaths
from runtime.strategy_state_writer import StrategyHoldingState, write_strategy_instance_state


@dataclass(frozen=True)
class QualityOverlayComputation:
    """冻结 Quality 策略的纯计算产物。"""

    result: dict[str, Any]
    snapshot: QualityPaperSnapshot
    holdings: pd.DataFrame
    run: object
    benchmark_curve: pd.Series
    shanghai_curve: pd.Series
    latest_prices: dict[str, float]


def run_quality_overlay_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
) -> dict[str, Any]:
    """兼容入口：在当前线程依次计算并提交冻结 Quality 策略。"""
    computation = compute_quality_overlay_instance(instance, paths, trade_date)
    return persist_quality_overlay_instance(instance, paths, computation)


def compute_quality_overlay_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
) -> QualityOverlayComputation:
    """复用冻结 Alpha 逻辑，只生成内存快照和回测结果。"""
    from examples import run_quality_overlay_paper as quality

    if paths.root != quality.RUNTIME_PATHS.root:
        raise RuntimeError("quality runner paths must match configured QUANT_HOME")
    quality.validate_incremental_quality()
    snapshot, holdings, run, benchmark_curve, shanghai_curve = quality.build_snapshot([], as_of_date=trade_date)
    if snapshot.trade_date > trade_date:
        raise RuntimeError(
            f"quality data date {snapshot.trade_date} exceeds requested trade date {trade_date}"
        )
    result = {
        "strategy_id": str(instance["strategy_id"]),
        "trade_date": snapshot.trade_date,
        "selected_count": len(snapshot.target_weights),
        "target_weights": snapshot.target_weights,
        "nav": float(run.result.daily_values.iloc[-1]),
    }
    market_data = load_live_market_for_symbols(
        paths,
        snapshot.trade_date,
        sorted(snapshot.target_weights),
    )
    latest_prices = {
        str(row.symbol): float(row.close)
        for row in market_data.itertuples(index=False)
    }
    return QualityOverlayComputation(
        result,
        snapshot,
        holdings,
        run,
        benchmark_curve,
        shanghai_curve,
        latest_prices,
    )


def persist_quality_overlay_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    computation: QualityOverlayComputation,
) -> dict[str, Any]:
    """串行提交 Quality 监控、日报、理论快照和最新报告。"""
    from examples import run_quality_overlay_paper as quality

    snapshot = computation.snapshot
    holdings = computation.holdings
    run = computation.run
    benchmark_curve = computation.benchmark_curve
    shanghai_curve = computation.shanghai_curve
    quality.update_monitoring_dashboard(run, benchmark_curve, shanghai_curve)
    run_dir = quality.write_production_artifacts(snapshot, holdings, run, benchmark_curve, [])
    QualityPaperStore(paths.quality_overlay_paper_path).save(snapshot)
    daily_values = pd.Series(run.result.daily_values).dropna().astype(float).sort_index()
    normalized_nav = float(daily_values.iloc[-1] / daily_values.iloc[0])
    write_strategy_instance_state(
        paths,
        str(instance["strategy_id"]),
        snapshot.trade_date,
        normalized_nav,
        [
            StrategyHoldingState(
                symbol=symbol,
                weight=float(weight),
                last_close=float(computation.latest_prices.get(symbol, 0.0)),
            )
            for symbol, weight in sorted(snapshot.target_weights.items())
        ],
    )
    report = quality.render_report(snapshot, holdings, [])
    paths.latest_report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_report_path.write_text(report, encoding="utf-8")
    return {**computation.result, "run_dir": str(run_dir)}
