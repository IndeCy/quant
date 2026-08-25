"""成交额加权涨跌压力因子的数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from data.signed_amount_pressure import (
    SIGNED_AMOUNT_PRESSURE_TABLE,
    materialize_signed_amount_pressure,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "signed_amount_pressure_data_feasibility_v1"
REPORT_PATH = Path("docs/research/signed-amount-pressure-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
WINDOW = 20
MIN_CANDIDATES = 1000
MIN_UNIQUE_VALUES = 800
MIN_MONTH_SHARE = 0.90
MAX_DAILY_CONCENTRATION_MEDIAN = 0.35
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="成交额加权涨跌压力数据可行性 V1",
    category="data_feasibility",
    hypothesis="日收益方向签名成交额能否形成稳定、可辨识的全A月频截面",
    definition={
        "factor": {
            "formula": "sum(sign(qfq_daily_return)*amount,20d)/sum(amount,20d)",
            "range": [-1, 1],
            "direction": "higher_is_better",
            "semantic": "daily_price_volume_proxy_not_true_order_flow",
        },
        "visibility": {
            "window": WINDOW,
            "same_day_close_signal_next_trading_day_execution": True,
            "no_future_data": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "maximum_daily_amount_share_median": (
                MAX_DAILY_CONCENTRATION_MEDIAN
            ),
            "duplicate_signal_symbol_rows": 0,
            "range_violations": 0,
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
    """先申请研究指纹，再扫描全量日线窗口。"""
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
    """物化成交额压力并执行冻结数据门槛。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_signed_amount_pressure(connection, window=WINDOW)
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
    """连接标准可投股票池与同日成交额压力。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE signed_pressure_signal_dates("
        "signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO signed_pressure_signal_dates VALUES (?)",
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
                SELECT signal_date FROM signed_pressure_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            s.return_20d,
            s.signed_amount_pressure,
            s.positive_amount_share,
            s.negative_amount_share,
            s.neutral_amount_share,
            s.positive_day_share,
            s.maximum_daily_amount_share,
            s.amount_sum,
            s.observations
        FROM features f
        JOIN {SIGNED_AMOUNT_PRESSURE_TABLE} s
          ON f.trade_date = s.trade_date AND f.symbol = s.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
                SELECT signal_date FROM signed_pressure_signal_dates
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
    """统计月度有效候选和因子辨识度。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(len(group)),
                "unique_factor_values": int(
                    group["signed_amount_pressure"].nunique()
                ),
                "maximum_daily_concentration_median": float(
                    group["maximum_daily_amount_share"].median()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新截面的成交额压力和收益分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    return {
        "pressure_p01": float(latest["signed_amount_pressure"].quantile(0.01)),
        "pressure_median": float(latest["signed_amount_pressure"].median()),
        "pressure_p99": float(latest["signed_amount_pressure"].quantile(0.99)),
        "return_p01": float(latest["return_20d"].quantile(0.01)),
        "return_median": float(latest["return_20d"].median()),
        "return_p99": float(latest["return_20d"].quantile(0.99)),
    }


def load_diagnostics(
    connection: Any,
    panel: pd.DataFrame,
) -> dict[str, float]:
    """检查范围、窗口、主键和价格动量重合。"""
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) - COUNT(DISTINCT trade_date || ':' || symbol),
            SUM(CASE WHEN observations <> {WINDOW} THEN 1 ELSE 0 END),
            SUM(
                CASE WHEN signed_amount_pressure < -1
                       OR signed_amount_pressure > 1
                     THEN 1 ELSE 0 END
            )
        FROM {SIGNED_AMOUNT_PRESSURE_TABLE}
        """
    ).fetchone()
    correlations: list[float] = []
    for _, group in panel.groupby("signal_date", sort=True):
        correlation = group["signed_amount_pressure"].rank().corr(
            group["return_20d"].rank()
        )
        if pd.notna(correlation):
            correlations.append(float(correlation))
    return {
        "duplicate_signal_symbol_rows": float(row[0] or 0),
        "window_length_violations": float(row[1] or 0),
        "range_violations": float(row[2] or 0),
        "median_spearman_with_return_20d": float(
            pd.Series(correlations).median()
        ),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结的覆盖、集中度和数值门槛。"""
    if monthly.empty:
        raise ValueError("成交额压力覆盖审计没有月末数据")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["maximum_daily_concentration_median"].le(
            MAX_DAILY_CONCENTRATION_MEDIAN
        )
    )
    full_share = float(qualified.mean())
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = (
        locked["candidate_count"].ge(MIN_CANDIDATES)
        & locked["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & locked["maximum_daily_concentration_median"].le(
            MAX_DAILY_CONCENTRATION_MEDIAN
        )
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
        "zero_range_violations": diagnostics["range_violations"] == 0,
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
        "unique_value_min": int(monthly["unique_factor_values"].min()),
        "concentration_median_max": float(
            monthly["maximum_daily_concentration_median"].max()
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
    """归档数据审计，未通过时不启动回测。"""
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
            "成交额压力数据稳定，可进入固定回测"
            if passed
            else "成交额压力未通过冻结数据门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成成交额压力数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 成交额加权涨跌压力数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值最少：{result['unique_value_min']}；
  单日成交额集中度月度中位数最大值：
  {result['concentration_median_max']:.2%}。
- 最新压力 P1/中位/P99：{distribution['pressure_p01']:.3f} /
  {distribution['pressure_median']:.3f} /
  {distribution['pressure_p99']:.3f}。
- 最新20日收益 P1/中位/P99：{distribution['return_p01']:.2%} /
  {distribution['return_median']:.2%} / {distribution['return_p99']:.2%}。
- 与20日收益的月度 Spearman 中位数：
  {diagnostics['median_spearman_with_return_20d']:.3f}。
- 重复主键/窗口异常/范围异常：
  {diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['window_length_violations']:.0f} /
  {diagnostics['range_violations']:.0f}。

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
