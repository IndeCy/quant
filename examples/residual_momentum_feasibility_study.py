"""走步双因子残差动量的数据可行性与重复性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.benchmark_series import load_adjusted_fund_curve
from data.intermediate_momentum import materialize_intermediate_momentum
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.residual_momentum import (
    RESIDUAL_MOMENTUM_TABLE,
    build_style_factor_frame,
    materialize_residual_momentum,
)
from examples.residual_momentum_feasibility_report import render_report
from examples.residual_momentum_feasibility_support import (
    MAX_INTERMEDIATE_MOMENTUM_CORRELATION,
    MAX_VOLATILITY_CORRELATION,
    MIN_CANDIDATES,
    MIN_QUALIFIED_MONTH_SHARE,
    MIN_TOP40_MEDIAN_ADV_RMB,
    MIN_TOP40_TRADABLE_SHARE,
    MIN_UNIQUE_VALUES,
    TOP_N,
    build_monthly_coverage,
    evaluate_feasibility,
)
from factors.residual_momentum import score_residual_momentum
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "residual_momentum_two_factor_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/residual-momentum-two-factor-data-feasibility-v1.md"
)
SOURCE_START = "20130101"
STUDY_START = "20150101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="走步双因子残差动量数据可行性 V1",
    category="data_feasibility",
    hypothesis="剔除市场与中盘暴露后的个股自身趋势能否形成独立可交易截面",
    definition={
        "factor": {
            "beta_estimation_window": "signal_lag_252_to_121",
            "residual_evaluation_window": "signal_lag_120_to_20",
            "market_factor": "510300_qfq_daily_return",
            "size_factor": "510500_qfq_return_minus_510300_qfq_return",
            "formula": (
                "sum(stock_return-market_beta*market_return"
                "-size_beta*size_return)"
            ),
            "direction": "higher_is_better",
        },
        "universe": (
            "listed_3y_ex_st_delisted_suspended_bottom20_amount"
        ),
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "maximum_intermediate_momentum_rank_correlation": (
                MAX_INTERMEDIATE_MOMENTUM_CORRELATION
            ),
            "maximum_vol60_rank_correlation": (
                MAX_VOLATILITY_CORRELATION
            ),
            "duplicate_visibility_identity_invalid_violations": 0,
        },
        "decision": "feasibility_only_no_future_return_backtest",
        "methodology_version": "split_estimation_evaluation_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在扫描行情前登记完整研究与数据指纹。"""
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
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造严格历史窗口并执行冻结数据门禁。"""
    hs300 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=as_of_date,
    )
    csi500 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=as_of_date,
    )
    style_factors = build_style_factor_frame(hs300, csi500)
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=SOURCE_START,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(
            connection,
            lookback_start=SOURCE_START,
        )
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
        materialize_intermediate_momentum(
            connection,
            source_start=SOURCE_START,
            research_start=STUDY_START,
        )
        materialize_residual_momentum(
            connection,
            style_factors,
            signal_dates,
            source_start=SOURCE_START,
        )
        source = load_investable_source(connection, signal_dates)
    finally:
        connection.close()
    candidates = score_residual_momentum(source)
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
    """连接标准可投池、普通动量和残差动量截面。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE rm_candidate_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO rm_candidate_dates VALUES (?)",
        [(str(value),) for value in signal_dates],
    )
    return connection.execute(
        f"""
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date
            FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date
            FROM stock_name_manual
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
            JOIN name_history h
              ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date FROM rm_candidate_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            r.* EXCLUDE(signal_date, symbol),
            m.intermediate_momentum,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS adv_rmb
        FROM features f
        JOIN {RESIDUAL_MOMENTUM_TABLE} r
          ON f.trade_date = r.signal_date AND f.symbol = r.symbol
        JOIN intermediate_momentum_features m
          ON f.trade_date = m.trade_date AND f.symbol = m.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
            SELECT signal_date FROM rm_candidate_dates
        )
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
          AND (
              sb.delist_date IS NULL
              OR sb.delist_date > f.trade_date
          )
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、ETF和增量文件，源修订后生成新运行。"""
    versions: list[str] = []
    for path in [
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
    ]:
        stat = path.stat()
        versions.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(versions)


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存数据门禁报告和月度覆盖，不保存未来收益。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    pd.DataFrame(result["monthly_records"]).to_csv(
        monthly_path,
        index=False,
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "PASSED_FEASIBILITY"
            if result["passed"]
            else "REJECTED"
        ),
        decision_reason=(
            "残差动量数据门禁通过，可执行一次固定多折回测"
            if result["passed"]
            else "残差动量覆盖、区分度或点时门禁未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact(
                "monthly_coverage",
                monthly_path,
                "月度覆盖与区分度",
            ),
        ],
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
