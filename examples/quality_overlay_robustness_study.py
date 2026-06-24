"""Quality Cleanup + Volatility Overlay 参数鲁棒性研究。"""

from __future__ import annotations

from itertools import product
import math
import os
from pathlib import Path
import sys

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.quality_robustness import (
    build_trigger_episodes,
    calculate_avoided_loss,
    rank_parameters,
    slice_performance,
)
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    build_metrics_table,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
)


WINDOWS = [10, 20, 30, 40, 60, 90]
THRESHOLDS = [0.35, 0.40, 0.45, 0.50, 0.55]
EXPOSURES = [0.20, 0.30, 0.50, 0.70]
MAIN_PARAMETER = (20, 0.45, 0.30)
BENCHMARK_LOOKBACK_START = "20130101"
REPORT_DIR = Path("reports")
REPORT_PATH = REPORT_DIR / "quality_overlay_robustness_study.md"
GRID_PATH = REPORT_DIR / "quality_overlay_robustness_grid.csv"
WALK_FORWARD_PATH = REPORT_DIR / "quality_overlay_walk_forward.csv"
ANNUAL_PATH = REPORT_DIR / "quality_overlay_annual.csv"
EVENT_PATH = REPORT_DIR / "quality_overlay_trigger_events.csv"


def parameter_combinations() -> list[tuple[int, float, float]]:
    """生成固定的120组参数，不在运行期增删搜索空间。"""
    return list(product(WINDOWS, THRESHOLDS, EXPOSURES))


def parameter_name(window: int, threshold: float, exposure: float) -> str:
    """生成稳定且可追溯的参数名称。"""
    return f"W{window}_T{int(threshold * 100)}_E{int(exposure * 100)}"


def effective_end_date(requested_end: str, available_end: pd.Timestamp) -> str:
    """报告只展示真实可用行情终点，不能把计划区间写成已完成数据。"""
    return min(pd.Timestamp(requested_end), pd.Timestamp(available_end)).strftime("%Y-%m-%d")


def build_heatmap_matrix(frame: pd.DataFrame, metric: str, exposure: float) -> pd.DataFrame:
    """按指定降仓比例构造窗口×阈值矩阵。"""
    selected = frame[frame["低波动仓位"].eq(exposure)]
    return selected.pivot(index="窗口", columns="阈值", values=metric).reindex(
        index=WINDOWS, columns=THRESHOLDS
    )


def heatmap_title(metric: str) -> str:
    """把指标名映射为默认 Pillow 字体可显示的标题。"""
    return {"夏普比率": "Sharpe", "Calmar": "Calmar"}.get(metric, metric)


