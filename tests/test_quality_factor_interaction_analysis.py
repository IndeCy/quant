"""Quality 因子交互分析辅助函数测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.quality_factor_interaction_analysis import (
    assign_quintiles,
    compare_roa_top_with_ocf_filter,
    compute_cell_forward_stats,
    max_drawdown_from_returns,
)


def test_assign_quintiles_creates_roa_and_ocf_groups_by_signal_date() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 5,
            "symbol": list("ABCDE"),
            "roa": [1, 2, 3, 4, 5],
            "ocf_to_or": [5, 4, 3, 2, 1],
        }
    )

    result = assign_quintiles(frame)

    assert result.loc[result["symbol"].eq("E"), "roa_q"].iloc[0] == "Q5"
    assert result.loc[result["symbol"].eq("E"), "ocf_q"].iloc[0] == "Q1"


def test_compute_cell_forward_stats_outputs_return_winrate_vol_drawdown_and_excess() -> None:
    rows = pd.DataFrame(
        {
            "roa_q": ["Q5", "Q5", "Q5"],
            "ocf_q": ["Q5", "Q5", "Q5"],
            "forward_return_1m": [0.1, -0.02, 0.04],
            "forward_excess_1m": [0.08, -0.03, 0.01],
            "forward_vol_1m": [0.2, 0.3, 0.1],
            "forward_drawdown_1m": [-0.05, -0.1, -0.02],
        }
    )

    stats = compute_cell_forward_stats(rows, "1m")

    row = stats.iloc[0]
    assert row["平均收益"] == pytest.approx(0.04)
    assert row["胜率"] == pytest.approx(2 / 3)
    assert row["平均超额收益"] == pytest.approx(0.02)
    assert row["最大回撤"] == pytest.approx(-0.1)


def test_compare_roa_top_with_ocf_filter_separates_return_and_drawdown_effect() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 5,
            "roa_q": ["Q5", "Q5", "Q5", "Q4", "Q3"],
            "ocf_q": ["Q5", "Q3", "Q1", "Q5", "Q5"],
            "forward_return_1m": [0.10, 0.02, -0.05, 0.03, 0.04],
            "forward_drawdown_1m": [-0.03, -0.08, -0.20, -0.04, -0.05],
        }
    )

    result = compare_roa_top_with_ocf_filter(frame, "1m")

    assert set(result["组合"]) == {"ROA Top20%", "ROA Top20% + OCF Top50%"}
    filtered = result[result["组合"].eq("ROA Top20% + OCF Top50%")].iloc[0]
    assert filtered["平均收益"] == pytest.approx(0.06)
    assert filtered["最大回撤"] == pytest.approx(-0.08)


def test_max_drawdown_from_returns_uses_compounded_path() -> None:
    assert max_drawdown_from_returns(pd.Series([0.1, -0.2, 0.05])) == pytest.approx(-0.2)
