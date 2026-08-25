"""用早期校准期冻结国内Quality与全球防守块风险权重。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.mixed_asset_execution import MixedAssetExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples import global_defensive_equal_study as global_study
from examples import quality_defensive_assets_study as quality_defensive
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.quality_balanced_value_buffered_study import _data_version
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from portfolio.fixed_sleeve import build_core_scoped_sleeve_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "quality_global_risk_balanced_validation_frozen_v1"
QUALITY_ID = "quality_calibration_block_same_snapshot_v1"
GLOBAL_ID = "global_defensive_calibration_block_same_snapshot_v1"
REPORT_PATH = Path(
    "docs/research/quality-global-risk-balanced-validation-frozen-v1.md"
)
CALIBRATION_START = "20150101"
CALIBRATION_END = "20181231"
OOS_START = "20190101"
LOCKED_START = "20220101"
QUALITY_WEIGHT_FLOOR = 0.20
QUALITY_WEIGHT_CAP = 0.50
PERIODS = {
    "2019_2021": ("20190101", "20211231"),
    "2022_2024": ("20220101", "20241231"),
    "2025_latest": ("20250101", "latest"),
    "locked_test": (LOCKED_START, "latest"),
    "oos_full": (OOS_START, "latest"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="国内Quality×全球防守校准期风险平衡 V1",
    category="portfolio_strategy",
    hypothesis="只用2015至2018波动率冻结块权重，能否在2019后降低Quality风险主导并保留组合收益",
    definition={
        "blocks": {
            "quality": "quality_balanced_value_v1_with_existing_core_risk_overlay",
            "global_defensive": {
                global_study.SP500_SYMBOL: 1 / 3,
                global_study.GOLD_SYMBOL: 1 / 3,
                global_study.BOND_SYMBOL: 1 / 3,
            },
        },
        "calibration": {
            "period": [CALIBRATION_START, CALIBRATION_END],
            "statistic": "daily_return_annualized_volatility",
            "quality_weight_formula": (
                "global_vol / (quality_vol + global_vol)"
            ),
            "quality_weight_clip": [
                QUALITY_WEIGHT_FLOOR,
                QUALITY_WEIGHT_CAP,
            ],
            "frozen_after_calibration": True,
        },
        "evaluation": {
            "start": OOS_START,
            "locked_start": LOCKED_START,
            "weight_grid": False,
        },
        "risk_overlay": {
            "scope": "quality_block_only",
            "global_block_budget_fixed": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
        },
        "frozen_gate": {
            "oos_return_min": 0.09,
            "oos_drawdown_floor": -0.16,
            "oos_sharpe_min": 1.00,
            "oos_calmar_min": 0.60,
            "all_three_folds_positive": True,
            "worst_fold_drawdown_floor": -0.18,
            "median_fold_sharpe_min": 0.75,
            "turnover_max": 3.5,
            "locked_return_min": 0.09,
            "locked_drawdown_floor": -0.15,
            "locked_sharpe_min": 0.90,
            "candidate_quality_correlation_max": 0.88,
            "locked_quality_risk_contribution_share": [0.25, 0.75],
            "return_at_least_global_minus": 0.005,
            "sharpe_at_least_quality_block": True,
            "stress_return_min": 0.08,
            "stress_sharpe_min": 0.90,
            "positive_years_min": 6,
        },
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "validation_inverse_vol_frozen_oos_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先冻结校准公式和样本外门槛，再读取点时数据。"""
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
        result, runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    funds = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [
            global_study.SP500_SYMBOL,
            global_study.GOLD_SYMBOL,
            global_study.BOND_SYMBOL,
            global_study.BENCHMARK_SYMBOL,
        ],
        start_date="20130101",
        end_date=as_of_date,
    )
    latest_date = funds.latest_common_date
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=latest_date,
    )
    try:
        materialize_market_features(connection)
        monthly_dates = [
            date
            for date in load_month_end_signal_dates(connection)
            if date >= CALIBRATION_START
        ]
        quality_targets, quality_holdings = quality_support._build_core(
            connection,
            monthly_dates,
            paths,
        )
        stock_symbols = sorted(
            {
                symbol
                for weights in quality_targets.values()
                for symbol in weights
            }
        )
        stock_bars = load_feature_bars(connection, stock_symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = quality_defensive._benchmark_curve(paths, latest_date)
    quality_run = quality_defensive._run_candidate(
        QUALITY_ID,
        quality_targets,
        stock_bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        risk_overlay=True,
    )
    global_targets = global_study._build_targets(
        [pd.Timestamp(date) for date in quality_targets],
        global_study.ASSET_WEIGHTS,
    )
    fund_model = MixedAssetExecutionModel(
        set(global_study.ASSET_WEIGHTS),
        slippage_bps=5.0,
    )
    global_run = quality_defensive._run_candidate(
        GLOBAL_ID,
        global_targets,
        funds.bars,
        calendar,
        benchmark,
        fund_model,
        risk_overlay=False,
    )
    calibration = calibrate_quality_weight(quality_run, global_run)
    quality_weight = calibration["quality_weight"]
    fund_weights = {
        symbol: (1.0 - quality_weight) / 3.0
        for symbol in global_study.ASSET_WEIGHTS
    }
    candidate_targets = build_core_scoped_sleeve_targets(
        quality_targets,
        quality_run.exposure,
        core_allocation=quality_weight,
        defensive_weights=fund_weights,
    )
    bars = pd.concat([stock_bars, funds.bars]).sort_index()
    candidate_run = quality_defensive._run_candidate(
        EXPERIMENT_ID,
        candidate_targets,
        bars,
        calendar,
        benchmark,
        fund_model,
        risk_overlay=False,
    )
    stress_run = quality_defensive._run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        candidate_targets,
        bars,
        calendar,
        benchmark,
        MixedAssetExecutionModel(
            set(global_study.ASSET_WEIGHTS),
            slippage_bps=20.0,
        ),
        risk_overlay=False,
    )
    runs = {
        QUALITY_ID: quality_run,
        GLOBAL_ID: global_run,
        EXPERIMENT_ID: candidate_run,
    }
    periods = {
        name: (
            start,
            latest_date if end == "latest" else min(end, latest_date),
        )
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    metrics = build_period_metrics(
        {key: value.result for key, value in runs.items()},
        benchmark,
        periods,
    )
    stress = build_period_metrics(
        {"20bps": stress_run.result},
        benchmark,
        {"oos_full": (OOS_START, latest_date)},
    )["20bps"]["oos_full"]
    annual = build_annual_metrics(
        {EXPERIMENT_ID: candidate_run},
        benchmark,
        latest_date,
    )[EXPERIMENT_ID]
    annual = {
        year: item
        for year, item in annual.items()
        if int(year) >= int(OOS_START[:4])
    }
    diagnostics = build_diagnostics(
        runs,
        quality_weight,
    )
    gate = evaluate_gate(metrics, annual, stress, diagnostics)
    latest_target_date = max(candidate_targets)
    names = (
        quality_holdings[["symbol", "name"]]
        .drop_duplicates("symbol", keep="last")
        .set_index("symbol")["name"]
        .to_dict()
    )
    latest_holdings = [
        {
            "signal_date": latest_target_date,
            "symbol": symbol,
            "name": names.get(symbol, _fund_name(symbol)),
            "target_weight": weight,
            "sleeve": (
                "global_defensive"
                if symbol in global_study.ASSET_WEIGHTS
                else "quality"
            ),
        }
        for symbol, weight in sorted(
            candidate_targets[latest_target_date].items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "calibration": calibration,
        "fund_weights": fund_weights,
        "metrics": metrics,
        "annual_metrics": annual,
        "stress_20bps_metrics": stress,
        "diagnostics": diagnostics,
        "gate": gate,
        "decision": (
            "HISTORICAL_GATE_PASSED_FORWARD_CONFIRMATION_ONLY"
            if gate["passed"]
            else "REJECTED_NO_PRODUCTION_CHANGE"
        ),
        "latest_holdings": latest_holdings,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs


def calibrate_quality_weight(
    quality_run: RiskLayerRun,
    global_run: RiskLayerRun,
) -> dict[str, float]:
    """只使用2015至2018的日收益波动率冻结逆波动块权重。"""
    quality = quality_run.result.daily_values.pct_change().loc[
        CALIBRATION_START:CALIBRATION_END
    ]
    global_returns = global_run.result.daily_values.pct_change().loc[
        CALIBRATION_START:CALIBRATION_END
    ]
    aligned = pd.concat(
        [quality.rename("quality"), global_returns.rename("global")],
        axis=1,
    ).dropna()
    quality_vol = float(aligned["quality"].std(ddof=1) * np.sqrt(252))
    global_vol = float(aligned["global"].std(ddof=1) * np.sqrt(252))
    raw_weight = global_vol / (quality_vol + global_vol)
    quality_weight = min(
        QUALITY_WEIGHT_CAP,
        max(QUALITY_WEIGHT_FLOOR, raw_weight),
    )
    return {
        "quality_volatility": quality_vol,
        "global_volatility": global_vol,
        "raw_quality_weight": raw_weight,
        "quality_weight": quality_weight,
        "global_weight": 1.0 - quality_weight,
        "observation_count": float(len(aligned)),
    }


def build_diagnostics(
    runs: dict[str, RiskLayerRun],
    quality_weight: float,
) -> dict[str, float]:
    """计算样本外相关性和锁定期两块Euler风险贡献。"""
    quality = runs[QUALITY_ID].result.daily_values.pct_change()
    global_returns = runs[GLOBAL_ID].result.daily_values.pct_change()
    candidate = runs[EXPERIMENT_ID].result.daily_values.pct_change()
    oos = pd.concat(
        [
            quality.rename("quality"),
            global_returns.rename("global"),
            candidate.rename("candidate"),
        ],
        axis=1,
    ).loc[OOS_START:].dropna()
    locked = oos.loc[LOCKED_START:, ["quality", "global"]]
    weights = np.array([quality_weight, 1.0 - quality_weight], dtype=float)
    covariance = locked.cov().to_numpy(dtype=float)
    contributions = weights * covariance.dot(weights)
    total = float(contributions.sum())
    quality_share = float(contributions[0] / total) if total > 0 else 0.0
    return {
        "candidate_quality_correlation": float(
            oos["candidate"].corr(oos["quality"])
        ),
        "candidate_global_correlation": float(
            oos["candidate"].corr(oos["global"])
        ),
        "quality_global_correlation": float(
            oos["quality"].corr(oos["global"])
        ),
        "locked_quality_risk_contribution_share": quality_share,
        "locked_global_risk_contribution_share": 1.0 - quality_share,
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    stress: dict[str, float],
    diagnostics: dict[str, float],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    oos = candidate["oos_full"]
    locked = candidate["locked_test"]
    quality = metrics[QUALITY_ID]["oos_full"]
    global_def = metrics[GLOBAL_ID]["oos_full"]
    folds = [
        candidate[key]
        for key in ("2019_2021", "2022_2024", "2025_latest")
    ]
    risk_share = diagnostics["locked_quality_risk_contribution_share"]
    checks = {
        "oos_return_at_least_9pct": oos["annualized_return"] >= 0.09,
        "oos_drawdown_within_16pct": oos["max_drawdown"] >= -0.16,
        "oos_sharpe_at_least_100": oos["sharpe"] >= 1.00,
        "oos_calmar_at_least_060": oos["calmar"] >= 0.60,
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_18pct": (
            min(item["max_drawdown"] for item in folds) >= -0.18
        ),
        "median_fold_sharpe_at_least_075": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.75
        ),
        "annual_turnover_below_3_5x": oos["annual_turnover"] <= 3.5,
        "locked_return_at_least_9pct": locked["annualized_return"] >= 0.09,
        "locked_drawdown_within_15pct": locked["max_drawdown"] >= -0.15,
        "locked_sharpe_at_least_090": locked["sharpe"] >= 0.90,
        "candidate_quality_correlation_at_most_088": (
            abs(diagnostics["candidate_quality_correlation"]) <= 0.88
        ),
        "locked_quality_risk_contribution_between_25_and_75pct": (
            0.25 <= risk_share <= 0.75
        ),
        "return_at_least_global_minus_05pct": (
            oos["annualized_return"] >= global_def["annualized_return"] - 0.005
        ),
        "sharpe_at_least_quality_block": oos["sharpe"] >= quality["sharpe"],
        "stress_return_at_least_8pct": stress["annualized_return"] >= 0.08,
        "stress_sharpe_at_least_090": stress["sharpe"] >= 0.90,
        "at_least_six_positive_years": (
            sum(item["annualized_return"] > 0 for item in annual.values()) >= 6
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _fund_name(symbol: str) -> str:
    return {
        global_study.SP500_SYMBOL: "博时标普500ETF",
        global_study.GOLD_SYMBOL: "华安黄金ETF",
        global_study.BOND_SYMBOL: "国泰5年国债ETF",
    }.get(symbol, "")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.concat(
        [
            (run.result.daily_values / float(run.result.daily_values.iloc[0])).rename(
                strategy_id
            )
            for strategy_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "校准期风险平衡杠铃通过全部样本外门槛，仅进入冻结前瞻确认"
            if passed
            else "校准期风险平衡杠铃未通过全部样本外门槛，不修改观察或生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "风险平衡报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与块净值"),
            ExperimentArtifact("latest_holdings", holdings_path, "最新目标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for strategy_id in (QUALITY_ID, GLOBAL_ID, EXPERIMENT_ID):
        for period in (
            "2019_2021",
            "2022_2024",
            "2025_latest",
            "locked_test",
            "oos_full",
        ):
            item = result["metrics"][strategy_id][period]
            rows.append(
                f"| {strategy_id} | {period} | "
                f"{item['annualized_return']:.2%} | {item['max_drawdown']:.2%} | "
                f"{item['sharpe']:.3f} | {item['annual_turnover']:.2f}x |"
            )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'}：{key}"
        for key, value in result["gate"]["checks"].items()
    )
    calibration = result["calibration"]
    diagnostics = result["diagnostics"]
    stress = result["stress_20bps_metrics"]
    return f"""# 国内Quality×全球防守校准期风险平衡 V1

- 数据截止：{result['latest_date']}
- 权重仅由2015–2018日波动率按逆波动公式产生，2019后冻结。
- Quality/全球块冻结权重：
  {calibration['quality_weight']:.2%} /
  {calibration['global_weight']:.2%}。
- 不做权重网格，不读取锁定期定权。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---|---:|---:|---:|---:|
{chr(10).join(rows)}

## 风险与成本

- 校准期Quality/全球年化波动：
  {calibration['quality_volatility']:.2%} /
  {calibration['global_volatility']:.2%}。
- 样本外候选与Quality/全球相关：
  {diagnostics['candidate_quality_correlation']:.3f} /
  {diagnostics['candidate_global_correlation']:.3f}。
- 锁定期Quality/全球风险贡献：
  {diagnostics['locked_quality_risk_contribution_share']:.2%} /
  {diagnostics['locked_global_risk_contribution_share']:.2%}。
- 20bps压力年化/Sharpe：
  {stress['annualized_return']:.2%} / {stress['sharpe']:.3f}。

## 冻结门槛

{checks}

结论：{result['decision']}。
"""


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
