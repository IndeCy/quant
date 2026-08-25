"""机器学习研究的不可变数据契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


QUALITY_ML_FEATURES = ("roe", "roa", "ocf_to_or")
QUALITY_ML_TARGET = "forward_rank"


@dataclass(frozen=True)
class DatasetSpec:
    """Quality ML V0 的冻结数据集口径。"""

    dataset_id: str = "quality_ml_ranker_v0"
    start_date: str = "20150101"
    adjust_policy: str = "qfq"
    benchmark: str = "510300"
    rebalance: str = "monthly"
    execution_policy: str = "m0_t1"
    annual_report_only: bool = True
    listed_years: int = 3
    top_n: int = 20
    features: tuple[str, ...] = QUALITY_ML_FEATURES
    target: str = QUALITY_ML_TARGET

    def to_dict(self) -> dict[str, Any]:
        """生成可序列化配置，供实验清单保存。"""
        return asdict(self)


@dataclass(frozen=True)
class DatasetManifest:
    """记录训练数据的范围、质量和内容哈希。"""

    dataset_id: str
    dataset_hash: str
    row_count: int
    trainable_count: int
    first_signal_date: str
    last_signal_date: str
    feature_columns: tuple[str, ...]
    target_column: str
    as_of_violation_count: int
    duplicate_count: int
    invalid_label_count: int

    def to_dict(self) -> dict[str, Any]:
        """生成可序列化清单。"""
        return asdict(self)
