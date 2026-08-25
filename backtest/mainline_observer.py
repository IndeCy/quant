"""
主线链动策略盘后观察模块

职责：
- 读取模拟盘账户与持仓
- 尝试补齐最新行情缓存，失败时自动回退本地缓存
- 计算账户收盘后净值、单票盈亏、上证指数表现
- 评估当前最强产业链，以及 B 策略是否需要下一交易日调仓
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

import pandas as pd

from backtest.cache import DEFAULT_CACHE_PATH, MarketDataCache
from backtest.chain_selection import ChainDefinition, ChainStockSelectionStrategy
from backtest.notifier import NotificationMessage, build_notifier
from backtest.paper_trading import DEFAULT_PAPER_TRADING_PATH, PaperTradingStore
from examples.compare_chain_stock_selection import (
    ADJUST as STOCK_ADJUST,
    FREQUENCY as STOCK_FREQUENCY,
    TENCENT_PROVIDER as STOCK_PROVIDER,
    build_default_chain_definitions,
    fetch_tencent_stock_klines,
)
from examples.shanghai_index_ma_backtest import (
    ADJUST as INDEX_ADJUST,
    FREQUENCY as INDEX_FREQUENCY,
    SYMBOL as BENCHMARK_SYMBOL,
    TENCENT_PROVIDER as INDEX_PROVIDER,
    fetch_tencent_index_klines,
)


WARMUP_DAYS = 200
MAINLINE_EFFECTIVE_RETURN_BASE = 1_000_000.0
MAINLINE_STORED_INITIAL_CASH = 1_001_437.0


@dataclass(frozen=True)
class PositionObservation:
    """单只持仓的盘后估值。"""

    symbol: str
    symbol_name: str
    quantity: int
    close_price: float
    market_value: float
    cost_amount: float
    cash_dividend: float
    pnl_amount: float
    pnl_ratio: float


@dataclass(frozen=True)
class MarketSnapshot:
    """盘后行情截面。"""

    trade_date: date
    stock_bars: Dict[str, pd.DataFrame]
    benchmark_bars: pd.DataFrame
    refresh_notes: List[str]
    valuation_bars: Dict[str, pd.DataFrame] | None = None


@dataclass(frozen=True)
class ObservationResult:
    """主线链动策略盘后观察结果。"""

    requested_date: date
    trade_date: date
    total_value: float
    cash: float
    position_value: float
    strategy_return: float
    benchmark_change: float
    benchmark_return: float
    strongest_chain: str
    strongest_chain_score: float
    rebalance_signal: str
    target_symbols: List[str]
    current_symbols: List[str]
    positions: List[PositionObservation]
    refresh_notes: List[str]
    summary_text: str


MarketLoader = Callable[[Sequence[str], date, date, Path | str], MarketSnapshot]


def _parse_date(value: date | str | None) -> date:
    """把外部日期参数统一解析成 date。"""
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _format_pct(value: float) -> str:
    """格式化百分比，统一带正负号。"""
    return f"{value:+.2%}"


def _format_wan(value: float) -> str:
    """金额统一转为万元，便于手机查看。"""
    return f"{value / 10000:.2f}万"


def _resolve_return_base(account: dict) -> float:
    """解析盘后观察使用的收益率基数。"""
    initial_cash = float(account["initial_cash"])
    # 主线链动账户在券商软件里的“总盈亏”口径按 100 万初始本金展示，
    # 但本地 SQLite 中落成了 100.1437 万，这里统一按券商口径纠偏，
    # 这样盘后观察的总收益率才能和真实持仓页面对齐。
    if (
        str(account.get("strategy_code", "")) == "Mainline_Chain_Momentum"
        and abs(initial_cash - MAINLINE_STORED_INITIAL_CASH) < 1e-6
    ):
        return MAINLINE_EFFECTIVE_RETURN_BASE
    return initial_cash


def _build_b_strategy(chains: List[ChainDefinition]) -> ChainStockSelectionStrategy:
    """构建与 ABC 对比工具一致的 B 策略参数。"""
    return ChainStockSelectionStrategy(
        chains=chains,
        mode="multi_chain",
        top_n=5,
        rebalance_frequency=5,
        momentum_windows=[60, 120],
        chain_momentum_window=60,
        chain_gate_symbol="市场基线",
    )


def _load_cached_stock_bars(
    cache: MarketDataCache,
    symbol: str,
    fetch_start: date,
    fetch_end: date,
    adjust: str = STOCK_ADJUST,
) -> pd.DataFrame:
    """从本地缓存读取个股/ETF 日线。"""
    return cache.read_bars(
        provider=STOCK_PROVIDER,
        symbol=symbol,
        frequency=STOCK_FREQUENCY,
        adjust=adjust,
        start_date=fetch_start,
        end_date=fetch_end,
    )


def _load_cached_index_bars(
    cache: MarketDataCache,
    symbol: str,
    fetch_start: date,
    fetch_end: date,
) -> pd.DataFrame:
    """从本地缓存读取上证指数日线。"""
    return cache.read_bars(
        provider=INDEX_PROVIDER,
        symbol=symbol,
        frequency=INDEX_FREQUENCY,
        adjust=INDEX_ADJUST,
        start_date=fetch_start,
        end_date=fetch_end,
    )


def load_market_snapshot(
    symbols: Sequence[str],
    fetch_start: date,
    fetch_end: date,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
) -> MarketSnapshot:
    """优先尝试刷新行情，失败后回退到本地缓存。"""
    notes: List[str] = []
    stock_bars: Dict[str, pd.DataFrame] = {}
    valuation_bars: Dict[str, pd.DataFrame] = {}
    cache = MarketDataCache(cache_path)
    try:
        for symbol in symbols:
            try:
                stock_bars[symbol] = fetch_tencent_stock_klines(
                    symbol,
                    fetch_start,
                    fetch_end,
                    adjust=STOCK_ADJUST,
                    cache_path=cache_path,
                )
            except Exception as exc:
                cached = _load_cached_stock_bars(cache, symbol, fetch_start, fetch_end, adjust=STOCK_ADJUST)
                if cached.empty:
                    raise RuntimeError(f"{symbol} 无法刷新且本地缓存为空") from exc
                stock_bars[symbol] = cached
                notes.append(f"{symbol} 行情刷新失败，回退缓存: {exc}")

            # 真实持仓估值必须使用不复权价格，才能和券商软件的市值、盈亏口径一致。
            try:
                valuation_bars[symbol] = fetch_tencent_stock_klines(
                    symbol,
                    fetch_start,
                    fetch_end,
                    adjust="none",
                    cache_path=cache_path,
                )
            except Exception as exc:
                cached = _load_cached_stock_bars(cache, symbol, fetch_start, fetch_end, adjust="none")
                if cached.empty:
                    valuation_bars[symbol] = stock_bars[symbol]
                    notes.append(f"{symbol} 不复权行情缺失，估值回退前复权: {exc}")
                else:
                    valuation_bars[symbol] = cached
                    notes.append(f"{symbol} 不复权行情刷新失败，估值回退缓存: {exc}")

        try:
            benchmark_bars = fetch_tencent_index_klines(
                BENCHMARK_SYMBOL,
                fetch_start=fetch_start,
                fetch_end=fetch_end,
                cache_path=cache_path,
            )
        except Exception as exc:
            benchmark_bars = _load_cached_index_bars(cache, BENCHMARK_SYMBOL, fetch_start, fetch_end)
            if benchmark_bars.empty:
                raise RuntimeError("上证指数无法刷新且本地缓存为空") from exc
            notes.append(f"{BENCHMARK_SYMBOL} 行情刷新失败，回退缓存: {exc}")
    finally:
        cache.close()

    latest_dates = [pd.Timestamp(df.index.max()).date() for df in stock_bars.values() if not df.empty]
    latest_dates.extend(pd.Timestamp(df.index.max()).date() for df in valuation_bars.values() if not df.empty)
    latest_dates.append(pd.Timestamp(benchmark_bars.index.max()).date())
    trade_date = min(latest_dates)
    return MarketSnapshot(
        trade_date=trade_date,
        stock_bars=stock_bars,
        valuation_bars=valuation_bars,
        benchmark_bars=benchmark_bars,
        refresh_notes=notes,
    )


def _slice_to_date(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """把行情截断到指定收盘日。"""
    result = df[df.index.date <= trade_date].copy()
    if result.empty:
        raise ValueError(f"行情在 {trade_date} 前为空")
    return result


def _momentum(df: pd.DataFrame, window: int) -> float | None:
    """计算固定窗口收益率。"""
    if len(df) < window + 1:
        return None
    past_close = float(df["close"].iloc[-(window + 1)])
    if past_close == 0:
        return None
    return float(df["close"].iloc[-1]) / past_close - 1


def _chain_score(
    chain: ChainDefinition,
    stock_bars: Dict[str, pd.DataFrame],
    chain_window: int,
    trade_date: date,
) -> float | None:
    """按代理标的的中期动量评估产业链强度。"""
    proxy_bars = stock_bars.get(chain.proxy_symbol)
    if proxy_bars is None:
        return None
    return _momentum(_slice_to_date(proxy_bars, trade_date), chain_window)


def _benchmark_change(benchmark_bars: pd.DataFrame, trade_date: date) -> float:
    """计算上证指数当日涨跌幅。"""
    sliced = _slice_to_date(benchmark_bars, trade_date)
    if len(sliced) < 2:
        return 0.0
    prev_close = float(sliced["close"].iloc[-2])
    if prev_close == 0:
        return 0.0
    return float(sliced["close"].iloc[-1]) / prev_close - 1


def _benchmark_total_return(benchmark_bars: pd.DataFrame, start_date: date, trade_date: date) -> float:
    """计算策略起始日至观察日的上证指数区间收益。"""
    sliced = benchmark_bars[
        (benchmark_bars.index.date >= start_date) & (benchmark_bars.index.date <= trade_date)
    ].copy()
    if sliced.empty:
        return 0.0
    start_close = float(sliced["close"].iloc[0])
    if start_close == 0:
        return 0.0
    return float(sliced["close"].iloc[-1]) / start_close - 1


def _simulate_b_signal(
    chains: List[ChainDefinition],
    stock_bars: Dict[str, pd.DataFrame],
    benchmark_bars: pd.DataFrame,
    trade_date: date,
) -> List[str]:
    """把 B 策略从历史起点滚动到观察日，判断当日是否触发新调仓目标。"""
    strategy = _build_b_strategy(chains)
    signal_today: Dict[str, float] = {}
    available_dates = [index for index in benchmark_bars.index if index.date() <= trade_date]
    for current_ts in available_dates:
        current_date = current_ts.date()
        current_data = {
            symbol: _slice_to_date(bars, current_date)
            for symbol, bars in stock_bars.items()
            if not bars[bars.index.date <= current_date].empty
        }
        current_data["市场基线"] = _slice_to_date(benchmark_bars, current_date)
        signal = strategy.generate_signals(current_data, current_ts.to_pydatetime())
        if current_date == trade_date:
            signal_today = signal
    return sorted(symbol for symbol, weight in signal_today.items() if weight > 0)


def _build_position_observations(
    positions: Iterable[dict],
    stock_bars: Dict[str, pd.DataFrame],
    valuation_bars: Dict[str, pd.DataFrame] | None,
    corporate_cash: Dict[str, float],
    trade_date: date,
) -> List[PositionObservation]:
    """将数据库持仓转换成带估值和盈亏的观察对象。"""
    result: List[PositionObservation] = []
    price_bars = valuation_bars or stock_bars
    for position in positions:
        symbol = str(position["symbol"])
        bars = _slice_to_date(price_bars[symbol], trade_date)
        close_price = float(bars["close"].iloc[-1])
        quantity = int(position["quantity"])
        cost_amount = float(position["cost_amount"])
        market_value = close_price * quantity
        cash_dividend = float(corporate_cash.get(symbol, 0.0))
        pnl_amount = market_value + cash_dividend - cost_amount
        pnl_ratio = pnl_amount / cost_amount if cost_amount else 0.0
        result.append(
            PositionObservation(
                symbol=symbol,
                symbol_name=str(position["symbol_name"]),
                quantity=quantity,
                close_price=close_price,
                market_value=market_value,
                cost_amount=cost_amount,
                cash_dividend=cash_dividend,
                pnl_amount=pnl_amount,
                pnl_ratio=pnl_ratio,
            )
        )
    return sorted(result, key=lambda item: item.pnl_amount, reverse=True)


def _build_summary_text(result: ObservationResult) -> str:
    """生成适合命令行和 Bark 的盘后观察文本。"""
    lines = [
        f"主线链动策略盘后观察",
        f"请求日期: {result.requested_date.isoformat()}",
        f"统计收盘: {result.trade_date.isoformat()}",
        f"账户1 总资产 {_format_wan(result.total_value)} 持仓 {_format_wan(result.position_value)} 现金 {_format_wan(result.cash)}",
        f"总收益率 {_format_pct(result.strategy_return)} 上证指数当日 {_format_pct(result.benchmark_change)}",
        f"当前最强产业链: {result.strongest_chain} ({_format_pct(result.strongest_chain_score)})",
        "单票盈亏:",
    ]
    for item in result.positions:
        lines.append(
            f"- {item.symbol_name} {item.symbol} "
            f"收盘 {item.close_price:.2f} 盈亏 {_format_pct(item.pnl_ratio)} "
            f"({item.pnl_amount:+.0f})"
        )
    if result.refresh_notes:
        lines.append("行情说明:")
        lines.append(f"- 外部行情刷新失败，当前使用本地缓存截至 {result.trade_date.isoformat()}")
    if result.rebalance_signal == "SWITCH":
        lines.append("明日预案:")
        lines.append(f"- B策略目标持仓: {', '.join(result.target_symbols)}")
        lines.append(f"- 当前持仓: {', '.join(result.current_symbols)}")
    else:
        lines.append("B策略: 今日未产生明日调仓信号")
    return "\n".join(lines)


def observe_account(
    account_id: int,
    requested_date: date | str | None = None,
    db_path: Path | str = DEFAULT_PAPER_TRADING_PATH,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    market_loader: MarketLoader | None = None,
    chains: List[ChainDefinition] | None = None,
) -> ObservationResult:
    """读取账户 1 持仓并生成盘后观察结果。"""
    observe_date = _parse_date(requested_date)
    store = PaperTradingStore(db_path)
    try:
        account = store.get_account(account_id)
        positions = store.list_positions(account_id)
        if not positions:
            raise ValueError(f"账户 {account_id} 当前无持仓，无法生成盘后观察")

        chain_list = chains or build_default_chain_definitions()
        symbols = sorted(
            {
                position["symbol"] for position in positions
            } | {
                chain.proxy_symbol for chain in chain_list
            } | {
                stock.symbol for chain in chain_list for stock in chain.stocks
            }
        )
        fetch_start = _parse_date(account["start_date"]) - timedelta(days=WARMUP_DAYS)
        loader = market_loader or load_market_snapshot
        snapshot = loader(symbols, fetch_start, observe_date, cache_path)

        trade_date = snapshot.trade_date
        corporate_cash = store.get_corporate_action_cash_by_symbol(account_id, trade_date.isoformat())
        position_views = _build_position_observations(
            positions,
            snapshot.stock_bars,
            snapshot.valuation_bars,
            corporate_cash,
            trade_date,
        )
        position_value = sum(item.market_value for item in position_views)
        cash = float(account["cash"])
        total_value = cash + position_value
        return_base = _resolve_return_base(account)
        strategy_return = total_value / return_base - 1 if return_base else 0.0
        benchmark_change = _benchmark_change(snapshot.benchmark_bars, trade_date)
        benchmark_return = _benchmark_total_return(
            snapshot.benchmark_bars,
            _parse_date(account["start_date"]),
            trade_date,
        )

        strategy = _build_b_strategy(chain_list)
        chain_scores = [
            (chain.name, score) for chain in chain_list
            if (score := _chain_score(chain, snapshot.stock_bars, strategy.chain_momentum_window, trade_date)) is not None
        ]
        strongest_chain, strongest_chain_score = max(chain_scores, key=lambda item: item[1])
        current_symbols = sorted(str(position["symbol"]) for position in positions)
        target_symbols = _simulate_b_signal(chain_list, snapshot.stock_bars, snapshot.benchmark_bars, trade_date)
        rebalance_signal = "SWITCH" if target_symbols and set(target_symbols) != set(current_symbols) else "NONE"

        result = ObservationResult(
            requested_date=observe_date,
            trade_date=trade_date,
            total_value=total_value,
            cash=cash,
            position_value=position_value,
            strategy_return=strategy_return,
            benchmark_change=benchmark_change,
            benchmark_return=benchmark_return,
            strongest_chain=strongest_chain,
            strongest_chain_score=strongest_chain_score,
            rebalance_signal=rebalance_signal,
            target_symbols=target_symbols,
            current_symbols=current_symbols,
            positions=position_views,
            refresh_notes=snapshot.refresh_notes,
            summary_text="",
        )
        summary_text = _build_summary_text(result)
        final_result = ObservationResult(**{**result.__dict__, "summary_text": summary_text})

        store.record_daily_snapshot(
            account_id=account_id,
            trade_date=trade_date.isoformat(),
            total_value=total_value,
            cash=cash,
            position_value=position_value,
            strategy_return=strategy_return,
            benchmark_return=benchmark_return,
            excess_return=strategy_return - benchmark_return,
            strongest_chain=strongest_chain,
            rebalance_signal=rebalance_signal,
            target_symbols=target_symbols,
        )
        return final_result
    finally:
        store.close()


def push_observation(result: ObservationResult, bark_url: str) -> None:
    """将盘后观察发送到 Bark。"""
    notifier = build_notifier("bark", bark_url)
    notifier.send(NotificationMessage(title="主线链动策略盘后观察", body=result.summary_text))
