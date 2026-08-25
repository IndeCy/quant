"""净股本发行独立因子的点时可行性审计。"""

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
from data.net_share_issuance import (
    NET_SHARE_ISSUANCE_TABLE,
    NetShareIssuancePaths,
    attach_net_share_issuance_database,
    create_net_share_issuance_signal_dates,
    materialize_net_share_issuance_asof,
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


EXPERIMENT_ID = "net_share_issuance_data_feasibility_v1"
REPORT_PATH = Path("docs/research/net-share-issuance-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_MONTH_SHARE = 0.90
MIN_NEGATIVE_ISSUERS = 40
MIN_DISTINGUISHABLE_MONTH_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净股本发行数据可行性 V1",
    category="data_feasibility",
    hypothesis="连续年报股本收缩能否形成无公司行为污染的独立长端候选池",
    definition={
        "factor": {
            "formula": "annual_total_share/prior_annual_total_share-1",
            "direction": "lower_is_better",
            "annual_reports_only": True,
            "requires_consecutive_years": True,
        },
        "visibility": {
            "rule": "latest_revision_f_ann_date_lte_signal_date",
            "report_freshness_years": [1, 2],
        },
        "corporate_action_gate": {
            "audit": "report_period_adj_factor_change",
            "material_change": 0.10,
            "exclude_when_share_and_adj_factor_both_change": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "candidate_month_share": MIN_MONTH_SHARE,
            "negative_issuer_floor": MIN_NEGATIVE_ISSUERS,
            "distinguishable_month_share": MIN_DISTINGUISHABLE_MONTH_SHARE,
            "visibility_violations": 0,
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
    """先登记指纹，再扫描资产负债表和复权历史。"""
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
    """验证股本变化是否能组成不依赖代码排序的 Top40。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_net_share_issuance_signal_dates(connection, signal_dates)
        attach_net_share_issuance_database(
            connection,
            NetShareIssuancePaths(paths.balance_sheet_path),
        )
        materialize_net_share_issuance_asof(connection)
        candidates = load_candidates(connection)
        source_diagnostics = load_source_diagnostics(connection)
    finally:
        connection.close()

    monthly = build_monthly_coverage(candidates)
    distribution = build_latest_distribution(candidates)
    result = evaluate_feasibility(
        monthly,
        distribution,
        source_diagnostics,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_candidates(connection: Any) -> pd.DataFrame:
    """读取公司行为口径清晰且可交易的年度股本变化。"""
    source = load_investable_source(connection)
    available = source["adjustment_available"].fillna(False).astype(bool)
    ambiguous = source["corporate_action_ambiguous"].fillna(False).astype(bool)
    return source[available & ~ambiguous].reset_index(drop=True)


def load_investable_source(connection: Any) -> pd.DataFrame:
    """先应用标准股票池，保留复权缺失和歧义记录供审计。"""
    return connection.execute(
        f"""
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            sb.name,
            f.ret120,
            s.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN {NET_SHARE_ISSUANCE_TABLE} s
          ON f.trade_date = s.signal_date AND f.symbol = s.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        WHERE f.trade_date IN (SELECT signal_date FROM share_signal_dates)
          AND f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND NOT REGEXP_MATCHES(COALESCE(sb.name, ''), 'ST|退')
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def load_source_diagnostics(connection: Any) -> dict[str, float]:
    """审计公告越界、重复、复权缺失和公司行为歧义。"""
    row = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN publish_date > signal_date
                       OR prior_publish_date > signal_date
                     THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol),
            AVG(CASE WHEN NOT adjustment_available THEN 1.0 ELSE 0.0 END),
            AVG(CASE WHEN corporate_action_ambiguous THEN 1.0 ELSE 0.0 END)
        FROM {NET_SHARE_ISSUANCE_TABLE}
        """
    ).fetchone()
    return {
        "visibility_violations": float(row[0] or 0),
        "duplicate_signal_symbol_rows": float(row[1] or 0),
        "adjustment_missing_share": float(row[2] or 0),
        "corporate_action_ambiguous_share": float(row[3] or 0),
    }


def build_monthly_coverage(candidates: pd.DataFrame) -> pd.DataFrame:
    """统计总候选和真正可区分的缩股候选数量。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        growth = pd.to_numeric(group["net_share_growth"], errors="coerce")
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(growth.notna().sum()),
                "negative_issuer_count": int(growth.lt(-1e-12).sum()),
                "unchanged_issuer_count": int(growth.abs().le(1e-12).sum()),
                "positive_issuer_count": int(growth.gt(1e-12).sum()),
                "unique_factor_values": int(growth.nunique()),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最新一期股本变化分布和零值占比。"""
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["net_share_growth"], errors="coerce")
    return {
        "p01": float(values.quantile(0.01)),
        "median": float(values.median()),
        "p99": float(values.quantile(0.99)),
        "unchanged_share": float(values.abs().le(1e-12).mean()),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行覆盖与低发行端可辨识性门槛。"""
    if monthly.empty:
        raise ValueError("净股本发行覆盖审计没有有效月末数据")
    candidate_share = float(
        monthly["candidate_count"].ge(MIN_CANDIDATES).mean()
    )
    distinguishable_share = float(
        monthly["negative_issuer_count"].ge(MIN_NEGATIVE_ISSUERS).mean()
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_distinguishable_share = float(
        locked["negative_issuer_count"].ge(MIN_NEGATIVE_ISSUERS).mean()
        if not locked.empty
        else 0.0
    )
    checks = {
        "candidate_month_share": candidate_share >= MIN_MONTH_SHARE,
        "distinguishable_month_share": (
            distinguishable_share >= MIN_DISTINGUISHABLE_MONTH_SHARE
        ),
        "locked_distinguishable_month_share": (
            locked_distinguishable_share >= MIN_DISTINGUISHABLE_MONTH_SHARE
        ),
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "adjustment_coverage_at_least_95pct": (
            diagnostics["adjustment_missing_share"] <= 0.05
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "negative_count_min": int(monthly["negative_issuer_count"].min()),
        "negative_count_median": float(
            monthly["negative_issuer_count"].median()
        ),
        "negative_count_latest": int(
            monthly["negative_issuer_count"].iloc[-1]
        ),
        "candidate_month_share": candidate_share,
        "distinguishable_month_share": distinguishable_share,
        "locked_distinguishable_month_share": locked_distinguishable_share,
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
    """归档可辨识性结果，无法稳定选股时不运行收益回测。"""
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
            "净股本发行低端候选可稳定区分，可进入固定回测"
            if passed
            else "缩股候选不足，Top40将退化为零值并列，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "净股本发行可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度可辨识性明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成净股本发行数据与组合可辨识性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 净股本发行数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 总候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 缩股候选最少/中位/最新：{result['negative_count_min']} /
  {result['negative_count_median']:.0f} / {result['negative_count_latest']}。
- 全样本/2022年后可组成无并列Top40的月份：
  {result['distinguishable_month_share']:.2%} /
  {result['locked_distinguishable_month_share']:.2%}。
- 最新变化 P1/中位/P99：{distribution['p01']:.2%} /
  {distribution['median']:.2%} / {distribution['p99']:.2%}；
  零变化占比 {distribution['unchanged_share']:.2%}。
- 复权缺失/公司行为歧义占比：
  {diagnostics['adjustment_missing_share']:.2%} /
  {diagnostics['corporate_action_ambiguous_share']:.2%}。
- 公告越界/重复：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定资产负债表和行情复权数据版本。"""
    parts: list[str] = []
    for label, path in [
        ("balance", paths.balance_sheet_path),
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
