"""标准化意外盈利（SUE）月频数据可行性研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.earnings_surprise import (
    EARNINGS_SURPRISE_ASOF_TABLE,
    EarningsSurprisePaths,
    attach_earnings_surprise_database,
    create_earnings_surprise_signal_date_table,
    materialize_earnings_surprise_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from factors.earnings_surprise import score_earnings_surprise_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "earnings_surprise_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/earnings-surprise-data-feasibility-v1.md"
)
STUDY_START = "20150101"
TOP_N = 20
FOLDS = {
    "2015_2018": ("20150101", "20181231"),
    "2019_2021": ("20190101", "20211231"),
    "2022_latest": ("20220101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标准化意外盈利数据可行性 V1",
    category="data_feasibility",
    hypothesis="季度EPS意外程度能否按公告日形成长期完整的月频A股截面",
    definition={
        "factor_candidate": {
            "name": "standardized_unexpected_earnings",
            "numerator": "basic_eps_t_minus_same_quarter_basic_eps_t_minus_1y",
            "denominator": "std_of_prior_8_eps_yoy_changes_excluding_current",
            "direction": "higher_is_better",
            "current_basic_eps_positive": True,
            "eps_change_positive": True,
        },
        "visibility": {
            "publish_column": "income.f_ann_date",
            "publish_date_lte_signal_date": True,
            "event_age_days_max": 90,
            "current_change_excluded_from_denominator": True,
        },
        "universe": (
            "listed_3y_ex_st_delisted_suspended_bottom20_amount"
        ),
        "frequency": "monthly",
        "top_n_requirement": TOP_N,
        "folds": FOLDS,
        "frozen_gate": {
            "asof_violations": 0,
            "duplicate_signal_symbol": 0,
            "history_observations_must_equal": 8,
            "constructible_month_share": 1.0,
            "median_candidate_count_min": 100,
            "latest_candidate_count_min": 100,
            "each_fold_constructible_share_min": 0.95,
            "classified_years_min": 10,
        },
        "feasibility_only_no_backtest": True,
        "parameters_fixed_before_data_read": True,
        "methodology_version": "sue_asof_feasibility_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请确定性指纹，再读取利润表与全量月末截面。"""
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
        result, monthly = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, monthly)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """构造SUE点时截面并检查月频Top20可构造性。"""
    latest_date, candidates, monthly = load_feasibility_data(
        paths,
        as_of_date,
    )
    diagnostics = build_diagnostics(candidates, monthly)
    gate = evaluate_feasibility(diagnostics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(diagnostics, monthly, gate, latest_date),
        encoding="utf-8",
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "diagnostics": diagnostics,
        "gate": gate,
        "decision": (
            "BACKTEST_ALLOWED" if gate["passed"] else "STOP_BEFORE_BACKTEST"
        ),
        "report_path": str(report_path),
        "reused": False,
    }, monthly


def load_feasibility_data(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """加载统一行情和SUE候选，供不同调仓定义复用。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute(
                "SELECT MAX(trade_date) FROM features"
            ).fetchone()[0]
        )
        signal_dates = [
            date
            for date in load_month_end_signal_dates(connection)
            if STUDY_START <= date <= latest_date
        ]
        create_earnings_surprise_signal_date_table(
            connection,
            signal_dates,
        )
        attach_earnings_surprise_database(
            connection,
            EarningsSurprisePaths(paths.income_statement_path),
        )
        materialize_earnings_surprise_asof(connection)
        candidates = load_earnings_surprise_candidates(connection)
    finally:
        connection.close()
    monthly = build_monthly_coverage(candidates, signal_dates)
    return latest_date, candidates, monthly


def load_earnings_surprise_candidates(connection: Any) -> pd.DataFrame:
    """连接统一行情、历史名称和SUE公告日截面。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM sue_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            s.end_date,
            s.publish_date,
            s.prior_year_end_date,
            s.prior_year_publish_date,
            s.basic_eps,
            s.prior_year_basic_eps,
            s.eps_change,
            s.historical_change_std,
            s.history_observations,
            s.sue,
            s.event_age_days,
            f.ret20,
            f.ret120,
            f.vol60
        FROM features f
        JOIN {EARNINGS_SURPRISE_ASOF_TABLE} s
          ON f.trade_date = s.signal_date AND f.symbol = s.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM sue_signal_dates)
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(
              COALESCE(na.asof_name, sb.name, ''),
              'ST|退'
          )
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
    signal_dates: list[str],
) -> pd.DataFrame:
    """逐月统计有效正SUE候选数量。"""
    counts: dict[str, int] = {}
    for signal_date in signal_dates:
        frame = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        counts[signal_date] = len(score_earnings_surprise_frame(frame))
    return pd.DataFrame(
        {
            "signal_date": list(counts),
            "candidate_count": list(counts.values()),
        }
    ).assign(
        constructible=lambda frame: frame["candidate_count"].ge(TOP_N)
    )


