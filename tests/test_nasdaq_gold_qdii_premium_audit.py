"""纳指黄金QDII折溢价审计测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples import nasdaq_gold_qdii_premium_audit as audit


def test_premium_decomposition_recovers_known_expansion() -> None:
    dates = pd.date_range("2020-01-01", periods=800, freq="B")
    nav = pd.Series(
        1.0 * np.cumprod(np.repeat(1.0002, len(dates))),
        index=dates,
    )
    premium = pd.Series(
        np.linspace(0.01, 0.05, len(dates)),
        index=dates,
    )
    frame = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "symbol": audit.base.NASDAQ,
            "close": nav * (1.0 + premium),
            "nav": nav,
        }
    )

    result = audit.summarize_premium(frame, "20230131")

    assert result["nav_coverage"] == 1.0
    assert result["annualized_log_premium_contribution"] > 0
    assert result["premium_identity_error_p99"] < 1e-10


def test_definition_does_not_treat_nav_counterfactual_as_tradable() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["decomposition"]["counterfactual_is_not_tradable"] is True
    assert definition["does_not_override_source_gate"] is True
    assert definition["decomposition"]["nasdaq_portfolio_weight"] == 0.60
