"""标普500 ETF溢价与净值跟踪归因测试。"""

import numpy as np
import pandas as pd

from examples import sp500_etf_premium_tracking_attribution_audit as audit


def _matched(symbol: str, premium_scale: float) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=720)
    underlying = 100.0 * np.cumprod(
        1.0 + 0.0004 + 0.008 * np.sin(np.arange(720) / 11.0)
    )
    premium = (
        0.04
        + premium_scale * np.sin(np.arange(720) / 5.0)
        + premium_scale * 0.3 * np.cos(np.arange(720) / 17.0)
    )
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates.strftime("%Y%m%d"),
            "unit_nav": underlying,
            "close": underlying * (1.0 + premium),
            "premium": premium,
        }
    )


def test_price_decomposition_is_exact() -> None:
    panel = audit.build_panel(
        _matched(audit.source.CANDIDATE, 0.015),
        _matched(audit.source.CONTROL, 0.003),
    )

    assert len(panel) == 719
    assert panel["reconstruction_error_candidate"].abs().max() < 1e-12
    assert panel["reconstruction_error_control"].abs().max() < 1e-12


def test_definition_is_attribution_only() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_authorize_instrument_substitution"] is True
    assert definition["does_not_override_source_failure"] is True
    assert definition["external_read"]["writes_production_database"] is False
