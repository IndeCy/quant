"""Quality Alpha V1 的股票池构造与过滤规则。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from data.quality_financial import QUALITY_ANNUAL_ASOF_TABLE
from factors.quality import QUALITY_COLUMNS


class QueryConnection(Protocol):
    """声明股票池查询需要的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行查询。"""


def load_annual_quality_candidates(connection: QueryConnection) -> pd.DataFrame:
    """读取月末可交易且具备年度 Quality 财务快照的候选池。"""
    return connection.execute(
        f"""
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                h.name AS asof_name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            sb.list_status,
            sb.list_date,
            sb.delist_date,
            f.close,
            f.raw_close,
            f.adj_factor AS current_adj_factor,
            f.vol60,
            f.ret20,
            f.ret120,
            f.ma60,
            f.ma120,
            f.amount20,
            f.amount60,
            f.downside_vol60,
            f.worst_ret60,
            f.amount,
            f.amount_p20,
            f.volume,
            f.st_name,
            q.end_date,
            q.f_ann_date,
            q.roe,
            q.roa,
            q.ocf_to_or,
            q.ocf_to_profit,
            q.grossprofit_margin,
            q.netprofit_margin,
            q.assets_yoy,
            q.roic,
            q.assets_turn,
            q.salescash_to_or,
            q.dtprofit_to_profit,
            q.netprofit_yoy,
            q.eps,
            q.bps,
            q.debt_to_assets,
            q.tr_yoy
        FROM features f
        JOIN {QUALITY_ANNUAL_ASOF_TABLE} q
          ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def apply_quality_universe_filters(
    frame: pd.DataFrame,
    *,
    quantile_filter: bool = True,
) -> pd.DataFrame:
    """复现上市满三年、ST、退市和 ROE/ROA 分位过滤。"""
    required = [
        "signal_date", "symbol", "name", "list_date", "delist_date",
        "st_name", "end_date", *QUALITY_COLUMNS,
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"quality candidates missing columns: {missing}")
    data = frame.copy()
    signal_date = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    list_date = pd.to_datetime(data["list_date"], format="%Y%m%d", errors="coerce")
    delist_date = pd.to_datetime(data["delist_date"], format="%Y%m%d", errors="coerce")
    listed_years = (signal_date - list_date).dt.days / 365.25
    delisted_asof = delist_date.notna() & (delist_date <= signal_date)
    valid = (
        (listed_years >= 3)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~delisted_asof
        & data["end_date"].astype(str).str.endswith("1231")
        & data[QUALITY_COLUMNS].notna().all(axis=1)
    )
    filtered = data[valid].copy()
    if not quantile_filter or filtered.empty:
        return filtered

    groups: list[pd.DataFrame] = []
    for _, group in filtered.groupby("signal_date", sort=True):
        roe_low, roe_high = group["roe"].quantile([0.05, 0.95])
        roa_low, roa_high = group["roa"].quantile([0.05, 0.95])
        groups.append(
            group[
                group["roe"].between(roe_low, roe_high, inclusive="both")
                & group["roa"].between(roa_low, roa_high, inclusive="both")
            ]
        )
    return pd.concat(groups, ignore_index=True) if groups else filtered.iloc[0:0].copy()
