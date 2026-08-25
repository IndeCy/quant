"""盈利质量与资产负债表因子固定候选研究。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.quality_factor_study_support import (
    build_period_metrics,
    select_on_validation,
)
from factors.quality import score_quality_frame
from factors.quality_fundamental import score_quality_fundamental_frame
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


REPORT_PATH = Path("docs/research/quality-balance-sheet-factor-study.md")
TOP_N = 20
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"


@dataclass(frozen=True)
class Candidate:
    """一组研究前冻结的财务因子及方向。"""

    candidate_id: str
    name: str
    factor_directions: dict[str, int]

    def research_spec(self) -> ResearchSpec:
        """生成与展示名称无关的完整研究定义。"""
        factor_count = len(self.factor_directions)
        return ResearchSpec(
            experiment_id=self.candidate_id,
            name=self.name,
            category="factor_strategy",
            hypothesis="盈利质量与资产负债表信息能否形成可执行的样本外Alpha",
            definition={
                "factors": {
                    factor: {
                        "direction": direction,
                        "weight": 1.0 / factor_count,
                        "source": "tushare_fina_indicator_annual_asof",
                    }
                    for factor, direction in sorted(self.factor_directions.items())
                },
                "transform": "winsorize_1_99_then_zscore",
                "universe": "quality_cleanup",
                "portfolio": {
                    "top_n": TOP_N,
                    "weight": "equal",
                    "rebalance": "monthly",
                },
                "risk_overlay": {
                    "scheme": "GRID",
                    "window": 20,
                    "threshold": 0.45,
                    "reduced_exposure": 0.30,
                },
                "execution": {
                    "model": "M0",
                    "lag": 1,
                    "adjust": "qfq",
                    "slippage_bps": 5.0,
                },
                "evaluation": {
                    "train": TRAIN_RANGE,
                    "validation": VALIDATION_RANGE,
                    "locked_test_start": LOCKED_TEST_START,
                    "selection_order": [
                        "sharpe_desc",
                        "calmar_desc",
                        "max_drawdown_desc",
                        "turnover_asc",
                        "candidate_id_asc",
                    ],
                },
                "methodology_version": "v1",
            },
        )


CANDIDATES = (
    Candidate(
        "quality_cash_conversion_v1",
        "Quality Cash Conversion V1",
        {"roa": 1, "ocf_to_or": 1, "ocf_to_profit": 1},
    ),
    Candidate(
        "quality_conservative_balance_v1",
        "Quality Conservative Balance V1",
        {"roa": 1, "ocf_to_or": 1, "assets_yoy": -1, "debt_to_assets": -1},
    ),
    Candidate(
        "quality_margin_efficiency_v1",
        "Quality Margin Efficiency V1",
        {"roa": 1, "ocf_to_or": 1, "grossprofit_margin": 1, "assets_turn": 1},
    ),
    Candidate(
        "quality_balanced_fundamental_v1",
        "Quality Balanced Fundamental V1",
        {
            "roa": 1,
            "ocf_to_or": 1,
            "grossprofit_margin": 1,
            "assets_yoy": -1,
            "debt_to_assets": -1,
        },
    ),
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请候选指纹，再执行共享数据准备与固定样本外验收。"""
    attempts = {
        item.candidate_id: begin_research_attempt(
            item.research_spec(),
            paths=paths,
            data_as_of=as_of_date,
            force=force,
        )
        for item in CANDIDATES
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
        result = _run_study_calculation(paths, as_of_date)
        _complete_attempts(attempts, result)
        return result
    except Exception as error:
        for attempt in attempts.values():
            fail_research_attempt(attempt, error)
        raise


def _run_study_calculation(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """一次加载数据并完成全部冻结候选的可比回测。"""
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
        candidates = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
        selections, holdings = _build_all_selections(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        bars = load_feature_bars(connection, symbols)
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
        name: _run_candidate(name, mapping, bars, calendar, benchmark)
        for name, mapping in selections.items()
    }
    period_metrics = _build_period_metrics(runs, benchmark, latest_date)
    selected_id = select_on_validation(
        period_metrics,
        {candidate.candidate_id for candidate in CANDIDATES},
    )
    gate = evaluate_locked_gate(
        period_metrics[selected_id],
        period_metrics["quality_v1_baseline"],
    )
    report = render_report(period_metrics, selected_id, gate, latest_date)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    latest_holdings = holdings[
        holdings["strategy_id"].eq(selected_id)
        & holdings["signal_date"].eq(holdings["signal_date"].max())
    ]
    return {
        "selected_candidate": selected_id,
        "gate": gate,
        "period_metrics": period_metrics,
        "latest_holdings": latest_holdings[
            ["signal_date", "symbol", "name", "rank", "factor_score"]
        ].to_dict("records"),
        "latest_date": latest_date,
        "report_path": str(output),
        "reused": False,
    }


def evaluate_locked_gate(
    selected: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """研究前固定门槛；锁定测试结果不得用于反向改阈值。"""
    test = selected["locked_test"]
    full = selected["full"]
    baseline_test = baseline["locked_test"]
    checks = {
        "locked_test_annual_return_at_least_8pct": test["annualized_return"] >= 0.08,
        "locked_test_sharpe_at_least_055": test["sharpe"] >= 0.55,
        "locked_test_drawdown_within_30pct": test["max_drawdown"] >= -0.30,
        "locked_test_positive_excess": test["excess_return"] > 0,
        "drawdown_not_worse_than_quality_v1_by_5pct": (
            test["max_drawdown"] >= baseline_test["max_drawdown"] - 0.05
        ),
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_drawdown_within_32pct": full["max_drawdown"] >= -0.32,
        "turnover_not_over_quality_v1_125pct": (
            full["annual_turnover"]
            <= baseline["full"]["annual_turnover"] * 1.25
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _build_all_selections(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame]:
    """分别计算基线和候选分数，组合层统一选择Top20。"""
    mappings: dict[str, dict[str, list[str]]] = {}
    holdings: list[pd.DataFrame] = []
    baseline = _score_by_date(candidates, None)
    baseline["strategy_id"] = "quality_v1_baseline"
    mappings["quality_v1_baseline"], base_holdings = build_topn_selections(
        baseline,
        "factor_score",
        TOP_N,
    )
    base_holdings["strategy_id"] = "quality_v1_baseline"
    holdings.append(base_holdings)
    for candidate in CANDIDATES:
        scored = _score_by_date(candidates, candidate.factor_directions)
        scored["strategy_id"] = candidate.candidate_id
        mapping, selected = build_topn_selections(scored, "factor_score", TOP_N)
        selected["strategy_id"] = candidate.candidate_id
        mappings[candidate.candidate_id] = mapping
        holdings.append(selected)
    return mappings, pd.concat(holdings, ignore_index=True)


def _score_by_date(
    candidates: pd.DataFrame,
    factor_directions: dict[str, int] | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        if factor_directions is None:
            scored = score_quality_frame(group).rename(
                columns={"quality_score": "factor_score"}
            )
        else:
            scored = score_quality_fundamental_frame(group, factor_directions)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _run_candidate(
    name: str,
    selections: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }
    return run_risk_layer_backtest(
        name,
        "GRID",
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )


def _build_period_metrics(
    runs: dict[str, RiskLayerRun],
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, dict[str, float]]]:
    periods = {
        "train": (*TRAIN_RANGE,),
        "validation": (*VALIDATION_RANGE,),
        "locked_test": (LOCKED_TEST_START, latest_date),
        "full": ("20150101", latest_date),
    }
    return build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )


def _complete_attempts(
    attempts: dict[str, ResearchAttempt],
    result: dict[str, Any],
) -> None:
    selected_id = str(result["selected_candidate"])
    gate = dict(result["gate"])
    report_path = Path(str(result["report_path"]))
    for candidate_id, attempt in attempts.items():
        if not attempt.should_run:
            continue
        summary_path = attempt.output_dir / "summary.md"
        summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
        selected = candidate_id == selected_id
        passed = selected and bool(gate["passed"])
        complete_research_attempt(
            attempt,
            metrics={
                "candidate_id": candidate_id,
                "selected_on_validation": selected,
                "gate": gate if selected else {"passed": False, "reason": "validation_rank"},
                "period_metrics": result["period_metrics"][candidate_id],
                "report_path": str(report_path),
            },
            outcome="PASSED" if passed else "REJECTED",
            decision_reason=(
                "验证集第一且锁定测试通过固定晋级门槛"
                if passed
                else "未通过固定的验证集选择与锁定测试晋级流程"
            ),
            artifacts=[ExperimentArtifact("summary", summary_path, "研究报告")],
        )


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    selected_id: str,
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """输出足以复核选择过程和锁定测试的研究报告。"""
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
    return f"""# Quality Balance Sheet Factor Study

- 数据截止：{latest_date}
- 候选：研究前固定四组，不新增数据源。
- 选择：只按2019-2021验证集的Sharpe、Calmar、回撤、换手率依次排序。
- 锁定测试：2022年至数据截止日，禁止根据测试结果反向换候选或改门槛。
- 统一口径：Quality Cleanup股票池、Top20等权、月频、qfq、M0 T+1、5bps。
- 风险层：20日组合波动率大于45%时仓位降至30%。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 验证集选择

入选候选：`{selected_id}`。

## 锁定测试晋级门槛

{checks}

结论：{'允许进入标准策略注册验收' if gate['passed'] else '不注册，保留失败指纹并研究下一组假设'}。
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
