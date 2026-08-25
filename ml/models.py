"""Quality ML V0 的固定模型定义，不提供参数搜索入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sklearn.base import RegressorMixin
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RANDOM_SEED = 42


@dataclass(frozen=True)
class ModelDefinition:
    """一个不可变候选模型及其构造函数。"""

    model_id: str
    name: str
    builder: Callable[[], RegressorMixin]
    sample_weight_parameter: str


def fixed_model_definitions() -> tuple[ModelDefinition, ...]:
    """返回预先冻结的线性基线和浅层非线性模型。"""
    return (
        ModelDefinition(
            model_id="ridge_v0",
            name="Ridge V0",
            builder=_build_ridge,
            sample_weight_parameter="ridge__sample_weight",
        ),
        ModelDefinition(
            model_id="hist_gbdt_v0",
            name="Histogram GBDT V0",
            builder=_build_hist_gbdt,
            sample_weight_parameter="sample_weight",
        ),
    )


def _build_ridge() -> RegressorMixin:
    """线性基线仅固定 alpha=1，不做网格搜索。"""
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=1.0)),
        ]
    )


def _build_hist_gbdt() -> RegressorMixin:
    """浅层树只验证非线性交互，容量保持克制。"""
    return HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_iter=100,
        max_depth=2,
        min_samples_leaf=100,
        l2_regularization=0.1,
        random_state=RANDOM_SEED,
    )
