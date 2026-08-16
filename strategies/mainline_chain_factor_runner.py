"""主线链动原生因子组合运行器。"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.chain_selection import ChainDefinition, ChainStock
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.execution_model import ExecutionModel
from backtest.strategy import BaseStrategy
from data.market_cache_reader import read_cached_daily_bars
from examples.compare_chain_stock_selection import build_default_chain_definitions
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_state_writer import StrategyHoldingState, write_strategy_instance_state


INITIAL_CAPITAL = 1_000_000.0
BENCHMARK_SYMBOL = "000001.SH"
BENCHMARK_ALIAS = "市场基线"
MIN_HISTORY_ROWS = 180


@dataclass(frozen=True)
class SelectionRecord:
    """记录最近一次调仓选择，方便生成调仓建议。"""

    symbol: str
    name: str
    chain: str
    segment: str
    score: float
    target_weight: float


@dataclass(frozen=True)
class MainlineChainComputation:
    """主线链动回测的纯计算产物。"""

    result: dict[str, Any]
    strategy: "FactorChainRotationStrategy"
    monitoring_frame: pd.DataFrame
    engine: BacktestEngine
    latest_prices: dict[str, float]


class FactorChainRotationStrategy(BaseStrategy):
    """用系统登记因子组合生成产业链轮动目标权重。"""

    def __init__(
        self,
        chains: list[ChainDefinition],
        factor_weights: dict[str, float],
        top_n: int = 5,
        rebalance_frequency: int = 5,
        chain_momentum_window: int = 60,
    ) -> None:
        super().__init__("Factor_Chain_Rotation")
        self.chains = chains
        self.factor_weights = factor_weights
        self.top_n = top_n
        self.rebalance_frequency = rebalance_frequency
        self.chain_momentum_window = chain_momentum_window
        self.current_holdings: set[str] = set()
        self.latest_targets: list[SelectionRecord] = []
        self.latest_chain = ""
        self._last_rebalance_length: int | None = None

    def generate_signals(self, data: dict[str, pd.DataFrame], date: pd.Timestamp) -> dict[str, float]:
        """每到固定交易日频率，按链强度和链内因子分数生成等权目标。"""
        if not self._should_rebalance(data):
            return {}
        self._last_rebalance_length = self._reference_length(data)
        selected_chain = self._select_chain(data)
        if selected_chain is None or self._is_blocked_by_market_gate(selected_chain, data):
            return self._target_weight_signals([])
        ranked = self._rank_stocks(selected_chain.stocks, data)
        targets = ranked[: self.top_n]
        weight = 1.0 / len(targets) if targets else 0.0
        self.latest_chain = selected_chain.name if targets else ""
        self.latest_targets = [
            SelectionRecord(stock.symbol, stock.name, stock.chain, stock.segment, score, weight)
            for stock, score in targets
        ]
        return self._target_weight_signals(self.latest_targets)

    def _reference_length(self, data: dict[str, pd.DataFrame]) -> int:
        """用股票池中第一条可用序列确定调仓节奏。"""
        for chain in self.chains:
            for stock in chain.stocks:
                if stock.symbol in data:
                    return len(data[stock.symbol])
        return 0

    def _should_rebalance(self, data: dict[str, pd.DataFrame]) -> bool:
        current_length = self._reference_length(data)
        if current_length == 0:
            return False
        if self._last_rebalance_length is None:
            return True
        return current_length - self._last_rebalance_length >= self.rebalance_frequency

    def _select_chain(self, data: dict[str, pd.DataFrame]) -> ChainDefinition | None:
        scored = [(chain, self._momentum(data.get(chain.proxy_symbol), self.chain_momentum_window)) for chain in self.chains]
        valid = [(chain, score) for chain, score in scored if score is not None]
        if not valid:
            return None
        return max(valid, key=lambda item: float(item[1]))[0]

    def _is_blocked_by_market_gate(self, chain: ChainDefinition, data: dict[str, pd.DataFrame]) -> bool:
        chain_score = self._momentum(data.get(chain.proxy_symbol), self.chain_momentum_window)
        market_score = self._momentum(data.get(BENCHMARK_ALIAS), self.chain_momentum_window)
        if chain_score is None or market_score is None:
            return False
        return chain_score < market_score

    def _rank_stocks(
        self,
        stocks: list[ChainStock],
        data: dict[str, pd.DataFrame],
    ) -> list[tuple[ChainStock, float]]:
        rows: list[tuple[ChainStock, float]] = []
        for stock in stocks:
            frame = data.get(stock.symbol)
            if frame is None:
                continue
            score = self._weighted_stock_score(frame)
            if score is not None:
                rows.append((stock, score))
        return sorted(rows, key=lambda item: (item[1], item[0].symbol), reverse=True)

    def _weighted_stock_score(self, frame: pd.DataFrame) -> float | None:
        values = {
            "mainline_stock_momentum_120d": self._momentum(frame, 120),
            "mainline_stock_momentum_60d": self._momentum(frame, 60),
        }
        score = 0.0
        used = 0.0
        for factor_id, value in values.items():
            if value is None:
                continue
            weight = float(self.factor_weights.get(factor_id, 0.0))
            score += weight * float(value)
            used += abs(weight)
        return score if used > 0 else None

    def _momentum(self, frame: pd.DataFrame | None, window: int) -> float | None:
        if frame is None or len(frame) < window + 1:
            return None
        past_close = float(frame["close"].iloc[-(window + 1)])
        if past_close <= 0:
            return None
        return float(frame["close"].iloc[-1]) / past_close - 1.0

    def _target_weight_signals(self, targets: list[SelectionRecord]) -> dict[str, float]:
        target_symbols = {item.symbol for item in targets}
        symbols = sorted(self.current_holdings | target_symbols)
        signals = {symbol: 0.0 for symbol in symbols}
        for item in targets:
            signals[item.symbol] = item.target_weight
        self.current_holdings = target_symbols
        if not targets:
            self.latest_targets = []
            self.latest_chain = ""
        return signals


def run_factor_chain_rotation_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]:
    """兼容入口：在当前线程依次计算并提交主线链动策略。"""
    computation = compute_factor_chain_rotation_instance(instance, paths)
    return persist_factor_chain_rotation_instance(instance, paths, computation)


def compute_factor_chain_rotation_instance(
    instance: dict[str, Any], paths: RuntimePaths
) -> MainlineChainComputation:
    """只读标准缓存完成回测，不写监控库、状态库和运行目录。"""
    strategy_id = str(instance["strategy_id"])
    strategy_name = str(instance["name"])
    chains = build_default_chain_definitions()
    bars = _load_chain_bars(instance, paths, chains)
    benchmark = bars.pop(BENCHMARK_ALIAS)
    data_manager = DataManager()
    for symbol, frame in bars.items():
        data_manager.load_data(symbol, frame, adjust="qfq")
    data_manager.load_data(BENCHMARK_ALIAS, benchmark, adjust="qfq")

    strategy = FactorChainRotationStrategy(
        chains=chains,
        factor_weights=_factor_weights(instance),
        top_n=int(instance.get("construction", {}).get("top_n", 5)),
        rebalance_frequency=int(instance.get("construction", {}).get("rebalance_frequency", 5)),
        chain_momentum_window=int(instance.get("construction", {}).get("chain_momentum_window", 60)),
    )
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=float(instance.get("config", {}).get("initial_capital", INITIAL_CAPITAL)),
        execution_model=ExecutionModel(slippage_bps=float(instance.get("config", {}).get("execution_slippage_bps", 10.0))),
    )
    with contextlib.redirect_stdout(io.StringIO()):
        results = engine.run()
    if len(results) < MIN_HISTORY_ROWS:
        raise RuntimeError(f"mainline_chain_factor_history_too_short: {len(results)} rows")

    monitor_frame = _build_monitor_frame(strategy_id, strategy_name, results, benchmark, engine, instance)
    latest_date = str(monitor_frame.iloc[-1]["trade_date"])
    result = {
        "strategy_id": strategy_id,
        "trade_date": latest_date,
        "selected_count": len(strategy.latest_targets),
        "selected_symbols": [item.symbol for item in strategy.latest_targets],
        "target_weights": {item.symbol: item.target_weight for item in strategy.latest_targets},
        "nav": float(monitor_frame.iloc[-1]["nav"]),
        "rows": len(monitor_frame),
    }
    return MainlineChainComputation(result, strategy, monitor_frame, engine, _latest_prices(bars))


def persist_factor_chain_rotation_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    computation: MainlineChainComputation,
) -> dict[str, Any]:
    """串行提交主线链动监控历史、目标持仓和运行产物。"""
    result = computation.result
    strategy_id = str(result["strategy_id"])
    latest_date = str(result["trade_date"])
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(computation.monitoring_frame)
    run_dir = paths.runs_dir / latest_date
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _write_artifacts(
        run_dir,
        computation.strategy,
        computation.monitoring_frame,
        computation.engine,
        instance,
    )
    write_strategy_instance_state(
        paths,
        strategy_id,
        latest_date,
        float(result["nav"]),
        [
            StrategyHoldingState(
                symbol=item.symbol,
                weight=item.target_weight,
                last_close=computation.latest_prices.get(item.symbol, 0.0),
            )
            for item in computation.strategy.latest_targets
        ],
    )
    _record_success(
        paths,
        strategy_id,
        latest_date,
        run_dir,
        artifacts,
        len(computation.monitoring_frame),
        computation.strategy.latest_targets,
    )
    return {**result, "run_dir": str(run_dir)}


def _load_chain_bars(
    instance: dict[str, Any],
    paths: RuntimePaths,
    chains: list[ChainDefinition],
) -> dict[str, pd.DataFrame]:
    config = dict(instance.get("config") or {})
    cache_path = paths.root / str(config.get("data_cache", "data/market_cache.sqlite3"))
    provider = str(config.get("provider", "tencent"))
    frequency = str(config.get("frequency", "1d"))
    adjust = str(config.get("adjust_policy", "qfq"))
    symbols = _chain_symbols(chains)
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = read_cached_daily_bars(cache_path, provider, symbol, frequency, adjust)
        if not frame.empty:
            result[symbol] = frame
    benchmark = read_cached_daily_bars(cache_path, provider, BENCHMARK_SYMBOL, frequency, "none")
    if not benchmark.empty:
        result[BENCHMARK_ALIAS] = benchmark
    missing = sorted(set(symbols) - set(result))
    if missing:
        raise RuntimeError(f"mainline_chain_cache_missing_symbols: {','.join(missing)}")
    if BENCHMARK_ALIAS not in result:
        raise RuntimeError("mainline_chain_cache_missing_benchmark: 000001.SH")
    return result


def _chain_symbols(chains: list[ChainDefinition]) -> list[str]:
    symbols: list[str] = []
    for chain in chains:
        symbols.append(chain.proxy_symbol)
        symbols.extend(stock.symbol for stock in chain.stocks)
    return list(dict.fromkeys(symbols))


def _factor_weights(instance: dict[str, Any]) -> dict[str, float]:
    return {str(item["factor_id"]): float(item.get("weight", 0.0)) for item in instance.get("factors", [])}


def _build_monitor_frame(
    strategy_id: str,
    strategy_name: str,
    results: pd.DataFrame,
    benchmark: pd.DataFrame,
    engine: BacktestEngine,
    instance: dict[str, Any],
) -> pd.DataFrame:
    daily_values = results["total_value"].astype(float)
    benchmark_values = benchmark["close"].reindex(daily_values.index).ffill()
    exposure = (results["positions_value"].astype(float) / results["total_value"].replace(0, pd.NA)).fillna(0.0)
    total_cost = float(sum(float(trade.get("total_fee", 0.0)) for trade in engine.trades))
    turnover = float(sum(abs(float(trade.get("quantity", 0)) * float(trade.get("price", 0.0))) for trade in engine.trades))
    return build_strategy_monitor_frame(
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        daily_values=daily_values,
        benchmark_values=benchmark_values,
        exposure=exposure,
        total_cost=total_cost,
        failed_order_count=engine.failed_trade_count,
        turnover_notional=turnover,
        benchmark_id=str(instance.get("benchmark") or BENCHMARK_SYMBOL),
    )


def _write_artifacts(
    run_dir: Path,
    strategy: FactorChainRotationStrategy,
    monitor_frame: pd.DataFrame,
    engine: BacktestEngine,
    instance: dict[str, Any],
) -> dict[str, Path]:
    latest = monitor_frame.iloc[-1]
    plan = pd.DataFrame([item.__dict__ for item in strategy.latest_targets])
    if plan.empty:
        plan = pd.DataFrame(columns=["symbol", "name", "chain", "segment", "score", "target_weight"])
    plan["reason"] = "入选最强产业链链内动量TopN"
    snapshot = plan[["symbol", "name", "chain", "segment", "target_weight"]].copy()
    metrics = {
        "strategy_id": instance["strategy_id"],
        "trade_date": str(latest["trade_date"]),
        "nav": float(latest["nav"]),
        "daily_return": float(latest["daily_return"]),
        "cumulative_return": float(latest["cumulative_return"]),
        "current_drawdown": float(latest["drawdown"]),
        "max_drawdown": float(latest["max_drawdown"]),
        "excess_return": float(latest["excess_return"]),
        "volatility_20": float(latest["volatility_20"]),
        "target_exposure": float(latest["exposure"]),
        "risk_state": _risk_state(float(latest["volatility_20"]), float(latest["drawdown"])),
        "selected_chain": strategy.latest_chain,
        "selected_count": len(strategy.latest_targets),
        "total_execution_cost": float(latest["total_execution_cost"]),
        "failed_order_count": int(latest["failed_order_count"]),
        "trade_count": len(engine.trades),
    }
    report = _format_daily_report(metrics, plan)
    artifacts = {
        "rebalance_plan": run_dir / f"{instance['strategy_id']}_rebalance_plan.csv",
        "portfolio_snapshot": run_dir / f"{instance['strategy_id']}_portfolio_snapshot.csv",
        "strategy_metrics": run_dir / f"{instance['strategy_id']}_strategy_metrics.json",
        "daily_report": run_dir / f"{instance['strategy_id']}_daily_report.md",
    }
    plan.to_csv(artifacts["rebalance_plan"], index=False)
    snapshot.to_csv(artifacts["portfolio_snapshot"], index=False)
    artifacts["strategy_metrics"].write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts["daily_report"].write_text(report, encoding="utf-8")
    return artifacts


def _format_daily_report(metrics: dict[str, Any], plan: pd.DataFrame) -> str:
    symbols = "、".join(plan["name"].tolist()) if not plan.empty else "空仓"
    return "\n".join(
        [
            "# 主线链动因子 V1 日报",
            "",
            f"- 交易日：{metrics['trade_date']}",
            f"- 当前净值：{metrics['nav']:.4f}",
            f"- 当前仓位：{metrics['target_exposure']:.2%}",
            f"- 当日收益：{metrics['daily_return']:.2%}",
            f"- 累计收益：{metrics['cumulative_return']:.2%}",
            f"- 超额收益：{metrics['excess_return']:.2%}",
            f"- 当前回撤：{metrics['current_drawdown']:.2%}",
            f"- 最大回撤：{metrics['max_drawdown']:.2%}",
            f"- 20日波动率：{metrics['volatility_20']:.2%}",
            f"- 风险状态：{metrics['risk_state']}",
            f"- 入选产业链：{metrics['selected_chain'] or '无'}",
            f"- 目标持仓：{symbols}",
            f"- 成交失败次数：{metrics['failed_order_count']}",
        ]
    )


def _risk_state(volatility_20: float, drawdown: float) -> str:
    """按统一日报口径给高波动策略打风险标签。"""
    if volatility_20 >= 0.50 or drawdown <= -0.20:
        return "HIGH_VOL"
    if volatility_20 >= 0.35 or drawdown <= -0.10:
        return "ELEVATED"
    return "NORMAL"


def _record_success(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    run_dir: Path,
    artifacts: dict[str, Path],
    rows: int,
    targets: list[SelectionRecord],
) -> None:
    repository = SystemRepository(paths.system_state_path)
    message = f"native factor chain rotation completed, rows {rows}, selected {len(targets)} symbols"
    repository.record_strategy_run(strategy_id, trade_date, "SUCCESS", run_dir, message)
    repository.record_run_step(strategy_id, trade_date, 1, "load_standard_cache", "SUCCESS", "loaded qfq local cache")
    repository.record_run_step(strategy_id, trade_date, 2, "run_m0_backtest", "SUCCESS", f"rows {rows}")
    repository.record_run_step(strategy_id, trade_date, 3, "write_artifacts", "SUCCESS", "daily outputs generated")
    for report_type, path in artifacts.items():
        repository.upsert_report(report_type, strategy_id, trade_date, report_type, path, tags=["strategy_instance", "mainline"])


def _latest_prices(bars: dict[str, pd.DataFrame]) -> dict[str, float]:
    """提取最新收盘价，保存到实例持仓状态用于前端展示。"""
    result: dict[str, float] = {}
    for symbol, frame in bars.items():
        if frame.empty or "close" not in frame.columns:
            continue
        close = pd.to_numeric(frame["close"].iloc[-1], errors="coerce")
        if not pd.isna(close) and float(close) > 0:
            result[symbol] = float(close)
    return result
