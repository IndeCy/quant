"""Quality防御组合的T+1订单数量规划研究。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.market_data_dependencies import (
    load_market_data_dependencies,
    validate_fund_incremental_coverage,
)
from data.tushare_benchmark_incremental import (
    BenchmarkIncrementalStore,
    TushareBenchmarkProClient,
    TushareBenchmarkUpdater,
)
from examples import quality_defensive_assets_capital_feasibility_study as capital_study
from examples import quality_defensive_assets_study as base_study
from examples.quality_defensive_assets_order_sizing_metrics import (
    ORDER_POLICIES,
    build_open_aware_order_weights,
    estimate_buy_cost,
    evaluate_order_policies,
    fit_quantities_to_cash,
    render_report,
)
from examples.quality_defensive_assets_production_readiness_study import (
    CORE_STRATEGY_ID,
    DEFENSIVE_WEIGHTS,
    _load_fund_base_latest,
    _prepare_sandbox,
    blend_target_weights,
)
from runtime.config import get_config_value
from runtime.experiment_runner import ExperimentArtifact
from runtime.local_paper_bridge import (
    load_live_market_for_symbols,
    next_broker_trading_dates,
)
from runtime.local_paper_broker import LocalPaperBroker, PaperBrokerTarget
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_value_lowvol_runner import (
    compute_quality_value_lowvol_instance,
)


EXPERIMENT_ID = "quality_defensive_assets_order_sizing_v1"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality防御组合T+1订单数量规划V1",
    category="production_readiness",
    hypothesis="T+1按开盘可执行价重算股数可消除隔夜跳空导致的尾部整单拒绝",
    definition={
        "strategy": "quality_defensive_assets_core_scoped_70_15_15_v2",
        "target_source": CORE_STRATEGY_ID,
        "capital_levels": list(capital_study.CAPITAL_LEVELS),
        "open_gap_scenarios": capital_study.OPEN_GAP_SCENARIOS,
        "order_policies": list(ORDER_POLICIES),
        "fixed_cash_reserve": 0.05,
        "open_aware_price": "T+1_open_plus_slippage",
        "lot_size": 100,
        "fees": {
            "slippage_bps": 10.0,
            "commission_rate": 0.0003,
            "min_commission": 5.0,
        },
        "liquidity_volume": (
            "signal_day_tushare_lots_converted_to_shares_as_execution_proxy"
        ),
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记确定性指纹，再读取点时数据和启动撮合。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=base_study._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, attempt, as_of_date)
        report_path = attempt.output_dir / "order_sizing_study.md"
        cases_path = attempt.output_dir / "order_sizing_cases.csv"
        policies_path = attempt.output_dir / "order_policy_summary.csv"
        report_path.write_text(render_report(result), encoding="utf-8")
        pd.DataFrame(result["cases"]).to_csv(cases_path, index=False)
        pd.DataFrame(result["policy_summary"]).to_csv(
            policies_path,
            index=False,
        )
        complete_research_attempt(
            attempt,
            metrics=result,
            outcome=str(result["research_outcome"]),
            decision_reason=str(result["decision_reason"]),
            artifacts=[
                ExperimentArtifact(
                    "order_sizing_report",
                    report_path,
                    "T+1订单数量规划研究报告",
                ),
                ExperimentArtifact(
                    "order_sizing_cases",
                    cases_path,
                    "订单数量规划情景明细",
                ),
                ExperimentArtifact(
                    "order_policy_summary",
                    policies_path,
                    "订单数量规划政策汇总",
                ),
            ],
        )
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    attempt: ResearchAttempt,
    as_of_date: str,
) -> dict[str, Any]:
    compact_date = _compact_date(as_of_date)
    sandbox_paths = _prepare_sandbox(paths, attempt.output_dir)
    dependencies = load_market_data_dependencies()
    store = BenchmarkIncrementalStore(sandbox_paths.benchmark_increment_path)
    updater = TushareBenchmarkUpdater(
        TushareBenchmarkProClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        ),
        store,
    )
    update_result = updater.update(
        compact_date,
        fund_base_latest=_load_fund_base_latest(
            paths.fund_daily_history_path,
            dependencies.fund_symbols,
        ),
        index_base_latest={},
    )
    issues = validate_fund_incremental_coverage(
        store,
        dependencies.fund_symbols,
        compact_date,
    )
    if issues:
        raise RuntimeError("基金增量覆盖失败: " + "; ".join(issues))

    instance = load_strategy_definition(CORE_STRATEGY_ID).to_instance_payload()
    computation = compute_quality_value_lowvol_instance(
        instance,
        paths,
        compact_date,
    )
    core_weights = {
        str(symbol): float(weight)
        for symbol, weight in computation.result["target_weights"].items()
    }
    target_weights = blend_target_weights(core_weights, DEFENSIVE_WEIGHTS)
    signal_market = load_live_market_for_symbols(
        sandbox_paths,
        compact_date,
        sorted(target_weights),
    )
    missing = sorted(
        set(target_weights) - set(signal_market["symbol"].astype(str))
    )
    if missing:
        raise RuntimeError(f"目标组合缺少信号日原始行情: {missing}")
    execution_date = next_broker_trading_dates(compact_date)[-1]

    cases: list[dict[str, Any]] = []
    for scenario, open_gap in capital_study.OPEN_GAP_SCENARIOS.items():
        execution_market = capital_study.build_execution_market(
            signal_market,
            execution_date,
            open_gap,
        )
        market = pd.concat(
            [signal_market, execution_market],
            ignore_index=True,
        )
        for capital in capital_study.CAPITAL_LEVELS:
            for policy in ORDER_POLICIES:
                order_weights = order_weights_for_policy(
                    policy,
                    target_weights,
                    signal_market,
                    execution_market,
                    capital,
                )
                cases.append(
                    run_policy_case(
                        attempt.output_dir,
                        compact_date,
                        execution_date,
                        target_weights,
                        order_weights,
                        market,
                        capital,
                        scenario,
                        policy,
                    )
                )
    conclusion = evaluate_order_policies(cases)
    return {
        "data_as_of": compact_date,
        "execution_date": execution_date,
        "target_count": len(target_weights),
        "target_exposure": float(sum(target_weights.values())),
        "increment_update": asdict(update_result),
        "cases": cases,
        **conclusion,
    }


def order_weights_for_policy(
    policy: str,
    target_weights: dict[str, float],
    signal_market: pd.DataFrame,
    execution_market: pd.DataFrame,
    capital: float,
) -> dict[str, float]:
    """把研究政策转换为Broker可复用的信号日目标权重。"""
    if policy == "close_sized_current":
        return dict(target_weights)
    if policy == "close_sized_cash_reserve_5pct":
        return {
            symbol: weight * 0.95
            for symbol, weight in target_weights.items()
        }
    if policy == "open_aware_resized":
        return build_open_aware_order_weights(
            target_weights,
            signal_market,
            execution_market,
            capital,
            capital_study._broker_config(),
        )
    raise ValueError(f"未知订单数量政策: {policy}")


def run_policy_case(
    output_dir: Path,
    signal_date: str,
    execution_date: str,
    target_weights: dict[str, float],
    order_weights: dict[str, float],
    market: pd.DataFrame,
    capital: float,
    scenario: str,
    policy: str,
) -> dict[str, Any]:
    """使用真实LocalPaperBroker验证一档订单规划政策。"""
    database = output_dir / f"paper_{policy}_{scenario}_{int(capital)}.sqlite3"
    broker = LocalPaperBroker(database, capital_study._broker_config())
    try:
        sync = broker.sync_target(
            PaperBrokerTarget(
                strategy_id=f"{EXPERIMENT_ID}_{policy}_{scenario}_{int(capital)}",
                strategy_name="Quality防御组合订单规划研究",
                trade_date=signal_date,
                target_weights=order_weights,
                market_data=market,
                trading_dates=[signal_date, execution_date],
                initial_cash=capital,
            )
        )
        executed, rejected = broker.execute_due_orders(
            execution_date,
            market,
            [sync.account_id],
        )
        summary = capital_study.summarize_capital_case(
            broker,
            sync.account_id,
            market,
            execution_date,
            target_weights,
            capital,
            scenario,
            executed,
            rejected,
        )
        return {
            "order_policy": policy,
            "planned_order_exposure": float(sum(order_weights.values())),
            **summary,
        }
    finally:
        broker.close()


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"非法交易日: {value}")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                get_runtime_paths(),
                args.as_of_date,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