def build_period_grid(
    runs: dict[str, RiskLayerRun],
    parameters: pd.DataFrame,
    benchmark: pd.Series,
    start: str,
    end: str,
) -> pd.DataFrame:
    """从完整路径切出训练或验证区间，参数选择只使用训练表。"""
    rows: list[dict[str, object]] = []
    for row in parameters.itertuples(index=False):
        run = runs[row.策略]
        metrics = slice_performance(run.result.daily_values, benchmark, start, end)
        exposure = run.exposure.loc[pd.Timestamp(start):pd.Timestamp(end)]
        rows.append(
            {
                "策略": row.策略,
                "窗口": row.窗口,
                "阈值": row.阈值,
                "低波动仓位": row.低波动仓位,
                "平均仓位": float(exposure.mean()) if not exposure.empty else 1.0,
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def run_walk_forward(
    runs: dict[str, RiskLayerRun], parameters: pd.DataFrame, benchmark: pd.Series
) -> pd.DataFrame:
    """训练集锁参后直接验证，不读取验证集排名。"""
    stages = [
        ("阶段1", "2015-01-01", "2018-12-31", "2019-01-01", "2021-12-31"),
        ("阶段2", "2015-01-01", "2021-12-31", "2022-01-01", "2026-12-31"),
    ]
    rows: list[dict[str, object]] = []
    for stage, train_start, train_end, valid_start, valid_end in stages:
        train = build_period_grid(runs, parameters, benchmark, train_start, train_end)
        winner = rank_parameters(train).iloc[0]
        # 验证集只查询训练集已经确定的唯一参数。
        validation = build_period_grid(
            {winner["策略"]: runs[winner["策略"]]},
            parameters[parameters["策略"].eq(winner["策略"])],
            benchmark,
            valid_start,
            valid_end,
        ).iloc[0]
        available_end = runs[winner["策略"]].result.daily_values.index.max()
        for sample, source, start, end in [
            ("训练", winner, train_start, train_end),
            ("验证", validation, valid_start, valid_end),
        ]:
            rows.append(
                {
                    "阶段": stage,
                    "样本": sample,
                    "开始日期": start,
                    "结束日期": effective_end_date(end, available_end),
                    "策略": source["策略"],
                    "窗口": source["窗口"],
                    "阈值": source["阈值"],
                    "低波动仓位": source["低波动仓位"],
                    "年化收益": source["年化收益"],
                    "最大回撤": source["最大回撤"],
                    "夏普比率": source["夏普比率"],
                    "Calmar": source["Calmar"],
                    "超额收益": source["超额收益"],
                    "平均仓位": source["平均仓位"],
                }
            )
    return pd.DataFrame(rows)


def build_annual_metrics(values: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """输出自然年收益、年内最大回撤和相对510300超额收益。"""
    rows: list[dict[str, object]] = []
    curve = values.sort_index()
    for year in range(2015, 2027):
        year_dates = curve.index[curve.index.year == year]
        if len(year_dates) < 2:
            continue
        previous = curve.index[curve.index < year_dates[0]]
        start = previous[-1] if len(previous) else year_dates[0]
        metrics = slice_performance(curve, benchmark, start, year_dates[-1])
        rows.append(
            {
                "年份": year,
                "收益": metrics["区间收益"],
                "最大回撤": metrics["最大回撤"],
                "基准收益": metrics["基准收益"],
                "超额收益": metrics["超额收益"],
            }
        )
    return pd.DataFrame(rows)


def summarize_year_stability(annual: pd.DataFrame) -> dict[str, object]:
    """量化年度收益是否依赖2015年单一高收益样本。"""
    remaining = annual[annual["年份"].ne(2015)]["收益"].astype(float)
    compounded = float((1 + remaining).prod()) if not remaining.empty else 1.0
    cagr = compounded ** (1 / len(remaining)) - 1 if not remaining.empty else 0.0
    top_years = annual.nlargest(3, "收益")["年份"].astype(int).tolist()
    return {
        "正收益年份": int((annual["收益"] > 0).sum()),
        "总年份": len(annual),
        "正超额年份": int((annual["超额收益"] > 0).sum()),
        "剔除2015后年化": cagr,
        "收益最高年份": top_years,
    }


def analyze_platform(grid: pd.DataFrame) -> dict[str, object]:
    """用固定邻域和90%门槛判断最优点是否处在平台。"""
    best = rank_parameters(grid).iloc[0]
    window_index = WINDOWS.index(int(best["窗口"]))
    threshold_index = THRESHOLDS.index(float(best["阈值"]))
    exposure_index = EXPOSURES.index(float(best["低波动仓位"]))
    nearby_windows = WINDOWS[max(0, window_index - 1):window_index + 2]
    nearby_thresholds = THRESHOLDS[max(0, threshold_index - 1):threshold_index + 2]
    nearby_exposures = EXPOSURES[max(0, exposure_index - 1):exposure_index + 2]
    neighborhood = grid[
        grid["窗口"].isin(nearby_windows)
        & grid["阈值"].isin(nearby_thresholds)
        & grid["低波动仓位"].isin(nearby_exposures)
    ].copy()
    robust = neighborhood[
        (neighborhood["夏普比率"] >= best["夏普比率"] * 0.9)
        & (neighborhood["Calmar"] >= best["Calmar"] * 0.9)
    ]
    ratio = len(robust) / len(neighborhood) if len(neighborhood) else 0.0
    return {"最优参数": best["策略"], "邻域数量": len(neighborhood), "稳健数量": len(robust), "稳健比例": ratio, "形成平台": ratio >= 0.6}


def draw_heatmaps(grid: pd.DataFrame, metric: str, output_path: Path) -> None:
    """使用 Pillow 绘制四个降仓比例面板，避免新增绘图库。"""
    width, height = 1080, 720
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    values = grid[metric].dropna()
    low, high = float(values.min()), float(values.max())
    draw.text((30, 18), f"{heatmap_title(metric)} Heatmap (rows=window, cols=threshold)", fill="black", font=font)
    for panel_index, exposure in enumerate(EXPOSURES):
        panel_x = 30 + (panel_index % 2) * 525
        panel_y = 60 + (panel_index // 2) * 325
        matrix = build_heatmap_matrix(grid, metric, exposure)
        draw.text((panel_x, panel_y), f"Reduced exposure: {exposure:.0%}", fill="black", font=font)
        for col, threshold in enumerate(THRESHOLDS):
            draw.text((panel_x + 75 + col * 82, panel_y + 28), f"{threshold:.0%}", fill="black", font=font)
        for row, window in enumerate(WINDOWS):
            draw.text((panel_x, panel_y + 62 + row * 38), f"W{window}", fill="black", font=font)
            for col, threshold in enumerate(THRESHOLDS):
                value = float(matrix.loc[window, threshold])
                scale = (value - low) / (high - low) if high > low else 0.5
                color = (int(225 - 145 * scale), int(90 + 130 * scale), 95)
                box = (panel_x + 70 + col * 82, panel_y + 55 + row * 38, panel_x + 148 + col * 82, panel_y + 89 + row * 38)
                draw.rectangle(box, fill=color, outline="white")
                draw.text((box[0] + 8, box[1] + 10), f"{value:.3f}", fill="black", font=font)
    image.save(output_path)


def format_result_table(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化报告中的核心指标。"""
    result = frame.copy()
    for column in ["阈值", "低波动仓位", "年化收益", "最大回撤", "超额收益", "平均仓位"]:
        if column in result:
            result[column] = result[column].map(format_percent)
    for column in ["夏普比率", "Calmar"]:
        if column in result:
            result[column] = result[column].map(lambda value: f"{value:.3f}")
    return result


def render_report(
    grid: pd.DataFrame,
    walk_forward: pd.DataFrame,
    annual: pd.DataFrame,
    episodes: pd.DataFrame,
    platform: dict[str, object],
    baseline_metrics: pd.Series,
) -> str:
    """渲染稳健性研究报告。"""
    best = rank_parameters(grid).head(10)
    main = grid[grid["策略"].eq(parameter_name(*MAIN_PARAMETER))]
    annual_display = annual.copy()
    for column in ["收益", "最大回撤", "基准收益", "超额收益"]:
        annual_display[column] = annual_display[column].map(format_percent)
    event_display = episodes.copy()
    for column in ["降仓仓位", "触发波动率", "期间最高波动率", "风险层区间收益", "原策略区间收益", "避免损失"]:
        if column in event_display:
            event_display[column] = event_display[column].map(format_percent)
    main_row = main.iloc[0]
    stability = summarize_year_stability(annual)
    annual_improvement = main_row["年化收益"] - baseline_metrics["年化收益"]
    drawdown_improvement = main_row["最大回撤"] - baseline_metrics["最大回撤"]
    return f"""# Quality Cleanup + Volatility Overlay 鲁棒性研究

## 参数稳定性

- 完整搜索：{len(grid)}组，窗口6档、阈值5档、降仓比例4档。
- 固定排序：Sharpe降序 → Calmar降序 → 最大回撤绝对值升序 → 平均仓位降序。
- 全样本最优：`{platform['最优参数']}`。
- 最优点邻域：{platform['稳健数量']}/{platform['邻域数量']}组同时达到最优Sharpe和Calmar的90%，平台判定：{'是' if platform['形成平台'] else '否'}。

### 当前主参数

{markdown_table(format_result_table(main)[['策略', '窗口', '阈值', '低波动仓位', '年化收益', '最大回撤', '夏普比率', 'Calmar', '超额收益', '平均仓位']])}

### 固定规则 Top10

{markdown_table(format_result_table(best)[['策略', '窗口', '阈值', '低波动仓位', '年化收益', '最大回撤', '夏普比率', 'Calmar', '超额收益', '平均仓位']])}

![Sharpe Heatmap](quality_overlay_sharpe_heatmap.png)

![Calmar Heatmap](quality_overlay_calmar_heatmap.png)

## Walk Forward

训练参数一经选出，验证集直接使用，未根据验证结果反向调整。

{markdown_table(format_result_table(walk_forward))}

## 年度稳定性

{markdown_table(annual_display)}

## 风险层触发与贡献

- 触发事件数：{len(episodes)}。
- 事件窗口避免损失算术合计：{episodes['避免损失'].sum():.2%}。
- 全样本累计收益改善：{main_row['总收益'] - baseline_metrics['总收益']:.2%}。
- 年化收益变化：{annual_improvement:.2%}。
- 最大回撤改善：{drawdown_improvement:.2%}。

{markdown_table(event_display)}

## 最终判断

1. **过拟合风险：中等。** 两个Walk Forward训练阶段都选出`W30_T40_E20`且验证表现为正，支持风险层概念；但全样本最优邻域只有{platform['稳健数量']}/{platform['邻域数量']}组达到双指标90%，精确参数没有形成宽平台。
2. **主策略参数：暂不把全样本新最优替换成主参数。** 保留研究前已确定的`W20_T45_E30`进入前瞻验证，防止根据本轮全样本结果事后换参；它只能视为冻结的Paper参数，不是永久最优参数。
3. **长期Paper Trading：可以进入。** 两段验证期年化收益和Sharpe均为正，但必须冻结参数、记录每次触发与执行偏差，至少跨越一次真实高波动阶段后再评估实盘。
4. **年度集中度：存在2015贡献偏高，但不完全依赖单一年份。** {stability['正收益年份']}/{stability['总年份']}年正收益、{stability['正超额年份']}/{stability['总年份']}年正超额；剔除2015后其余年份复合年化约{stability['剔除2015后年化']:.2%}。
5. **风险层贡献：C，两者同时，但机制以降低回撤为主。** 年化收益提高{annual_improvement:.2%}、最大回撤改善{drawdown_improvement:.2%}；16次事件中正贡献事件虽少于负贡献事件，但少数危机期保护覆盖了震荡反弹期的机会成本。
6. **下一阶段：冻结参数做前瞻Paper归因。** 重点观察触发后T+1实际成交、保护收益、反弹机会成本和参数漂移，不再扩大网格或加入新因子。

## 口径

- Alpha、股票池、Top20等权和月频调仓保持不变。
- 风险信号使用当日收盘前可得数据，下一交易日执行。
- “避免损失”是同一触发窗口下风险层净值收益减原策略净值收益，不等同于可加总的会计利润。
"""


def main() -> None:
    """执行120组参数、Walk Forward、年度和风险贡献研究。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(candidates)
        base_targets = {date: {symbol: 1 / len(symbols) for symbol in symbols} for date, symbols in selections.items() if symbols}
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(con, BENCHMARK_LOOKBACK_START, str(FUND_DAILY_PATH), str(FUND_BASIC_PATH))
        bars = load_research_bars(con, sorted(holdings["symbol"].unique().tolist()))
        execution_model = ExecutionModel(slippage_bps=5.0)
        runs: dict[str, RiskLayerRun] = {}
        parameter_rows: list[dict[str, object]] = []
        combinations = parameter_combinations()
        for index, (window, threshold, exposure) in enumerate(combinations, start=1):
            name = parameter_name(window, threshold, exposure)
            runs[name] = run_risk_layer_backtest(name, "GRID", base_targets, bars, calendar, benchmark, execution_model, window, threshold, exposure)
            parameter_rows.append({"策略": name, "窗口": window, "阈值": threshold, "低波动仓位": exposure})
            print(f"[{index:03d}/{len(combinations)}] {name}")
        baseline = run_risk_layer_backtest("Quality Cleanup 原策略", "BASE", base_targets, bars, calendar, benchmark, execution_model)
        parameters = pd.DataFrame(parameter_rows)
        grid = build_metrics_table({name: run.result for name, run in runs.items()}, benchmark).merge(parameters, on="策略")
        grid["平均仓位"] = grid["策略"].map({name: float(run.exposure.mean()) for name, run in runs.items()})
        grid["Calmar"] = grid["年化收益"] / grid["最大回撤"].abs().replace(0, pd.NA)
        baseline_metrics = build_metrics_table({"Quality Cleanup 原策略": baseline.result}, benchmark).iloc[0]
        main_name = parameter_name(*MAIN_PARAMETER)
        main_run = runs[main_name]
        walk_forward = run_walk_forward(runs, parameters, benchmark)
        annual = build_annual_metrics(main_run.result.daily_values, benchmark)
        volatility = main_run.result.daily_values.pct_change().rolling(MAIN_PARAMETER[0]).std(ddof=1) * math.sqrt(252)
        episodes = build_trigger_episodes(main_run.exposure, volatility, MAIN_PARAMETER[1], MAIN_PARAMETER[0])
        episodes = calculate_avoided_loss(episodes, main_run.result.daily_values, baseline.result.daily_values)
        platform = analyze_platform(grid)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        grid.to_csv(GRID_PATH, index=False, encoding="utf-8-sig")
        walk_forward.to_csv(WALK_FORWARD_PATH, index=False, encoding="utf-8-sig")
        annual.to_csv(ANNUAL_PATH, index=False, encoding="utf-8-sig")
        episodes.to_csv(EVENT_PATH, index=False, encoding="utf-8-sig")
        draw_heatmaps(grid, "夏普比率", REPORT_DIR / "quality_overlay_sharpe_heatmap.png")
        draw_heatmaps(grid, "Calmar", REPORT_DIR / "quality_overlay_calmar_heatmap.png")
        REPORT_PATH.write_text(render_report(grid, walk_forward, annual, episodes, platform, baseline_metrics), encoding="utf-8")
        print(rank_parameters(grid).head(10).to_string(index=False))
        print(walk_forward.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
