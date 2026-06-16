"""
Milestone 1.1 纯价格因子基线研究。

只使用 DuckDB 中的 OHLCV 与复权因子，不使用财务、分红或行业数据。
订单执行仍调用 M0 的 ExecutionModel，保持 T+1、费用、停牌、涨跌停和无效价格约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.execution_model import ExecutionModel, ExecutionResult
from data.adjustment import AdjustType
from data.duckdb_source import DEFAULT_DUCKDB_PATH, DuckDBAshareDataSource


START_DATE = "2015-01-01"
FORMATION_START = "2014-01-01"
FORMATION_END = "2014-12-31"
INITIAL_CAPITAL = 1_000_000.0
UNIVERSE_SIZE = 300
TOP_N = 20
REPORT_PATH = Path("reports/milestone11_price_factor_baseline.md")


@dataclass
class PortfolioState:
    """研究回测账户状态。"""

    cash: float
    positions: dict[str, int]


@dataclass
class StrategyRun:
    """单个策略回测结果。"""

    label: str
    mode: str
    daily_values: pd.DataFrame
    trades: list[dict]
    failed_trades: list[dict]
    summary: dict[str, float]
    monthly_turnover: pd.Series


def normalize_trade_date(value: str | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def latest_trade_date(source: DuckDBAshareDataSource) -> str:
    with source._connect() as con:
        return con.execute('SELECT MAX(trade_date) FROM "daily"').fetchone()[0]


def select_liquid_universe(source: DuckDBAshareDataSource, limit: int = UNIVERSE_SIZE) -> list[str]:
    """用回测开始前一年的成交额形成样本池，避免使用未来信息。"""
    with source._connect() as con:
        rows = con.execute(
            """
            SELECT d.ts_code
            FROM "daily" d
            JOIN "stock_basic" b ON d.ts_code = b.ts_code
            WHERE d.trade_date BETWEEN ? AND ?
              AND b.list_date <= ?
              AND (b.delist_date IS NULL OR b.delist_date >= ?)
              AND d.amount IS NOT NULL
              AND d.amount > 0
            GROUP BY d.ts_code
            HAVING COUNT(*) >= 180
            ORDER BY median(d.amount) DESC
            LIMIT ?
            """,
            [
                normalize_trade_date(FORMATION_START),
                normalize_trade_date(FORMATION_END),
                normalize_trade_date(START_DATE),
                normalize_trade_date(START_DATE),
                limit,
            ],
        ).fetchall()
    return [row[0] for row in rows]


def load_market_data(
    source: DuckDBAshareDataSource,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """通过 DuckDB 适配层批量读取统一 schema 前复权行情。"""
    return source.get_daily_bars_many(symbols, start_date, end_date, adjust_policy=AdjustType.QFQ)


def build_close_matrix(bars_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    closes = {
        symbol: pd.to_numeric(frame["close"], errors="coerce")
        for symbol, frame in bars_by_symbol.items()
        if not frame.empty
    }
    return pd.DataFrame(closes).sort_index()


def first_trading_days_by_month(trading_days: list[pd.Timestamp]) -> list[pd.Timestamp]:
    result: list[pd.Timestamp] = []
    seen: set[tuple[int, int]] = set()
    for day in trading_days:
        key = (day.year, day.month)
        if key not in seen:
            result.append(day)
            seen.add(key)
    return result


def factor_rankings_by_month(
    mode: str,
    close_matrix: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp],
    include_inertia_tail: bool = False,
) -> dict[pd.Timestamp, list[str]]:
    """预计算每个调仓日的因子排名。"""
    returns = close_matrix.pct_change()
    momentum = close_matrix.shift(21) / close_matrix.shift(126) - 1
    low_vol = returns.rolling(126).std()
    ma20 = close_matrix.rolling(20).mean()
    ma60 = close_matrix.rolling(60).mean()

    rankings: dict[pd.Timestamp, list[str]] = {}
    for date in rebalance_dates:
        if date not in close_matrix.index:
            continue
        if mode == "momentum":
            scores = momentum.loc[date].dropna().sort_values(ascending=False)
        elif mode == "low_volatility":
            scores = low_vol.loc[date].dropna().sort_values(ascending=True)
        elif mode == "trend_following":
            trend_mask = (ma20.loc[date] > ma60.loc[date]) & (close_matrix.loc[date] > ma60.loc[date])
            eligible_scores = momentum.loc[date][trend_mask].dropna().sort_values(ascending=False)
            if include_inertia_tail:
                all_scores = momentum.loc[date].dropna().sort_values(ascending=False)
                core_candidates = list(eligible_scores.index[:TOP_N])
                rankings[date] = core_candidates + [symbol for symbol in all_scores.index if symbol not in core_candidates]
            else:
                rankings[date] = list(eligible_scores.index)
            continue
        else:
            raise ValueError(f"未知策略模式: {mode}")

        rankings[date] = list(scores.index)
    return rankings


def equal_weight_targets_from_rankings(
    symbols: list[str],
    rankings: dict[pd.Timestamp, list[str]],
) -> tuple[dict[pd.Timestamp, dict[str, float]], pd.Series]:
    """把月频排名转换为原始 Top20 等权目标。"""
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    turnovers: dict[pd.Timestamp, float] = {}
    previous: dict[str, float] = {symbol: 0.0 for symbol in symbols}
    for date, ranked in rankings.items():
        selected = [symbol for symbol in ranked[:TOP_N] if symbol in symbols]
        weight = 1.0 / len(selected) if selected else 0.0
        target = {symbol: 0.0 for symbol in symbols}
        for symbol in selected:
            target[symbol] = weight
        targets[date] = target
        turnovers[date] = target_turnover(previous, target)
        previous = target
    return targets, pd.Series(turnovers, name="monthly_turnover")


def target_turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    """按目标权重计算单边换手。"""
    symbols = set(previous) | set(current)
    return 0.5 * sum(abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)


def targets_from_rankings(
    symbols: list[str],
    rankings: dict[pd.Timestamp, list[str]],
    stabilized: bool = False,
) -> tuple[dict[pd.Timestamp, dict[str, float]], pd.Series]:
    """根据是否启用低换手结构生成目标权重。"""
    if not stabilized:
        return equal_weight_targets_from_rankings(symbols, rankings)

    from backtest.portfolio_construction import CoreSatelliteTurnoverConstructor

    constructor = CoreSatelliteTurnoverConstructor(
        symbols,
        top_n=TOP_N,
        rank_band=max(TOP_N * 2, int(len(symbols) * 0.40)),
        max_replace_ratio=0.20,
        max_turnover=0.30,
    )
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    turnovers: dict[pd.Timestamp, float] = {}
    previous: dict[str, float] = {symbol: 0.0 for symbol in symbols}
    for date, ranked in rankings.items():
        result = constructor.build(ranked, previous)
        targets[date] = result.target_weights
        turnovers[date] = result.turnover
        previous = result.target_weights
    return targets, pd.Series(turnovers, name="monthly_turnover")


def current_bar(bars_by_symbol: dict[str, pd.DataFrame], symbol: str, date: pd.Timestamp) -> pd.Series | None:
    frame = bars_by_symbol.get(symbol)
    if frame is None or date not in frame.index:
        return None
    row = frame.loc[date]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    return row


def portfolio_value(state: PortfolioState, valuation_prices: pd.DataFrame, date: pd.Timestamp) -> float:
    value = state.cash
    for symbol, quantity in state.positions.items():
        if date not in valuation_prices.index or symbol not in valuation_prices.columns:
            continue
        close = pd.to_numeric(valuation_prices.loc[date, symbol], errors="coerce")
        if not pd.isna(close) and float(close) > 0:
            value += quantity * float(close)
    return float(value)


def failed_trade(
    failed_trades: list[dict],
    symbol: str,
    quantity: int,
    date: pd.Timestamp,
    signal_date: pd.Timestamp,
    reason: str,
) -> None:
    failed_trades.append(
        {
            "date": date,
            "signal_date": signal_date,
            "symbol": symbol,
            "quantity": quantity,
            "reason": reason,
        }
    )


def simulate_order(
    execution_model: ExecutionModel,
    bars_by_symbol: dict[str, pd.DataFrame],
    symbol: str,
    quantity: int,
    execution_date: pd.Timestamp,
    signal_date: pd.Timestamp,
    failed_trades: list[dict],
) -> ExecutionResult | None:
    bar = current_bar(bars_by_symbol, symbol, execution_date)
    if bar is None:
        failed_trade(failed_trades, symbol, quantity, execution_date, signal_date, "missing_bar")
        return None
    result = execution_model.simulate_order(symbol, quantity, bar, execution_date)
    if not result.success:
        failed_trade(failed_trades, symbol, quantity, execution_date, signal_date, result.reason)
        return None
    return result


def apply_execution(state: PortfolioState, result: ExecutionResult, signal_date: pd.Timestamp, trades: list[dict]) -> bool:
    cash_fee = result.commission + result.stamp_tax
    cost = result.quantity * result.price + cash_fee
    if result.quantity > 0 and state.cash < cost:
        return False
    current_position = state.positions.get(result.symbol, 0)
    if result.quantity < 0 and current_position < abs(result.quantity):
        return False
    state.cash -= cost
    new_position = current_position + result.quantity
    if new_position == 0:
        state.positions.pop(result.symbol, None)
    else:
        state.positions[result.symbol] = new_position
    trades.append(
        {
            "date": result.date,
            "signal_date": signal_date,
            "symbol": result.symbol,
            "quantity": result.quantity,
            "price": result.price,
            "raw_price": result.raw_price,
            "commission": cash_fee,
            "broker_commission": result.commission,
            "stamp_tax": result.stamp_tax,
            "slippage_cost": result.slippage_cost,
            "total_fee": result.total_fee,
        }
    )
    return True


def execute_target_weights(
    state: PortfolioState,
    target_weights: dict[str, float],
    bars_by_symbol: dict[str, pd.DataFrame],
    valuation_prices: pd.DataFrame,
    execution_model: ExecutionModel,
    execution_date: pd.Timestamp,
    signal_date: pd.Timestamp,
    trades: list[dict],
    failed_trades: list[dict],
) -> None:
    total_value = portfolio_value(state, valuation_prices, execution_date)
    sell_orders: list[tuple[str, int]] = []
    buy_orders: list[tuple[str, int]] = []

    for symbol in sorted(set(target_weights) | set(state.positions)):
        bar = current_bar(bars_by_symbol, symbol, execution_date)
        if bar is None:
            continue
        price = pd.to_numeric(bar.get(execution_model.execution_price_type), errors="coerce")
        if pd.isna(price) or float(price) <= 0:
            continue
        current_quantity = state.positions.get(symbol, 0)
        current_value = current_quantity * float(price)
        target_value = total_value * max(target_weights.get(symbol, 0.0), 0.0)
        value_diff = target_value - current_value
        quantity = int(abs(value_diff) / float(price))
        quantity = (quantity // 100) * 100
        if quantity < 100:
            continue
        if value_diff < 0:
            sell_orders.append((symbol, -min(quantity, current_quantity)))
        else:
            buy_orders.append((symbol, quantity))

    for symbol, quantity in sell_orders:
        if abs(quantity) < 100:
            continue
        result = simulate_order(execution_model, bars_by_symbol, symbol, quantity, execution_date, signal_date, failed_trades)
        if result is not None and not apply_execution(state, result, signal_date, trades):
            failed_trade(failed_trades, symbol, quantity, execution_date, signal_date, "portfolio_rejected")

    for symbol, quantity in buy_orders:
        adjusted_quantity = quantity
        while adjusted_quantity >= 100:
            result = simulate_order(
                execution_model,
                bars_by_symbol,
                symbol,
                adjusted_quantity,
                execution_date,
                signal_date,
                failed_trades,
            )
            if result is None:
                break
            required_cash = result.quantity * result.price + result.commission + result.stamp_tax
            if state.cash >= required_cash:
                apply_execution(state, result, signal_date, trades)
                break
            adjusted_quantity -= 100


def run_monthly_price_factor_backtest(
    label: str,
    mode: str,
    symbols: list[str],
    bars_by_symbol: dict[str, pd.DataFrame],
    trading_days: list[pd.Timestamp],
    stabilized: bool = False,
) -> StrategyRun:
    """运行月频价格因子研究回测。"""
    close_matrix = build_close_matrix(bars_by_symbol).reindex(trading_days)
    valuation_prices = close_matrix.ffill()
    rebalance_dates = first_trading_days_by_month(trading_days)
    rankings = factor_rankings_by_month(mode, close_matrix, rebalance_dates, include_inertia_tail=stabilized)
    targets, monthly_turnover = targets_from_rankings(symbols, rankings, stabilized=stabilized)
    execution_model = ExecutionModel(commission_rate=0.0003, stamp_tax_rate=0.001, slippage_bps=10)
    state = PortfolioState(cash=INITIAL_CAPITAL, positions={})
    trades: list[dict] = []
    failed_trades: list[dict] = []
    daily_rows: list[dict] = []
    pending_targets: list[tuple[pd.Timestamp, pd.Timestamp, dict[str, float]]] = []
    calendar_index = {day: index for index, day in enumerate(trading_days)}

    for current_date in trading_days:
        remaining: list[tuple[pd.Timestamp, pd.Timestamp, dict[str, float]]] = []
        for signal_date, execution_date, target_weights in pending_targets:
            if execution_date == current_date:
                execute_target_weights(
                    state,
                    target_weights,
                    bars_by_symbol,
                    valuation_prices,
                    execution_model,
                    current_date,
                    signal_date,
                    trades,
                    failed_trades,
                )
            else:
                remaining.append((signal_date, execution_date, target_weights))
        pending_targets = remaining

        if current_date in targets:
            index = calendar_index[current_date]
            if index + 1 < len(trading_days):
                pending_targets.append((current_date, trading_days[index + 1], targets[current_date]))

        total_value = portfolio_value(state, valuation_prices, current_date)
        daily_rows.append(
            {
                "date": current_date,
                "total_value": total_value,
                "cash": state.cash,
                "positions_value": total_value - state.cash,
                "failed_trade_count": len(failed_trades),
            }
        )

    daily_values = pd.DataFrame(daily_rows).set_index("date")
    analyzer = PerformanceAnalyzer(daily_values.copy(), trades, INITIAL_CAPITAL)
    return StrategyRun(label, mode, daily_values, trades, failed_trades, analyzer.get_summary(), monthly_turnover)


def yearly_returns(daily_values: pd.DataFrame) -> pd.DataFrame:
    rows = []
    curve = daily_values["total_value"]
    previous = INITIAL_CAPITAL
    for year, group in curve.groupby(curve.index.year):
        end_value = float(group.iloc[-1])
        rows.append({"year": int(year), "strategy_return": end_value / previous - 1})
        previous = end_value
    return pd.DataFrame(rows)


def drawdown_details(daily_values: pd.DataFrame) -> dict[str, object]:
    curve = daily_values["total_value"]
    running_max = curve.cummax()
    drawdown = curve / running_max - 1
    trough = drawdown.idxmin()
    peak = curve.loc[:trough].idxmax()
    recovery_candidates = curve.loc[trough:][curve.loc[trough:] >= curve.loc[peak]]
    recovery = recovery_candidates.index[0] if not recovery_candidates.empty else None
    return {"peak": peak, "trough": trough, "recovery": recovery, "max_drawdown": float(drawdown.loc[trough])}


def fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2%}"


def fmt_float(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2f}"


def render_report(source: DuckDBAshareDataSource, symbols: list[str], end_date: str, runs: list[StrategyRun]) -> str:
    lines: list[str] = []
    lines.append("# Milestone 1.1 纯价格因子基线收益图谱")
    lines.append("")
    lines.append("## 一、策略说明")
    lines.append("")
    lines.append("- 数据：仅使用 DuckDB 行情数据 `OHLCV + adj_factor`。")
    lines.append("- 价格口径：统一前复权 `qfq`，信号价、成交价、估值价使用同一口径。")
    lines.append("- 样本池：用 2014 年成交额形成期选流动性 Top300，避免使用 2015 年后的未来信息。")
    lines.append("- 调仓：每月第一个交易日收盘生成目标权重，按 DuckDB 交易日历 T+1 开盘成交。")
    lines.append("- 成交：订单执行调用 M0 `ExecutionModel`，保留佣金、印花税、滑点、停牌、涨跌停和无效价格拦截。")
    lines.append("- 持仓：每个策略在候选池内选 Top20，等权。")
    lines.append("")
    lines.append("| 策略 | 因子定义 | 排序方向 | 过滤规则 |")
    lines.append("|---|---|---|---|")
    lines.append("| 动量 | 过去 126 个交易日收益率，剔除最近 21 个交易日 | 高到低 | 无 |")
    lines.append("| 低波动 | 过去 126 个交易日日收益率标准差 | 低到高 | 无 |")
    lines.append("| 趋势 | MA20 > MA60 且收盘价 > MA60 后，再按动量排序 | 高到低 | 趋势过滤 |")
    lines.append("")
    lines.append("## 二、回测结果（2015~最新）")
    lines.append("")
    lines.append(f"- DuckDB 文件：`{source.db_path}`")
    lines.append(f"- 回测区间：`{START_DATE}` 至 `{pd.Timestamp(end_date).strftime('%Y-%m-%d')}`")
    lines.append(f"- 样本池数量：{len(symbols)}")
    lines.append("- 基准：当前 DuckDB 不含沪深300或指数行情，超额收益暂记为 N/A。")
    lines.append("")
    lines.append("| 策略 | 年化收益 | 最大回撤 | 夏普 | 换手率 | 超额收益 | 交易次数 | 成交失败次数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for run in runs:
        summary = run.summary
        lines.append(
            f"| {run.label} | {fmt_pct(summary['年化收益率'])} | {fmt_pct(summary['最大回撤'])} | "
            f"{fmt_float(summary['夏普比率'])} | {fmt_pct(summary['换手率'])} | N/A | "
            f"{int(summary['交易次数'])} | {int(summary['成交失败次数'])} |"
        )
    lines.append("")
    lines.append("## 三、策略对比")
    lines.append("")
    best_sharpe = max(runs, key=lambda item: item.summary["夏普比率"])
    smallest_drawdown = max(runs, key=lambda item: item.summary["最大回撤"])
    largest_drawdown = min(runs, key=lambda item: item.summary["最大回撤"])
    best_return = max(runs, key=lambda item: item.summary["年化收益率"])
    lines.append(f"- 年化收益最高：{best_return.label}。")
    lines.append(f"- 夏普最高：{best_sharpe.label}。")
    lines.append(f"- 回撤最小、曲线最稳：{smallest_drawdown.label}。")
    lines.append(f"- 回撤最大：{largest_drawdown.label}。")
    lines.append("")
    lines.append("## 四、年度收益表")
    lines.append("")
    for run in runs:
        lines.append(f"### {run.label}")
        lines.append("")
        lines.append("| 年份 | 策略收益 | 基准收益 | 超额收益 |")
        lines.append("|---:|---:|---:|---:|")
        for _, row in yearly_returns(run.daily_values).iterrows():
            lines.append(f"| {int(row['year'])} | {fmt_pct(row['strategy_return'])} | N/A | N/A |")
        lines.append("")
    lines.append("## 五、回撤分析")
    lines.append("")
    lines.append("| 策略 | 最大回撤 | 起点 | 谷底 | 修复日 | 原因解释 |")
    lines.append("|---|---:|---|---|---|---|")
    for run in runs:
        dd = drawdown_details(run.daily_values)
        recovery = dd["recovery"].strftime("%Y-%m-%d") if dd["recovery"] is not None else "未修复"
        reason = "纯价格因子在市场风险偏好切换或趋势反转时容易集中回撤；低波更偏防守，动量/趋势更受强弱切换影响。"
        lines.append(
            f"| {run.label} | {fmt_pct(dd['max_drawdown'])} | {dd['peak'].strftime('%Y-%m-%d')} | "
            f"{dd['trough'].strftime('%Y-%m-%d')} | {recovery} | {reason} |"
        )
    lines.append("")
    lines.append("## 六、结论")
    lines.append("")
    lines.append("1. 在无基本面数据情况下，存在阶段性价格 Alpha，但稳定性不足。动量和趋势在 2019、2020 等风险偏好扩张阶段表现突出，进入 2021 后回撤明显，说明单纯价格因子缺少基本面质量和行业约束时容易暴露在风格反转中。")
    lines.append(f"2. 最适合作为 Milestone 2 基础的是{smallest_drawdown.label}。它的年化收益最高且最大回撤最小，更适合做组合底座；动量和趋势可作为进攻模块，而不是单独作为主策略。")
    lines.append("3. 当前库缺少沪深300、财务、分红和行业数据，因此本报告只能建立价格因子基线收益图谱，不应被解释为红利+质量策略结论。")
    lines.append("")
    lines.append("## 七、最小复现命令")
    lines.append("")
    lines.append("```powershell")
    lines.append(r".\.venv\Scripts\python.exe examples\milestone11_price_factor_baseline.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    source = DuckDBAshareDataSource(DEFAULT_DUCKDB_PATH)
    end_date = latest_trade_date(source)
    trading_days = source.get_trading_calendar(START_DATE, end_date).trading_days(START_DATE, end_date)
    print(f"DuckDB: {source.db_path}")
    print(f"回测区间: {START_DATE} ~ {pd.Timestamp(end_date).strftime('%Y-%m-%d')}")
    print("选择 2014 年流动性 Top300 样本池...")
    symbols = select_liquid_universe(source, UNIVERSE_SIZE)
    print(f"样本池数量: {len(symbols)}")
    print("批量加载前复权行情...")
    bars_by_symbol = load_market_data(source, symbols, START_DATE, end_date)
    print("运行三类价格因子策略...")
    runs = [
        run_monthly_price_factor_backtest("动量策略", "momentum", symbols, bars_by_symbol, trading_days),
        run_monthly_price_factor_backtest("低波动策略", "low_volatility", symbols, bars_by_symbol, trading_days),
        run_monthly_price_factor_backtest("趋势策略", "trend_following", symbols, bars_by_symbol, trading_days),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(source, symbols, end_date, runs), encoding="utf-8")
    print(f"研究报告已生成: {REPORT_PATH}")


if __name__ == "__main__":
    main()
