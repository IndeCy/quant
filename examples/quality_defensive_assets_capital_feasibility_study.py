"""Quality防御组合的资金规模、整手和次日现金可行性研究。"""

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

from backtest.paper_execution import BrokerConfig
from data.market_data_dependencies import (
    load_market_data_dependencies,
    validate_fund_incremental_coverage,
)
from data.tushare_benchmark_incremental import (
    BenchmarkIncrementalStore,
    TushareBenchmarkProClient,
    TushareBenchmarkUpdater,
)
from examples import quality_defensive_assets_study as base_study
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
from strategies.quality_value_lowvol_runner import compute_quality_value_lowvol_instance


STRATEGY_ID = "quality_defensive_assets_capital_feasibility_v2"
CAPITAL_LEVELS = (100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0)
OPEN_GAP_SCENARIOS = {
    "flat_open": 0.00,
    "gap_up_2pct": 0.02,
    "gap_up_5pct": 0.05,
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防御组合资金可行性V1",
    category="production_readiness",
    hypothesis="固定组合在整手、费用和次日高开后能否保持目标覆盖与现金可执行",
    definition={
        "strategy": "quality_defensive_assets_core_scoped_70_15_15_v2",
        "target_source": CORE_STRATEGY_ID,
        "capital_levels": list(CAPITAL_LEVELS),
        "open_gap_scenarios": OPEN_GAP_SCENARIOS,
        "signal": {"price": "raw_close", "date": "T"},
        "execution": {
            "date": "T+1_trading_day",
            "price": "raw_open",
            "slippage_bps": 10.0,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.001,
            "min_commission": 5.0,
            "lot_size": 100,
            "max_participation_rate": 0.01,
            "fund_tax_exempt": sorted(DEFENSIVE_WEIGHTS),
        },
        "liquidity_volume": (
            "signal_day_tushare_lots_converted_to_shares_as_execution_proxy"
        ),
        "data": {"signal_adjust": "qfq", "execution_adjust": "none"},
        "methodology_version": "v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请研究指纹，再重建点时目标和执行情景。"""
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
        report_path = attempt.output_dir / "capital_feasibility.md"
        cases_path = attempt.output_dir / "capital_cases.csv"
        report_path.write_text(_render_report(result), encoding="utf-8")
        pd.DataFrame(result["cases"]).to_csv(cases_path, index=False)
        complete_research_attempt(
            attempt,
            metrics=result,
            outcome=str(result["research_outcome"]),
            decision_reason=str(result["decision_reason"]),
            artifacts=[
                ExperimentArtifact(
                    "capital_feasibility_report",
                    report_path,
                    "Quality防御组合资金可行性报告",
                ),
                ExperimentArtifact(
                    "capital_feasibility_cases",
                    cases_path,
                    "资金规模执行情景明细",
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
    coverage_issues = validate_fund_incremental_coverage(
        store,
        dependencies.fund_symbols,
        compact_date,
    )
    if coverage_issues:
        raise RuntimeError("基金增量覆盖失败: " + "; ".join(coverage_issues))

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
    for scenario, open_gap in OPEN_GAP_SCENARIOS.items():
        execution_market = build_execution_market(
            signal_market,
            execution_date,
            open_gap,
        )
        market = pd.concat(
            [signal_market, execution_market],
            ignore_index=True,
        )
        for capital in CAPITAL_LEVELS:
            cases.append(
                run_capital_case(
                    attempt.output_dir,
                    compact_date,
                    execution_date,
                    target_weights,
                    market,
                    capital,
                    scenario,
                )
            )
    conclusion = evaluate_capital_cases(cases)
    return {
        "data_as_of": compact_date,
        "execution_date": execution_date,
        "core_risk_state": str(computation.metrics["risk_state"]),
        "core_exposure": float(computation.metrics["target_exposure"]),
        "target_count": len(target_weights),
        "target_exposure": float(sum(target_weights.values())),
        "increment_update": asdict(update_result),
        "cases": cases,
        **conclusion,
    }


def build_execution_market(
    signal_market: pd.DataFrame,
    execution_date: str,
    open_gap: float,
) -> pd.DataFrame:
    """用信号日原始量价构造可复现的次日开盘压力情景。"""
    frame = signal_market.copy()
    frame["trade_date"] = execution_date
    execution_open = pd.to_numeric(frame["close"], errors="coerce") * (
        1.0 + float(open_gap)
    )
    frame["open"] = execution_open
    frame["high"] = execution_open
    frame["low"] = execution_open
    frame["close"] = execution_open
    frame["limit_up"] = False
    frame["limit_down"] = False
    return frame


def run_capital_case(
    output_dir: Path,
    signal_date: str,
    execution_date: str,
    target_weights: dict[str, float],
    market: pd.DataFrame,
    capital: float,
    scenario: str,
) -> dict[str, Any]:
    """通过真实LocalPaperBroker生成并撮合一档资金情景。"""
    database = output_dir / f"paper_{scenario}_{int(capital)}.sqlite3"
    broker = LocalPaperBroker(database, _broker_config())
    try:
        sync = broker.sync_target(
            PaperBrokerTarget(
                strategy_id=f"{STRATEGY_ID}_{scenario}_{int(capital)}",
                strategy_name="Quality防御组合资金可行性",
                trade_date=signal_date,
                target_weights=target_weights,
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
        return summarize_capital_case(
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
    finally:
        broker.close()


def summarize_capital_case(
    broker: LocalPaperBroker,
    account_id: int,
    market: pd.DataFrame,
    execution_date: str,
    target_weights: dict[str, float],
    capital: float,
    scenario: str,
    executed: int,
    rejected: int,
) -> dict[str, Any]:
    """量化整手、费用和拒单后的实际组合偏差。"""
    positions = broker.store.list_positions(account_id)
    orders = broker.store.list_orders(account_id)
    account = broker.store.get_account(account_id)
    prices = {
        str(row.symbol): float(row.close)
        for row in market[
            market["trade_date"].astype(str).str.replace("-", "").eq(
                _compact_date(execution_date)
            )
        ].itertuples(index=False)
    }
    position_values = {
        str(row["symbol"]): int(row["quantity"]) * prices[str(row["symbol"])]
        for row in positions
    }
    total_value = float(account["cash"]) + sum(position_values.values())
    actual_weights = {
        symbol: value / total_value
        for symbol, value in position_values.items()
        if total_value > 0
    }
    target_cash = max(1.0 - sum(target_weights.values()), 0.0)
    cash_weight = float(account["cash"]) / total_value if total_value > 0 else 1.0
    total_variation = 0.5 * (
        sum(
            abs(actual_weights.get(symbol, 0.0) - target)
            for symbol, target in target_weights.items()
        )
        + abs(cash_weight - target_cash)
    )
    order_symbols = {str(item["symbol"]) for item in orders}
    position_symbols = set(actual_weights)
    rejected_orders = [item for item in orders if item["status"] == "REJECTED"]
    partial_orders = [
        item for item in orders if item["status"] == "PARTIAL_FILLED"
    ]
    return {
        "scenario": scenario,
        "capital": float(capital),
        "created_orders": len(orders),
        "executed_orders": int(executed),
        "rejected_orders": int(rejected),
        "partial_fill_orders": len(partial_orders),
        "held_symbols": len(position_symbols),
        "zero_lot_symbols": len(set(target_weights) - order_symbols),
        "rejected_symbols": "|".join(
            sorted(str(item["symbol"]) for item in rejected_orders)
        ),
        "rejected_target_weight": float(
            sum(
                target_weights.get(str(item["symbol"]), 0.0)
                for item in rejected_orders
            )
        ),
        "cash_weight": cash_weight,
        "gross_exposure": 1.0 - cash_weight,
        "tracking_total_variation": total_variation,
        "max_abs_weight_gap": max(
            abs(actual_weights.get(symbol, 0.0) - target)
            for symbol, target in target_weights.items()
        ),
        "execution_cost": float(
            sum(
                float(item.get("commission") or 0.0)
                + float(item.get("stamp_tax") or 0.0)
                + float(item.get("execution_impact") or 0.0)
                for item in orders
            )
        ),
        "nav_after_execution": total_value / float(capital),
    }


def evaluate_capital_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """以零拒单和不超过5%组合偏差判断资金可执行性。"""
    acceptable = [
        item
        for item in cases
        if item["rejected_orders"] == 0
        and item["tracking_total_variation"] <= 0.05
    ]
    baseline = [
        item for item in cases if item["scenario"] == "flat_open"
    ]
    gap_up = [
        item for item in cases if item["scenario"] == "gap_up_2pct"
    ]
    minimum_baseline = min(
        (item["capital"] for item in baseline if item in acceptable),
        default=None,
    )
    minimum_gap_up = min(
        (item["capital"] for item in gap_up if item in acceptable),
        default=None,
    )
    all_primary_capitals_pass = all(
        item in acceptable for item in gap_up
        if item["capital"] in {500_000.0, 1_000_000.0}
    )
    if all_primary_capitals_pass:
        outcome = "CONTINUE_OBSERVATION"
        reason = "50万和100万资金在2%高开压力下仍满足零拒单和5%目标偏差门槛"
    else:
        outcome = "REQUIRES_ENGINE_FIX"
        reason = "现有订单规划在2%高开压力下出现拒单或超过5%的目标偏差"
    return {
        "minimum_capital_flat_open": minimum_baseline,
        "minimum_capital_gap_up_2pct": minimum_gap_up,
        "research_outcome": outcome,
        "decision_reason": reason,
    }


def _broker_config() -> BrokerConfig:
    return BrokerConfig(
        slippage_bps=10.0,
        execution_delay=1,
        max_participation_rate=0.01,
        commission_rate=0.0003,
        stamp_tax_rate=0.001,
        min_commission=5.0,
        lot_size=100,
        tax_exempt_symbols=frozenset(DEFENSIVE_WEIGHTS),
    )


def _render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        "| {scenario} | {capital:,.0f} | {held_symbols} | {zero_lot_symbols} | "
        "{rejected_orders} | {partial_fill_orders} | {cash_weight:.2%} | "
        "{tracking_total_variation:.2%} | "
        "{execution_cost:,.2f} |".format(**item)
        for item in result["cases"]
    )
    return f"""# Quality防御组合资金可行性

- 信号日：{result['data_as_of']}
- 执行日：{result['execution_date']}
- 目标标的：{result['target_count']}
- 目标暴露：{result['target_exposure']:.2%}
- 研究结论：{result['research_outcome']}
- 原因：{result['decision_reason']}

| 情景 | 本金 | 实际持仓数 | 零手数标的 | 拒单 | 部分成交 | 现金 | 目标偏差 | 执行成本 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{rows}
"""


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
