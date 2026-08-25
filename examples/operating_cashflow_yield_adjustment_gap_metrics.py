"""经营现金流收益率复权缺口的纯统计诊断。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.quality_value_lowvol import MATERIAL_ADJ_FACTOR_CHANGE


def diagnose_adjustment_gaps(frame: pd.DataFrame) -> dict[str, Any]:
    """判断统一视图缺口是否能由同源完整复权历史无歧义恢复。"""
    required = [
        "signal_date",
        "symbol",
        "f_ann_date",
        "current_adj_factor",
        "report_adj_factor",
        "full_report_adj_factor",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"adjustment gap audit missing columns: {missing}")
    data = frame.copy()
    for column in [
        "current_adj_factor",
        "report_adj_factor",
        "full_report_adj_factor",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    limited_missing = data["report_adj_factor"].isna()
    recovered = limited_missing & data["full_report_adj_factor"].notna()
    unresolved = limited_missing & data["full_report_adj_factor"].isna()
    full_available = data[
        ["current_adj_factor", "full_report_adj_factor"]
    ].notna().all(axis=1)
    full_change = (
        data["current_adj_factor"] / data["full_report_adj_factor"] - 1.0
    ).abs()
    signal_year_counts = _year_counts(data[limited_missing], "signal_date")
    report_year_counts = _year_counts(data[limited_missing], "f_ann_date")
    checks = {
        "zero_current_adjustment_missing": (
            int(data["current_adj_factor"].isna().sum()) == 0
        ),
        "all_limited_view_gaps_recovered": (
            int(recovered.sum()) == int(limited_missing.sum())
        ),
        "zero_full_history_unresolved": int(unresolved.sum()) == 0,
        "all_gaps_are_2015_signals": (
            set(signal_year_counts) == {"2015"}
        ),
        "all_gaps_are_2014_reports": (
            set(report_year_counts) == {"2014"}
        ),
    }
    passed = all(checks.values())
    return {
        "eligible_rows": int(len(data)),
        "current_adjustment_missing_rows": int(
            data["current_adj_factor"].isna().sum()
        ),
        "limited_view_missing_rows": int(limited_missing.sum()),
        "limited_view_missing_share": (
            float(limited_missing.mean()) if len(data) else 1.0
        ),
        "recovered_rows": int(recovered.sum()),
        "unresolved_rows": int(unresolved.sum()),
        "unresolved_share": (
            float(unresolved.mean()) if len(data) else 1.0
        ),
        "full_history_material_action_share": (
            float((full_available & full_change.gt(MATERIAL_ADJ_FACTOR_CHANGE)).mean())
            if len(data)
            else 0.0
        ),
        "signal_year_counts": signal_year_counts,
        "report_year_counts": report_year_counts,
        "first_gap_signal_date": (
            str(data.loc[limited_missing, "signal_date"].min())
            if limited_missing.any()
            else ""
        ),
        "last_gap_signal_date": (
            str(data.loc[limited_missing, "signal_date"].max())
            if limited_missing.any()
            else ""
        ),
        "first_gap_report_date": (
            str(data.loc[limited_missing, "f_ann_date"].min())
            if limited_missing.any()
            else ""
        ),
        "last_gap_report_date": (
            str(data.loc[limited_missing, "f_ann_date"].max())
            if limited_missing.any()
            else ""
        ),
        "checks": checks,
        "passed": passed,
        "decision": (
            "DATA_LAYER_LOOKBACK_DEFECT_CONFIRMED"
            if passed
            else "GENUINE_ADJUSTMENT_GAPS_REMAIN"
        ),
    }


def _year_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    """按日期字段前四位统计缺口年份。"""
    if frame.empty:
        return {}
    return {
        str(year): int(count)
        for year, count in (
            frame[column].astype(str).str[:4].value_counts().sort_index().items()
        )
    }
