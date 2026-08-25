"""机器学习信号评估与晋级门禁测试。"""

import pandas as pd

from ml.evaluation import (
    build_prediction_selections,
    evaluate_promotion_gate,
    select_model_on_validation,
)


def test_prediction_scores_are_converted_by_generic_topn_layer() -> None:
    predictions = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 3,
            "symbol": ["B", "A", "C"],
            "prediction": [0.8, 0.8, 0.2],
        }
    )

    selections, holdings = build_prediction_selections(predictions, top_n=2)

    assert selections == {"20240131": ["A", "B"]}
    assert holdings["rank"].tolist() == [1, 2]


def test_model_selection_uses_only_frozen_validation_order() -> None:
    metrics = pd.DataFrame(
        [
            {
                "model_id": "ridge_v0",
                "validation_mean_rank_ic": 0.03,
                "validation_sharpe": 1.0,
                "validation_max_drawdown": -0.2,
                "validation_turnover": 1.0,
                "test_mean_rank_ic": 0.5,
            },
            {
                "model_id": "hist_gbdt_v0",
                "validation_mean_rank_ic": 0.04,
                "validation_sharpe": 0.5,
                "validation_max_drawdown": -0.3,
                "validation_turnover": 2.0,
                "test_mean_rank_ic": -0.5,
            },
        ]
    )

    assert select_model_on_validation(metrics) == "hist_gbdt_v0"


def test_promotion_gate_requires_all_out_of_sample_checks() -> None:
    result = evaluate_promotion_gate(
        {
            "test_mean_rank_ic": 0.01,
            "test_positive_ic_ratio": 0.51,
            "test_sharpe": 0.8,
            "baseline_test_sharpe": 0.7,
            "test_max_drawdown": -0.30,
            "baseline_test_max_drawdown": -0.28,
            "test_turnover": 1.2,
            "baseline_test_turnover": 1.0,
        }
    )

    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["test_rank_ic", "positive_ic_months"]
