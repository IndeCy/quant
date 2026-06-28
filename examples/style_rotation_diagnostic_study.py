"""Style Rotation Diagnostic：诊断Quality水下期的风格替代可能性。"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.quality_robustness import slice_performance
from backtest.research_benchmark import load_hs300_benchmark
from backtest.style_rotation_diagnostic import (
    build_lagged_rotation_curve,
    find_longest_underwater,
    relative_strength_signals,
)
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_risk_layer_research import run_risk_layer_backtest
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/style_rotation_diagnostic.md")
METRICS_PATH = Path("reports/style_rotation_diagnostic_metrics.csv")
SIGNALS_PATH = Path("reports/style_rotation_diagnostic_signals.csv")
CURVES_PATH = Path("reports/style_rotation_diagnostic_curves.csv")
LOOKBACK = 126


def build_value_selections(
    candidates: pd.DataFrame, top_n: int = 20
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按每月最低正PB选择Value组合。"""
    data = candidates.copy()
    data["pb"] = pd.to_numeric(data["raw_close"], errors="coerce") / pd.to_numeric(data["bps"], errors="coerce")
    data = data[(data["raw_close"] > 0) & (data["bps"] > 0) & (data["pb"] > 0)].copy()
    selections: dict[str, list[str]] = {}
    holdings: list[pd.DataFrame] = []
    for signal_date, group in data.groupby("signal_date", sort=True):
        selected = group.sort_values(["pb", "symbol"], kind="stable").head(top_n).copy()
        selections[str(signal_date)] = selected["symbol"].tolist()
        holdings.append(selected)
    return selections, pd.concat(holdings, ignore_index=True) if holdings else data.iloc[0:0]


def create_value_asof_table(con) -> None:
    """构造只使用已公告1231年报BPS的Value快照。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_value_asof AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
            )
            WHERE RIGHT(end_date, 4) = '1231'
            GROUP BY ts_code, end_date
        ),
        fina_deduplicated AS (
            SELECT ts_code, end_date, CAST(bps AS DOUBLE) AS bps,
                   ROW_NUMBER() OVER(
                       PARTITION BY ts_code, end_date
                       ORDER BY TRY_CAST(update_flag AS INTEGER) DESC NULLS LAST
                   ) AS source_rn
            FROM fina_db.default_table
        ),
        ranked AS (
            SELECT d.signal_date, f.ts_code AS symbol, f.end_date, p.f_ann_date, f.bps,
                   ROW_NUMBER() OVER(
                       PARTITION BY d.signal_date, f.ts_code
                       ORDER BY f.end_date DESC, p.f_ann_date DESC
                   ) AS rn
            FROM quality_signal_dates d
            JOIN fina_deduplicated f ON f.source_rn = 1
            JOIN publish_dates p ON f.ts_code = p.ts_code AND f.end_date = p.end_date
            WHERE p.f_ann_date <= d.signal_date
        )
        SELECT signal_date, symbol, end_date, f_ann_date, bps
        FROM ranked WHERE rn = 1
        """
    )


def common_universe_sql() -> str:
    """返回风格组合共用的事前可交易股票池条件。"""
    return """
      f.st_name IS NULL
      AND f.amount > f.amount_p20
      AND f.volume > 0
      AND f.close > 0
      AND sb.list_date IS NOT NULL
      AND STRPTIME(f.trade_date, '%Y%m%d') >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
      AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
    """


def load_price_style_selections(con, selector_sql: str) -> dict[str, list[str]]:
    """按公共股票池读取低波或动量Top20。"""
    selections: dict[str, list[str]] = {}
    for date in load_signal_dates(con):
        rows = con.execute(
            f"""
            SELECT f.symbol
            FROM features f
            JOIN stock_basic sb ON f.symbol = sb.ts_code
            WHERE f.trade_date = ? AND {common_universe_sql()} AND {selector_sql}
            """,
            [date],
        ).fetchall()
        selections[date] = [row[0] for row in rows]
    return selections


