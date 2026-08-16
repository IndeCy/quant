"""机器学习未来收益标签测试。"""

import pandas as pd
import pytest

from ml.labeling import build_forward_monthly_labels, required_label_price_dates


def test_monthly_label_uses_next_trading_day_open() -> None:
    """月末信号只能使用下一交易日开盘建立标签。"""
    calendar = list(pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"]))
    prices = pd.DataFrame(
        {
            "trade_date": ["20240131", "20240201", "20240229", "20240301"],
            "symbol": ["AAA.SZ"] * 4,
            "open": [100.0, 10.0, 999.0, 12.0],
        }
    )

    labels = build_forward_monthly_labels(prices, calendar, ["20240131", "20240229"])

    assert labels.loc[0, "entry_date"] == "20240201"
    assert labels.loc[0, "exit_date"] == "20240301"
    assert labels.loc[0, "forward_return"] == pytest.approx(0.20)


def test_required_label_dates_skip_non_trading_days() -> None:
    """周五月末信号的标签价格日必须顺延到下一个交易日。"""
    calendar = list(pd.to_datetime(["2024-05-31", "2024-06-03", "2024-06-28", "2024-07-01"]))

    dates = required_label_price_dates(calendar, ["20240531", "20240628"])

    assert dates == ["20240603", "20240701"]


def test_duplicate_open_price_rows_are_rejected() -> None:
    """同一股票同一天多个开盘价会让标签不确定，必须阻断。"""
    prices = pd.DataFrame(
        {
            "trade_date": ["20240201", "20240201"],
            "symbol": ["AAA.SZ", "AAA.SZ"],
            "open": [10.0, 11.0],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        build_forward_monthly_labels(
            prices,
            list(pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"])),
            ["20240131", "20240229"],
        )
