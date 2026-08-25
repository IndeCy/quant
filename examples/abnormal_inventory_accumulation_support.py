"""异常存货积累研究的股票池、门禁和组合诊断。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.abnormal_inventory import ABNORMAL_INVENTORY_TABLE
from factors.abnormal_inventory import score_abnormal_inventory_frame
from portfolio.topn import build_topn_selections


LOCKED_START = "20220101"
TOP_N = 40
MIN_CANDIDATES = 500
MIN_UNIQUE_VALUES = 400
MIN_COVERAGE = 0.50
MIN_MONTH_SHARE = 0.90


def load_investable_panel(connection: Any) -> pd.DataFrame:
    """连接标准可投股票池，保留财务缺失记录作为覆盖分母。"""
    return connection.execute(
        f"""
        WITH names AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                n.name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY n.start_date DESC
                ) AS rn
            FROM features f
            JOIN names n ON f.symbol = n.ts_code
             AND n.start_date <= f.trade_date
             AND (n.end_date IS NULL OR n.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date FROM abnormal_inventory_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.name, sb.name) AS name,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS amount20_rmb,
            a.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        LEFT JOIN {ABNORMAL_INVENTORY_TABLE} a
          ON f.trade_date = a.signal_date AND f.symbol = a.symbol
        WHERE f.trade_date IN (
                SELECT signal_date FROM abnormal_inventory_signal_dates
              )
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(COALESCE(na.name, sb.name, ''), 'ST|退')
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_monthly_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """统计因子在标准可投股票池中的覆盖与辨识度。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        values = pd.to_numeric(
            group["abnormal_inventory_accumulation"],
            errors="coerce",
        )
        rows.append(
            {
                "signal_date": str(signal_date),
                "investable_count": int(len(group)),
                "candidate_count": int(values.notna().sum()),
                "coverage": float(values.notna().mean()),
                "unique_factor_values": int(values.nunique()),
            }
        )
    return pd.DataFrame(rows)


def evaluate_data_gate(
    connection: Any,
    monthly: pd.DataFrame,
) -> dict[str, Any]:
    """执行研究前冻结的数据覆盖、公告日和唯一性门槛。"""
    if monthly.empty:
        raise ValueError("异常存货数据门禁没有月末截面")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["coverage"].ge(MIN_COVERAGE)
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = (
        locked["candidate_count"].ge(MIN_CANDIDATES)
        & locked["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & locked["coverage"].ge(MIN_COVERAGE)
    )
    audit = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN publish_date > signal_date
                       OR income_publish_date > signal_date
                       OR balance_publish_date > signal_date
                       OR prior_publish_date > signal_date
                     THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol)
        FROM {ABNORMAL_INVENTORY_TABLE}
        """
    ).fetchone()
    full_share = float(qualified.mean())
    locked_share = float(
        locked_qualified.mean() if not locked.empty else 0.0
    )
    checks = {
        "full_qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
        "zero_visibility_violations": int(audit[0] or 0) == 0,
        "zero_duplicate_signal_symbol_rows": int(audit[1] or 0) == 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "investable_count_min": float(monthly["investable_count"].min()),
        "coverage_min": float(monthly["coverage"].min()),
        "coverage_median": float(monthly["coverage"].median()),
        "full_qualified_month_share": full_share,
        "locked_qualified_month_share": locked_share,
        "visibility_violations": int(audit[0] or 0),
        "duplicate_rows": int(audit[1] or 0),
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月生成异常存货 Top40 等权目标。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_abnormal_inventory_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mappings.items()
    }
    values = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(values.min()),
        "median": float(values.median()),
        "latest": float(values.iloc[-1]),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """区分异常积累、纯存货收缩和动量暴露。"""
    inventory_corr: list[float] = []
    revenue_corr: list[float] = []
    momentum_corr: list[float] = []
    inventory_overlap: list[float] = []
    momentum_overlap: list[float] = []
    top_score_ties: list[int] = []
    selected_tie_shares: list[float] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=[
                "abnormal_inventory_accumulation",
                "inventory_log_growth",
                "revenue_log_growth",
                "ret120",
            ]
        )
        if len(valid) < TOP_N:
            continue
        scored = score_abnormal_inventory_frame(valid)
        top_score = float(scored["factor_score"].max())
        top_score_ties.append(
            int(scored["factor_score"].eq(top_score).sum())
        )
        base_rank = valid["abnormal_inventory_accumulation"].rank()
        inventory_corr.append(
            float(base_rank.corr(valid["inventory_log_growth"].rank()))
        )
        revenue_corr.append(
            float(base_rank.corr(valid["revenue_log_growth"].rank()))
        )
        momentum_corr.append(float(base_rank.corr(valid["ret120"].rank())))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        selected_frame = holdings.loc[
            holdings["signal_date"].astype(str).eq(str(signal_date))
        ]
        selected_tie_shares.append(
            float(selected_frame["factor_score"].eq(top_score).mean())
        )
        low_inventory = set(
            valid.nsmallest(TOP_N, "inventory_log_growth")["symbol"].astype(str)
        )
        momentum = set(
            valid.nlargest(TOP_N, "ret120")["symbol"].astype(str)
        )
        inventory_overlap.append(len(selected & low_inventory) / TOP_N)
        momentum_overlap.append(len(selected & momentum) / TOP_N)
    return {
        "median_spearman_with_inventory_growth": _median(inventory_corr),
        "median_spearman_with_revenue_growth": _median(revenue_corr),
        "median_spearman_with_ret120": _median(momentum_corr),
        "median_top40_overlap_with_low_inventory_growth": _median(
            inventory_overlap
        ),
        "median_top40_overlap_with_momentum": _median(momentum_overlap),
        "median_top_score_tie_count": _median(top_score_ties),
        "maximum_top_score_tie_count": float(max(top_score_ties)),
        "median_selected_clipped_tie_share": _median(selected_tie_shares),
        "selected_abnormal_accumulation_median": float(
            holdings["abnormal_inventory_accumulation"].median()
        ),
        "selected_inventory_log_growth_median": float(
            holdings["inventory_log_growth"].median()
        ),
        "selected_revenue_log_growth_median": float(
            holdings["revenue_log_growth"].median()
        ),
    }


def _median(values: list[float]) -> float:
    """返回非空中位数。"""
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")
