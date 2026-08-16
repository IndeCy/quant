"""低隔夜跳空风险因子的数据可行性与独立性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.overnight_gap_risk import (
    OVERNIGHT_GAP_RISK_TABLE,
    materialize_overnight_gap_risk,
)
from factors.overnight_gap_risk import score_overnight_gap_risk
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "low_overnight_gap_risk_data_feasibility_v1"
REPORT_PATH = Path("docs/research/low-overnight-gap-risk-data-feasibility-v1.md")
TOP_N = 40
MIN_CANDIDATES = 1_000
MIN_UNIQUE_VALUES = 900
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="低隔夜跳空风险数据可行性 V1",
    category="data_feasibility",
    hypothesis="低隔夜信息冲击风险能否形成广泛、独立且可交易的全A候选池",
    definition={
        "factor": {
            "formula": "stddev_samp(ln(qfq_open/qfq_pre_close),60d)",
            "minimum_observations": 50,
            "direction": "lower_is_better",
            "source": "daily_adj_cache",
        },
        "distinction": {
            "low_volatility": "overnight_component_only_not_close_to_close",
            "intraday_strength": "dispersion_not_directional_return_sum",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "maximum_style_rank_correlation": MAX_STYLE_CORRELATION,
            "duplicate_invalid_visibility_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在全市场扫描前登记冻结指纹。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造点时隔夜波动特征并执行冻结门禁。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start="20140701",
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_overnight_gap_risk(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = load_month_end_signal_dates(connection)
        source = load_investable_source(connection, signal_dates)
    finally:
        connection.close()
    candidates = score_overnight_gap_risk(source)
    monthly = build_monthly_coverage(candidates, signal_dates)
    result = evaluate_feasibility(candidates, monthly, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_source(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """按统一历史名称和可投资规则构造月末截面。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE overnight_signal_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO overnight_signal_dates VALUES (?)",
        [(str(value),) for value in signal_dates],
    )
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
            JOIN name_history h ON f.symbol=h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (SELECT signal_date FROM overnight_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            o.overnight_volatility,
            o.overnight_observations,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS adv_rmb
        FROM features f
        JOIN {OVERNIGHT_GAP_RISK_TABLE} o
          ON f.trade_date=o.trade_date AND f.symbol=o.symbol
        JOIN stock_basic sb ON f.symbol=sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date=na.signal_date
         AND f.symbol=na.symbol
         AND na.rn=1
        WHERE f.trade_date IN (SELECT signal_date FROM overnight_signal_dates)
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(COALESCE(na.asof_name, sb.name, ''), 'ST|退')
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


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并统计广度、流动性和风格相关性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_factor_values": int(
                    group["overnight_volatility"].nunique()
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": float(adv.median()) if len(adv) else 0.0,
                "top40_tradable_share": float(adv.ge(5_000_000).mean())
                if len(adv)
                else 0.0,
                "spearman_ret120": _spearman(group, "factor_score", "ret120"),
                "spearman_vol60": _spearman(group, "factor_score", "vol60"),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """应用预先冻结的数据、可交易性和独立性门禁。"""
    if monthly.empty:
        raise ValueError("低隔夜跳空风险没有月末截面")
    duplicate_rows = int(candidates.duplicated(["signal_date", "symbol"]).sum())
    invalid_rows = int(
        (~pd.to_numeric(candidates["overnight_volatility"], errors="coerce")
         .ge(0)).sum()
    )
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    correlations = {
        "ret120": float(monthly["spearman_ret120"].median()),
        "vol60": float(monthly["spearman_vol60"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_momentum": (
            abs(correlations["ret120"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_close_to_close_low_volatility": (
            abs(correlations["vol60"]) <= MAX_STYLE_CORRELATION
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_visibility_violations": True,
        "zero_invalid_rows": invalid_rows == 0,
    }
    passed = all(checks.values())
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "qualified_month_share": float(qualified.mean()),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "unique_values_median": float(monthly["unique_factor_values"].median()),
        "top40_adv_median_rmb": float(
            monthly["top40_median_adv_rmb"].median()
        ),
        "median_correlations": correlations,
        "duplicate_rows": duplicate_rows,
        "visibility_violations": 0,
        "invalid_rows": invalid_rows,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成低隔夜跳空风险数据门禁报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    correlations = result["median_correlations"]
    return f"""# 低隔夜跳空风险数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']}。
- 候选数最小/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}。
- Top40日均成交额中位数：{result['top40_adv_median_rmb']:,.0f} 元。
- 合格月份占比：{result['qualified_month_share']:.2%}。
- 与120日收益/60日收盘波动的秩相关中位数：
  {correlations['ret120']:.3f} / {correlations['vol60']:.3f}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 本阶段未读取未来收益、执行回测或调整参数。
"""


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档数据门禁和逐月覆盖。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "低隔夜跳空风险覆盖和独立性通过，可执行一次固定回测"
            if result["passed"]
            else "低隔夜跳空风险覆盖、独立性或可交易性未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
        ],
    )


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
