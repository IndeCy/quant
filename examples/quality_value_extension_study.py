"""Quality V1 少量点时估值增强因子的固定样本外研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    CorporateActionAudit,
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_extension_factor_study import evaluate_gate
from examples.quality_factor_study_support import (
    build_period_metrics,
    select_on_validation,
)
from examples.quality_market_extension_study import MarketCandidate
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.quality import score_quality_frame
from factors.quality_market_extension import score_quality_market_extension
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


REPORT_PATH = Path("docs/research/quality-value-extension-study.md")
TOP_N = 20
TRAIN_RANGE = ("20150101", "20201231")
VALIDATION_RANGE = ("20210101", "20231231")
LOCKED_TEST_START = "20240101"
CANDIDATES = (
    MarketCandidate(
        "quality_earnings_yield_extension_v1",
        "Quality Earnings Yield Extension V1",
        {"earnings_yield": 0.15},
    ),
    MarketCandidate(
        "quality_book_yield_extension_v1",
        "Quality Book Yield Extension V1",
        {"book_yield": 0.15},
    ),
    MarketCandidate(
        "quality_balanced_value_extension_v1",
        "Quality Balanced Value Extension V1",
        {"earnings_yield": 0.10, "book_yield": 0.10},
    ),
    MarketCandidate(
        "quality_defensive_value_extension_v1",
        "Quality Defensive Value Extension V1",
        {"earnings_yield": 0.10, "book_yield": 0.10, "low_volatility_60d": 0.10},
    ),
    MarketCandidate(
        "quality_value_30_extension_v1",
        "Quality Value 30 Extension V1",
        {"earnings_yield": 0.15, "book_yield": 0.15},
    ),
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先用完整语义指纹判重，再执行统一公司行动门禁和回测。"""
    attempts = {
        candidate.candidate_id: begin_research_attempt(
            candidate.research_spec(),
            paths=paths,
            data_as_of=as_of_date,
            force=force,
        )
        for candidate in CANDIDATES
    }
    if all(not attempt.should_run for attempt in attempts.values()):
        return {
            "reused": True,
            "candidates": {
                key: attempt.cached_result()
                for key, attempt in attempts.items()
            },
        }
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempts(attempts, result)
        return result
    except Exception as error:
        for attempt in attempts.values():
            fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
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
        signal_dates = load_month_end_signal_dates(connection)
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        source = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
        source = attach_report_adjustment_factors(connection, source)
        source, audit = build_quality_value_lowvol_candidates(source)
        selections, holdings = _build_selections(source)
        bars = load_feature_bars(
            connection,
            sorted(holdings["symbol"].astype(str).unique().tolist()),
        )
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    runs = {
        strategy_id: run_risk_layer_backtest(
            strategy_id,
            "GRID",
            {
                date: {symbol: 1.0 / len(symbols) for symbol in symbols}
                for date, symbols in mapping.items()
                if symbols
            },
            bars,
            calendar,
            benchmark,
            ExecutionModel(slippage_bps=5.0),
            vol_window=20,
            vol_threshold=0.45,
            reduced_exposure=0.30,
        )
        for strategy_id, mapping in selections.items()
    }
    metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test": (LOCKED_TEST_START, latest_date),
            "full": ("20150101", latest_date),
        },
    )
    selected_id = select_on_validation(
        metrics,
        {candidate.candidate_id for candidate in CANDIDATES},
    )
    gate = evaluate_gate(metrics[selected_id], metrics["quality_v1_baseline"])
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(metrics, selected_id, gate, latest_date, audit),
        encoding="utf-8",
    )
    latest_signal = str(holdings["signal_date"].max())
    latest = holdings[
        holdings["strategy_id"].eq(selected_id)
        & holdings["signal_date"].astype(str).eq(latest_signal)
    ]
    return {
        "selected_candidate": selected_id,
        "gate": gate,
        "period_metrics": metrics,
        "corporate_action_audit": audit.__dict__,
        "latest_holdings": latest[
            ["signal_date", "symbol", "name", "rank", "factor_score"]
        ].to_dict("records"),
        "latest_date": latest_date,
        "report_path": str(output),
        "reused": False,
    }


def _build_selections(
    source: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame]:
    mappings: dict[str, dict[str, list[str]]] = {}
    holdings: list[pd.DataFrame] = []
    baseline = _score(source, None)
    mappings["quality_v1_baseline"], selected = build_topn_selections(
        baseline,
        "factor_score",
        TOP_N,
    )
    selected["strategy_id"] = "quality_v1_baseline"
    holdings.append(selected)
    for candidate in CANDIDATES:
        scored = _score(source, candidate.extension_weights)
        mapping, selected = build_topn_selections(scored, "factor_score", TOP_N)
        selected["strategy_id"] = candidate.candidate_id
        mappings[candidate.candidate_id] = mapping
        holdings.append(selected)
    return mappings, pd.concat(holdings, ignore_index=True)


def _score(
    source: pd.DataFrame,
    extension_weights: dict[str, float] | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        if extension_weights is None:
            scored = score_quality_frame(group).rename(
                columns={"quality_score": "factor_score"}
            )
        else:
            scored = score_quality_market_extension(group, extension_weights)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _complete_attempts(
    attempts: dict[str, ResearchAttempt],
    result: dict[str, Any],
) -> None:
    selected_id = str(result["selected_candidate"])
    report_path = Path(str(result["report_path"]))
    for candidate_id, attempt in attempts.items():
        if not attempt.should_run:
            continue
        summary = attempt.output_dir / "summary.md"
        summary.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
        selected = candidate_id == selected_id
        passed = selected and bool(result["gate"]["passed"])
        complete_research_attempt(
            attempt,
            metrics={
                "candidate_id": candidate_id,
                "selected_on_validation": selected,
                "gate": result["gate"] if selected else {
                    "passed": False,
                    "reason": "validation_rank",
                },
                "period_metrics": result["period_metrics"][candidate_id],
                "corporate_action_audit": result["corporate_action_audit"],
                "report_path": str(report_path),
            },
            outcome="PASSED" if passed else "REJECTED",
            decision_reason=(
                "验证集第一且锁定测试通过固定晋级门槛"
                if passed
                else "未通过固定的验证集选择与锁定测试晋级流程"
            ),
            artifacts=[ExperimentArtifact("summary", summary, "研究报告")],
        )


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    selected_id: str,
    gate: dict[str, Any],
    latest_date: str,
    audit: CorporateActionAudit,
) -> str:
    rows = []
    for strategy_id, periods in metrics.items():
        for period in ("validation", "locked_test", "full"):
            item = periods[period]
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2%} |"
            )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality Value Extension Study

- 数据截止：{latest_date}
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- Quality主体70%-85%，估值增强使用点时E/P、B/P和可选低波。
- 公司行动门禁：检查{audit.checked_rows}条，剔除{audit.excluded_rows}条重大变化。
- 统一Top20月频、qfq、M0 T+1、5bps及原风险层。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

验证集入选：`{selected_id}`。

## 锁定测试门槛

{checks}

结论：{'允许进入标准策略注册验收' if gate['passed'] else '不注册，保留失败指纹'}。
"""


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
