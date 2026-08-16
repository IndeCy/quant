"""境内纳指100 ETF替代载体可行性测试。"""

import pandas as pd
import pytest

from examples import nasdaq100_domestic_etf_execution_feasibility_study as study


def test_definition_never_uses_returns_or_authorizes_substitution() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["universe"]["strategy_returns_used"] is False
    assert definition["does_not_authorize_instrument_substitution"] is True
    assert definition["external_read"]["writes_production_database"] is False


def test_universe_requires_etf_and_nasdaq100_identity() -> None:
    basic = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E"],
            "name": [
                "纳指ETF",
                "纳斯达克生物ETF",
                "纳指100ETF",
                "黄金ETF",
                "纳指ETF联接(QDII-LOF)",
            ],
            "benchmark": [
                "纳斯达克100指数",
                "纳斯达克生物科技指数",
                "",
                "黄金现货",
                "纳斯达克100指数",
            ],
            "list_date": ["20200101"] * 5,
        }
    )

    selected = study.select_nasdaq100_etfs(basic)

    assert selected["ts_code"].tolist() == ["A", "C"]


def test_candidate_gate_uses_same_date_nav_price_and_capacity() -> None:
    class Item:
        ts_code = "159999.SZ"
        name = "纳指ETF"
        benchmark = "纳斯达克100指数"
        list_date = "20200101"

    nav = pd.DataFrame(
        {"nav_date": ["20260727"], "unit_nav": [1.00]}
    )
    daily = pd.DataFrame(
        {
            "trade_date": ["20260727"] * 20,
            "close": [1.04] * 20,
            "amount": [200_000.0] * 20,
        }
    )

    result = study.summarize_candidate(
        Item(),
        nav,
        daily,
        "20260728",
    )

    assert result["latest_premium"] == pytest.approx(0.04)
    assert result["one_million_participation"] == pytest.approx(0.005)
    assert result["eligible"] is True
