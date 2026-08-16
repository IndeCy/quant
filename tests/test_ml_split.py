"""机器学习时间切分与 purge 测试。"""

import pandas as pd

from ml.split import split_train_validation_test


def test_split_purges_labels_crossing_next_sample_boundary() -> None:
    """标签结束日进入后续区间的边界月份不能参与训练或验证。"""
    frame = pd.DataFrame(
        [
            _row("20181031", "20181203", 0.6),
            _row("20181130", "20190102", 0.7),
            _row("20181228", "20190201", 0.8),
            _row("20190131", "20190301", 0.6),
            _row("20211029", "20211201", 0.7),
            _row("20211130", "20220104", 0.8),
            _row("20211231", "20220207", 0.9),
            _row("20220128", "20220301", 0.6),
        ]
    )

    splits = split_train_validation_test(frame)

    assert splits.train["signal_date"].tolist() == ["20181031"]
    assert splits.validation["signal_date"].tolist() == ["20190131", "20211029"]
    assert splits.test["signal_date"].tolist() == ["20220128"]
    assert splits.train["exit_date"].max() < splits.validation["signal_date"].min()
    assert splits.validation["exit_date"].max() < splits.test["signal_date"].min()


def _row(signal_date: str, exit_date: str, target: float) -> dict[str, object]:
    return {
        "signal_date": signal_date,
        "symbol": f"{signal_date}.SZ",
        "exit_date": exit_date,
        "forward_rank": target,
    }
