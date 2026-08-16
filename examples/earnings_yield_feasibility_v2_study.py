"""标准可投股票池内盈利收益率公司行为门禁修正版。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.quality_financial import (
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    MATERIAL_ADJ_FACTOR_CHANGE,
    attach_report_adjustment_factors,
)
from examples.earnings_yield_feasibility_study import (
    MAX_ADJUSTMENT_MISSING_SHARE,
    MAX_STYLE_CORRELATION,
    MIN_CANDIDATES,
    MIN_QUALIFIED_MONTH_SHARE,
    MIN_TOP40_MEDIAN_ADV_RMB,
    MIN_TOP40_TRADABLE_SHARE,
    MIN_UNIQUE_VALUES,
    STUDY_START,
    TOP_N,
    _data_version,
    _financial_paths,
    build_monthly_coverage,
    evaluate_feasibility,
    score_monthly_candidates,
)
from examples.earnings_yield_feasibility_v2_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import load_annual_quality_candidates


EXPERIMENT_ID = "earnings_yield_investable_adjustment_feasibility_v2"
REPORT_PATH = Path(
    "docs/research/earnings-yield-investable-adjustment-feasibility-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="点时盈利收益率数据可行性 V2",
    category="data_feasibility",
    hypothesis="标准可投股票池内的盈利收益率数据能否通过冻结公司行为门禁",
    definition={
        "factor": {
            "formula": "latest_visible_annual_eps/raw_close_on_signal_date",
            "direction": "higher_is_better",
            "eligibility": "eps_positive",
            "price_policy": "raw_close_for_valuation_qfq_reserved_for_execution",
        },
        "visibility": {
            "annual_1231_only": True,
            "publish_date": "max_income_balance_cashflow_f_ann_date",
            "publish_date_lte_signal_date": True,
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "corporate_action_gate": {
            "denominator": "otherwise_eligible_standard_investable_rows",
            "report_to_signal_adj_factor_change_max": MATERIAL_ADJ_FACTOR_CHANGE,
            "missing_adjustment_rejected": True,
        },
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "maximum_style_rank_correlation": MAX_STYLE_CORRELATION,
            "adjustment_missing_share_max": MAX_ADJUSTMENT_MISSING_SHARE,
            "duplicate_visibility_invalid_violations": 0,
        },
        "methodology_correction": (
            "V1在全量财务源记录计算复权缺失率；V2仅修正为标准可投候选分母"
        ),
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v2_investable_denominator",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在扫描数据前登记 V2 确定性研究指纹。"""
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
    """构造点时截面，先限定可投范围，再执行公司行为门禁。"""
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
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        source = load_annual_quality_candidates(connection)
        source = attach_report_adjustment_factors(connection, source)
    finally:
        connection.close()

    candidates, diagnostics = build_investable_candidates(source)
    scored = score_monthly_candidates(candidates)
    monthly = build_monthly_coverage(scored, signal_dates)
    result = evaluate_feasibility(scored, monthly, diagnostics, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_investable_candidates(
    source: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """仅对其余门槛均合格的候选统计复权因子缺失率。"""
    data = source.copy()
    signal = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    listed = pd.to_datetime(data["list_date"], format="%Y%m%d", errors="coerce")
    delisted = pd.to_datetime(
        data["delist_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    report_year = pd.to_numeric(
        data["end_date"].astype(str).str[:4],
        errors="coerce",
    )
    for column in [
        "eps",
        "raw_close",
        "current_adj_factor",
        "report_adj_factor",
        "roa",
        "vol60",
        "ret120",
        "amount20",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    # 公司行为数据不是股票池资格；先固定其余可投条件，避免错误扩大分母。
    otherwise_eligible = (
        (signal - listed).dt.days.ge(1095)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~(delisted.notna() & delisted.le(signal))
        & data["end_date"].astype(str).str.endswith("1231")
        & data["f_ann_date"].astype(str).le(data["signal_date"].astype(str))
        & (signal.dt.year - report_year).between(1, 2)
        & data["eps"].gt(0)
        & data["raw_close"].gt(0)
    )
    base = data[otherwise_eligible].copy()
    adjustment_available = base[
        ["current_adj_factor", "report_adj_factor"]
    ].notna().all(axis=1)
    adjustment_change = (
        base["current_adj_factor"] / base["report_adj_factor"] - 1.0
    ).abs()
    material_action = (
        adjustment_available
        & adjustment_change.gt(MATERIAL_ADJ_FACTOR_CHANGE)
    )
    accepted = base[adjustment_available & ~material_action].copy()
    accepted["earnings_yield"] = accepted["eps"] / accepted["raw_close"]
    accepted["adv_rmb"] = accepted["amount20"] * 1000.0
    diagnostics = {
        "eligible_source_rows": float(len(base)),
        "adjustment_missing_share": (
            float((~adjustment_available).mean()) if len(base) else 1.0
        ),
        "material_action_share": (
            float(material_action.mean()) if len(base) else 0.0
        ),
        "visibility_violations": float(
            (
                accepted["f_ann_date"].astype(str)
                > accepted["signal_date"].astype(str)
            ).sum()
        ),
        "duplicate_rows": float(
            accepted.duplicated(["signal_date", "symbol"]).sum()
        ),
        "invalid_rows": float(
            (
                ~np.isfinite(
                    pd.to_numeric(accepted["earnings_yield"], errors="coerce")
                )
            ).sum()
        ),
    }
    return accepted, diagnostics


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档 V2 门禁明细，门禁失败同样保留。"""
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
            "标准可投股票池内 E/P 公司行为门禁通过，可执行一次固定回测"
            if result["passed"]
            else "修正分母后 E/P 数据、排重或公司行为门禁仍未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "V2 数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
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
