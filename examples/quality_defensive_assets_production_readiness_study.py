"""Quality防御组合的生产数据与本地Paper接入就绪研究。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.paper_execution import BrokerConfig
from data.market_data_dependencies import (
    load_market_data_dependencies,
    validate_fund_incremental_coverage,
)
from data.market_snapshot import create_fund_market_snapshot
from data.tushare_benchmark_incremental import (
    BenchmarkIncrementalStore,
    TushareBenchmarkProClient,
    TushareBenchmarkUpdater,
)
from examples import quality_defensive_assets_study as base_study
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


STRATEGY_ID = "quality_defensive_assets_production_readiness_v1"
CORE_STRATEGY_ID = "quality_balanced_value_v1"
DEFENSIVE_WEIGHTS = {"518880.SH": 0.15, "511010.SH": 0.15}
INITIAL_CASH = 1_000_000.0
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防御组合生产就绪研究V1",
    category="production_readiness",
    hypothesis="冻结的70/15/15组合能否复用标准数据层并生成真实T+1 Paper委托",
    definition={
        "core_strategy": CORE_STRATEGY_ID,
        "allocation": {
            "quality_core": 0.70,
            "518880.SH": 0.15,
            "511010.SH": 0.15,
        },
        "risk": {
            "scope": "quality_core_only",
            "window": 20,
            "threshold": 0.45,
            "reduced_core_exposure": 0.30,
        },
        "data": {
            "signal_adjust": "qfq",
            "execution_adjust": "none",
            "financial_visibility": "as_of",
            "dependencies": ["510300.SH", "518880.SH", "511010.SH"],
        },
        "execution": {
            "delay": 1,
            "order_sizing": "t1_open_aware",
            "slippage_bps": 10.0,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
            "lot_size": 100,
        },
        "promotion_gates": [
            "paper_execution_policy_persisted_per_strategy_or_account",
            "paper_target_batch_persisted_for_t1_open_resizing",
            "paper_t1_sla_20_consecutive_trading_days",
        ],
        "methodology_version": "v4",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究指纹，再执行外部数据拉取与策略重放。"""
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
        report_path = attempt.output_dir / "production_readiness.md"
        report_path.write_text(_render_report(result), encoding="utf-8")
        complete_research_attempt(
            attempt,
            metrics=result,
            outcome="CONTINUE_OBSERVATION",
            decision_reason=(
                "数据、委托与账户级执行参数干跑通过，但T+1执行SLA尚未"
                "达到连续20个交易日，不注册为生产策略。"
            ),
            artifacts=[
                ExperimentArtifact(
                    "production_readiness_report",
                    report_path,
                    "Quality防御组合生产就绪报告",
                )
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
    """在隔离运行目录中补数据、构造目标并生成待撮合委托。"""
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
    base_latest = _load_fund_base_latest(
        paths.fund_daily_history_path,
        dependencies.fund_symbols,
    )
    update_result = updater.update(
        compact_date,
        fund_base_latest=base_latest,
        index_base_latest={},
    )
    coverage_issues = validate_fund_incremental_coverage(
        store,
        dependencies.fund_symbols,
        compact_date,
    )
    if coverage_issues:
        raise RuntimeError("基金增量覆盖失败: " + "; ".join(coverage_issues))

    fund_snapshots = _audit_fund_snapshots(
        sandbox_paths,
        dependencies.fund_symbols,
        compact_date,
    )
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
    market_data = load_live_market_for_symbols(
        sandbox_paths,
        compact_date,
        sorted(target_weights),
    )
    loaded_symbols = set(market_data["symbol"].astype(str))
    missing_market = sorted(set(target_weights) - loaded_symbols)
    if missing_market:
        raise RuntimeError(f"目标组合缺少原始成交行情: {missing_market}")

    (
        paper_result,
        pending_orders,
        execution_policy_persisted,
        target_batch_persisted,
    ) = _dry_run_paper(
        attempt,
        compact_date,
        target_weights,
        market_data,
    )
    pending_symbols = {str(item["symbol"]) for item in pending_orders}
    result = {
        "data_as_of": compact_date,
        "configured_funds": list(dependencies.fund_symbols),
        "increment_update": asdict(update_result),
        "increment_coverage_issues": coverage_issues,
        "fund_snapshots": fund_snapshots,
        "core_strategy_id": CORE_STRATEGY_ID,
        "core_risk_state": str(computation.metrics["risk_state"]),
        "core_exposure": float(computation.metrics["target_exposure"]),
        "core_target_count": len(core_weights),
        "combined_target_count": len(target_weights),
        "combined_target_exposure": float(sum(target_weights.values())),
        "market_coverage_count": len(loaded_symbols),
        "missing_market_symbols": missing_market,
        "paper_created_orders": paper_result.created_orders,
        "paper_pending_orders": paper_result.pending_orders,
        "paper_next_trade_date": paper_result.next_trade_date,
        "paper_order_symbols": sorted(pending_symbols),
        "paper_zero_lot_symbols": sorted(set(target_weights) - pending_symbols),
        "defensive_orders_present": all(
            symbol in pending_symbols for symbol in DEFENSIVE_WEIGHTS
        ),
        "data_and_order_dry_run_passed": True,
        "paper_execution_policy_persisted": execution_policy_persisted,
        "paper_target_batch_persisted": target_batch_persisted,
        "production_registration_ready": False,
        "remaining_gates": [
            "T+1执行SLA连续20个交易日100%通过",
        ],
    }
    issues = evaluate_readiness(result)
    if issues:
        raise RuntimeError("生产就绪干跑失败: " + "; ".join(issues))
    return result


def blend_target_weights(
    core_weights: dict[str, float],
    defensive_weights: dict[str, float],
    *,
    core_allocation: float = 0.70,
) -> dict[str, float]:
    """仅缩放核心目标，风险降仓时防守袖套保持固定权重。"""
    if core_allocation < 0 or sum(defensive_weights.values()) > 1:
        raise ValueError("非法组合配置")
    result = {
        symbol: float(weight) * core_allocation
        for symbol, weight in core_weights.items()
        if float(weight) > 0
    }
    for symbol, weight in defensive_weights.items():
        result[symbol] = result.get(symbol, 0.0) + float(weight)
    return result


def evaluate_readiness(result: dict[str, Any]) -> list[str]:
    """把生产候选的最低数据与委托门槛集中成可测试规则。"""
    issues: list[str] = []
    if result.get("increment_coverage_issues"):
        issues.append("基金增量不完整")
    if result.get("missing_market_symbols"):
        issues.append("目标行情不完整")
    if not bool(result.get("defensive_orders_present")):
        issues.append("防守资产未生成委托")
    if not bool(result.get("paper_execution_policy_persisted")):
        issues.append("账户执行参数未持久化")
    if not bool(result.get("paper_target_batch_persisted")):
        issues.append("T+1目标组合批次未持久化")
    if int(result.get("paper_created_orders") or 0) <= 0:
        issues.append("未生成T+1委托")
    if str(result.get("paper_next_trade_date") or "") <= str(result["data_as_of"]):
        issues.append("委托日期未顺延到下一交易日")
    return issues


def _prepare_sandbox(paths: RuntimePaths, output_dir: Path) -> RuntimePaths:
    """复制可写基金缓存，并只读链接股票增量，避免污染正式数据。"""
    sandbox = RuntimePaths(output_dir / "runtime_sandbox")
    sandbox.ensure_directories()
    if not paths.benchmark_increment_path.exists():
        raise FileNotFoundError(paths.benchmark_increment_path)
    shutil.copy2(paths.benchmark_increment_path, sandbox.benchmark_increment_path)
    if not paths.live_market_increment_path.exists():
        raise FileNotFoundError(paths.live_market_increment_path)
    sandbox.live_market_increment_path.symlink_to(
        paths.live_market_increment_path.resolve()
    )
    return sandbox


def _load_fund_base_latest(
    history_path: Path,
    symbols: tuple[str, ...],
) -> dict[str, str | None]:
    """读取基金历史基线的逐标的截止日。"""
    with duckdb.connect(str(history_path), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT ts_code, MAX(trade_date) AS latest_date
            FROM etf_lof_reits_daily_adj
            WHERE ts_code IN (SELECT UNNEST(?))
            GROUP BY ts_code
            """,
            [list(symbols)],
        ).fetchall()
    values = {str(symbol): str(latest) for symbol, latest in rows}
    return {symbol: values.get(symbol) for symbol in symbols}


def _audit_fund_snapshots(
    paths: RuntimePaths,
    symbols: tuple[str, ...],
    as_of_date: str,
) -> list[dict[str, Any]]:
    """同时验证前复权信号价与不复权成交价。"""
    snapshots: list[dict[str, Any]] = []
    for adjust_policy in ("qfq", "none"):
        snapshot = create_fund_market_snapshot(
            paths.fund_daily_history_path,
            paths.benchmark_increment_path,
            as_of_date,
            lookback_start=as_of_date,
            adjust_policy=adjust_policy,
        )
        for symbol in symbols:
            bars = snapshot.load_daily_bars(symbol)
            if bars.empty:
                raise RuntimeError(f"{symbol} {adjust_policy} 快照为空")
            row = bars.iloc[-1]
            row_date = pd.Timestamp(bars.index[-1]).strftime("%Y%m%d")
            if row_date != as_of_date or float(row["close"]) <= 0:
                raise RuntimeError(f"{symbol} {adjust_policy} 快照日期或价格异常")
            if pd.isna(row["adj_factor"]):
                raise RuntimeError(f"{symbol} 缺少复权因子")
            snapshots.append(
                {
                    "symbol": symbol,
                    "adjust_policy": adjust_policy,
                    "trade_date": row_date,
                    "close": float(row["close"]),
                    "adj_factor": float(row["adj_factor"]),
                    "snapshot_id": snapshot.snapshot_id,
                }
            )
    return snapshots


def _dry_run_paper(
    attempt: ResearchAttempt,
    trade_date: str,
    target_weights: dict[str, float],
    market_data: pd.DataFrame,
) -> tuple[Any, list[dict[str, Any]], bool, bool]:
    """使用隔离账户验证目标组合能生成下一交易日委托。"""
    broker = LocalPaperBroker(
        attempt.output_dir / "paper_dry_run.sqlite3",
        BrokerConfig(
            slippage_bps=10.0,
            execution_delay=1,
            max_participation_rate=0.01,
            commission_rate=0.0003,
            stamp_tax_rate=0.001,
            min_commission=5.0,
            lot_size=100,
            open_aware_order_sizing=True,
            tax_exempt_symbols=frozenset(DEFENSIVE_WEIGHTS),
        ),
    )
    try:
        result = broker.sync_target(
            PaperBrokerTarget(
                strategy_id=STRATEGY_ID,
                strategy_name="Quality防御组合生产就绪干跑",
                trade_date=trade_date,
                target_weights=target_weights,
                market_data=market_data,
                trading_dates=next_broker_trading_dates(trade_date),
                initial_cash=INITIAL_CASH,
            )
        )
        orders = broker.store.list_orders(result.account_id, status="PENDING")
        policy = broker.execution_policies.load(result.account_id)
        persisted = (
            policy is not None
            and policy.slippage_bps == 10.0
            and policy.commission_rate == 0.0003
            and policy.stamp_tax_rate == 0.001
            and policy.lot_size == 100
            and policy.open_aware_order_sizing
            and policy.tax_exempt_symbols == frozenset(DEFENSIVE_WEIGHTS)
        )
        batch = broker.store.conn.execute(
            """
            SELECT target_weights FROM paper_target_batch
            WHERE account_id = ? AND execute_date = ? AND status = 'PENDING'
            """,
            (result.account_id, _iso_date(result.next_trade_date)),
        ).fetchone()
        target_batch_persisted = (
            batch is not None
            and json.loads(str(batch["target_weights"]))
            == {
                symbol: float(weight)
                for symbol, weight in sorted(target_weights.items())
            }
        )
        return result, orders, persisted, target_batch_persisted
    finally:
        broker.close()


def _render_report(result: dict[str, Any]) -> str:
    """生成面向生产准入的短报告。"""
    funds = "、".join(result["configured_funds"])
    return f"""# Quality防御组合生产就绪研究

- 数据截止：{result['data_as_of']}
- 固定基金依赖：{funds}
- Core 风险状态：{result['core_risk_state']}
- Core 当前暴露：{result['core_exposure']:.2%}
- 合并目标暴露：{result['combined_target_exposure']:.2%}
- 目标标的数：{result['combined_target_count']}
- 行情覆盖数：{result['market_coverage_count']}
- T+1 委托数：{result['paper_created_orders']}
- 下一撮合日：{result['paper_next_trade_date']}
- 防守资产委托：{'通过' if result['defensive_orders_present'] else '失败'}
- 账户级执行参数持久化：{'通过' if result['paper_execution_policy_persisted'] else '失败'}
- T+1目标组合批次持久化：{'通过' if result['paper_target_batch_persisted'] else '失败'}

## 结论

数据更新、前复权信号价、不复权成交价与混合资产委托链路已通过隔离干跑。
当前仍不注册生产策略，剩余门槛：

1. {result['remaining_gates'][0]}
"""


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"非法交易日: {value}")
    return text


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


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
