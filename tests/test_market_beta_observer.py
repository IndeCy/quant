"""Market Beta Observatory 指标与状态测试。"""

from __future__ import annotations

import pandas as pd

from runtime.market_beta_observer import build_market_beta_snapshot, compute_liquidity_metrics, enrich_market_observations


def _market_frame(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.DataFrame(
        {
            "trade_date": [date.strftime("%Y%m%d") for date in dates],
            "benchmark_nav": values,
            "benchmark_return": pd.Series(values).pct_change().fillna(0.0).tolist(),
            "benchmark_drawdown": pd.Series(values) / pd.Series(values).cummax() - 1.0,
            "ma60": pd.Series(values).rolling(20, min_periods=1).mean(),
            "ma120": pd.Series(values).rolling(40, min_periods=1).mean(),
            "breadth_up_count": [4200] * len(values),
            "breadth_down_count": [900] * len(values),
            "limit_up_count": [80] * len(values),
            "limit_down_count": [2] * len(values),
        }
    )


def test_beta_on_when_trend_and_breadth_are_strong() -> None:
    """趋势向上、赚钱效应扩散且资金为正时，应输出顺风 beta。"""
    market = _market_frame([1.0 + i * 0.01 for i in range(80)])
    beta = {"north_money": 30.0, "rzrqye": 1200.0, "pe_ttm": 12.0}

    snapshot = build_market_beta_snapshot("20260422", market, beta)

    assert snapshot.beta_state == "BETA_ON"
    assert snapshot.beta_score >= 70


def test_beta_off_when_index_breaks_trend_and_breadth_is_weak() -> None:
    """趋势破位且下跌家数明显占优时，应输出逆风 beta。"""
    market = _market_frame([1.2 - i * 0.002 for i in range(80)])
    market["breadth_up_count"] = 800
    market["breadth_down_count"] = 4300
    market["limit_up_count"] = 8
    market["limit_down_count"] = 45
    beta = {"north_money": -20.0, "rzrqye": 900.0, "pe_ttm": 20.0}

    snapshot = build_market_beta_snapshot("20260422", market, beta)

    assert snapshot.beta_state == "BETA_OFF"
    assert 25 <= snapshot.beta_score < 45


def test_crash_risk_when_short_term_drop_and_limit_down_expand() -> None:
    """短期急跌叠加跌停扩散时，应优先进入极端风险。"""
    values = [1.0 + i * 0.002 for i in range(60)] + [1.05, 0.98, 0.9, 0.82]
    market = _market_frame(values)
    market["breadth_up_count"] = 300
    market["breadth_down_count"] = 4800
    market["limit_up_count"] = 2
    market["limit_down_count"] = 120

    snapshot = build_market_beta_snapshot("20260422", market, {})

    assert snapshot.beta_state == "CRASH_RISK"
    assert snapshot.risk_level == "HIGH"


def test_beta_observer_degrades_without_extended_beta_data() -> None:
    """缺少资金和估值扩展数据时，仍应用价格、宽度和情绪给出状态。"""
    market = _market_frame([1.0 + i * 0.001 for i in range(80)])

    snapshot = build_market_beta_snapshot("20260422", market, None)

    assert snapshot.beta_state in {"BETA_ON", "NEUTRAL"}
    assert snapshot.funding_score == 5.0
    assert snapshot.valuation_score == 5.0


def test_liquidity_uses_persisted_market_amount() -> None:
    """全市场成交额已沉淀后，流动性评分不应再使用占位原因。"""
    market = _market_frame([1.0 + i * 0.001 for i in range(30)])
    market["market_amount"] = [1000.0] * 29 + [1300.0]
    market["amount_ma20"] = [1000.0] * 30
    market["zero_volume_ratio"] = [0.01] * 30

    score, reasons = compute_liquidity_metrics(market)

    assert score == 15.0
    assert "未沉淀" not in reasons[0]


def test_enrich_market_observations_merges_limit_emotion() -> None:
    """涨跌停缓存聚合结果应覆盖大盘监控表中的占位0。"""
    market = pd.DataFrame(
        [
            {
                "trade_date": "20260710",
                "benchmark_id": "510300",
                "benchmark_nav": 1.0,
                "limit_up_count": 0,
                "limit_down_count": 0,
            }
        ]
    )
    breadth = pd.DataFrame([{"trade_date": "20260710", "market_amount": 1000.0}])
    emotion = pd.DataFrame([{"trade_date": "20260710", "limit_up_count": 92, "limit_down_count": 4}])

    enriched = enrich_market_observations(market, breadth, emotion)

    assert enriched.loc[0, "market_amount"] == 1000.0
    assert enriched.loc[0, "limit_up_count"] == 92
    assert enriched.loc[0, "limit_down_count"] == 4
