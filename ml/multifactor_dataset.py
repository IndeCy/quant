"""Quality、价值和低波特征的点时机器学习数据集。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

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
from data.quality_value_lowvol import (
    CorporateActionAudit,
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from ml.contracts import DatasetManifest, DatasetSpec
from ml.labeling import build_forward_monthly_labels, required_label_price_dates
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


@dataclass(frozen=True)
class MultiFactorMLDataset:
    """训练面板、数据清单与公司行动审计。"""

    frame: pd.DataFrame
    manifest: DatasetManifest
    spec: DatasetSpec
    corporate_action_audit: CorporateActionAudit

    def trainable_frame(self) -> pd.DataFrame:
        """只返回特征、标签和标签退出日均完整的样本。"""
        required = [*self.spec.features, self.spec.target, "exit_date"]
        return self.frame.dropna(subset=required).copy()


def build_multifactor_ml_dataset(
    connection,
    financial_paths: QualityFinancialPaths,
    *,
    spec: DatasetSpec,
) -> MultiFactorMLDataset:
    """通过统一行情、财务as-of和公司行动门禁生成训练面板。"""
    signal_dates = [
        date
        for date in load_month_end_signal_dates(connection)
        if date >= spec.start_date
    ]
    if len(signal_dates) < 2:
        raise ValueError("multifactor ML dataset requires at least two signal dates")
    create_quality_signal_date_table(connection, signal_dates)
    attach_quality_financial_databases(connection, financial_paths)
    materialize_quality_financial_asof(
        connection,
        annual_only=spec.annual_report_only,
    )
    candidates = apply_quality_universe_filters(
        load_annual_quality_candidates(connection)
    )
    candidates = attach_report_adjustment_factors(connection, candidates)
    candidates, audit = build_quality_value_lowvol_candidates(candidates)

    calendar = load_trading_calendar(connection)
    required_dates = required_label_price_dates(calendar, signal_dates)
    open_prices = load_open_prices_on_dates(connection, required_dates)
    labels = build_forward_monthly_labels(
        open_prices,
        calendar,
        signal_dates,
    )
    frame = candidates.merge(
        labels,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    frame = frame.sort_values(
        ["signal_date", "symbol"],
        kind="stable",
    ).reset_index(drop=True)
    manifest = build_manifest(frame, spec)
    enforce_dataset_gate(frame, manifest, spec)
    return MultiFactorMLDataset(frame, manifest, spec, audit)


def build_manifest(
    frame: pd.DataFrame,
    spec: DatasetSpec,
) -> DatasetManifest:
    """生成绑定内容、特征和标签边界的数据清单。"""
    missing = [
        column
        for column in [
            "signal_date",
            "symbol",
            "end_date",
            "f_ann_date",
            *spec.features,
            spec.target,
        ]
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(f"multifactor dataset missing columns: {missing}")
    signal = frame["signal_date"].astype(str)
    publish = frame["f_ann_date"].astype(str)
    required = [*spec.features, spec.target]
    hash_columns = [
        "signal_date",
        "symbol",
        "end_date",
        "f_ann_date",
        *spec.features,
        spec.target,
    ]
    content = frame[hash_columns].to_csv(index=False, float_format="%.12g")
    return DatasetManifest(
        dataset_id=spec.dataset_id,
        dataset_hash=sha256(content.encode("utf-8")).hexdigest(),
        row_count=len(frame),
        trainable_count=int(frame[required].notna().all(axis=1).sum()),
        first_signal_date=str(signal.min()),
        last_signal_date=str(signal.max()),
        feature_columns=spec.features,
        target_column=spec.target,
        as_of_violation_count=int((publish > signal).sum()),
        duplicate_count=int(
            frame.duplicated(["signal_date", "symbol"]).sum()
        ),
        invalid_label_count=int(frame[spec.target].isna().sum()),
    )


def enforce_dataset_gate(
    frame: pd.DataFrame,
    manifest: DatasetManifest,
    spec: DatasetSpec,
) -> None:
    """阻断公告穿越、重复样本、未来特征和标签日期倒流。"""
    if manifest.as_of_violation_count:
        raise ValueError(
            f"financial as-of violations: {manifest.as_of_violation_count}"
        )
    if manifest.duplicate_count:
        raise ValueError(f"duplicate samples: {manifest.duplicate_count}")
    forbidden = [
        feature
        for feature in spec.features
        if feature.startswith("forward_")
    ]
    if forbidden:
        raise ValueError(f"future columns cannot be features: {forbidden}")
    labeled = frame.dropna(subset=[spec.target]).copy()
    if labeled.empty:
        raise ValueError("multifactor dataset has no valid labels")
    invalid_entry = (
        labeled["entry_date"].astype(str)
        <= labeled["signal_date"].astype(str)
    )
    invalid_exit = (
        labeled["exit_date"].astype(str)
        <= labeled["entry_date"].astype(str)
    )
    if invalid_entry.any() or invalid_exit.any():
        raise ValueError("forward labels must occur strictly after signal date")
