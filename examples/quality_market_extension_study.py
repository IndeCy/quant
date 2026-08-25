"""Quality V1 少量市场行为增强因子的固定样本外研究。"""

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
from examples.quality_extension_factor_study import evaluate_gate
from examples.quality_factor_study_support import (
    build_period_metrics,
    select_on_validation,
)
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.quality import score_quality_frame
from factors.quality_market_extension import score_quality_market_extension
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


REPORT_PATH = Path("docs/research/quality-market-extension-study.md")
TOP_N = 20
TRAIN_RANGE = ("20150101", "20201231")
VALIDATION_RANGE = ("20210101", "20231231")
LOCKED_TEST_START = "20240101"


@dataclass(frozen=True)
class MarketCandidate:
    """冻结的Quality主体与市场增强权重。"""

    candidate_id: str
    name: str
    extension_weights: dict[str, float]

    def research_spec(self) -> ResearchSpec:
        return ResearchSpec(
            experiment_id=self.candidate_id,
            name=self.name,
            category="factor_strategy",
            hypothesis="少量趋势或低波暴露能否增强Quality V1的样本外稳定性",
            definition={
                "base_alpha": {
                    "strategy": "quality_v1_score",
                    "weight": 1.0 - sum(self.extension_weights.values()),
                    "factors": ["roe", "roa", "ocf_to_or"],
                    "transform": "winsorize_5_95_then_zscore",
                },
                "extensions": {
                    factor: {
                        "weight": weight,
                        "source": "daily_qfq_asof_signal_date",
                        "transform": "winsorize_1_99_then_zscore",
                    }
                    for factor, weight in sorted(self.extension_weights.items())
                },
                "universe": "quality_cleanup",
                "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
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
    MarketCandidate(
        "quality_momentum_120_extension_v1",
        "Quality Momentum 120 Extension V1",
        {"momentum_120d": 0.15},
    ),
    MarketCandidate(
        "quality_trend_strength_extension_v1",
        "Quality Trend Strength Extension V1",
        {"trend_strength_60_120": 0.15},
    ),
    MarketCandidate(
        "quality_lowvol_extension_v1",
        "Quality LowVol Extension V1",
        {"low_volatility_60d": 0.20},
    ),
    MarketCandidate(
        "quality_momentum_lowvol_extension_v1",
        "Quality Momentum LowVol Extension V1",
        {"momentum_120d": 0.10, "low_volatility_60d": 0.10},
    ),
    MarketCandidate(
        "quality_trend_lowvol_extension_v1",
        "Quality Trend LowVol Extension V1",
        {"trend_strength_60_120": 0.10, "low_volatility_60d": 0.10},
    ),
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """按候选语义指纹去重，并执行固定的验证/锁定测试。"""
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
        source = _add_market_factors(source)
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
        render_report(metrics, selected_id, gate, latest_date),
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
        "latest_holdings": latest[
            ["signal_date", "symbol", "name", "rank", "factor_score"]
        ].to_dict("records"),
        "latest_date": latest_date,
        "report_path": str(output),
        "reused": False,
    }


def _add_market_factors(source: pd.DataFrame) -> pd.DataFrame:
    result = source.copy()
    result["momentum_120d"] = pd.to_numeric(result["ret120"], errors="coerce")
    result["trend_strength_60_120"] = (
        pd.to_numeric(result["ma60"], errors="coerce")
        / pd.to_numeric(result["ma120"], errors="coerce").replace(0, pd.NA)
        - 1
    )
    result["low_volatility_60d"] = -pd.to_numeric(result["vol60"], errors="coerce")
    return result


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
    return f"""# Quality Market Extension Study

- 数据截止：{latest_date}
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- Quality V1主体权重80%-85%，市场增强仅占15%-20%。
- 统一口径：Quality Cleanup、Top20等权、月频、qfq、M0 T+1、5bps及原风险层。

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
