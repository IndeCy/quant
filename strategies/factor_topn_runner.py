"""多因子 TopN 策略实例运行器。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import duckdb
import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def run_factor_topn_monthly_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]:
    """运行一个配置化多因子 TopN 策略实例。"""
    strategy_id = str(instance["strategy_id"])
    scores = _load_latest_scores(paths.factor_scores_path, [item["factor_id"] for item in instance["factors"]])
    weighted = _build_weighted_scores(scores, instance["factors"])
    top_n = int(instance.get("construction", {}).get("top_n", 20))
    selected = weighted.sort_values(["score", "symbol"], ascending=[False, True]).head(top_n)
    trade_date = str(selected["trade_date"].iloc[0])
    symbols = selected["symbol"].tolist()
    weights = {symbol: 1.0 / len(symbols) for symbol in symbols} if symbols else {}
    nav_result = _update_paper_state(paths, strategy_id, trade_date, weights)

    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / f"{strategy_id}_rebalance_plan.csv"
    snapshot_path = run_dir / f"{strategy_id}_portfolio_snapshot.csv"
    target_frame = pd.DataFrame({"symbol": list(weights), "target_weight": list(weights.values())})
    target_frame.to_csv(plan_path, index=False)
    target_frame.to_csv(snapshot_path, index=False)

    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(
        strategy_id,
        trade_date,
        "SUCCESS",
        run_dir,
        f"selected {len(symbols)} symbols, nav {nav_result['nav']:.6f}",
    )
    repository.upsert_report(
        "rebalance_plan",
        strategy_id,
        trade_date,
        "调仓建议",
        plan_path,
        tags=["strategy_instance", "rebalance"],
    )
    repository.upsert_report(
        "portfolio_snapshot",
        strategy_id,
        trade_date,
        "目标组合快照",
        snapshot_path,
        tags=["strategy_instance", "portfolio"],
    )
    _write_monitoring_snapshot(paths, instance, trade_date, float(nav_result["nav"]))
    return {
        "strategy_id": strategy_id,
        "trade_date": trade_date,
        "selected_count": len(symbols),
        "symbols": symbols,
        "target_weights": weights,
        "nav": float(nav_result["nav"]),
    }


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


def _update_paper_state(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    target_weights: dict[str, float],
) -> dict[str, float]:
    """按上一期持仓估值并保存新目标持仓，形成可连续观测的 paper NAV。"""
    with sqlite3.connect(paths.system_state_path) as con:
        _init_paper_state_schema(con)
        state = con.execute(
            """
            SELECT trade_date, nav
            FROM strategy_instance_state
            WHERE strategy_id = ?
            """,
            [strategy_id],
        ).fetchone()
        old_holdings = con.execute(
            """
            SELECT symbol, weight, last_close
            FROM strategy_instance_holdings
            WHERE strategy_id = ?
            """,
            [strategy_id],
        ).fetchall()
        previous_nav = float(state[1]) if state else 1.0
        nav = _estimate_next_nav(paths, trade_date, previous_nav, old_holdings)
        prices = _load_prices(paths, trade_date, list(target_weights))
        con.execute(
            """
            INSERT INTO strategy_instance_state(strategy_id, trade_date, nav)
            VALUES (?, ?, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
                trade_date=excluded.trade_date,
                nav=excluded.nav,
                modified_at=CURRENT_TIMESTAMP
            """,
            [strategy_id, trade_date, nav],
        )
        con.execute("DELETE FROM strategy_instance_holdings WHERE strategy_id = ?", [strategy_id])
        con.executemany(
            """
            INSERT INTO strategy_instance_holdings(strategy_id, symbol, weight, last_close)
            VALUES (?, ?, ?, ?)
            """,
            [(strategy_id, symbol, weight, prices.get(symbol, 0.0)) for symbol, weight in target_weights.items()],
        )
    return {"nav": nav}


def _estimate_next_nav(
    paths: RuntimePaths,
    trade_date: str,
    previous_nav: float,
    old_holdings: list[tuple[str, float, float]],
) -> float:
    """用上一期持仓的价格变化估计今日净值；首日或缺价格时保持上一净值。"""
    if not old_holdings:
        return previous_nav
    symbols = [str(row[0]) for row in old_holdings]
    prices = _load_prices(paths, trade_date, symbols)
    if not prices:
        return previous_nav
    portfolio_return = 0.0
    valid_weight = 0.0
    for symbol, weight, last_close in old_holdings:
        close = prices.get(str(symbol))
        if close is None or float(last_close) <= 0:
            continue
        valid_weight += float(weight)
        portfolio_return += float(weight) * (float(close) / float(last_close) - 1.0)
    if valid_weight <= 0:
        return previous_nav
    return previous_nav * (1.0 + portfolio_return)


def _init_paper_state_schema(con: sqlite3.Connection) -> None:
    """初始化配置化策略实例的轻量 paper 持仓状态。"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_instance_state (
            strategy_id TEXT NOT NULL PRIMARY KEY,
            trade_date TEXT NOT NULL,
            nav REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_instance_holdings (
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            weight REAL NOT NULL,
            last_close REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(strategy_id, symbol)
        )
        """
    )


def _load_prices(paths: RuntimePaths, trade_date: str, symbols: list[str]) -> dict[str, float]:
    """读取标准价格快照；优先 SQLite 标准表，缺失时回退 Tushare 增量 DuckDB。"""
    if not symbols:
        return {}
    sqlite_prices = _load_sqlite_prices(paths.factor_scores_path, trade_date, symbols)
    if sqlite_prices:
        return sqlite_prices
    return _load_duckdb_prices(paths.live_market_increment_path, trade_date, symbols)


def _load_sqlite_prices(path: Path, trade_date: str, symbols: list[str]) -> dict[str, float]:
    if not path.exists():
        return {}
    placeholders = ",".join("?" for _ in symbols)
    with sqlite3.connect(path) as con:
        exists = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_prices'"
        ).fetchone()
        if exists is None:
            return {}
        rows = con.execute(
            f"""
            SELECT symbol, close
            FROM daily_prices
            WHERE trade_date = ? AND symbol IN ({placeholders})
            """,
            [trade_date, *symbols],
        ).fetchall()
    return {str(symbol): float(close) for symbol, close in rows if close is not None and float(close) > 0}


def _load_duckdb_prices(path: Path, trade_date: str, symbols: list[str]) -> dict[str, float]:
    if not path.exists():
        return {}
    placeholders = ",".join("?" for _ in symbols)
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            rows = con.execute(
                f"""
                SELECT ts_code, close
                FROM daily
                WHERE trade_date = ? AND ts_code IN ({placeholders})
                """,
                [trade_date, *symbols],
            ).fetchall()
    except Exception:
        return {}
    return {str(symbol): float(close) for symbol, close in rows if close is not None and float(close) > 0}


def _write_monitoring_snapshot(paths: RuntimePaths, instance: dict[str, Any], trade_date: str, nav: float) -> None:
    date = pd.to_datetime(trade_date)
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history(str(instance["strategy_id"]))
    if history.empty:
        values = pd.Series([nav], index=[date])
    else:
        existing = pd.Series(history["nav"].astype(float).values, index=pd.to_datetime(history["trade_date"], format="%Y%m%d"))
        values = pd.concat([existing[existing.index != date], pd.Series([nav], index=[date])]).sort_index()
    exposure = pd.Series(1.0, index=values.index)
    frame = build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=values,
        benchmark_values=values,
        exposure=exposure,
        benchmark_id=str(instance.get("benchmark") or "510300"),
    )
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
