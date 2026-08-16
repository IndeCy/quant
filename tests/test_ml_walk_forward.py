"""年度扩展 Walk Forward 测试。"""

import numpy as np
import pandas as pd

from ml.walk_forward import run_annual_expanding_walk_forward


def test_walk_forward_only_uses_labels_finished_before_test_year() -> None:
    """每个测试年度的训练标签结束日必须早于当年第一天。"""
    frame = _build_frame()

    result = run_annual_expanding_walk_forward(frame, model_id="ridge_v0", first_test_year=2022)

    assert result.windows["test_year"].tolist() == [2022, 2023]
    assert (
        result.windows["train_max_exit_date"].astype(str)
        < result.windows["test_signal_start"].astype(str)
    ).all()
    assert set(result.predictions["test_year"]) == {2022, 2023}


def _build_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in range(2018, 2024):
        for month in [1, 4, 7, 10]:
            signal = f"{year}{month:02d}28"
            exit_year = year + 1 if month == 10 else year
            exit_month = 1 if month == 10 else month + 1
            exit_date = f"{exit_year}{exit_month:02d}28"
            for index, value in enumerate(np.linspace(-1, 1, 12)):
                rows.append(
                    {
                        "signal_date": signal,
                        "symbol": f"{index:06d}.SZ",
                        "entry_date": signal,
                        "exit_date": exit_date,
                        "roe": value * 5 + 10,
                        "roa": value * 2 + 4,
                        "ocf_to_or": value * value + value,
                        "forward_return": value / 10,
                        "forward_rank": (index + 1) / 12,
                    }
                )
    return pd.DataFrame(rows)
