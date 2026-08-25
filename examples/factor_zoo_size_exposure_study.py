"""用预先冻结的代表策略验证因子动物园持仓市值暴露。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.block_trades import (
    attach_block_trade_database,
    create_block_trade_signal_date_table,
    materialize_block_trade_premium_asof,
)
from data.fund_ownership import (
    attach_fund_ownership_database,
    create_fund_ownership_signal_date_table,
    materialize_fund_ownership_breadth_asof,
)
from data.holder_trades import (
    attach_holder_trade_database,
    create_holder_trade_signal_date_table,
    materialize_holder_trade_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.profitability_history import (
    ProfitabilityHistoryPaths,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    materialize_profitability_floor_asof,
)
from examples.block_trade_premium_study import (
    LOOKBACK_DAYS as BLOCK_LOOKBACK,
    build_block_trade_targets,
    load_block_trade_candidates,
)
from examples.factor_zoo_size_exposure_metrics import (
    compare_style_groups,
    evaluate_size_exposure_gate,
    summarize_size_exposure,
)
from examples.factor_zoo_size_exposure_report import render_report
from examples.fund_ownership_breadth_study import (
    build_targets as build_fund_targets,
    load_candidates as load_fund_candidates,
)
from examples.insider_net_buying_study import (
    LOOKBACK_DAYS as HOLDER_LOOKBACK,
    build_holder_trade_targets,
    load_holder_trade_candidates,
)
from examples.profitability_floor_study import (
    build_profitability_targets,
    load_profitability_candidates,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
    research_fingerprint,
)


EXPERIMENT_ID = "factor_zoo_holdings_size_attribution_v1"
SOURCE_EXPERIMENT_ID = "factor_zoo_common_mode_attribution_v1"
REPORT_PATH = Path("docs/research/factor-zoo-holdings-size-attribution-v1.md")
STUDY_START = "20150101"
STYLE_GROUPS = {
    "insider_net_buying_v1": "HIGH_MIDCAP_CORRELATION",
    "block_trade_premium_v1": "HIGH_MIDCAP_CORRELATION",
    "fund_ownership_breadth_v1": "LOW_MIDCAP_CORRELATION",
    "profitability_floor_5y_v1": "LOW_MIDCAP_CORRELATION",
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="因子动物园持仓级市值归因 V1",
    category="research_governance",
    hypothesis="年度中盘共同模式能否由预先冻结代表策略的实际持仓市值分布确认",
    definition={
        "source_experiment": SOURCE_EXPERIMENT_ID,
        "representatives_fixed_before_holdings_rebuild": STYLE_GROUPS,
        "market_cap_proxy": {
            "formula": "signal_date_raw_close_times_latest_visible_total_share",
            "total_share_visibility": "balance_f_ann_date_lte_signal_date",
            "percentile_universe": (
                "listed_3y_ex_st_delisted_suspended_bottom20_amount"
            ),
            "percentile_direction": "zero_smallest_one_largest",
        },
        "frozen_gate": {
            "coverage_min": 0.90,
            "low_minus_high_size_percentile_min": 0.10,
            "high_minus_low_bottom_half_share_min": 0.10,
            "style_corr_vs_size_spearman_max": -0.50,
        },
        "no_backtest_or_strategy_change": True,
        "methodology_version": "representative_holdings_asof_size_name_filter_v1_1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """绑定源归因、策略数据和财务库版本后执行持仓审计。"""
    source = _load_source_result(paths)
    data_version = research_fingerprint(
        {
            "source_run": source["run_fingerprint"],
            "source_files": _source_file_versions(paths),
        }
    )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=data_version,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date, source)
        _complete_attempt(attempt, result)
        return result
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    """重建代表策略原始持仓并连接同日可见市值。"""
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
        holdings = _rebuild_representative_holdings(
            connection,
            paths,
            signal_dates,
        )
        size_universe = _build_size_universe(
            connection,
            sorted(holdings["signal_date"].astype(str).unique()),
        )
    finally:
        connection.close()
    enriched = holdings.merge(
        size_universe,
        on=["signal_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    style_correlations = {
        item["experiment_id"]: float(item["correlation"])
        for item in source["metrics"]["style_attribution"][
            "strategy_correlations"
        ]
        if item["experiment_id"] in STYLE_GROUPS
    }
    if set(style_correlations) != set(STYLE_GROUPS):
        raise ValueError("源共同模式研究缺少冻结代表策略相关性")
    exposures = summarize_size_exposure(
        enriched,
        style_correlations,
        STYLE_GROUPS,
    )
    comparison = compare_style_groups(exposures)
    gate = evaluate_size_exposure_gate(comparison)
    result = {
        "as_of_date": str(as_of_date),
        "latest_date": latest_date,
        "source_run_id": source["run_id"],
        "strategy_exposures": exposures,
        "group_comparison": comparison,
        "gate": gate,
        "decision": (
            "REPRESENTATIVE_HOLDINGS_SUPPORT_MIDCAP_EXPOSURE"
            if gate["passed"]
            else "ANNUAL_STYLE_SIGNAL_NOT_CONFIRMED_BY_HOLDINGS"
        ),
        "explanation": (
            "高年度中盘相关代表策略实际持仓显著更偏中小市值，收益风格归因获得持仓级支持。"
            if gate["passed"]
            else "代表策略实际持仓未满足全部预注册市值差异门槛，年度收益归因不能升级为持仓级结论。"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["_enriched_holdings"] = enriched
    return result


def _rebuild_representative_holdings(
    connection: Any,
    paths: RuntimePaths,
    signal_dates: list[str],
) -> pd.DataFrame:
    """复用四个原研究的候选门面和选股函数，不执行回测。"""
    frames: list[pd.DataFrame] = []

    create_holder_trade_signal_date_table(connection, signal_dates)
    attach_holder_trade_database(connection, paths.holder_trade_path)
    materialize_holder_trade_asof(
        connection,
        lookback_days=HOLDER_LOOKBACK,
    )
    holder_candidates = load_holder_trade_candidates(connection)
    _, holder_holdings, _ = build_holder_trade_targets(
        holder_candidates,
        signal_dates,
    )
    frames.append(_tag_holdings(holder_holdings, "insider_net_buying_v1"))

    create_block_trade_signal_date_table(connection, signal_dates)
    attach_block_trade_database(connection, paths.block_trade_path)
    materialize_block_trade_premium_asof(
        connection,
        lookback_days=BLOCK_LOOKBACK,
    )
    block_candidates = load_block_trade_candidates(connection)
    _, block_holdings, _ = build_block_trade_targets(
        block_candidates,
        signal_dates,
    )
    frames.append(_tag_holdings(block_holdings, "block_trade_premium_v1"))

    create_fund_ownership_signal_date_table(connection, signal_dates)
    attach_fund_ownership_database(connection, paths.fund_ownership_path)
    materialize_fund_ownership_breadth_asof(connection)
    fund_candidates = load_fund_candidates(connection)
    _, fund_holdings, _ = build_fund_targets(fund_candidates)
    frames.append(
        _tag_holdings(fund_holdings, "fund_ownership_breadth_v1")
    )

    create_profitability_signal_date_table(connection, signal_dates)
    attach_profitability_history_databases(
        connection,
        ProfitabilityHistoryPaths(
            indicator=paths.fina_indicator_path,
            income=paths.income_statement_path,
            balance=paths.balance_sheet_path,
            cashflow=paths.cashflow_statement_path,
        ),
    )
    materialize_profitability_floor_asof(connection)
    profitability_candidates = load_profitability_candidates(connection)
    _, profitability_holdings, _ = build_profitability_targets(
        profitability_candidates
    )
    frames.append(
        _tag_holdings(
            profitability_holdings,
            "profitability_floor_5y_v1",
        )
    )
    return pd.concat(frames, ignore_index=True)


def _tag_holdings(frame: pd.DataFrame, strategy_id: str) -> pd.DataFrame:
    """只保留市值归因需要的原始持仓身份。"""
    if frame.empty:
        raise ValueError(f"冻结代表策略没有历史持仓: {strategy_id}")
    tagged = frame[["signal_date", "symbol"]].copy()
    tagged["signal_date"] = tagged["signal_date"].astype(str)
    tagged["symbol"] = tagged["symbol"].astype(str)
    tagged["strategy_id"] = strategy_id
    return tagged.drop_duplicates(
        ["strategy_id", "signal_date", "symbol"]
    )


def _build_size_universe(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """按财报公告日可见总股本构造同日可投池市值分位。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE size_signal_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO size_signal_dates VALUES (?)",
        [(date,) for date in signal_dates],
    )
    return connection.execute(
        """
        WITH share_ranked AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                CAST(b.total_share AS DOUBLE) AS total_share,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code
                    ORDER BY b.end_date DESC, b.f_ann_date DESC,
                             b.update_flag DESC
                ) AS rn
            FROM size_signal_dates d
            JOIN profit_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE b.f_ann_date IS NOT NULL
              AND b.total_share > 0
        ),
        name_history AS (
            SELECT ts_code, name, start_date, end_date
            FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date
            FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                d.signal_date,
                h.ts_code AS symbol,
                h.name,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, h.ts_code
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM size_signal_dates d
            JOIN name_history h
              ON h.start_date <= d.signal_date
             AND (h.end_date IS NULL OR h.end_date >= d.signal_date)
        ),
        investable AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                f.raw_close * s.total_share AS market_cap_proxy
            FROM features f
            JOIN share_ranked s
              ON f.trade_date = s.signal_date
             AND f.symbol = s.symbol
             AND s.rn = 1
            JOIN stock_basic sb ON f.symbol = sb.ts_code
            LEFT JOIN name_asof na
              ON f.trade_date = na.signal_date
             AND f.symbol = na.symbol
             AND na.rn = 1
            WHERE f.trade_date IN (
                SELECT signal_date FROM size_signal_dates
            )
              AND f.st_name IS NULL
              AND NOT REGEXP_MATCHES(
                  COALESCE(na.name, sb.name, ''),
                  'ST|退'
              )
              AND NOT f.is_suspended
              AND f.amount > f.amount_p20
              AND f.volume > 0
              AND f.raw_close > 0
              AND sb.list_date IS NOT NULL
              AND STRPTIME(f.trade_date, '%Y%m%d')
                  >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
              AND (
                  sb.delist_date IS NULL
                  OR sb.delist_date > f.trade_date
              )
        )
        SELECT
            signal_date,
            symbol,
            market_cap_proxy,
            PERCENT_RANK() OVER(
                PARTITION BY signal_date
                ORDER BY market_cap_proxy
            ) AS market_cap_percentile
        FROM investable
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _load_source_result(paths: RuntimePaths) -> dict[str, Any]:
    """读取共同模式研究的最新有效结构化结果。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT run_id, run_fingerprint, metrics_json
            FROM experiment_runs
            WHERE experiment_id = ? AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [SOURCE_EXPERIMENT_ID],
        ).fetchone()
    if row is None:
        raise ValueError("缺少因子动物园共同模式源研究")
    return {
        "run_id": str(row[0]),
        "run_fingerprint": str(row[1]),
        "metrics": json.loads(str(row[2] or "{}")),
    }


def _source_file_versions(paths: RuntimePaths) -> list[str]:
    """绑定所有历史持仓与市值代理输入文件。"""
    files = [
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.balance_sheet_path,
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.cashflow_statement_path,
        paths.holder_trade_path,
        paths.block_trade_path,
        paths.fund_ownership_path,
    ]
    versions: list[str] = []
    for path in files:
        stat = path.stat()
        versions.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return versions


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存持仓级证据和报告，排除内部DataFrame后登记指标。"""
    holdings = result.pop("_enriched_holdings")
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    holdings_path = attempt.output_dir / "representative_holdings_size.csv"
    holdings.to_csv(holdings_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            "代表因子持仓级市值归因完成："
            f"{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "持仓市值归因报告"),
            ExperimentArtifact(
                "holdings",
                holdings_path,
                "代表策略历史持仓市值分位",
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
