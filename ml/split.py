"""机器学习数据的固定时间切分和 purge 门禁。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FixedTimeSplit:
    """Quality ML V0 预先冻结的训练、验证和测试边界。"""

    train_start: str = "20150101"
    validation_start: str = "20190101"
    test_start: str = "20220101"


@dataclass(frozen=True)
class DatasetSplits:
    """互不穿越的三个样本区间。"""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    definition: FixedTimeSplit


def split_train_validation_test(
    frame: pd.DataFrame,
    definition: FixedTimeSplit | None = None,
) -> DatasetSplits:
    """按标签结束日 purge 边界，禁止训练标签进入后续区间。"""
    split = definition or FixedTimeSplit()
    required = ["signal_date", "exit_date", "forward_rank"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"split frame missing columns: {missing}")
    data = frame.dropna(subset=["forward_rank", "exit_date"]).copy()
    signal = data["signal_date"].astype(str)
    exit_date = data["exit_date"].astype(str)

    train = data[
        signal.ge(split.train_start) & exit_date.lt(split.validation_start)
    ].copy()
    validation = data[
        signal.ge(split.validation_start) & exit_date.lt(split.test_start)
    ].copy()
    test = data[signal.ge(split.test_start)].copy()
    _validate_non_empty(train, validation, test)
    _validate_boundaries(train, validation, test)
    return DatasetSplits(train, validation, test, split)


def _validate_non_empty(train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame) -> None:
    empty = [name for name, value in [("train", train), ("validation", validation), ("test", test)] if value.empty]
    if empty:
        raise ValueError(f"empty ML split: {empty}")


def _validate_boundaries(train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame) -> None:
    if str(train["exit_date"].max()) >= str(validation["signal_date"].min()):
        raise ValueError("train labels overlap validation signals")
    if str(validation["exit_date"].max()) >= str(test["signal_date"].min()):
        raise ValueError("validation labels overlap test signals")
