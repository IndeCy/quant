"""513650与513500载体等价性测试。"""

import pandas as pd

from examples import sp500_etf_instrument_equivalence_audit as audit


def test_definition_never_authorizes_replacement() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_authorize_control_replacement"] is True
    assert definition["does_not_authorize_strategy_substitution"] is True
    assert definition["strategy_returns_used"] is False


def test_return_normalization_uses_pct_change_percent_units() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20230405", "20230404"],
            "pct_chg": [1.5, -2.0],
        }
    )

    result = audit.normalize_returns(frame, audit.CANDIDATE)

    assert result["trade_date"].tolist() == ["20230404", "20230405"]
    assert result["return"].tolist() == [-0.02, 0.015]
