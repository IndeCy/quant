"""产业机会观察池每日研究监控。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.cache import MarketDataCache
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_monitor_scoring import (
    build_observation_priority as _build_observation_priority,
    build_powerlaw_evidence as _build_powerlaw_evidence,
    classify_watch_level as _classify_watch_level,
    is_case_study_theme as _is_case_study_theme,
    is_formal_observation_stock as _is_formal_observation_stock,
    metric_float as _metric_float,
)


@dataclass(frozen=True)
class ResearchMonitorResult:
    """研究监控运行摘要。"""

    trade_date: str
    theme_count: int
    stock_count: int
    upgrade_candidates: int


def format_research_monitor_notification(result: ResearchMonitorResult) -> str:
    """投研监控 Bark 摘要模板，保持每天消息结构稳定。"""
    return "\n".join(
        [
            "投研监控状态：SUCCESS",
            f"交易日：{result.trade_date}",
            f"观察主题：{result.theme_count}",
            f"观察股票：{result.stock_count}",
            f"升级候选：{result.upgrade_candidates}",
            f"是否需要关注：{'是' if result.upgrade_candidates > 0 else '否'}",
        ]
    )


def run_research_monitor(paths: RuntimePaths | None = None) -> ResearchMonitorResult:
    """运行所有机会池研究监控，更新研究指标和升级建议。"""
    runtime_paths = paths or get_runtime_paths()
    repository = SystemRepository(runtime_paths.system_state_path)
    themes = repository.list_opportunity_themes()
    latest_trade_date = _latest_cache_date(runtime_paths.data_dir / "market_cache.sqlite3") or date.today().strftime("%Y%m%d")
    stock_count = 0
    upgrade_candidates = 0
    for theme in themes:
        stock_levels: list[str] = []
        stock_evidence: list[dict[str, Any]] = []
        eligible_levels: list[str] = []
        eligible_evidence: list[dict[str, Any]] = []
        for stock in theme.get("stocks", []):
            metrics = _build_stock_metrics(runtime_paths, str(stock["symbol"]))
            evidence = _build_powerlaw_evidence(runtime_paths, metrics, theme)
            if isinstance(stock.get("evidence"), dict) and stock["evidence"].get("verification"):
                evidence["verification"] = stock["evidence"]["verification"]
            evidence["priority"] = _build_observation_priority(metrics, evidence, stock)
            level = _classify_watch_level(metrics, evidence, theme)
            repository.update_opportunity_stock_monitor(
                str(theme["theme_id"]),
                str(stock["symbol"]),
                level,
                metrics,
                latest_trade_date,
                evidence,
            )
            stock_levels.append(level)
            stock_evidence.append(evidence)
            if _is_formal_observation_stock(stock):
                eligible_levels.append(level)
                eligible_evidence.append(evidence)
            stock_count += 1
        theme_metrics = _theme_metrics(stock_levels, theme, stock_evidence, eligible_levels, eligible_evidence)
        if theme_metrics["upgrade_candidate"]:
            upgrade_candidates += 1
        summary = _summary(theme_metrics)
        repository.record_research_monitor_run(
            str(theme["theme_id"]),
            latest_trade_date,
            "SUCCESS",
            summary,
            theme_metrics,
        )
        repository.record_opportunity_direction_ranking(latest_trade_date, theme, theme_metrics, summary)
    return ResearchMonitorResult(latest_trade_date, len(themes), stock_count, upgrade_candidates)


def _build_stock_metrics(paths: RuntimePaths, symbol: str) -> dict[str, Any]:
    bars = _load_bars(paths, symbol)
    metrics: dict[str, Any] = {"symbol": symbol, "data_status": "missing"}
    if bars.empty:
        return metrics
    close = bars["close"].astype(float)
    returns = close.pct_change().dropna()
    metrics.update(
        {
            "data_status": "ok",
            "latest_date": close.index[-1].strftime("%Y%m%d"),
            "latest_close": float(close.iloc[-1]),
            "ret_60d": _return(close, 60),
            "ret_120d": _return(close, 120),
            "ret_250d": _return(close, 250),
            "ret_1y": _return(close, 250),
            "ret_2y": _return(close, 500),
            "vol_60d": float(returns.tail(60).std(ddof=1) * math.sqrt(252)) if len(returns.tail(60)) >= 2 else 0.0,
            "drawdown_120d": _drawdown(close.tail(120)),
            "drawdown_250d": _drawdown(close.tail(250)),
            "distance_to_high_250d": _distance_to_high(close.tail(250)),
        }
    )
    metrics.update(_latest_financial_metrics(paths.root, symbol))
    metrics.update(_relative_strength_metrics(paths, close))
    return metrics


def _load_bars(paths: RuntimePaths, symbol: str) -> pd.DataFrame:
    cache = MarketDataCache(paths.data_dir / "market_cache.sqlite3")
    try:
        for provider in ["tushare", "tencent"]:
            bars = cache.read_bars(provider, symbol, "1d", "qfq", date(2000, 1, 1), date.today())
            if len(bars) >= 251:
                return bars
    finally:
        cache.close()
    return _load_bars_from_live_view(paths, symbol)


def _load_bars_from_live_view(paths: RuntimePaths, symbol: str) -> pd.DataFrame:
    """SQLite 缓存历史不足时，从 DuckDB 基线+增量视图读取完整前复权行情。"""
    base_path = paths.base_market_path
    if not base_path.exists() or not paths.live_market_increment_path.exists():
        return pd.DataFrame()
    try:
        from data.market_snapshot import create_market_snapshot

        snapshot = create_market_snapshot(
            base_path,
            paths.live_market_increment_path,
            date.today().strftime("%Y%m%d"),
            lookback_start="20000101",
            adjust_policy="qfq",
        )
        frame = snapshot.load_daily_bars(symbol).reset_index()
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume", "amount"]]


def _latest_financial_metrics(root: Path, symbol: str) -> dict[str, Any]:
    path = root / "fina_indicator.duckdb"
    if not path.exists():
        return {}
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as con:
            row = con.execute(
                """
                SELECT end_date, roe, roa, grossprofit_margin, ocf_to_or, tr_yoy, netprofit_yoy
                FROM default_table
                WHERE ts_code = ?
                ORDER BY end_date DESC
                LIMIT 1
                """,
                [symbol],
            ).fetchone()
    except Exception:
        return {}
    if row is None:
        return {}
    keys = ["finance_end_date", "roe", "roa", "grossprofit_margin", "ocf_to_or", "tr_yoy", "netprofit_yoy"]
    return {key: _float_or_text(value) for key, value in zip(keys, row)}


def _relative_strength_metrics(paths: RuntimePaths, close: pd.Series) -> dict[str, Any]:
    benchmark = _load_benchmark_close(paths.data_dir / "market_cache.sqlite3")
    if benchmark.empty:
        return {"benchmark_status": "missing", "relative_strength_250d": None}
    aligned = pd.concat([close.rename("stock"), benchmark.rename("benchmark")], axis=1).dropna()
    if len(aligned) < 251:
        return {"benchmark_status": "insufficient", "relative_strength_250d": None}
    stock_return = _return(aligned["stock"], 250)
    benchmark_return = _return(aligned["benchmark"], 250)
    if stock_return is None or benchmark_return is None:
        return {"benchmark_status": "insufficient", "relative_strength_250d": None}
    return {
        "benchmark_status": "ok",
        "benchmark_ret_250d": benchmark_return,
        "relative_strength_250d": float(stock_return - benchmark_return),
    }


def _load_benchmark_close(cache_path: Path) -> pd.Series:
    cache = MarketDataCache(cache_path)
    try:
        for provider in ["tushare", "tencent"]:
            for symbol in ["510300.SH", "510300"]:
                bars = cache.read_bars(provider, symbol, "1d", "qfq", date(2000, 1, 1), date.today())
                if not bars.empty:
                    return bars["close"].astype(float)
    finally:
        cache.close()
    return pd.Series(dtype=float)


def _theme_metrics(
    levels: list[str],
    theme: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    eligible_levels: list[str] | None = None,
    eligible_evidence_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    formal_levels = eligible_levels or []
    formal_evidence = eligible_evidence_items or []
    strong = sum(1 for level in formal_levels if level in {"S", "A"})
    case_study = _is_case_study_theme(theme)
    early = _average_metric(formal_evidence, "early_signal_score")
    maturity = _average_metric(formal_evidence, "maturity_score")
    crowding = _average_metric(formal_evidence, "crowding_score")
    strength = _direction_strength_score(early, maturity, crowding, strong, len(formal_levels), case_study)
    return {
        "stock_count": len(levels),
        "eligible_stock_count": len(formal_levels),
        "seed_stock_count": len(levels) - len(formal_levels),
        "s_count": formal_levels.count("S"),
        "a_count": formal_levels.count("A"),
        "b_count": formal_levels.count("B"),
        "case_count": levels.count("案例") + levels.count("校准"),
        "mature_count": formal_levels.count("成熟"),
        "rejected_count": formal_levels.count("淘汰"),
        "case_study": case_study,
        "theme_early_signal_score": early,
        "theme_maturity_score": maturity,
        "theme_crowding_score": crowding,
        "strength_score": strength,
        "upgrade_candidate": False if case_study else strong >= 3,
    }


def _average_metric(items: list[dict[str, Any]], key: str) -> float:
    values = [float(item.get(key) or 0.0) for item in items if item]
    return float(sum(values) / len(values)) if values else 0.0


def _direction_strength_score(
    early_signal_score: float,
    maturity_score: float,
    crowding_score: float,
    strong_count: int,
    stock_count: int,
    case_study: bool,
) -> float:
    """计算产业方向每日排序分，越高越值得继续前置研究。"""
    breadth_bonus = 20.0 * strong_count / stock_count if stock_count else 0.0
    raw = early_signal_score + breadth_bonus - 0.35 * maturity_score - 0.25 * crowding_score
    if case_study:
        raw *= 0.25
    return float(max(0.0, min(100.0, raw)))


def _summary(metrics: dict[str, Any]) -> str:
    if metrics.get("case_study"):
        return f"{metrics['case_count']} 个案例样本，用于校准早期识别规则，不作为未来机会升级候选"
    if metrics.get("eligible_stock_count", 0) <= 0:
        return f"已验证入池股票不足，{metrics.get('seed_stock_count', 0)} 个候选种子仅供人工校验"
    if metrics["upgrade_candidate"]:
        return f"{metrics['s_count']} 个S级、{metrics['a_count']} 个A级，建议进入可结构化策略草案评估"
    return f"{metrics['s_count']} 个S级、{metrics['a_count']} 个A级，继续观察"


def _latest_cache_date(cache_path: Path) -> str | None:
    if not cache_path.exists():
        return None
    cache = MarketDataCache(cache_path)
    try:
        row = cache.conn.execute(
            """
            SELECT MAX(trade_time) FROM market_ohlcv_bar
            WHERE provider IN ('tushare', 'tencent') AND adjust = 'qfq'
            """
        ).fetchone()
    finally:
        cache.close()
    if row is None or row[0] is None:
        return None
    return pd.Timestamp(row[0]).strftime("%Y%m%d")


def _return(close: pd.Series, window: int) -> float | None:
    if len(close) < window + 1:
        return None
    base = float(close.iloc[-window - 1])
    return float(close.iloc[-1] / base - 1.0) if base > 0 else None


def _drawdown(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    return float((close / close.cummax() - 1.0).min())


def _distance_to_high(close: pd.Series) -> float:
    """计算当前价格距离窗口高点的比例，越接近0代表修复能力越强。"""
    if close.empty:
        return 0.0
    high = float(close.max())
    latest = float(close.iloc[-1])
    return float(latest / high - 1.0) if high > 0 else 0.0


def _float_or_text(value: Any) -> Any:
    try:
        return float(value)
    except Exception:
        return value
