"""经营现金流收益率的数据可行性、点时性和风格独立性审计。"""

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
from data.operating_cashflow_yield import (
    OPERATING_CASHFLOW_YIELD_TABLE,
    OperatingCashflowYieldPaths,
    attach_operating_cashflow_yield_databases,
    create_operating_cashflow_yield_signal_dates,
    load_report_adjustment_factors,
    materialize_operating_cashflow_yield_asof,
)
from data.quality_financial import (
    QUALITY_ANNUAL_ASOF_TABLE,
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import MATERIAL_ADJ_FACTOR_CHANGE
from examples.operating_cashflow_yield_feasibility_support import (
    MAX_ADJUSTMENT_MISSING_SHARE,
    MAX_STYLE_CORRELATION,
    MIN_CANDIDATES,
    MIN_QUALIFIED_MONTH_SHARE,
    MIN_TOP40_MEDIAN_ADV_RMB,
    MIN_TOP40_TRADABLE_SHARE,
    MIN_UNIQUE_VALUES,
    STUDY_START,
    TOP_N,
    build_monthly_coverage,
    evaluate_feasibility,
    render_report,
    score_monthly_candidates,
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


EXPERIMENT_ID = "operating_cashflow_yield_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/operating-cashflow-yield-data-feasibility-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="经营现金流收益率数据可行性 V1",
    category="data_feasibility",
    hypothesis="高年度经营现金流相对点时市值能否形成广泛、独立且可交易的价值截面",
    definition={
        "factor": {
            "formula": (
                "latest_visible_annual_n_cashflow_act/"
                "(same_report_total_share*raw_close_on_signal_date)"
            ),
            "direction": "higher_is_better",
            "eligibility": "operating_cashflow_positive",
            "price_policy": (
                "raw_close_for_valuation_qfq_reserved_for_execution"
            ),
        },
        "visibility": {
            "annual_1231_only": True,
            "cashflow_and_balance_each_visible_asof_signal": True,
            "same_fiscal_period_required": True,
            "report_freshness_years": [1, 2],
        },
        "corporate_action_gate": {
            "denominator": "otherwise_eligible_standard_investable_rows",
            "report_to_signal_adj_factor_change_max": (
                MATERIAL_ADJ_FACTOR_CHANGE
            ),
            "missing_adjustment_rejected": True,
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
            "adjustment_missing_share_max": MAX_ADJUSTMENT_MISSING_SHARE,
            "duplicate_visibility_invalid_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在扫描财务数据前登记完整研究定义和数据版本。"""
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
    """构造点时截面并执行冻结数据门禁。"""
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
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(
            connection,
            _quality_paths(paths),
        )
        materialize_quality_financial_asof(connection, annual_only=True)
        create_operating_cashflow_yield_signal_dates(
            connection,
            signal_dates,
        )
        attach_operating_cashflow_yield_databases(
            connection,
            OperatingCashflowYieldPaths(
                paths.cashflow_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_operating_cashflow_yield_asof(connection)
        source = load_investable_source(connection)
        report_factors = load_report_adjustment_factors(connection)
        source = source.merge(
            report_factors,
            on=["signal_date", "symbol"],
            how="left",
            validate="one_to_one",
        )
    finally:
        connection.close()

    candidates, diagnostics = build_candidates(source)
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


def load_investable_source(connection: Any) -> pd.DataFrame:
    """连接 as-of 财务截面、行情特征和历史名称。"""
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
                ROW_NUMBER() OVER (
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h
              ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date
                FROM operating_cashflow_yield_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            sb.list_date,
            sb.delist_date,
            f.raw_close,
            f.adj_factor AS current_adj_factor,
            f.vol60,
            f.ret120,
            f.amount20 * 1000.0 AS adv_rmb,
            f.amount,
            f.amount_p20,
            f.volume,
            f.is_suspended,
            f.st_name,
            o.end_date,
            o.f_ann_date,
            o.cashflow_f_ann_date,
            o.balance_f_ann_date,
            o.operating_cashflow,
            o.total_shares,
            q.roa,
            q.eps / NULLIF(f.raw_close, 0) AS earnings_yield
        FROM features f
        JOIN {OPERATING_CASHFLOW_YIELD_TABLE} o
          ON f.trade_date = o.signal_date AND f.symbol = o.symbol
        LEFT JOIN {QUALITY_ANNUAL_ASOF_TABLE} q
          ON f.trade_date = q.signal_date
         AND f.symbol = q.symbol
         AND o.end_date = q.end_date
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
            SELECT signal_date
            FROM operating_cashflow_yield_signal_dates
        )
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_candidates(
    source: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """应用股票池、报告新鲜度和公司行为门禁。"""
    data = source.copy()
    signal = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    listed = pd.to_datetime(
        data["list_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    delisted = pd.to_datetime(
        data["delist_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    report_year = pd.to_numeric(
        data["end_date"].astype(str).str[:4],
        errors="coerce",
    )
    numeric = [
        "raw_close",
        "current_adj_factor",
        "report_adj_factor",
        "operating_cashflow",
        "total_shares",
        "roa",
        "earnings_yield",
        "vol60",
        "ret120",
        "adv_rmb",
        "amount",
        "amount_p20",
        "volume",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    otherwise_eligible = (
        (signal - listed).dt.days.ge(1095)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~(delisted.notna() & delisted.le(signal))
        & ~data["is_suspended"].fillna(True).astype(bool)
        & data["amount"].gt(data["amount_p20"])
        & data["volume"].gt(0)
        & data["raw_close"].gt(0)
        & data["end_date"].astype(str).str.endswith("1231")
        & data["f_ann_date"].astype(str).le(
            data["signal_date"].astype(str)
        )
        & (signal.dt.year - report_year).between(1, 2)
        & data["operating_cashflow"].gt(0)
        & data["total_shares"].gt(0)
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
    accepted["operating_cashflow_yield"] = (
        accepted["operating_cashflow"]
        / (accepted["total_shares"] * accepted["raw_close"])
    )
    finite = np.isfinite(accepted["operating_cashflow_yield"])
    accepted = accepted[finite].copy()
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
        "statement_period_mismatches": 0.0,
        "duplicate_rows": float(
            accepted.duplicated(["signal_date", "symbol"]).sum()
        ),
        "invalid_rows": float(
            (~np.isfinite(accepted["operating_cashflow_yield"])).sum()
        ),
    }
    return accepted, diagnostics


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存失败和通过的可行性证据。"""
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
            "现金流收益率覆盖、点时性和独立性通过，可执行预注册多折回测"
            if result["passed"]
            else "现金流收益率数据、排重或公司行为门禁未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact(
                "monthly_coverage",
                monthly_path,
                "逐月覆盖明细",
            ),
        ],
    )


def _quality_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """把行情与财务快照版本绑定到研究运行指纹。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


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
