"""标普500 ETF高溢价归一化风险测试。"""

import numpy as np
import pandas as pd

from examples import sp500_etf_premium_normalization_risk_audit as audit


def _matched() -> pd.DataFrame:
    rows = 100
    premium = np.linspace(0.08, 0.01, rows)
    return pd.DataFrame(
        {
            "symbol": "TEST",
            "trade_date": pd.bdate_range(
                "2025-01-02", periods=rows
            ).strftime("%Y%m%d"),
            "unit_nav": np.linspace(1.0, 1.2, rows),
            "close": np.linspace(1.0, 1.2, rows) * (1.0 + premium),
            "premium": premium,
        }
    )


def test_forward_effect_uses_frozen_twenty_day_horizon() -> None:
    observations = audit.build_forward_observations(_matched())
    first = observations.iloc[0]
    expected = (1.0 + _matched().iloc[20]["premium"]) / (
        1.0 + _matched().iloc[0]["premium"]
    ) - 1.0

    assert len(observations) == 80
    assert abs(first["forward_premium_effect"] - expected) < 1e-12
    assert bool(first["high_premium"]) is True


def test_definition_is_execution_risk_only() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_use_strategy_returns"] is True
    assert definition["does_not_authorize_instrument_substitution"] is True
    assert definition["does_not_define_a_trading_signal"] is True
