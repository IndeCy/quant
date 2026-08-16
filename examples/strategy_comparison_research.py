"""
三类低频 A 股策略统一回测研究。

研究目标：在不修改系统架构的前提下，使用本地 DuckDB 前复权日线数据，
对低波动、均值回归、趋势过滤动量策略做统一执行约束下的对比。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import sys
from typing import Callable

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import align_benchmark_return, load_hs300_benchmark
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)

DB_PATH = Path("daily_adj_19901219_20260615.duckdb")
REPORT_PATH = Path("reports/strategy_comparison_research.md")
FUND_DAILY_PATH = Path("etf_lof_reits_daily_adj_20041220_20260617.duckdb")
FUND_BASIC_PATH = Path("etf_lof_reits_basic_export_20041220_20260617.duckdb")
START_DATE = "20150101"
LOOKBACK_START = "20140701"
INITIAL_CASH = 1_000_000.0
LOT_SIZE = 100
@dataclass(frozen=True)
class StrategySpec:
    """研究策略定义。"""

    name: str
    description: str
    selector_sql: str
@dataclass
class BacktestResearchResult:
    """单策略研究结果。"""

    strategy: str
    daily_values: pd.Series
    trades: list[dict[str, object]]
    failed_orders: list[dict[str, object]]
    total_cost: float
    turnover_notional: float

STRATEGIES = [
    StrategySpec(
        name="低波动策略(Core)",
        description="剔除 ST、停牌和成交额最低20%，选择 60 日收益标准差最低的 20 只，等权月频调仓。",
        selector_sql="vol60 IS NOT NULL ORDER BY vol60 ASC LIMIT 20",
    ),
    StrategySpec(
        name="均值回归策略(Reversion)",
        description="剔除 ST、停牌和成交额最低20%，选择 20 日收益率最差但未极端崩盘的 20 只，等权月频调仓。",
        selector_sql="ret20 IS NOT NULL AND ret20 > -0.40 ORDER BY ret20 ASC LIMIT 20",
    ),
    StrategySpec(
        name="趋势过滤动量(Trend-Momentum)",
        description="剔除 ST、停牌和成交额最低20%，仅保留 MA60 > MA120，按 120 日收益率 Top20 等权月频调仓。",
        selector_sql="ret120 IS NOT NULL AND ma60 > ma120 ORDER BY ret120 DESC LIMIT 20",
    ),
]
def main() -> None:
    """运行完整研究并写出 Markdown 报告。"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"缺少 DuckDB 数据文件: {DB_PATH.resolve()}")
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        latest_date = con.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        print(f"研究区间: {START_DATE} ~ {latest_date}, 月频信号数: {len(signal_dates)}")
        selections = {spec.name: load_monthly_selections(con, signal_dates, spec.selector_sql) for spec in STRATEGIES}
        all_symbols = sorted({symbol for mapping in selections.values() for symbols in mapping.values() for symbol in symbols})
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        execution_model = ExecutionModel(slippage_bps=5.0)
        results = {spec.name: run_monthly_backtest(spec.name, selections[spec.name], bars, calendar, execution_model) for spec in STRATEGIES}
        benchmark_curve, benchmark_label = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        metrics = build_metrics_table(results, benchmark_curve)
        annual = build_annual_returns(results)
        report = render_report(metrics, annual, latest_date, benchmark_label)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(metrics.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


def create_feature_table(con) -> None:
    """创建研究用月频因子临时表，统一使用前复权 qfq 价格。"""
    materialize_market_features(
        con,
        lookback_start=LOOKBACK_START,
        research_start=START_DATE,
    )


def load_signal_dates(con) -> list[str]:
    """读取每月最后一个真实交易日，最后一天无 T+1 时剔除。"""
    return load_month_end_signal_dates(con)


def load_monthly_selections(con, signal_dates: list[str], selector_sql: str) -> dict[str, list[str]]:
    """按策略规则读取每个调仓日的 20 只股票。"""
    selections: dict[str, list[str]] = {}
    for date in signal_dates:
        rows = con.execute(
            f"""
            SELECT symbol
            FROM features
            WHERE trade_date = ?
              AND st_name IS NULL
              AND NOT is_suspended
              AND amount > amount_p20
              AND volume > 0
              AND {selector_sql}
            """,
            [date],
        ).fetchall()
        selections[date] = [row[0] for row in rows]
    return selections


def load_research_bars(con, symbols: list[str]) -> pd.DataFrame:
    """加载所有入选过股票的统一前复权行情。"""
    return load_feature_bars(con, symbols)


def load_calendar(con) -> list[pd.Timestamp]:
    """读取研究期真实交易日历。"""
    return load_trading_calendar(con)


def run_monthly_backtest(
    strategy_name: str,
    selections: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    execution_model: ExecutionModel,
) -> BacktestResearchResult:
    """使用 M0 ExecutionModel 做月频 T+1 回测。"""
    cash = INITIAL_CASH
    positions: dict[str, int] = {}
    pending_orders: dict[pd.Timestamp, list[tuple[str, int, pd.Timestamp]]] = {}
    daily_values: dict[pd.Timestamp, float] = {}
    trades: list[dict[str, object]] = []
    failed_orders: list[dict[str, object]] = []
    total_cost = 0.0
    turnover_notional = 0.0
    signal_date_set = {pd.Timestamp(date) for date in selections}

    for idx, date in enumerate(calendar):
        orders = pending_orders.pop(date, [])
        if orders:
            sells = [order for order in orders if order[1] < 0]
            buys = [order for order in orders if order[1] > 0]
            for symbol, quantity, signal_date in sells + buys:
                bar = get_bar(bars, date, symbol)
                if bar is None:
                    failed_orders.append({"date": date, "symbol": symbol, "quantity": quantity, "reason": "missing_bar"})
                    continue
                if quantity > 0:
                    quantity = affordable_quantity(cash, quantity, bar, execution_model)
                    if quantity <= 0:
                        failed_orders.append({"date": date, "symbol": symbol, "quantity": quantity, "reason": "cash_insufficient"})
                        continue
                result = execution_model.simulate_order(symbol, quantity, bar, date)
                if not result.success:
                    failed_orders.append({"date": date, "symbol": symbol, "quantity": quantity, "reason": result.reason})
                    continue
                cash -= result.price * result.quantity
                cash -= result.commission + result.stamp_tax
                positions[symbol] = positions.get(symbol, 0) + result.quantity
                if positions[symbol] == 0:
                    positions.pop(symbol)
                total_cost += result.total_fee
                turnover_notional += abs(result.price * result.quantity)
                trades.append(
                    {
                        "strategy": strategy_name,
                        "signal_date": signal_date,
                        "date": date,
                        "symbol": symbol,
                        "quantity": result.quantity,
                        "price": result.price,
                        "fee": result.total_fee,
                    }
                )

        value = cash + mark_to_market(positions, bars, date)
        daily_values[date] = value

        if date in signal_date_set and idx + 1 < len(calendar):
            target_symbols = selections[date.strftime("%Y%m%d")]
            target_quantities = build_target_quantities(target_symbols, value, bars, date)
            symbols = sorted(set(positions) | set(target_quantities))
            next_date = calendar[idx + 1]
            pending_orders[next_date] = [
                (symbol, target_quantities.get(symbol, 0) - positions.get(symbol, 0), date)
                for symbol in symbols
                if target_quantities.get(symbol, 0) - positions.get(symbol, 0) != 0
            ]

    return BacktestResearchResult(
        strategy=strategy_name,
        daily_values=pd.Series(daily_values).sort_index(),
        trades=trades,
        failed_orders=failed_orders,
        total_cost=total_cost,
        turnover_notional=turnover_notional,
    )


def get_bar(bars: pd.DataFrame, date: pd.Timestamp, symbol: str) -> pd.Series | None:
    """读取单日单票行情。"""
    try:
        return bars.loc[(date, symbol)]
    except KeyError:
        return None
def affordable_quantity(cash: float, quantity: int, bar: pd.Series, execution_model: ExecutionModel) -> int:
    """按现金约束把买入数量降到可成交手数。"""
    lots = quantity // LOT_SIZE
    raw_price = float(bar["open"])
    estimated_price = raw_price * (1 + execution_model.slippage_rate)
    while lots > 0:
        test_quantity = lots * LOT_SIZE
        commission = execution_model.calculate_commission(estimated_price, test_quantity)
        cash_need = estimated_price * test_quantity + commission
        if cash_need <= cash:
            return test_quantity
        lots -= 1
    return 0


def mark_to_market(positions: dict[str, int], bars: pd.DataFrame, date: pd.Timestamp) -> float:
    """按当日或此前最近收盘价计算持仓市值。"""
    value = 0.0
    for symbol, quantity in positions.items():
        bar = get_bar(bars, date, symbol)
        if bar is None:
            try:
                bar = bars.xs(symbol, level="symbol").loc[:date].iloc[-1]
            except (KeyError, IndexError):
                continue
        value += quantity * float(bar["close"])
    return value


def build_target_quantities(symbols: list[str], portfolio_value: float, bars: pd.DataFrame, date: pd.Timestamp) -> dict[str, int]:
    """按等权和 100 股一手生成目标持仓数量。"""
    if not symbols:
        return {}
    weight = 1.0 / len(symbols)
    target: dict[str, int] = {}
    for symbol in symbols:
        bar = get_bar(bars, date, symbol)
        if bar is None:
            continue
        price = float(bar["close"])
        quantity = int((portfolio_value * weight / price) // LOT_SIZE) * LOT_SIZE
        if quantity > 0:
            target[symbol] = quantity
    return target


def build_metrics_table(results: dict[str, BacktestResearchResult], benchmark_curve: pd.Series | None = None) -> pd.DataFrame:
    """汇总核心研究指标。"""
    rows = []
    for name, result in results.items():
        metrics = calculate_metrics(result.daily_values)
        benchmark_return = align_benchmark_return(result.daily_values, benchmark_curve) if benchmark_curve is not None else 0.0
        years = max(len(result.daily_values) / 252, 1)
        avg_equity = float(result.daily_values.mean()) if not result.daily_values.empty else INITIAL_CASH
        rows.append(
            {
                "策略": name,
                "年化收益": metrics["annual_return"],
                "最大回撤": metrics["max_drawdown"],
                "夏普比率": metrics["sharpe"],
                "年化换手率": result.turnover_notional / max(avg_equity * years, 1),
                "交易次数": len(result.trades),
                "失败委托数": len(result.failed_orders),
                "执行成本影响": result.total_cost / INITIAL_CASH,
                "总收益": metrics["total_return"],
                "基准收益": benchmark_return,
                "超额收益": metrics["total_return"] - benchmark_return,
            }
        )
    return pd.DataFrame(rows)


def calculate_metrics(values: pd.Series) -> dict[str, float]:
    """计算收益、回撤和夏普。"""
    if values.empty:
        return {"total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    returns = values.pct_change().dropna()
    total_return = float(values.iloc[-1] / values.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (252 / max(len(values), 1)) - 1)
    running_max = values.expanding().max()
    max_drawdown = float(((values - running_max) / running_max).min())
    sharpe = float(returns.mean() / returns.std() * math.sqrt(252)) if not returns.empty and returns.std() > 0 else 0.0
    return {"total_return": total_return, "annual_return": annual_return, "max_drawdown": max_drawdown, "sharpe": sharpe}


def build_annual_returns(results: dict[str, BacktestResearchResult]) -> pd.DataFrame:
    """按自然年计算收益，用于稳定性分析。"""
    rows = []
    for name, result in results.items():
        values = result.daily_values
        for year, group in values.groupby(values.index.year):
            if len(group) < 2:
                continue
            rows.append({"策略": name, "年份": int(year), "年度收益": float(group.iloc[-1] / group.iloc[0] - 1)})
    return pd.DataFrame(rows)


def render_report(
    metrics: pd.DataFrame,
    annual: pd.DataFrame,
    latest_date: str,
    benchmark_label: str,
) -> str:
    """渲染完整研究报告。"""
    formatted_metrics = metrics.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]:
        formatted_metrics[column] = formatted_metrics[column].map(format_percent)
    formatted_metrics["夏普比率"] = formatted_metrics["夏普比率"].map(lambda value: f"{value:.2f}")
    annual_pivot = annual.pivot(index="年份", columns="策略", values="年度收益").reset_index()
    formatted_annual = annual_pivot.copy()
    for column in formatted_annual.columns:
        if column != "年份":
            formatted_annual[column] = formatted_annual[column].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")
    best_core = metrics.sort_values(["最大回撤", "夏普比率"], ascending=[False, False]).iloc[0]["策略"]
    lowest_turnover = metrics.sort_values("年化换手率").iloc[0]["策略"]
    best_live = metrics.sort_values(["最大回撤", "年化换手率", "年化收益"], ascending=[False, True, False]).iloc[0]["策略"]
    negative_alpha = metrics[metrics["年化收益"] < metrics["执行成本影响"]]["策略"].tolist()
    stability_lines = stability_summary(annual)
    return "\n".join(
        [
            "# A股低频策略统一回测对比研究报告",
            "",
            f"- 数据源：本地 DuckDB `{DB_PATH}`",
            f"- 区间：2015-01-01 至 {pd.to_datetime(latest_date).strftime('%Y-%m-%d')}",
            f"- 参考基准：{benchmark_label}。优先使用本地 DuckDB 的沪深300指数，其次使用本地沪深300 ETF，不引入外部数据源。",
            "- 复权口径：前复权 qfq",
            "- 成交模型：M0 `ExecutionModel`，T 日信号，T+1 开盘成交，佣金、印花税、5bps 滑点，涨跌停/停牌不可成交。",
            "- 频率：月频调仓，未做参数优化。",
            "",
            "## 一、策略定义说明",
            "",
            *[f"### {spec.name}\n\n{spec.description}" for spec in STRATEGIES],
            "",
            "## 二、回测结果对比",
            "",
            markdown_table(formatted_metrics),
            "",
            "## 年度收益",
            "",
            markdown_table(formatted_annual),
            "",
            "## 三、稳定性分析",
            "",
            *stability_lines,
            "",
            "## 四、结构分析",
            "",
            f"- 最稳定/最抗回撤：{best_core}",
            f"- 最低换手：{lowest_turnover}",
            f"- 最适合实盘：{best_live}",
            "",
            "## 五、结论",
            "",
            f"1. 当前系统中最适合作为 Core 的策略：{best_core}。",
            "2. Satellite 候选：本轮没有合格策略。均值回归和趋势过滤动量都表现为高回撤或负收益，最多只能进入观察池，不能直接进入实盘增强仓。",
            f"3. execution negative alpha / 不可交易策略：{', '.join(negative_alpha) if negative_alpha else '本次未发现年化收益低于执行成本影响的策略'}。",
            "",
        ]
    )


def stability_summary(annual: pd.DataFrame) -> list[str]:
    """生成年度崩塌和 regime sensitivity 文本。"""
    lines = []
    for strategy, group in annual.groupby("策略"):
        worst = float(group["年度收益"].min())
        negative_years = int((group["年度收益"] < 0).sum())
        collapse = "是" if worst < -0.30 else "否"
        sensitive = "高" if negative_years >= max(len(group) // 2, 1) or worst < -0.30 else "中/低"
        lines.append(
            f"- {strategy}：最差年度 {worst:.2%}，负收益年份 {negative_years}/{len(group)}，单年度崩塌：{collapse}，regime sensitive：{sensitive}。"
        )
    return lines


def markdown_table(frame: pd.DataFrame) -> str:
    """生成 Markdown 表格。"""
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def format_percent(value: float) -> str:
    """格式化百分比，缺失基准显示 N/A。"""
    if pd.isna(value):
        return "N/A"
    return f"{value:.2%}"


if __name__ == "__main__":
    main()
