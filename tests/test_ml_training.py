"""固定候选模型训练测试。"""

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from ml.models import fixed_model_definitions
from ml.preprocessing import MODEL_FEATURES, build_cross_section_features
from ml.split import DatasetSplits, FixedTimeSplit
from ml.trainer import train_fixed_candidates


def test_cross_section_preprocessing_does_not_depend_on_future_months() -> None:
    """新增未来截面不能改变历史日期的标准化结果。"""
    historical = _sample_frame(["20180131"], 10)
    with_future = pd.concat([historical, _sample_frame(["20250131"], 10)], ignore_index=True)

    expected = build_cross_section_features(historical)[list(MODEL_FEATURES)]
    actual = build_cross_section_features(with_future)
    actual = actual[actual["signal_date"].eq("20180131")][list(MODEL_FEATURES)].reset_index(drop=True)

    assert_frame_equal(actual, expected.reset_index(drop=True))


def test_fixed_candidates_are_deterministic_and_ignore_test_targets() -> None:
    """模型只拟合训练集，改变测试标签不能改变预测分数。"""
    splits = DatasetSplits(
        train=_sample_frame(pd.date_range("2016-01-31", periods=12, freq="ME").strftime("%Y%m%d").tolist(), 24),
        validation=_sample_frame(pd.date_range("2019-01-31", periods=4, freq="ME").strftime("%Y%m%d").tolist(), 24),
        test=_sample_frame(pd.date_range("2022-01-31", periods=4, freq="ME").strftime("%Y%m%d").tolist(), 24),
        definition=FixedTimeSplit(),
    )
    changed_test = splits.test.copy()
    changed_test["forward_rank"] = 1.0 - changed_test["forward_rank"]
    changed = DatasetSplits(splits.train, splits.validation, changed_test, splits.definition)

    first = train_fixed_candidates(splits)
    second = train_fixed_candidates(changed)

    assert set(first) == {definition.model_id for definition in fixed_model_definitions()}
    for model_id in first:
        first_test = first[model_id].predictions.query("sample == 'test'")["prediction"].reset_index(drop=True)
        second_test = second[model_id].predictions.query("sample == 'test'")["prediction"].reset_index(drop=True)
        assert np.allclose(first_test, second_test)
        assert np.isfinite(first[model_id].metrics["validation_mean_rank_ic"])


def _sample_frame(signal_dates: list[str], symbols_per_month: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for month_index, signal_date in enumerate(signal_dates):
        values = np.linspace(-1.0, 1.0, symbols_per_month)
        ranks = pd.Series(values + month_index * 0.001).rank(pct=True).to_numpy()
        for symbol_index, value in enumerate(values):
            rows.append(
                {
                    "signal_date": signal_date,
                    "symbol": f"{symbol_index:06d}.SZ",
                    "entry_date": signal_date,
                    "exit_date": signal_date,
                    "roe": value * 10 + 12,
                    "roa": value * 4 + 6,
                    "ocf_to_or": value * value * 5 + value,
                    "forward_return": value / 10,
                    "forward_rank": ranks[symbol_index],
                }
            )
    return pd.DataFrame(rows)
