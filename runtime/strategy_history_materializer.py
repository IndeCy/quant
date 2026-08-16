"""把通过晋级门槛的回测曲线资产化到统一监控库。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths


REQUIRED_COLUMNS = {
    "trade_date",
    "strategy_id",
    "strategy_name",
    "nav",
    "daily_return",
    "cumulative_return",
    "benchmark_id",
    "benchmark_nav",
    "benchmark_return",
    "excess_return",
    "drawdown",
    "max_drawdown",
    "volatility_20",
    "volatility_60",
    "sharpe_rolling",
    "exposure",
    "turnover_notional",
    "total_execution_cost",
    "failed_order_count",
}


@dataclass(frozen=True)
class StrategyHistoryMaterialization:
    """记录一次历史曲线物化结果，便于研究晋级流程审计。"""

    strategy_id: str
    row_count: int
    start_date: str
    end_date: str


def materialize_strategy_backtest_history(
    paths: RuntimePaths,
    strategy_id: str,
    monitoring_frame: pd.DataFrame,
) -> StrategyHistoryMaterialization:
    """幂等写入回测历史，但不修改实时持仓、Paper订单或策略运行状态。"""
    if monitoring_frame.empty:
        raise ValueError("strategy backtest history cannot be empty")
    missing = sorted(REQUIRED_COLUMNS.difference(monitoring_frame.columns))
    if missing:
        raise ValueError(f"strategy backtest history missing columns: {missing}")

    frame = monitoring_frame.copy()
    actual_ids = set(frame["strategy_id"].dropna().astype(str))
    if actual_ids != {strategy_id}:
        raise ValueError(
            f"strategy backtest history id mismatch: expected={strategy_id}, actual={sorted(actual_ids)}"
        )
    frame["trade_date"] = frame["trade_date"].astype(str)
    if frame["trade_date"].duplicated().any():
        raise ValueError("strategy backtest history contains duplicate trade dates")
    if frame["nav"].isna().any() or (frame["nav"].astype(float) <= 0).any():
        raise ValueError("strategy backtest history contains invalid nav")

    ordered = frame.sort_values("trade_date").reset_index(drop=True)
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(ordered)
    return StrategyHistoryMaterialization(
        strategy_id=strategy_id,
        row_count=len(ordered),
        start_date=str(ordered.iloc[0]["trade_date"]),
        end_date=str(ordered.iloc[-1]["trade_date"]),
    )
