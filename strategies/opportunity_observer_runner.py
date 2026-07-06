"""产业机会观察策略运行器。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

import duckdb
import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def run_opportunity_observer_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]:
    """运行观察策略，生成观察组合和净值曲线，不生成交易建议。"""
    repository = SystemRepository(paths.system_state_path)
    strategy_id = str(instance["strategy_id"])
    trade_date = _today()
    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    theme_id = str((instance.get("config") or {}).get("theme_id") or "").strip()
    if not theme_id:
        raise ValueError("opportunity observer requires config.theme_id")

    theme = repository.load_opportunity_theme(theme_id)
    selected, excluded = _select_holdings(theme, instance)
    target_weights = {item["symbol"]: float(item["weight"]) for item in selected}
    current_prices = _current_prices(paths, trade_date, theme, list(target_weights))
    nav = _update_observation_state(paths, strategy_id, trade_date, target_weights, current_prices)
    _write_monitoring_snapshot(paths, instance, trade_date, nav, bool(selected))
    artifacts = _write_artifacts(run_dir, strategy_id, trade_date, selected, excluded, nav)
    repository.record_strategy_run(strategy_id, trade_date, "SUCCESS", run_dir, f"observation selected {len(selected)} symbols")
    for report_type, path in artifacts.items():
        repository.upsert_report(report_type, strategy_id, trade_date, report_type, path, tags=["observation", "research"])
    return {"strategy_id": strategy_id, "trade_date": trade_date, "selected_count": len(selected), "nav": nav}


def _today() -> str:
    """返回当前运行日期，测试中可替换。"""
    return datetime.now().strftime("%Y%m%d")


def _select_holdings(theme: dict[str, Any], instance: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = dict(instance.get("config") or {})
    construction = dict(instance.get("construction") or {})
    top_n = int(construction.get("top_n") or 5)
    exclude_mature = bool(config.get("exclude_mature", True))
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for stock in theme.get("stocks", []):
        row = _stock_row(stock)
        level = row["watch_level"]
        if stock.get("status") != "active" or stock.get("verification_status") != "verified":
            row["exclude_reason"] = "未通过正式入池校验"
            excluded.append(row)
            continue
        if level == "淘汰":
            row["exclude_reason"] = "观察级别为淘汰"
            excluded.append(row)
            continue
        if exclude_mature and level == "成熟":
            row["exclude_reason"] = "成熟样本默认不进入观察组合"
            excluded.append(row)
            continue
        candidates.append(row)
    candidates.sort(key=lambda item: (-float(item["priority_score"]), str(item["symbol"])))
    selected = candidates[:top_n]
    weight = 1.0 / len(selected) if selected else 0.0
    for item in selected:
        item["weight"] = weight
    return selected, excluded


def _stock_row(stock: dict[str, Any]) -> dict[str, Any]:
    evidence = stock.get("evidence") if isinstance(stock.get("evidence"), dict) else {}
    priority = evidence.get("priority") if isinstance(evidence.get("priority"), dict) else {}
    metrics = stock.get("metrics") if isinstance(stock.get("metrics"), dict) else {}
    return {
        "symbol": str(stock.get("symbol") or ""),
        "name": str(stock.get("name") or ""),
        "watch_level": str(stock.get("watch_level") or ""),
        "priority_score": float(priority.get("score") or 0.0),
        "reason": "；".join(str(item) for item in priority.get("reasons") or []),
        "last_close": float(metrics.get("latest_close") or 0.0),
    }


def _current_prices(paths: RuntimePaths, trade_date: str, theme: dict[str, Any], symbols: list[str]) -> dict[str, float]:
    """读取当前价格，优先标准行情缓存，缺失时使用投研监控中的最新价。"""
    prices = _load_prices(paths, trade_date, symbols)
    if len(prices) == len(symbols):
        return prices
    for stock in theme.get("stocks", []):
        symbol = str(stock.get("symbol") or "")
        if symbol not in symbols or symbol in prices:
            continue
        metrics = stock.get("metrics") if isinstance(stock.get("metrics"), dict) else {}
        latest_close = float(metrics.get("latest_close") or 0.0)
        if latest_close > 0:
            prices[symbol] = latest_close
    return prices


def _update_observation_state(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    target_weights: dict[str, float],
    current_prices: dict[str, float],
) -> float:
    """用上一期观察持仓估算今日净值，并保存新的观察目标持仓。"""
    with sqlite3.connect(paths.system_state_path) as con:
        _init_state_schema(con)
        state = con.execute(
            "SELECT nav FROM strategy_instance_state WHERE strategy_id = ?",
            [strategy_id],
        ).fetchone()
        previous_nav = float(state[0]) if state else 1.0
        old_holdings = con.execute(
            "SELECT symbol, weight, last_close FROM strategy_instance_holdings WHERE strategy_id = ?",
            [strategy_id],
        ).fetchall()
        nav = _estimate_next_nav(previous_nav, old_holdings, current_prices)
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
            [(strategy_id, symbol, weight, current_prices.get(symbol, 0.0)) for symbol, weight in target_weights.items()],
        )
    return float(nav)


def _estimate_next_nav(previous_nav: float, old_holdings: list[tuple[str, float, float]], current_prices: dict[str, float]) -> float:
    """根据上一期持仓价格变化滚动净值；缺价格时保守保持上一净值。"""
    if not old_holdings:
        return previous_nav
    portfolio_return = 0.0
    valid_weight = 0.0
    for symbol, weight, last_close in old_holdings:
        close = current_prices.get(str(symbol))
        if close is None or float(last_close) <= 0:
            continue
        valid_weight += float(weight)
        portfolio_return += float(weight) * (float(close) / float(last_close) - 1.0)
    if valid_weight <= 0:
        return previous_nav
    return float(previous_nav * (1.0 + portfolio_return))


def _write_monitoring_snapshot(paths: RuntimePaths, instance: dict[str, Any], trade_date: str, nav: float, invested: bool) -> None:
    """把观察净值写入统一策略监控表，供前端曲线复用。"""
    date = pd.to_datetime(trade_date, format="%Y%m%d")
    monitoring = MonitoringRepository(paths.monitoring_path)
    history = monitoring.load_strategy_history(str(instance["strategy_id"]))
    if history.empty:
        values = pd.Series([nav], index=[date])
    else:
        existing = pd.Series(history["nav"].astype(float).values, index=pd.to_datetime(history["trade_date"], format="%Y%m%d"))
        values = pd.concat([existing[existing.index != date], pd.Series([nav], index=[date])]).sort_index()
    exposure = pd.Series(1.0 if invested else 0.0, index=values.index)
    frame = build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=values,
        benchmark_values=None,
        exposure=exposure,
        benchmark_id=str(instance.get("benchmark") or "510300"),
    )
    monitoring.upsert_strategy_daily(frame)


def _write_artifacts(
    run_dir: Path,
    strategy_id: str,
    trade_date: str,
    selected: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    nav: float,
) -> dict[str, Path]:
    snapshot_path = run_dir / f"{strategy_id}_snapshot.csv"
    metrics_path = run_dir / f"{strategy_id}_metrics.json"
    report_path = run_dir / f"{strategy_id}_report.md"
    pd.DataFrame(selected).to_csv(snapshot_path, index=False)
    metrics_path.write_text(
        json.dumps(
            {
                "trade_date": trade_date,
                "strategy_id": strategy_id,
                "nav": nav,
                "selected_count": len(selected),
                "excluded_count": len(excluded),
                "trade_policy": "observation_only",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path.write_text(_report_text(trade_date, selected, excluded), encoding="utf-8")
    return {"observation_snapshot": snapshot_path, "observation_metrics": metrics_path, "observation_report": report_path}


def _report_text(trade_date: str, selected: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    lines = [
        "# 创新药出海观察策略 V0",
        "",
        f"- 交易日：{trade_date}",
        "- 状态：观察策略，不构成调仓建议",
        f"- 入选数量：{len(selected)}",
        f"- 排除数量：{len(excluded)}",
        "",
        "## 当前观察组合",
    ]
    if not selected:
        lines.append("- 空仓观察")
    for item in selected:
        lines.append(f"- {item['symbol']} {item['name']}，权重 {float(item['weight']):.2%}，优先级 {float(item['priority_score']):.2f}")
    if excluded:
        lines.extend(["", "## 排除样本"])
        for item in excluded:
            lines.append(f"- {item['symbol']} {item['name']}：{item.get('exclude_reason', '未入选')}")
    return "\n".join(lines)


def _init_state_schema(con: sqlite3.Connection) -> None:
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
        exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_prices'").fetchone()
        if exists is None:
            return {}
        rows = con.execute(
            f"SELECT symbol, close FROM daily_prices WHERE trade_date = ? AND symbol IN ({placeholders})",
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
                f"SELECT ts_code, close FROM daily WHERE trade_date = ? AND ts_code IN ({placeholders})",
                [trade_date, *symbols],
            ).fetchall()
    except Exception:
        return {}
    return {str(symbol): float(close) for symbol, close in rows if close is not None and float(close) > 0}