def build_diagnostics(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
) -> dict[str, Any]:
    """汇总点时完整性、重复键和跨阶段覆盖。"""
    signal = candidates["signal_date"].astype(str)
    publish = candidates["publish_date"].astype(str)
    years = signal.str[:4].nunique() if not candidates.empty else 0
    fold_coverage: dict[str, float] = {}
    for name, (start, raw_end) in FOLDS.items():
        end = (
            str(monthly["signal_date"].max())
            if raw_end == "LATEST" and not monthly.empty
            else raw_end
        )
        rows = monthly[monthly["signal_date"].between(start, end)]
        fold_coverage[name] = (
            float(rows["constructible"].mean()) if not rows.empty else 0.0
        )
    counts = monthly["candidate_count"].astype(float)
    return {
        "signal_months": len(monthly),
        "raw_candidate_rows": len(candidates),
        "asof_violations": int((publish > signal).sum()),
        "event_age_violations": int(
            (
                ~pd.to_numeric(
                    candidates["event_age_days"],
                    errors="coerce",
                ).between(0, 90)
            ).sum()
        ),
        "history_observation_violations": int(
            pd.to_numeric(
                candidates["history_observations"],
                errors="coerce",
            ).ne(8).sum()
        ),
        "duplicate_signal_symbol": int(
            candidates.duplicated(["signal_date", "symbol"]).sum()
        ),
        "constructible_month_share": float(
            monthly["constructible"].mean()
        ),
        "candidate_count_min": float(counts.min()),
        "candidate_count_median": float(counts.median()),
        "candidate_count_latest": float(counts.iloc[-1]),
        "classified_years": int(years),
        "fold_constructible_share": fold_coverage,
    }


def evaluate_feasibility(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """按数据读取前冻结的门槛判断是否允许回测。"""
    checks = {
        "no_asof_violations": diagnostics["asof_violations"] == 0,
        "no_event_age_violations": (
            diagnostics["event_age_violations"] == 0
        ),
        "no_history_observation_violations": (
            diagnostics["history_observation_violations"] == 0
        ),
        "no_duplicate_signal_symbol": (
            diagnostics["duplicate_signal_symbol"] == 0
        ),
        "all_months_constructible": math_is_close(
            diagnostics["constructible_month_share"],
            1.0,
        ),
        "median_candidates_at_least_100": (
            diagnostics["candidate_count_median"] >= 100
        ),
        "latest_candidates_at_least_100": (
            diagnostics["candidate_count_latest"] >= 100
        ),
        "each_fold_constructible_at_least_95pct": all(
            value >= 0.95
            for value in diagnostics["fold_constructible_share"].values()
        ),
        "at_least_10_years": diagnostics["classified_years"] >= 10,
    }
    return {"passed": all(checks.values()), "checks": checks}


def render_report(
    diagnostics: dict[str, Any],
    monthly: pd.DataFrame,
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """生成SUE数据可行性报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    folds = "\n".join(
        f"- {name}：{value:.2%}"
        for name, value in diagnostics[
            "fold_constructible_share"
        ].items()
    )
    return f"""# 标准化意外盈利数据可行性 V1

- 数据截止：{latest_date}。
- 月度信号数：{diagnostics['signal_months']}。
- 点时候选记录：{diagnostics['raw_candidate_rows']}。
- 候选数最少/中位/最新：
  {diagnostics['candidate_count_min']:.0f} /
  {diagnostics['candidate_count_median']:.0f} /
  {diagnostics['candidate_count_latest']:.0f}。
- Top20可构造月份：{diagnostics['constructible_month_share']:.2%}。
- 公告日违规：{diagnostics['asof_violations']}；
  重复键：{diagnostics['duplicate_signal_symbol']}。
- 覆盖年份：{diagnostics['classified_years']}。

## 分阶段Top20可构造率

{folds}

## 固定门槛

{checks}

结论：{'允许进入固定定义回测' if gate['passed'] else '数据覆盖不足，停止于回测前'}。
"""


def math_is_close(value: float, target: float) -> bool:
    """避免浮点均值在100%附近产生误判。"""
    return abs(float(value) - float(target)) <= 1e-12


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    monthly: pd.DataFrame,
) -> None:
    """归档可行性成功或失败，禁止遗漏失败尝试。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "SUE公告日覆盖稳定，可进入固定定义回测"
            if passed
            else "SUE月频覆盖不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "可行性报告"),
            ExperimentArtifact(
                "monthly_coverage",
                monthly_path,
                "月度候选覆盖",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定利润表和统一行情版本。"""
    files = [
        ("income", paths.income_statement_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]
    return "|".join(
        f"{name}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for name, path in files
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