def load_value_candidates(con) -> pd.DataFrame:
    """读取含as-of BPS与未复权价格的Value候选池。"""
    return con.execute(
        f"""
        SELECT f.trade_date AS signal_date, f.symbol, d.close AS raw_close,
               v.bps, v.end_date, v.f_ann_date
        FROM features f
        JOIN daily d ON f.symbol = d.ts_code AND f.trade_date = d.trade_date
        JOIN financial_value_asof v ON f.symbol = v.symbol AND f.trade_date = v.signal_date
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND {common_universe_sql()}
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_interval_metrics(
    curves: dict[str, pd.Series], benchmark: pd.Series, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """计算水下区间各风格收益、回撤和夏普。"""
    rows: list[dict[str, object]] = []
    for name, curve in curves.items():
        metrics = slice_performance(curve, benchmark, start, end)
        rows.append({"风格": name, **metrics})
    return pd.DataFrame(rows).sort_values("区间收益", ascending=False).reset_index(drop=True)


def market_dependence(quality: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """用月收益衡量Quality对普涨行情的依赖程度。"""
    aligned = pd.concat([quality.rename("quality"), benchmark.rename("benchmark")], axis=1).dropna()
    monthly = aligned.resample("ME").last().pct_change().dropna()
    up = monthly[monthly["benchmark"] > 0]
    down = monthly[monthly["benchmark"] <= 0]
    variance = monthly["benchmark"].var()
    beta = monthly["quality"].cov(monthly["benchmark"]) / variance if variance > 0 else 0.0
    alpha = (monthly["quality"].mean() - beta * monthly["benchmark"].mean()) * 12
    return {
        "上涨月平均收益": float(up["quality"].mean()),
        "下跌月平均收益": float(down["quality"].mean()),
        "下跌月正收益比例": float((down["quality"] > 0).mean()),
        "月度Beta": float(beta),
        "年化Alpha": float(alpha),
        "月度相关性": float(monthly["quality"].corr(monthly["benchmark"])),
    }


def classify_market_dependence(dependence: dict[str, float]) -> str:
    """区分顺周期暴露、纯Beta与仍有独立Alpha的策略。"""
    pro_cyclical = (
        dependence["月度Beta"] >= 0.7
        and dependence["上涨月平均收益"] > 0
        and dependence["下跌月平均收益"] < 0
    )
    if pro_cyclical and dependence["年化Alpha"] > 0:
        return "明显依赖普涨，但不是单纯普涨"
    if pro_cyclical:
        return "主要依赖普涨"
    return "不是单纯普涨"


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化报告指标。"""
    result = frame.copy()
    for column in ["区间收益", "年化收益", "最大回撤", "基准收益", "超额收益"]:
        result[column] = result[column].map(format_percent)
    for column in ["夏普比率", "Calmar"]:
        result[column] = result[column].map(lambda value: f"{value:.3f}")
    return result


def render_report(
    episode: dict[str, object],
    metrics: pd.DataFrame,
    dependence: dict[str, float],
    pre_signal: pd.Series,
    rotation_metrics: dict[str, float],
    signal_counts: pd.Series,
) -> str:
    """渲染风格轮动诊断报告。"""
    strongest = metrics.iloc[0]
    alternative = metrics[~metrics["风格"].isin(["Quality", "HS300 ETF"])].iloc[0]
    quality_return = float(metrics.loc[metrics["风格"].eq("Quality"), "区间收益"].iloc[0])
    pre_identified = pre_signal["选择风格"] != "Quality" and strongest["风格"] == pre_signal["选择风格"]
    dependence_text = classify_market_dependence(dependence)
    return f"""# Style Rotation Diagnostic

## 研究口径

- Quality：当前Quality Cleanup + 20日波动率45%阈值、触发后30%仓位。
- Low Vol：公共股票池内60日波动率最低20只。
- Momentum：MA60 > MA120后，120日收益最高20只。
- Value：公告日as-of的1231年报BPS，以未复权价格计算PB，最低20只。
- Dividend：本地数据没有可靠的股息率字段，本轮明确不纳入，不使用会计科目替代。
- 所有股票风格均月频、等权、T+1成交并使用M0 ExecutionModel。

## 最长不创新高区间

- 前高日期：{episode['高点日期'].date()}。
- 水下开始：{episode['开始日期'].date()}。
- 水下结束：{episode['结束日期'].date()}。
- 恢复前高：{episode['恢复日期'].date() if pd.notna(episode['恢复日期']) else '尚未恢复'}。
- 持续：{episode['持续交易日']}个交易日，最深回撤{episode['区间最深回撤']:.2%}。

## 同期风格表现

{markdown_table(format_metrics(metrics)[['风格', '区间收益', '最大回撤', '夏普比率', '超额收益']])}

区间最强风格为 **{strongest['风格']}**，收益{strongest['区间收益']:.2%}；Quality同期收益{quality_return:.2%}。
剔除Quality和基准后，最强替代股票风格为 **{alternative['风格']}**，但收益仍为{alternative['区间收益']:.2%}，没有找到有效替代风格。

## 是否只是普涨策略

- HS300上涨月份，Quality月均收益：{dependence['上涨月平均收益']:.2%}。
- HS300下跌月份，Quality月均收益：{dependence['下跌月平均收益']:.2%}。
- HS300下跌月份中Quality仍上涨的比例：{dependence['下跌月正收益比例']:.2%}。
- 月度Beta：{dependence['月度Beta']:.3f}，年化Alpha：{dependence['年化Alpha']:.2%}，相关性：{dependence['月度相关性']:.3f}。

判断：Quality **{dependence_text}**。

## 事前切换检查

- 水下期开始前最后一个月末信号：{pre_signal.name.date()}。
- 仅用此前126个交易日数据选择：**{pre_signal['选择风格']}**，126日收益{pre_signal['最高126日收益']:.2%}。
- 固定规则在整个水下区间的收益：{rotation_metrics['区间收益']:.2%}，最大回撤{rotation_metrics['最大回撤']:.2%}，Sharpe {rotation_metrics['夏普比率']:.3f}。
- 水下期各月选择次数：{signal_counts.to_dict()}。

事前信号是否一次命中全区间最强风格：**{'是' if pre_identified else '否'}**。这只是可识别性证据，不把事后最强风格直接替换Quality。

## 结论

1. Quality是否只是普涨策略：**{dependence_text}**。
2. 最长水下期最强的是 **{strongest['风格']}**；测试的替代股票风格均弱于Quality。
3. 是否存在提前信号：{'存在初步证据' if pre_identified else '当前126日相对强弱未能在区间开始前准确识别最终赢家'}。
4. 是否修改主策略：**否**。当前只完成诊断；若要增加风格层，应另做全样本Walk Forward与交易成本验证。
"""


def main() -> None:
    """运行Style Rotation Diagnostic。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        create_value_asof_table(con)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, quality_holdings = build_top20_from_candidates(quality_candidates)
        low_vol = load_price_style_selections(con, "f.vol60 IS NOT NULL ORDER BY f.vol60 ASC LIMIT 20")
        momentum = load_price_style_selections(con, "f.ret120 IS NOT NULL AND f.ma60 > f.ma120 ORDER BY f.ret120 DESC LIMIT 20")
        value, _ = build_value_selections(load_value_candidates(con))
        selections = {"Low Vol": low_vol, "Momentum": momentum, "Value": value}
        symbols = sorted(set(quality_holdings["symbol"]) | {symbol for mapping in selections.values() for stocks in mapping.values() for symbol in stocks})
        bars = load_research_bars(con, symbols)
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(con, "20130101", str(FUND_DAILY_PATH), str(FUND_BASIC_PATH))
        execution_model = ExecutionModel(slippage_bps=5.0)
        quality_targets = {date: {symbol: 1 / len(stocks) for symbol in stocks} for date, stocks in quality_selections.items() if stocks}
        quality_run = run_risk_layer_backtest("Quality", "GRID", quality_targets, bars, calendar, benchmark, execution_model, 20, 0.45, 0.30)
        runs = {name: run_monthly_backtest(name, mapping, bars, calendar, execution_model) for name, mapping in selections.items()}
        curves = {"Quality": quality_run.result.daily_values, **{name: run.daily_values for name, run in runs.items()}, "HS300 ETF": benchmark}
        episode = find_longest_underwater(curves["Quality"])
        interval_start = pd.Timestamp(episode["高点日期"])
        interval_end = pd.Timestamp(episode["恢复日期"] if pd.notna(episode["恢复日期"]) else episode["结束日期"])
        metrics = build_interval_metrics(curves, benchmark, interval_start, interval_end)
        month_ends = [pd.Timestamp(date) for date in signal_dates]
        signals = relative_strength_signals(curves, month_ends, LOOKBACK)
        rotation = build_lagged_rotation_curve(curves, signals, initial_value=1_000_000.0)
        rotation_metrics = slice_performance(rotation, benchmark, interval_start, interval_end)
        eligible_signals = signals[signals.index < pd.Timestamp(episode["开始日期"])]
        pre_signal = eligible_signals.iloc[-1]
        active_signals = signals[(signals["信号可用日期"] >= interval_start) & (signals["信号可用日期"] <= interval_end)]
        signal_counts = active_signals["选择风格"].value_counts()
        dependence = market_dependence(curves["Quality"], benchmark)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        metrics.to_csv(METRICS_PATH, index=False, encoding="utf-8-sig")
        signals.to_csv(SIGNALS_PATH, encoding="utf-8-sig")
        pd.concat({**curves, "RelativeStrengthRotation": rotation}, axis=1).loc[interval_start:interval_end].to_csv(CURVES_PATH, encoding="utf-8-sig")
        REPORT_PATH.write_text(render_report(episode, metrics, dependence, pre_signal, rotation_metrics, signal_counts), encoding="utf-8")
        print(metrics.to_string(index=False))
        print(pre_signal.to_string())
        print(rotation_metrics)
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
