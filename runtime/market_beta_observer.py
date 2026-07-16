"""统一大盘 beta 观测与状态评分。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.hot_money_emotion import build_market_emotion_daily
from runtime.market_breadth_liquidity import build_breadth_liquidity_frame, load_recent_daily_bars
from runtime.paths import RuntimePaths, get_runtime_paths


@dataclass(frozen=True)
class MarketBetaSnapshot:
    """单日 beta 观测快照，供监控库、API 和前端共用。"""

    trade_date: str
    beta_state: str
    beta_score: float
    trend_score: float
    breadth_score: float
    sentiment_score: float
    liquidity_score: float
    funding_score: float
    valuation_score: float
    risk_level: str
    reasons: list[str]

    def to_record(self) -> dict[str, Any]:
        """转换为仓库写入需要的普通字典。"""
        return asdict(self)


def build_market_beta_snapshot(
    trade_date: str,
    market_history: pd.DataFrame,
    beta_data: dict[str, float] | None = None,
) -> MarketBetaSnapshot:
    """根据市场历史和扩展 beta 数据生成单日状态。"""
    if market_history.empty:
        return MarketBetaSnapshot(trade_date, "NEUTRAL", 50.0, 15.0, 12.5, 10.0, 7.5, 5.0, 5.0, "MEDIUM", ["市场数据为空，使用中性状态"])
    history = market_history.copy()
    history["trade_date"] = history["trade_date"].astype(str)
    history = history[history["trade_date"] <= trade_date].tail(120)
    if history.empty:
        history = market_history.copy().tail(120)
    trend_score, trend_reasons, crash_flag = compute_trend_metrics(history)
    breadth_score, breadth_reasons = compute_breadth_metrics(history)
    sentiment_score, sentiment_reasons, sentiment_crash = compute_sentiment_metrics(history)
    liquidity_score, liquidity_reasons = compute_liquidity_metrics(history)
    funding_score, valuation_score, funding_reasons = compute_funding_metrics(beta_data or {})
    score = round(
        trend_score + breadth_score + sentiment_score + liquidity_score + funding_score + valuation_score,
        2,
    )
    state, risk_level = classify_beta_state(score, crash_flag or sentiment_crash)
    reasons = [*trend_reasons, *breadth_reasons, *sentiment_reasons, *liquidity_reasons, *funding_reasons]
    return MarketBetaSnapshot(
        trade_date=trade_date,
        beta_state=state,
        beta_score=score,
        trend_score=round(trend_score, 2),
        breadth_score=round(breadth_score, 2),
        sentiment_score=round(sentiment_score, 2),
        liquidity_score=round(liquidity_score, 2),
        funding_score=round(funding_score, 2),
        valuation_score=round(valuation_score, 2),
        risk_level=risk_level,
        reasons=reasons[:8],
    )


def compute_trend_metrics(history: pd.DataFrame) -> tuple[float, list[str], bool]:
    """趋势 beta：看指数均线、20日收益和当前回撤。"""
    latest = history.iloc[-1]
    nav = pd.to_numeric(history["benchmark_nav"], errors="coerce").dropna()
    current = float(latest.get("benchmark_nav") or nav.iloc[-1])
    ma60 = float(latest.get("ma60") or nav.rolling(60, min_periods=1).mean().iloc[-1])
    ma120 = float(latest.get("ma120") or nav.rolling(120, min_periods=1).mean().iloc[-1])
    ret20 = current / float(nav.iloc[-21]) - 1.0 if len(nav) >= 21 and float(nav.iloc[-21]) else 0.0
    drawdown = float(latest.get("benchmark_drawdown") or current / float(nav.cummax().iloc[-1]) - 1.0)
    score = 0.0
    reasons: list[str] = []
    if current >= ma60 >= ma120:
        score += 15.0
        reasons.append("指数站上MA60且MA60高于MA120")
    elif current >= ma60:
        score += 10.0
        reasons.append("指数站上MA60但中期趋势仍需确认")
    elif current < ma120:
        score += 3.0
        reasons.append("指数低于MA120，趋势 beta 偏弱")
    else:
        score += 7.0
        reasons.append("指数处于均线纠缠区")
    if ret20 > 0.05:
        score += 10.0
        reasons.append("20日指数收益明显为正")
    elif ret20 > -0.03:
        score += 6.0
        reasons.append("20日指数收益未显著走弱")
    else:
        score += 1.0
        reasons.append("20日指数跌幅较大")
    if drawdown > -0.08:
        score += 5.0
    elif drawdown > -0.18:
        score += 2.0
        reasons.append("指数处于中等回撤")
    else:
        reasons.append("指数回撤较深")
    return min(score, 30.0), reasons, ret20 <= -0.15 or drawdown <= -0.25


def compute_breadth_metrics(history: pd.DataFrame) -> tuple[float, list[str]]:
    """宽度 beta：看上涨家数占比。"""
    latest = history.iloc[-1]
    up = float(latest.get("breadth_up_count") or 0.0)
    down = float(latest.get("breadth_down_count") or 0.0)
    total = up + down
    ratio = up / total if total else 0.5
    if ratio >= 0.65:
        return 25.0, [f"上涨占比{ratio:.1%}，赚钱效应扩散"]
    if ratio >= 0.5:
        return 18.0, [f"上涨占比{ratio:.1%}，宽度中性偏强"]
    if ratio >= 0.35:
        return 10.0, [f"上涨占比{ratio:.1%}，宽度偏弱"]
    return 3.0, [f"上涨占比{ratio:.1%}，宽度显著恶化"]


def compute_sentiment_metrics(history: pd.DataFrame) -> tuple[float, list[str], bool]:
    """情绪 beta：看涨停、跌停和极端亏钱效应。"""
    latest = history.iloc[-1]
    limit_up = float(latest.get("limit_up_count") or 0.0)
    limit_down = float(latest.get("limit_down_count") or 0.0)
    if limit_down >= 80:
        return 1.0, [f"跌停{int(limit_down)}家，极端亏钱效应"], True
    if limit_down >= 30:
        return 5.0, [f"跌停{int(limit_down)}家，情绪退潮"], False
    if limit_up >= 50 and limit_down <= 10:
        return 20.0, [f"涨停{int(limit_up)}家且跌停较少，情绪活跃"], False
    if limit_up >= 20:
        return 14.0, [f"涨停{int(limit_up)}家，情绪中性偏强"], False
    return 9.0, ["涨停扩散不足，情绪中性偏弱"], False


def compute_liquidity_metrics(history: pd.DataFrame) -> tuple[float, list[str]]:
    """流动性 beta：优先使用全市场成交额与无成交比例。"""
    if "market_amount" not in history.columns:
        return 7.5, ["全市场成交额未沉淀，流动性使用中性分"]
    amount = pd.to_numeric(history["market_amount"], errors="coerce").dropna()
    if amount.empty:
        return 7.5, ["成交额为空，流动性使用中性分"]
    latest = float(amount.iloc[-1])
    amount_ma20 = pd.to_numeric(history.get("amount_ma20", pd.Series(dtype=float)), errors="coerce").dropna()
    mean20 = float(amount_ma20.iloc[-1]) if not amount_ma20.empty and float(amount_ma20.iloc[-1]) > 0 else float(amount.tail(20).mean())
    if mean20 <= 0:
        return 7.5, ["成交额基准不足，流动性使用中性分"]
    ratio = latest / mean20
    zero_ratio = _latest_numeric(history, "zero_volume_ratio", 0.0)
    penalty = 2.0 if zero_ratio >= 0.08 else 0.0
    zero_reason = f"，无成交比例{zero_ratio:.1%}偏高" if penalty else ""
    if ratio >= 1.15:
        return max(0.0, 15.0 - penalty), [f"成交额高于20日均值，流动性改善{zero_reason}"]
    if ratio >= 0.85:
        return max(0.0, 10.0 - penalty), [f"成交额接近20日均值，流动性中性{zero_reason}"]
    return max(0.0, 4.0 - penalty), [f"成交额低于20日均值，流动性收缩{zero_reason}"]


def compute_funding_metrics(beta_data: dict[str, float]) -> tuple[float, float, list[str]]:
    """资金和估值 beta：缺失时明确降级为中性。"""
    reasons: list[str] = []
    if not beta_data:
        return 5.0, 5.0, ["资金/估值扩展数据缺失，使用中性分"]
    north = float(beta_data.get("north_money") or 0.0)
    margin_balance = float(beta_data.get("rzrqye") or 0.0)
    pe_ttm = float(beta_data.get("pe_ttm") or 0.0)
    funding_score = 5.0
    if north > 10:
        funding_score += 3.0
        reasons.append("北向资金净流入")
    elif north < -10:
        funding_score -= 3.0
        reasons.append("北向资金净流出")
    if margin_balance > 0:
        funding_score += 1.0
        reasons.append("两融余额数据有效")
    valuation_score = 5.0
    if 0 < pe_ttm <= 15:
        valuation_score += 3.0
        reasons.append("指数估值处于偏低区间")
    elif pe_ttm >= 25:
        valuation_score -= 2.0
        reasons.append("指数估值偏高")
    return max(0.0, min(funding_score, 5.0)), max(0.0, min(valuation_score, 5.0)), reasons or ["资金/估值数据中性"]


def classify_beta_state(score: float, crash_flag: bool = False) -> tuple[str, str]:
    """把 beta 总分转成状态枚举和风险等级。"""
    if crash_flag or score < 25:
        return "CRASH_RISK", "HIGH"
    if score < 45:
        return "BETA_OFF", "ELEVATED"
    if score < 70:
        return "NEUTRAL", "MEDIUM"
    return "BETA_ON", "LOW"


def record_market_beta_snapshot(paths: RuntimePaths | None = None, trade_date: str | None = None) -> dict[str, object]:
    """从监控库和 beta 增量库生成并保存当日 beta 快照。"""
    runtime_paths = paths or get_runtime_paths()
    repository = MonitoringRepository(runtime_paths.monitoring_path)
    market = repository.load_market_history("510300")
    if market.empty:
        return {"status": "SKIPPED", "message": "market_beta skipped=no_market_history"}
    target_date = trade_date or str(market.iloc[-1]["trade_date"])
    _refresh_market_breadth_liquidity(repository, runtime_paths, target_date)
    market = repository.load_market_history("510300")
    beta_data = load_beta_inputs(runtime_paths, target_date)
    snapshot = build_market_beta_snapshot(target_date, market, beta_data)
    repository.upsert_market_beta(snapshot.to_record())
    return {
        "status": "SUCCESS",
        "message": f"market_beta {snapshot.beta_state} score={snapshot.beta_score:.2f}",
        "snapshot": snapshot.to_record(),
    }


def _refresh_market_breadth_liquidity(
    repository: MonitoringRepository,
    paths: RuntimePaths,
    trade_date: str,
) -> None:
    """用统一行情口径补齐全A宽度和流动性派生指标。"""
    base_path = _resolve_base_daily_db(paths)
    if base_path is None or not paths.live_market_increment_path.exists():
        return
    daily = load_recent_daily_bars(base_path, paths.live_market_increment_path, trade_date)
    breadth = build_breadth_liquidity_frame(daily)
    if breadth.empty:
        return
    market = repository.load_market_history("510300")
    if market.empty:
        return
    emotion = _load_limit_emotion(paths, trade_date, breadth)
    enriched = enrich_market_observations(market, breadth, emotion)
    repository.upsert_market_daily(enriched)


def enrich_market_observations(
    market: pd.DataFrame,
    breadth: pd.DataFrame,
    emotion: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """把全A宽度、流动性和涨跌停情绪合并进大盘监控行。"""
    enriched = _merge_derived_columns(market, breadth)
    if emotion is not None and not emotion.empty:
        keep_columns = [
            "trade_date",
            "limit_up_count",
            "limit_down_count",
        ]
        available = [column for column in keep_columns if column in emotion.columns]
        enriched = _merge_derived_columns(enriched, emotion[available])
    return enriched


def _merge_derived_columns(base: pd.DataFrame, derived_frame: pd.DataFrame) -> pd.DataFrame:
    """按 trade_date 合并派生列，派生值优先，缺失时保留原值。"""
    enriched = base.merge(derived_frame, on="trade_date", how="left", suffixes=("", "_derived"))
    for column in derived_frame.columns:
        if column == "trade_date":
            continue
        derived = f"{column}_derived"
        if derived in enriched.columns:
            enriched[column] = enriched[derived].combine_first(enriched.get(column))
            enriched = enriched.drop(columns=[derived])
    return enriched


def _load_limit_emotion(paths: RuntimePaths, trade_date: str, breadth: pd.DataFrame) -> pd.DataFrame:
    """读取本地涨跌停缓存并聚合成每日情绪计数。"""
    if not paths.limit_list_increment_path.exists():
        return pd.DataFrame()
    try:
        import duckdb

        with duckdb.connect(str(paths.limit_list_increment_path), read_only=True) as con:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
            if "limit_list_daily" not in tables:
                return pd.DataFrame()
            start_date = str(breadth["trade_date"].min()) if not breadth.empty else trade_date
            rows = con.execute(
                """
                SELECT *
                FROM limit_list_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date, ts_code
                """,
                [start_date, trade_date],
            ).fetchdf()
    except Exception:
        return pd.DataFrame()
    market_amount = breadth[["trade_date", "market_amount"]] if "market_amount" in breadth.columns else None
    return build_market_emotion_daily(rows, market_amount)


def _resolve_base_daily_db(paths: RuntimePaths) -> Path | None:
    """定位历史基线库，兼容 QUANT_HOME 与项目根目录分离的部署方式。"""
    return paths.base_market_path if paths.base_market_path.exists() else None


def load_beta_inputs(paths: RuntimePaths, trade_date: str) -> dict[str, float]:
    """读取单日 P0 beta 扩展数据，缺失时返回空字典让状态机降级。"""
    if not paths.beta_increment_path.exists():
        return {}
    try:
        import duckdb

        with duckdb.connect(str(paths.beta_increment_path), read_only=True) as con:
            hsgt = _fetchdf_or_empty(con, "SELECT * FROM moneyflow_hsgt WHERE trade_date = ?", [trade_date])
            margin = _fetchdf_or_empty(con, "SELECT * FROM margin WHERE trade_date = ?", [trade_date])
            valuation = _fetchdf_or_empty(con, "SELECT * FROM index_dailybasic WHERE trade_date = ?", [trade_date])
    except Exception:
        return {}
    result: dict[str, float] = {}
    if not hsgt.empty:
        result["north_money"] = float(pd.to_numeric(hsgt["north_money"], errors="coerce").fillna(0.0).sum())
    if not margin.empty:
        result["rzrqye"] = float(pd.to_numeric(margin["rzrqye"], errors="coerce").fillna(0.0).sum())
    if not valuation.empty and "pe_ttm" in valuation.columns:
        result["pe_ttm"] = float(pd.to_numeric(valuation["pe_ttm"], errors="coerce").dropna().mean())
    return result


def _fetchdf_or_empty(con: object, sql: str, params: list[str]) -> pd.DataFrame:
    """表不存在或字段缺失时返回空表，避免 beta 扩展数据阻断主流程。"""
    try:
        return con.execute(sql, params).fetchdf()
    except Exception:
        return pd.DataFrame()


def _latest_numeric(history: pd.DataFrame, column: str, default: float) -> float:
    """读取最新数值字段，缺失或异常时返回默认值。"""
    if column not in history.columns or history.empty:
        return default
    values = pd.to_numeric(history[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else default
