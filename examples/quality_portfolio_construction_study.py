"""
Quality Portfolio Construction Study。

固定 ROE、ROA、OCF 因子，只研究持仓数量、行业上限和权重方式。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    add_industry,
    apply_quality_cleanup_filters,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    START_DATE,
    attach_financial_dbs,
    create_signal_date_table,
    score_quality_frame,
)
from examples.strategy_comparison_research import (
    BacktestResearchResult,
    INITIAL_CASH,
    LOT_SIZE,
    affordable_quantity,
    build_metrics_table,
    create_feature_table,
    format_percent,
    get_bar,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    mark_to_market,
)


REPORT_PATH = Path("reports/quality_portfolio_construction_study.md")


def apply_industry_cap(frame: pd.DataFrame, top_n: int, cap: float = 0.2) -> pd.DataFrame:
    """按质量分数顺序选股，已知行业持仓数量不超过组合的指定比例。"""
    maximum = max(1, int(math.floor(top_n * cap)))
    counts: dict[str, int] = defaultdict(int)
    selected_rows = []
    ordered = frame.sort_values(["quality_score", "symbol"], ascending=[False, True])
    for _, row in ordered.iterrows():
        industry = str(row.get("industry_level1", "未知"))
        # 行业数据未覆盖的股票不共用一个“未知行业”额度，避免人为制造伪行业集中。
        key = industry if industry != "未知" else f"未知:{row['symbol']}"
        if counts[key] >= maximum:
            continue
        selected_rows.append(row)
        counts[key] += 1
        if len(selected_rows) >= top_n:
            break
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def inverse_volatility_weights(frame: pd.DataFrame) -> dict[str, float]:
    """按 60 日波动率倒数分配权重。"""
    valid = frame.dropna(subset=["vol60"]).copy()
    valid = valid[valid["vol60"] > 0]
    if valid.empty:
        return {}
    inverse = 1.0 / valid["vol60"].astype(float)
    normalized = inverse / inverse.sum()
    return dict(zip(valid["symbol"], normalized, strict=False))


def equal_weights(frame: pd.DataFrame) -> dict[str, float]:
    """生成等权目标。"""
    if frame.empty:
        return {}
    weight = 1.0 / len(frame)
    return {symbol: weight for symbol in frame["symbol"]}


def build_variant_weights(candidates: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    """构造所有组合研究变体的月度目标权重。"""
    variants = {
        "Top20等权": {},
        "Top40等权": {},
        "Top60等权": {},
        "Top80等权": {},
        "Top40行业上限20%": {},
        "Top40逆波动率加权": {},
        "Quality+LowVol Top40": {},
    }
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_frame(group)
        date = str(signal_date)
        for top_n in [20, 40, 60, 80]:
            variants[f"Top{top_n}等权"][date] = equal_weights(scored.head(top_n))
        capped = apply_industry_cap(scored, top_n=40, cap=0.2)
        variants["Top40行业上限20%"][date] = equal_weights(capped)
        top40 = scored.head(40)
        variants["Top40逆波动率加权"][date] = inverse_volatility_weights(top40)

        quality_pool = scored.head(80).dropna(subset=["vol60"]).copy()
        quality_pool["quality_rank"] = quality_pool["quality_score"].rank(pct=True)
        quality_pool["low_vol_rank"] = quality_pool["vol60"].rank(pct=True, ascending=False)
        quality_pool["combined_score"] = (quality_pool["quality_rank"] + quality_pool["low_vol_rank"]) / 2
        combined = quality_pool.sort_values(["combined_score", "symbol"], ascending=[False, True]).head(40)
        variants["Quality+LowVol Top40"][date] = equal_weights(combined)
    return variants


def build_target_quantities(
    weights: dict[str, float],
    portfolio_value: float,
    bars: pd.DataFrame,
    date: pd.Timestamp,
) -> dict[str, int]:
    """按目标权重和 A 股 100 股一手生成目标数量。"""
    target = {}
    for symbol, weight in weights.items():
        bar = get_bar(bars, date, symbol)
        if bar is None:
            continue
        price = float(bar["close"])
        quantity = int((portfolio_value * weight / price) // LOT_SIZE) * LOT_SIZE
        if quantity > 0:
            target[symbol] = quantity
    return target


def run_weighted_monthly_backtest(
    name: str,
    target_weights: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    execution_model: ExecutionModel,
) -> BacktestResearchResult:
    """使用 M0 ExecutionModel 执行带目标权重的月频回测。"""
    cash = INITIAL_CASH
    positions: dict[str, int] = {}
    pending: dict[pd.Timestamp, list[tuple[str, int, pd.Timestamp]]] = {}
    daily_values = {}
    trades = []
    failed_orders = []
    total_cost = 0.0
    turnover_notional = 0.0
    signal_dates = {pd.Timestamp(date) for date in target_weights}

    for index, date in enumerate(calendar):
        orders = pending.pop(date, [])
        for symbol, quantity, signal_date in sorted(orders, key=lambda item: item[1] > 0):
            bar = get_bar(bars, date, symbol)
            if bar is None:
                failed_orders.append({"date": date, "symbol": symbol, "reason": "missing_bar"})
                continue
            if quantity > 0:
                quantity = affordable_quantity(cash, quantity, bar, execution_model)
                if quantity <= 0:
                    failed_orders.append({"date": date, "symbol": symbol, "reason": "cash_insufficient"})
                    continue
            result = execution_model.simulate_order(symbol, quantity, bar, date)
            if not result.success:
                failed_orders.append({"date": date, "symbol": symbol, "reason": result.reason})
                continue
            cash -= result.price * result.quantity + result.commission + result.stamp_tax
            positions[symbol] = positions.get(symbol, 0) + result.quantity
            if positions[symbol] == 0:
                positions.pop(symbol)
            total_cost += result.total_fee
            turnover_notional += abs(result.price * result.quantity)
            trades.append({"strategy": name, "signal_date": signal_date, "date": date, "symbol": symbol, "quantity": result.quantity, "price": result.price, "fee": result.total_fee})

        value = cash + mark_to_market(positions, bars, date)
        daily_values[date] = value
        if date in signal_dates and index + 1 < len(calendar):
            weights = target_weights[date.strftime("%Y%m%d")]
            targets = build_target_quantities(weights, value, bars, date)
            symbols = sorted(set(positions) | set(targets))
            pending[calendar[index + 1]] = [
                (symbol, targets.get(symbol, 0) - positions.get(symbol, 0), date)
                for symbol in symbols
                if targets.get(symbol, 0) != positions.get(symbol, 0)
            ]

    return BacktestResearchResult(
        strategy=name,
        daily_values=pd.Series(daily_values).sort_index(),
        trades=trades,
        failed_orders=failed_orders,
        total_cost=total_cost,
        turnover_notional=turnover_notional,
    )


def add_comparison_columns(metrics: pd.DataFrame) -> pd.DataFrame:
    """计算相对 Top20 的收益损失和回撤改善。"""
    result = metrics.copy()
    base = result[result["策略"].eq("Top20等权")].iloc[0]
    result["年化收益损失"] = base["年化收益"] - result["年化收益"]
    result["回撤改善"] = result["最大回撤"] - base["最大回撤"]
    return result


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化研究指标。"""
    formatted = frame.copy()
    columns = ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益", "年化收益损失", "回撤改善"]
    for column in columns:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    return formatted


