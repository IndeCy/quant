"""Quality Value LowVol 的时点估值与公司行为一致性门面。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Protocol

import pandas as pd

from data.quality_financial import QUALITY_ANNUAL_ASOF_TABLE


MATERIAL_ADJ_FACTOR_CHANGE = 0.10


class QueryConnection(Protocol):
    """声明本模块需要的最小 DuckDB 查询能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行查询。"""


@dataclass(frozen=True)
class CorporateActionAudit:
    """记录每个信号截面的复权因子一致性结果。"""

    checked_rows: int
    changed_rows: int
    excluded_rows: int
    missing_rows: int
    materiality_threshold: float


def attach_report_adjustment_factors(
    connection: QueryConnection,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    """取公告日最近交易日复权因子，禁止估值口径跨公司行为直接比较。"""
    if candidates.empty:
        result = candidates.copy()
        result["report_adj_factor"] = pd.Series(dtype=float)
        return result
    report_factors = connection.execute(
        f"""
        SELECT q.signal_date, q.symbol, a.adj_factor AS report_adj_factor
        FROM (
            SELECT signal_date, symbol, f_ann_date
            FROM {QUALITY_ANNUAL_ASOF_TABLE}
        ) q
        ASOF LEFT JOIN (
            SELECT ts_code AS symbol, trade_date, adj_factor
            FROM daily_adj_cache
            ORDER BY symbol, trade_date
        ) a
          ON q.symbol = a.symbol AND q.f_ann_date >= a.trade_date
        ORDER BY q.signal_date, q.symbol
        """
    ).fetchdf()
    return candidates.merge(report_factors, on=["signal_date", "symbol"], how="left")


def build_quality_value_lowvol_candidates(
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, CorporateActionAudit]:
    """生成五因子原始值，并过滤公告日至信号日的重大复权变化。"""
    required = [
        "raw_close",
        "current_adj_factor",
        "report_adj_factor",
        "roa",
        "ocf_to_or",
        "eps",
        "bps",
        "vol60",
    ]
    missing = [column for column in required if column not in candidates.columns]
    if missing:
        raise ValueError(f"quality value lowvol candidates missing columns: {missing}")
    data = candidates.copy()
    numeric_columns = required
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid_price = data["raw_close"].notna() & data["raw_close"].gt(0)
    available_adjustment = data[["current_adj_factor", "report_adj_factor"]].notna().all(axis=1)
    adjustment_change = (data["current_adj_factor"] / data["report_adj_factor"] - 1.0).abs()
    # 复权因子也会因现金分红小幅变化；仅拦截足以扭曲每股指标的重大变化，并保留完整审计计数。
    stable_adjustment = available_adjustment & adjustment_change.le(MATERIAL_ADJ_FACTOR_CHANGE)
    valid_factors = data[["roa", "ocf_to_or", "eps", "bps", "vol60"]].notna().all(axis=1)
    accepted = data[valid_price & stable_adjustment & valid_factors].copy()
    accepted["earnings_yield"] = accepted["eps"] / accepted["raw_close"]
    accepted["book_yield"] = accepted["bps"] / accepted["raw_close"]
    accepted["low_volatility_60d"] = -accepted["vol60"]
    finite = accepted[["earnings_yield", "book_yield", "low_volatility_60d"]].apply(
        lambda series: series.map(lambda value: pd.notna(value) and math.isfinite(float(value)))
    ).all(axis=1)
    accepted = accepted[finite].copy()
    audit = CorporateActionAudit(
        checked_rows=len(data),
        changed_rows=int((available_adjustment & adjustment_change.gt(1e-12)).sum()),
        excluded_rows=int((available_adjustment & ~stable_adjustment).sum()),
        missing_rows=int((~available_adjustment).sum()),
        materiality_threshold=MATERIAL_ADJ_FACTOR_CHANGE,
    )
    return accepted.reset_index(drop=True), audit
