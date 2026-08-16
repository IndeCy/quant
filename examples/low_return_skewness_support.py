"""低收益偏度研究的股票池、数据门禁和组合诊断。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.lottery_features import LOTTERY_MAX_TABLE
from data.return_skewness import RETURN_SKEWNESS_TABLE
from factors.return_skewness import score_low_return_skewness_frame
from portfolio.topn import build_topn_selections


TOP_N = 40
MIN_CANDIDATES = 1000
MIN_UNIQUE_VALUES = 1000
MIN_COVERAGE = 0.95
MIN_QUALIFIED_MONTH_SHARE = 0.90


def load_investable_panel(connection: Any) -> pd.DataFrame:
    """连接标准可投股票池，并保留偏度缺失记录作为覆盖分母。"""
    return connection.execute(
        f"""
        WITH signal_dates AS (
            SELECT MAX(trade_date) AS signal_date
            FROM features
            WHERE trade_date >= '20150101'
            GROUP BY SUBSTR(trade_date, 1, 6)
            HAVING MAX(trade_date) < (SELECT MAX(trade_date) FROM features)
        ),
        names AS (
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
            WHERE f.trade_date IN (SELECT signal_date FROM signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.name, sb.name) AS name,
            s.return_skewness_60d,
            s.observations,
            l.max_ret20,
            f.vol60,
            f.ret20,
            f.ret120,
            f.amount20 * 1000.0 AS amount20_rmb
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        LEFT JOIN {RETURN_SKEWNESS_TABLE} s
          ON f.trade_date = s.trade_date AND f.symbol = s.symbol
        LEFT JOIN {LOTTERY_MAX_TABLE} l
          ON f.trade_date = l.trade_date AND f.symbol = l.symbol
        WHERE f.trade_date IN (SELECT signal_date FROM signal_dates)
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
    """统计60日偏度在标准可投股票池中的覆盖与唯一值数量。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        values = pd.to_numeric(group["return_skewness_60d"], errors="coerce")
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
    panel: pd.DataFrame,
    monthly: pd.DataFrame,
) -> dict[str, Any]:
    """执行冻结覆盖、历史长度、唯一性和主键门禁。"""
    if monthly.empty:
        raise ValueError("收益偏度数据门禁没有月末截面")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["coverage"].ge(MIN_COVERAGE)
    )
    qualified_share = float(qualified.mean())
    observations = pd.to_numeric(panel["observations"], errors="coerce")
    valid = panel["return_skewness_60d"].notna()
    checks = {
        "qualified_month_share": (
            qualified_share >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "all_valid_rows_have_60_observations": bool(
            observations.loc[valid].eq(60).all()
        ),
        "zero_duplicate_signal_symbol_rows": not panel.duplicated(
            ["signal_date", "symbol"]
        ).any(),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "qualified_month_share": qualified_share,
        "coverage_min": float(monthly["coverage"].min()),
        "coverage_median": float(monthly["coverage"].median()),
        "duplicate_rows": int(
            panel.duplicated(["signal_date", "symbol"]).sum()
        ),
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """把月度偏度评分交给通用TopN组合层。"""
    scores: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_low_return_skewness_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            scores.append(scored)
    if not scores:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    score_frame = pd.concat(scores, ignore_index=True)
    mappings, holdings = build_topn_selections(
        score_frame,
        "factor_score",
        TOP_N,
    )
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mappings.items()
    }
    count_values = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(count_values.min()),
        "median": float(count_values.median()),
        "latest": float(count_values.iloc[-1]),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """衡量偏度与低波、MAX彩票暴露和动量的关系。"""
    vol_corr: list[float] = []
    max_corr: list[float] = []
    momentum_corr: list[float] = []
    lowvol_overlap: list[float] = []
    lowmax_overlap: list[float] = []
    cutoff_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=[
                "return_skewness_60d",
                "max_ret20",
                "vol60",
                "ret120",
            ]
        )
        if len(valid) < TOP_N:
            continue
        skew_rank = valid["return_skewness_60d"].rank()
        vol_corr.append(float(skew_rank.corr(valid["vol60"].rank())))
        max_corr.append(float(skew_rank.corr(valid["max_ret20"].rank())))
        momentum_corr.append(float(skew_rank.corr(valid["ret120"].rank())))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        lowvol = set(valid.nsmallest(TOP_N, "vol60")["symbol"].astype(str))
        lowmax = set(valid.nsmallest(TOP_N, "max_ret20")["symbol"].astype(str))
        lowvol_overlap.append(len(selected & lowvol) / TOP_N)
        lowmax_overlap.append(len(selected & lowmax) / TOP_N)
        cutoff = valid["return_skewness_60d"].nsmallest(TOP_N).iloc[-1]
        cutoff_ties.append(
            int(valid["return_skewness_60d"].eq(cutoff).sum())
        )
    return {
        "median_spearman_with_vol60": _median(vol_corr),
        "median_spearman_with_max20": _median(max_corr),
        "median_spearman_with_ret120": _median(momentum_corr),
        "median_top40_overlap_with_lowvol": _median(lowvol_overlap),
        "median_top40_overlap_with_lowmax": _median(lowmax_overlap),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
        "selected_skewness_median": float(
            holdings["return_skewness_60d"].median()
        ),
        "selected_vol60_median": float(holdings["vol60"].median()),
        "selected_max20_median": float(holdings["max_ret20"].median()),
    }


def records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """将缺失值转换为JSON null。"""
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in record.items()
        }
        for record in frame.to_dict("records")
    ]


def build_execution_attribution(
    net_metrics: dict[str, dict[str, float]],
    frictionless_metrics: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """比较真实费用口径与零摩擦反事实，不改变选股和风控规则。"""
    attribution: dict[str, dict[str, float]] = {}
    for period, net in net_metrics.items():
        gross = frictionless_metrics[period]
        attribution[period] = {
            "net_annualized_return": float(net["annualized_return"]),
            "frictionless_annualized_return": float(
                gross["annualized_return"]
            ),
            "annualized_return_drag": float(
                gross["annualized_return"] - net["annualized_return"]
            ),
            "net_sharpe": float(net["sharpe"]),
            "frictionless_sharpe": float(gross["sharpe"]),
            "sharpe_drag": float(gross["sharpe"] - net["sharpe"]),
            "net_max_drawdown": float(net["max_drawdown"]),
            "frictionless_max_drawdown": float(gross["max_drawdown"]),
        }
    return attribution


def diagnose_execution_attribution(
    attribution: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """判断候选是执行负Alpha，还是零摩擦下仍然缺乏稳健性。"""
    locked = attribution["locked_test"]
    full = attribution["full"]
    frictionless_checks = {
        "locked_annual_return_at_least_8pct": (
            locked["frictionless_annualized_return"] >= 0.08
        ),
        "locked_sharpe_at_least_055": (
            locked["frictionless_sharpe"] >= 0.55
        ),
        "locked_drawdown_within_30pct": (
            locked["frictionless_max_drawdown"] >= -0.30
        ),
        "full_annual_return_at_least_10pct": (
            full["frictionless_annualized_return"] >= 0.10
        ),
        "full_sharpe_at_least_065": (
            full["frictionless_sharpe"] >= 0.65
        ),
        "full_drawdown_within_32pct": (
            full["frictionless_max_drawdown"] >= -0.32
        ),
    }
    frictionless_passed = all(frictionless_checks.values())
    return {
        "classification": (
            "EXECUTION_NEGATIVE_ALPHA"
            if frictionless_passed
            else "WEAK_GROSS_SIGNAL_WITH_COST_DRAG"
        ),
        "frictionless_passed_core_gate": frictionless_passed,
        "frictionless_checks": frictionless_checks,
        "locked_annualized_cost_drag": locked["annualized_return_drag"],
        "full_annualized_cost_drag": full["annualized_return_drag"],
    }


def _median(values: list[float]) -> float:
    """返回非空中位数。"""
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")
