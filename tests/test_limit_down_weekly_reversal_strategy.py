from __future__ import annotations

import pandas as pd

from examples import limit_down_weekly_reversal_strategy_study as study


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_date": "20260109",
                "trade_date": "20260108",
                "ts_code": f"{index:06d}.SZ",
                "name": "样本",
                "amount": 100.0,
                "fd_amount": float(index + 1),
            }
            for index in range(25)
        ]
    )


def test_definition_is_frozen_before_return_loading() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["parameters_fixed_before_return_loading"] is True
    assert definition["ranking"]["threshold_search"] is False
    assert definition["dependency"]


def test_weak_seal_ranking_selects_lowest_ratios() -> None:
    targets, selected = study.build_targets(_candidates(), "weak_seal")

    assert len(targets["20260109"]) == 20
    assert selected["ts_code"].tolist()[0] == "000000.SZ"
    assert selected["ts_code"].tolist()[-1] == "000019.SZ"
    assert abs(sum(targets["20260109"].values()) - 1.0) < 1e-12


def test_amount_control_is_separate_fixed_ranking() -> None:
    candidates = _candidates()
    candidates.loc[24, "amount"] = 1000.0

    _, selected = study.build_targets(candidates, "amount")

    assert selected.iloc[0]["ts_code"] == "000024.SZ"
