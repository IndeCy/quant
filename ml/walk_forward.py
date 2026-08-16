"""冻结模型的年度扩展 Walk Forward。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ml.models import ModelDefinition, fixed_model_definitions
from ml.trainer import fit_fixed_model, predict_with_model


@dataclass(frozen=True)
class WalkForwardResult:
    """年度预测和每个窗口使用的数据边界。"""

    predictions: pd.DataFrame
    windows: pd.DataFrame


def run_annual_expanding_walk_forward(
    frame: pd.DataFrame,
    *,
    model_id: str,
    first_test_year: int = 2022,
) -> WalkForwardResult:
    """每年只用当年以前已结束标签重训，参数始终冻结。"""
    definition = _resolve_model(model_id)
    data = frame.dropna(subset=["forward_rank", "exit_date"]).copy()
    years = sorted(
        year
        for year in data["signal_date"].astype(str).str[:4].astype(int).unique()
        if year >= first_test_year
    )
    predictions: list[pd.DataFrame] = []
    windows: list[dict[str, object]] = []
    for year in years:
        year_start = f"{year}0101"
        year_end = f"{year}1231"
        train = data[data["exit_date"].astype(str).lt(year_start)].copy()
        test = data[
            data["signal_date"].astype(str).between(year_start, year_end, inclusive="both")
        ].copy()
        if train.empty or test.empty:
            continue
        estimator = fit_fixed_model(definition, train)
        predicted = predict_with_model(estimator, test, sample="walk_forward_test")
        predicted["test_year"] = year
        predicted["train_max_exit_date"] = str(train["exit_date"].max())
        predictions.append(predicted)
        windows.append(
            {
                "test_year": year,
                "model_id": model_id,
                "train_signal_start": str(train["signal_date"].min()),
                "train_signal_end": str(train["signal_date"].max()),
                "train_max_exit_date": str(train["exit_date"].max()),
                "test_signal_start": str(test["signal_date"].min()),
                "test_signal_end": str(test["signal_date"].max()),
                "train_rows": len(train),
                "test_rows": len(test),
            }
        )
    prediction_frame = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    window_frame = pd.DataFrame(windows)
    _validate_walk_forward(window_frame)
    return WalkForwardResult(prediction_frame, window_frame)


def _resolve_model(model_id: str) -> ModelDefinition:
    definitions = {definition.model_id: definition for definition in fixed_model_definitions()}
    if model_id not in definitions:
        raise ValueError(f"unknown fixed model: {model_id}")
    return definitions[model_id]


def _validate_walk_forward(windows: pd.DataFrame) -> None:
    if windows.empty:
        raise ValueError("walk-forward produced no windows")
    overlap = windows["train_max_exit_date"].astype(str) >= windows["test_signal_start"].astype(str)
    if overlap.any():
        raise ValueError("walk-forward training labels overlap test signals")
