"""Quality ML V0 的 point-in-time 数据集构造。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

import pandas as pd

from data.market_features import (
    load_month_end_signal_dates,
    load_open_prices_on_dates,
    load_trading_calendar,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from ml.contracts import DatasetManifest, DatasetSpec
from ml.labeling import build_forward_monthly_labels, required_label_price_dates
from strategies.quality_universe import apply_quality_universe_filters, load_annual_quality_candidates


class DatasetConnection(Protocol):
    """声明构造数据集所需的 DuckDB 连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class QualityMLDataset:
    """训练面板和可审计清单。"""

    frame: pd.DataFrame
    manifest: DatasetManifest
    spec: DatasetSpec

    def trainable_frame(self) -> pd.DataFrame:
        """只返回特征和标签都完整的历史训练样本。"""
        required = [*self.spec.features, self.spec.target]
        return self.frame.dropna(subset=required).copy()


def build_quality_ml_dataset(
    connection: DatasetConnection,
    financial_paths: QualityFinancialPaths,
    *,
    spec: DatasetSpec | None = None,
    signal_dates: list[str] | None = None,
) -> QualityMLDataset:
    """使用标准行情与财务门面生成可复现训练面板。"""
    definition = spec or DatasetSpec()
    dates = signal_dates or load_month_end_signal_dates(connection)
    dates = [date for date in dates if date >= definition.start_date]
    if len(dates) < 2:
        raise ValueError("quality ML dataset requires at least two signal dates")

    create_quality_signal_date_table(connection, dates)
    attach_quality_financial_databases(connection, financial_paths)
    materialize_quality_financial_asof(connection, annual_only=definition.annual_report_only)
    candidates = apply_quality_universe_filters(load_annual_quality_candidates(connection))

    calendar = load_trading_calendar(connection)
    required_dates = required_label_price_dates(calendar, dates)
    open_prices = load_open_prices_on_dates(connection, required_dates)
    labels = build_forward_monthly_labels(open_prices, calendar, dates)
    frame = candidates.merge(labels, on=["signal_date", "symbol"], how="left", validate="one_to_one")
    frame = frame.sort_values(["signal_date", "symbol"], kind="stable").reset_index(drop=True)
    manifest = _build_manifest(frame, definition)
    _enforce_dataset_gate(frame, manifest, definition)
    return QualityMLDataset(frame=frame, manifest=manifest, spec=definition)


def _build_manifest(frame: pd.DataFrame, spec: DatasetSpec) -> DatasetManifest:
    signal = frame["signal_date"].astype(str)
    publish = frame["f_ann_date"].astype(str)
    duplicates = int(frame.duplicated(["signal_date", "symbol"]).sum())
    as_of_violations = int((publish > signal).sum())
    invalid_labels = int(frame[spec.target].isna().sum())
    hash_columns = ["signal_date", "symbol", "end_date", "f_ann_date", *spec.features, spec.target]
    content = frame[hash_columns].to_csv(index=False, float_format="%.12g")
    return DatasetManifest(
        dataset_id=spec.dataset_id,
        dataset_hash=sha256(content.encode("utf-8")).hexdigest(),
        row_count=len(frame),
        trainable_count=int(frame[[*spec.features, spec.target]].notna().all(axis=1).sum()),
        first_signal_date=str(signal.min()),
        last_signal_date=str(signal.max()),
        feature_columns=spec.features,
        target_column=spec.target,
        as_of_violation_count=as_of_violations,
        duplicate_count=duplicates,
        invalid_label_count=invalid_labels,
    )


def _enforce_dataset_gate(
    frame: pd.DataFrame,
    manifest: DatasetManifest,
    spec: DatasetSpec,
) -> None:
    """阻断公告日穿越、重复样本和标签日期倒流。"""
    if manifest.as_of_violation_count:
        raise ValueError(f"financial as-of violations: {manifest.as_of_violation_count}")
    if manifest.duplicate_count:
        raise ValueError(f"duplicate samples: {manifest.duplicate_count}")
    labeled = frame.dropna(subset=[spec.target])
    if not labeled.empty:
        entry_invalid = labeled["entry_date"].astype(str) <= labeled["signal_date"].astype(str)
        exit_invalid = labeled["exit_date"].astype(str) <= labeled["entry_date"].astype(str)
        if entry_invalid.any() or exit_invalid.any():
            raise ValueError("forward labels must occur strictly after signal date")
    forbidden_features = [name for name in spec.features if name.startswith("forward_")]
    if forbidden_features:
        raise ValueError(f"future columns cannot be model features: {forbidden_features}")