def render_report(metrics: pd.DataFrame) -> str:
    """渲染组合构建研究报告。"""
    candidates = metrics[(metrics["策略"] != "Top20等权") & (metrics["回撤改善"] > 0)].copy()
    if candidates.empty:
        recommendation = "没有变体同时实现回撤改善；当前组合构建无法解决极端系统性回撤。"
    else:
        candidates["性价比"] = candidates["回撤改善"] / candidates["年化收益损失"].clip(lower=0.001)
        best = candidates.sort_values(["性价比", "回撤改善"], ascending=False).iloc[0]
        recommendation = f"综合收益损失和回撤改善，当前最优是 `{best['策略']}`。"
    return f"""# Quality Portfolio Construction Study

## 对比结果

{markdown_table(format_metrics(metrics))}

## 结论

{recommendation}

本研究固定 ROE、ROA、OCF 和 Cleanup 股票池，只改变持仓数量、行业上限和权重方式。
`Quality+LowVol` 仅把 60 日波动率作为组合构建覆盖层，不改变 Quality 因子定义。
"""


def main() -> None:
    """运行组合构建研究。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = add_industry(apply_quality_cleanup_filters(load_annual_candidates(con)))
        vol = con.execute("SELECT trade_date AS signal_date, symbol, vol60 FROM features WHERE trade_date IN (SELECT signal_date FROM quality_signal_dates)").fetchdf()
        candidates = candidates.merge(vol, on=["signal_date", "symbol"], how="left")
        variants = build_variant_weights(candidates)
        symbols = sorted({symbol for dates in variants.values() for weights in dates.values() for symbol in weights})
        bars = load_research_bars(con, symbols)
        calendar = load_calendar(con)
        execution_model = ExecutionModel(slippage_bps=5.0)
        results = {
            name: run_weighted_monthly_backtest(name, weights, bars, calendar, execution_model)
            for name, weights in variants.items()
        }
        benchmark, _ = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        metrics = add_comparison_columns(build_metrics_table(results, benchmark))
        REPORT_PATH.write_text(render_report(metrics), encoding="utf-8")
        print(metrics.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
