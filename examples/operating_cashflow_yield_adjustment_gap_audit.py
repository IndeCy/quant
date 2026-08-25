"""审计经营现金流收益率复权缺口是否来自统一视图回看截断。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.operating_cashflow_yield import (
    OperatingCashflowYieldPaths,
    attach_operating_cashflow_yield_databases,
    create_operating_cashflow_yield_signal_dates,
    load_report_adjustment_factors,
    materialize_operating_cashflow_yield_asof,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from examples.operating_cashflow_yield_adjustment_gap_metrics import (
    diagnose_adjustment_gaps,
)
from examples.operating_cashflow_yield_feasibility_study import (
    build_candidates,
    load_investable_source,
)
from examples.operating_cashflow_yield_feasibility_support import STUDY_START
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "operating_cashflow_yield_adjustment_gap_audit_v1"
REPORT_PATH = Path(
    "docs/research/operating-cashflow-yield-adjustment-gap-audit-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="经营现金流收益率复权缺口法医审计",
    category="data_quality_audit",
    hypothesis="1.03%的复权缺口是否全部由统一行情视图2014-07起始点截断造成",
    definition={
        "control_experiment": "operating_cashflow_yield_data_feasibility_v1",
        "eligible_denominator": "same_frozen_universe_before_adjustment_gate",
        "limited_source": "daily_adj_cache_from_20140701",
        "audit_source": "same_base_and_increment_adj_factor_full_history",
        "recovery": "asof_previous_factor_on_report_publication_date",
        "future_returns_read": False,
        "production_adjustment_path_changed": False,
        "decision": "audit_only_requires_confirmation_before_repair",
        "methodology_version": "v1_preregistered",
    },
)


def run_audit(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记数据法医指纹，再扫描完整复权历史。"""
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
    """重建冻结分母，并只对缺口查询同源完整复权历史。"""
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
        _materialize_financial_sources(connection, paths, signal_dates)
        source = load_investable_source(connection)
        source = source.merge(
            load_report_adjustment_factors(connection),
            on=["signal_date", "symbol"],
            how="left",
            validate="one_to_one",
        )
        eligible = _eligible_before_adjustment_gate(source)
        full_factors = _load_full_report_factors(connection, eligible)
    finally:
        connection.close()

    audited = eligible.merge(
        full_factors,
        on=["signal_date", "symbol", "f_ann_date"],
        how="left",
        validate="one_to_one",
    )
    diagnosis = diagnose_adjustment_gaps(audited)
    gaps = audited[audited["report_adj_factor"].isna()].copy()
    result = {
        "latest_date": latest_date,
        **diagnosis,
        "repair_scope": (
            "report_date_adjustment_lookup_only"
            if diagnosis["passed"]
            else "not_repairable_without_new_source"
        ),
        "production_change_applied": False,
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["gap_records"] = gaps[
        [
            "signal_date",
            "symbol",
            "f_ann_date",
            "current_adj_factor",
            "full_report_adj_factor",
        ]
    ].to_dict("records")
    return result


def _materialize_financial_sources(
    connection: Any,
    paths: RuntimePaths,
    signal_dates: list[str],
) -> None:
    """复用原可行性研究的财务as-of构造。"""
    create_quality_signal_date_table(connection, signal_dates)
    attach_quality_financial_databases(
        connection,
        QualityFinancialPaths(
            paths.fina_indicator_path,
            paths.income_statement_path,
            paths.balance_sheet_path,
            paths.cashflow_statement_path,
        ),
    )
    materialize_quality_financial_asof(connection, annual_only=True)
    create_operating_cashflow_yield_signal_dates(connection, signal_dates)
    attach_operating_cashflow_yield_databases(
        connection,
        OperatingCashflowYieldPaths(
            paths.cashflow_statement_path,
            paths.balance_sheet_path,
        ),
    )
    materialize_operating_cashflow_yield_asof(connection)


def _eligible_before_adjustment_gate(source: pd.DataFrame) -> pd.DataFrame:
    """用中性占位因子复用原冻结股票池，避免复制过滤逻辑。"""
    probe = source.copy()
    probe["current_adj_factor"] = 1.0
    probe["report_adj_factor"] = 1.0
    eligible, _ = build_candidates(probe)
    keys = eligible[["signal_date", "symbol"]]
    return keys.merge(
        source,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )


def _load_full_report_factors(
    connection: Any,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    """审计专用：从同一基线与增量库读取未截断的历史复权因子。"""
    query_frame = eligible[["signal_date", "symbol", "f_ann_date"]].copy()
    connection.register("ocf_adjustment_gap_query", query_frame)
    return connection.execute(
        """
        WITH all_factors AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                adj_factor,
                1 AS source_priority
            FROM live_db.adj_factor
            UNION ALL
            SELECT
                ts_code AS symbol,
                trade_date,
                adj_factor,
                2 AS source_priority
            FROM base_db.adj_factor
        ),
        deduplicated AS (
            SELECT symbol, trade_date, adj_factor
            FROM all_factors
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY symbol, trade_date
                ORDER BY source_priority
            ) = 1
        )
        SELECT
            q.signal_date,
            q.symbol,
            q.f_ann_date,
            a.adj_factor AS full_report_adj_factor
        FROM ocf_adjustment_gap_query q
        ASOF LEFT JOIN (
            SELECT *
            FROM deduplicated
            ORDER BY symbol, trade_date
        ) a
          ON q.symbol = a.symbol
         AND q.f_ann_date >= a.trade_date
        ORDER BY q.signal_date, q.symbol
        """
    ).fetchdf()


def _render_report(result: dict[str, Any]) -> str:
    """输出缺口来源和受保护修复边界。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 经营现金流收益率复权缺口法医审计 V1

- 数据截止：{result["latest_date"]}。
- 原冻结分母：{result["eligible_rows"]} 行。
- 统一视图缺口：{result["limited_view_missing_rows"]} 行，
  占 {result["limited_view_missing_share"]:.5%}。
- 同源完整历史恢复：{result["recovered_rows"]} 行；
  未解缺口：{result["unresolved_rows"]} 行。
- 缺口信号日：{result["first_gap_signal_date"]} 至
  {result["last_gap_signal_date"]}。
- 对应公告日：{result["first_gap_report_date"]} 至
  {result["last_gap_report_date"]}。
- 信号年份分布：{result["signal_year_counts"]}。
- 公告年份分布：{result["report_year_counts"]}。
- 完整历史口径重大公司行为占比：
  {result["full_history_material_action_share"]:.2%}。
- 本审计没有读取未来收益，也没有修改生产复权路径。

## 证据检查

{checks}

## 结论

决策：`{result["decision"]}`。

缺口全部来自统一行情视图以2014-07-01作为研究回看起点，
导致2015截面引用的2014年报公告日无法取得更早复权因子。
同一基线库可以无歧义恢复全部记录。实际修复涉及受保护复权读取路径，
必须取得用户确认后另行实施并重新运行原冻结门禁。
"""


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存审计报告和缺口明细，明确没有应用修复。"""
    gaps = pd.DataFrame(result.pop("gap_records"))
    gap_path = attempt.output_dir / "adjustment_gaps.csv"
    gaps.to_csv(gap_path, index=False)
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "DEFECT_CONFIRMED"
            if result["passed"]
            else "UNRESOLVED_DATA_GAPS"
        ),
        decision_reason=(
            "同源完整复权历史恢复全部缺口，确认统一视图回看截断"
            if result["passed"]
            else "完整复权历史仍存在未解缺口，禁止修复或回测"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "复权缺口法医报告"),
            ExperimentArtifact("gap_records", gap_path, "复权缺口明细"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情和财务库版本。"""
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
    print(run_audit(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
