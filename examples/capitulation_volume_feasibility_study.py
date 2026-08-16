"""放量下跌恐慌反转的数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.abnormal_amount import (
    ABNORMAL_AMOUNT_TABLE,
    materialize_abnormal_amount,
)
from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "capitulation_volume_data_feasibility_v1"
REPORT_PATH = Path("docs/research/capitulation-volume-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
RECENT_WINDOW = 20
BASELINE_WINDOW = 60
MIN_CANDIDATES = 1000
MIN_SIGNAL_CANDIDATES = 80
MIN_MONTH_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="放量下跌恐慌反转数据可行性 V1",
    category="data_feasibility",
    hypothesis="个股近期放量下跌样本能否稳定覆盖全A月频截面",
    definition={
        "source": {
            "provider": "local_duckdb",
            "fields": ["amount", "close_qfq"],
            "amount_semantic": "self_relative_trading_amount_not_turnover_rate",
        },
        "signal": {
            "return": "qfq_close/current_vs_20_observations_ago_minus_1",
            "abnormal_amount": "mean_amount_recent20/mean_amount_prior60",
            "gates": ["return_20d<0", "abnormal_amount_ratio>1"],
        },
        "visibility": {
            "recent_and_baseline_windows_non_overlapping": True,
            "same_day_close_signal_next_trading_day_execution": True,
            "no_future_data": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "capitulation_floor": MIN_SIGNAL_CANDIDATES,
            "month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "duplicate_signal_symbol_rows": 0,
        },
        "decision": "feasibility_only_no_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请运行指纹，再扫描全量日线窗口。"""
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
    """构造异常成交额面板并执行冻结覆盖门槛。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_abnormal_amount(
            connection,
            recent_window=RECENT_WINDOW,
            baseline_window=BASELINE_WINDOW,
        )
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        panel = load_investable_panel(connection, signal_dates)
        monthly = build_monthly_coverage(panel)
        distribution = build_latest_distribution(panel)
        diagnostics = load_diagnostics(connection, panel)
    finally:
        connection.close()
    result = evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_panel(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """连接标准可投股票池和同日异常成交额特征。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE capitulation_signal_dates("
        "signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO capitulation_signal_dates VALUES (?)",
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
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date FROM capitulation_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            a.return_20d,
            a.recent_amount_average,
            a.baseline_amount_average,
            a.abnormal_amount_ratio,
            a.log_abnormal_amount,
            a.recent_observations,
            a.baseline_observations
        FROM features f
        JOIN {ABNORMAL_AMOUNT_TABLE} a
          ON f.trade_date = a.trade_date AND f.symbol = a.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
                SELECT signal_date FROM capitulation_signal_dates
              )
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


def build_monthly_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """统计全部有效样本和放量下跌样本数量。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        signal = group[
            group["return_20d"].lt(0)
            & group["abnormal_amount_ratio"].gt(1)
        ]
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(len(group)),
                "signal_candidate_count": int(len(signal)),
                "unique_volume_ratios": int(
                    signal["abnormal_amount_ratio"].nunique()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新截面异常成交和跌幅分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    signal = latest[
        latest["return_20d"].lt(0)
        & latest["abnormal_amount_ratio"].gt(1)
    ]
    return {
        "ratio_p01": float(signal["abnormal_amount_ratio"].quantile(0.01)),
        "ratio_median": float(signal["abnormal_amount_ratio"].median()),
        "ratio_p99": float(signal["abnormal_amount_ratio"].quantile(0.99)),
        "return_p01": float(signal["return_20d"].quantile(0.01)),
        "return_median": float(signal["return_20d"].median()),
        "return_p99": float(signal["return_20d"].quantile(0.99)),
    }


def load_diagnostics(
    connection: Any,
    panel: pd.DataFrame,
) -> dict[str, float]:
    """检查主键、窗口长度和量价横截面关系。"""
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) - COUNT(DISTINCT trade_date || ':' || symbol),
            SUM(
                CASE WHEN recent_observations <> {RECENT_WINDOW}
                       OR baseline_observations <> {BASELINE_WINDOW}
                     THEN 1 ELSE 0 END
            )
        FROM {ABNORMAL_AMOUNT_TABLE}
        """
    ).fetchone()
    correlations: list[float] = []
    for _, group in panel.groupby("signal_date", sort=True):
        correlation = group["return_20d"].rank().corr(
            group["abnormal_amount_ratio"].rank()
        )
        if pd.notna(correlation):
            correlations.append(float(correlation))
    return {
        "duplicate_signal_symbol_rows": float(row[0] or 0),
        "window_length_violations": float(row[1] or 0),
        "median_spearman_return_vs_abnormal_amount": float(
            pd.Series(correlations).median()
        ),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结的覆盖、辨识度和窗口门槛。"""
    if monthly.empty:
        raise ValueError("恐慌反转覆盖审计没有月末数据")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["signal_candidate_count"].ge(MIN_SIGNAL_CANDIDATES)
        & monthly["unique_volume_ratios"].ge(MIN_SIGNAL_CANDIDATES)
    )
    full_share = float(qualified.mean())
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = (
        locked["candidate_count"].ge(MIN_CANDIDATES)
        & locked["signal_candidate_count"].ge(MIN_SIGNAL_CANDIDATES)
        & locked["unique_volume_ratios"].ge(MIN_SIGNAL_CANDIDATES)
    )
    locked_share = float(
        locked_qualified.mean() if not locked.empty else 0.0
    )
    checks = {
        "full_qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "zero_window_length_violations": (
            diagnostics["window_length_violations"] == 0
        ),
        "finite_latest_distribution": all(
            pd.notna(value) for value in distribution.values()
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "signal_count_min": int(monthly["signal_candidate_count"].min()),
        "signal_count_median": float(
            monthly["signal_candidate_count"].median()
        ),
        "signal_count_latest": int(
            monthly["signal_candidate_count"].iloc[-1]
        ),
        "full_qualified_month_share": full_share,
        "locked_qualified_month_share": locked_share,
        "latest_distribution": distribution,
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档数据审计，未通过时不启动收益回测。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "放量下跌样本稳定，可进入固定恐慌反转回测"
            if passed
            else "放量下跌样本不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成放量下跌数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 放量下跌恐慌反转数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 全部候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 放量下跌候选最少/中位/最新：{result['signal_count_min']} /
  {result['signal_count_median']:.0f} / {result['signal_count_latest']}。
- 最新异常成交比 P1/中位/P99：{distribution['ratio_p01']:.2f} /
  {distribution['ratio_median']:.2f} / {distribution['ratio_p99']:.2f}。
- 最新20日收益 P1/中位/P99：{distribution['return_p01']:.2%} /
  {distribution['return_median']:.2%} / {distribution['return_p99']:.2%}。
- 收益与异常成交比月度 Spearman 中位数：
  {diagnostics['median_spearman_return_vs_abnormal_amount']:.3f}。
- 重复主键/窗口长度异常：{diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['window_length_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定基础行情和增量行情版本。"""
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
