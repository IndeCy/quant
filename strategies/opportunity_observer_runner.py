"""产业机会观察策略运行器。"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class OpportunityObserverComputation:
    """机会观察策略的纯计算产物。"""

    result: dict[str, Any]
    selected: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    target_weights: dict[str, float]
    current_prices: dict[str, float]
    monitoring_frame: pd.DataFrame


def run_opportunity_observer_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """兼容入口：在当前线程依次计算并提交观察策略。"""
    computation = compute_opportunity_observer_instance(instance, paths, trade_date=trade_date)
    return persist_opportunity_observer_instance(instance, paths, computation)


def compute_opportunity_observer_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str | None = None,
) -> OpportunityObserverComputation:
    """只读投研池、价格和旧持仓，生成观察组合和待提交监控帧。"""
    strategy_id = str(instance["strategy_id"])
    target_date = trade_date or _today()
    theme_id = str((instance.get("config") or {}).get("theme_id") or "").strip()
    if not theme_id:
        raise ValueError("opportunity observer requires config.theme_id")

    theme = _load_opportunity_theme_readonly(paths.system_state_path, theme_id)
    selected, excluded = _select_holdings(theme, instance)
    target_weights = {item["symbol"]: float(item["weight"]) for item in selected}
    current_prices = _current_prices(paths, target_date, theme, list(target_weights))
    nav = _preview_observation_state(paths.system_state_path, strategy_id, current_prices)
    monitoring_frame = _build_monitoring_snapshot(paths, instance, target_date, nav, bool(selected))
    result = {"strategy_id": strategy_id, "trade_date": target_date, "selected_count": len(selected), "nav": nav}
    return OpportunityObserverComputation(
        result,
        selected,
        excluded,
        target_weights,
        current_prices,
        monitoring_frame,
    )


def persist_opportunity_observer_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    computation: OpportunityObserverComputation,
) -> dict[str, Any]:
    """串行提交观察状态、监控曲线和研究产物。"""
    result = computation.result
    strategy_id = str(result["strategy_id"])
    target_date = str(result["trade_date"])
    run_dir = paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_observation_state(
        paths,
        strategy_id,
        target_date,
        computation.target_weights,
        computation.current_prices,
        float(result["nav"]),
    )
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(computation.monitoring_frame)
    artifacts = _write_artifacts(
        run_dir,
        strategy_id,
        target_date,
        computation.selected,
        computation.excluded,
        float(result["nav"]),
    )
    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(
        strategy_id,
        target_date,
        "SUCCESS",
        run_dir,
        f"observation selected {len(computation.selected)} symbols",
    )
    for report_type, path in artifacts.items():
        repository.upsert_report(report_type, strategy_id, target_date, report_type, path, tags=["observation", "research"])
    return dict(result)


def _load_opportunity_theme_readonly(path: Path, theme_id: str) -> dict[str, Any]:
    """用只读连接加载主题，避免计算线程触发系统仓库 Schema 初始化。"""
    if not path.exists():
        raise KeyError(theme_id)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        theme = con.execute("SELECT * FROM opportunity_themes WHERE theme_id = ?", [theme_id]).fetchone()
        if theme is None:
            raise KeyError(theme_id)
        stocks = con.execute(
            "SELECT * FROM opportunity_stocks WHERE theme_id = ? ORDER BY watch_level, symbol",
            [theme_id],
        ).fetchall()
    result = _decode_row(theme)
    result["stocks"] = [_decode_row(row) for row in stocks]
    result["monitor_runs"] = []
    return result


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    if "evidence_json" in result:
        result["evidence"] = json.loads(result.pop("evidence_json") or "{}")
    if "metrics_json" in result:
        result["metrics"] = json.loads(result.pop("metrics_json") or "{}")
    if "tags_json" in result:
        result["tags"] = json.loads(result.pop("tags_json") or "[]")
    return result


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
    """兼容入口：预估并立即保存观察状态。"""
    nav = _preview_observation_state(paths.system_state_path, strategy_id, current_prices)
    _save_observation_state(paths, strategy_id, trade_date, target_weights, current_prices, nav)
    return nav


def _preview_observation_state(
    path: Path,
    strategy_id: str,
    current_prices: dict[str, float],
) -> float:
    """只读上一期持仓并预估观察净值。"""
    if not path.exists():
        return 1.0
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as con:
        state_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_instance_state'"
        ).fetchone()
        holdings_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_instance_holdings'"
        ).fetchone()
        state = None
        old_holdings = []
        if state_table:
            state = con.execute(
                "SELECT nav FROM strategy_instance_state WHERE strategy_id = ?",
                [strategy_id],
            ).fetchone()
        if holdings_table:
            old_holdings = con.execute(
                "SELECT symbol, weight, last_close FROM strategy_instance_holdings WHERE strategy_id = ?",
                [strategy_id],
            ).fetchall()
    previous_nav = float(state[0]) if state else 1.0
    holdings = [(str(row[0]), float(row[1]), float(row[2])) for row in old_holdings]
    return _estimate_next_nav(previous_nav, holdings, current_prices)


def _save_observation_state(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    nav: float,
) -> None:
    """只在串行提交阶段保存观察目标和净值。"""
    with sqlite3.connect(paths.system_state_path) as con:
        _init_state_schema(con)
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


def _build_monitoring_snapshot(
    paths: RuntimePaths,
    instance: dict[str, Any],
    trade_date: str,
    nav: float,
    invested: bool,
) -> pd.DataFrame:
    """只读已有历史并构造待提交观察监控帧。"""
    date = pd.to_datetime(trade_date, format="%Y%m%d")
    history = _load_monitoring_history(paths.monitoring_path, str(instance["strategy_id"]))
    if history.empty:
        values = pd.Series([nav], index=[date])
    else:
        existing = pd.Series(history["nav"].astype(float).values, index=pd.to_datetime(history["trade_date"], format="%Y%m%d"))
        values = pd.concat([existing[existing.index != date], pd.Series([nav], index=[date])]).sort_index()
    exposure = pd.Series(1.0 if invested else 0.0, index=values.index)
    return build_strategy_monitor_frame(
        strategy_id=str(instance["strategy_id"]),
        strategy_name=str(instance["name"]),
        daily_values=values,
        benchmark_values=None,
        exposure=exposure,
        benchmark_id=str(instance.get("benchmark") or "510300"),
    )


def _load_monitoring_history(path: Path, strategy_id: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as con:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_nav_daily'"
        ).fetchone()
        if table is None:
            return pd.DataFrame()
        return pd.read_sql_query(
            "SELECT * FROM strategy_nav_daily WHERE strategy_id = ? ORDER BY trade_date",
            con,
            params=[strategy_id],
        )


def _write_monitoring_snapshot(paths: RuntimePaths, instance: dict[str, Any], trade_date: str, nav: float, invested: bool) -> None:
    """兼容旧调用：构造后立即提交观察监控帧。"""
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(
        _build_monitoring_snapshot(paths, instance, trade_date, nav, invested)
    )


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
