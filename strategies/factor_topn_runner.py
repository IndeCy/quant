"""多因子 TopN 策略实例运行器。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def run_factor_topn_monthly_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]:
    """运行一个配置化多因子 TopN 策略实例。"""
    scores = _load_latest_scores(paths.factor_scores_path, [item["factor_id"] for item in instance["factors"]])
    weighted = _build_weighted_scores(scores, instance["factors"])
    top_n = int(instance.get("construction", {}).get("top_n", 20))
    selected = weighted.sort_values(["score", "symbol"], ascending=[False, True]).head(top_n)
    trade_date = str(selected["trade_date"].iloc[0])
    symbols = selected["symbol"].tolist()
    weights = {symbol: 1.0 / len(symbols) for symbol in symbols} if symbols else {}

    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / f"{instance['strategy_id']}_rebalance_plan.csv"
    pd.DataFrame({"symbol": list(weights), "target_weight": list(weights.values())}).to_csv(plan_path, index=False)

    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(
        str(instance["strategy_id"]),
        trade_date,
        "SUCCESS",
        run_dir,
        f"selected {len(symbols)} symbols",
    )
    repository.upsert_report(
        "rebalance_plan",
        str(instance["strategy_id"]),
        trade_date,
        "调仓建议",
        plan_path,
        tags=["strategy_instance", "rebalance"],
    )
    _write_monitoring_snapshot(paths, instance, trade_date)
    return {"strategy_id": instance["strategy_id"], "trade_date": trade_date, "selected_count": len(symbols), "symbols": symbols}


def _load_latest_scores(path: Path, factor_ids: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"factor_scores database not found: {path}")
    placeholders = ",".join("?" for _ in factor_ids)
    with sqlite3.connect(path) as con:
        latest = con.execute("SELECT MAX(trade_date) FROM factor_scores").fetchone()[0]
        frame = pd.read_sql_query(
            f"""
            SELECT trade_date, symbol, factor_id, value
            FROM factor_scores
            WHERE trade_date = ? AND factor_id IN ({placeholders})
            """,
            con,
            params=[latest, *factor_ids],
        )
    if frame.empty:
        raise RuntimeError("no factor scores available for requested factors")
    return frame


def _build_weighted_scores(scores: pd.DataFrame, factors: list[dict[str, Any]]) -> pd.DataFrame:
    pivot = scores.pivot_table(index=["trade_date", "symbol"], columns="factor_id", values="value", aggfunc="last")
    result = pd.Series(0.0, index=pivot.index)
    for factor in factors:
        factor_id = str(factor["factor_id"])
        values = pivot[factor_id].astype(float)
        transformed = _transform(values, str(factor.get("transform") or "zscore"))
        result = result.add(transformed * float(factor.get("weight", 1.0)), fill_value=0.0)
    return result.rename("score").reset_index()


def _transform(values: pd.Series, transform: str) -> pd.Series:
    series = values.copy()
    if transform == "winsorize_zscore":
        lower = series.quantile(0.05)
        upper = series.quantile(0.95)
        series = series.clip(lower, upper)
    if transform in {"zscore", "winsorize_zscore"}:
        std = series.std(ddof=0)
        return (series - series.mean()) / std if std > 0 else series * 0.0
    return series


def _write_monitoring_snapshot(paths: RuntimePaths, instance: dict[str, Any], trade_date: str) -> None:
    date = pd.to_datetime(trade_date)
    value = pd.Series([1.0], index=[date])
    exposure = pd.Series([1.0], index=[date])
    frame = build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=value,
        benchmark_values=value,
        exposure=exposure,
        benchmark_id=str(instance.get("benchmark") or "510300"),
    )
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
