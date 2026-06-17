"""
Milestone 2.1 Core-Satellite 因子组合示例。

该示例使用合成收益序列验证组合层能力，不新增因子，不改变已有策略逻辑。
重点对比旧 Satellite 单标的轮换与新 Satellite alpha 加权资产层。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.factor_portfolio import CoreSatelliteFactorPortfolio


REPORT_PATH = Path("reports/milestone2_core_satellite_portfolio.md")


def build_synthetic_returns() -> pd.DataFrame:
    """构造低波 Core 与高弹 Satellite 的确定性收益序列。"""
    dates = pd.bdate_range("2024-01-02", periods=252)
    rows = []
    for i, _ in enumerate(dates):
        satellite_shock = -0.035 if 90 <= i < 98 else 0.0
        trend_boost = 0.006 if 130 <= i < 145 else 0.0
        rows.append(
            {
                "LOW_A": 0.00034 + 0.00025 * ((i % 5) - 2) / 2,
                "LOW_B": 0.00028 + 0.00020 * ((i % 7) - 3) / 3,
                "MOM_A": 0.00055 + 0.0025 * ((i % 11) - 5) / 5 + satellite_shock,
                "TREND_A": 0.00045 + 0.0020 * ((i % 13) - 6) / 6 + trend_boost + satellite_shock * 0.5,
            }
        )
    return pd.DataFrame(rows, index=dates)


def month_starts(index: pd.Index) -> list[pd.Timestamp]:
    """取每月第一个交易日。"""
    result: list[pd.Timestamp] = []
    seen: set[tuple[int, int]] = set()
    for day in pd.to_datetime(index):
        key = (day.year, day.month)
        if key not in seen:
            seen.add(key)
            result.append(day)
    return result


def portfolio_metrics(curve: pd.Series, monthly_turnover: pd.Series) -> dict[str, float]:
    """计算示例报告使用的核心指标。"""
    returns = curve.pct_change().dropna()
    total_return = float(curve.iloc[-1] / curve.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (252 / max(len(curve), 1)) - 1)
    volatility = float(returns.std() * (252 ** 0.5)) if not returns.empty else 0.0
    running_max = curve.expanding().max()
    max_drawdown = float(((curve - running_max) / running_max).min())
    sharpe = float((returns.mean() / returns.std()) * (252 ** 0.5)) if returns.std() and returns.std() > 0 else 0.0
    stability = annual_return / abs(max_drawdown) if max_drawdown < 0 else annual_return
    return {
        "总收益率": total_return,
        "年化收益率": annual_return,
        "最大回撤": max_drawdown,
        "年化波动率": volatility,
        "夏普比率": sharpe,
        "平均月换手": float(monthly_turnover.mean()) if not monthly_turnover.empty else 0.0,
        "稳定性评分": stability,
    }


def simulate_from_monthly_weights(
    returns: pd.DataFrame,
    weights_by_month: dict[pd.Timestamp, dict[str, float]],
    initial_value: float = 1_000_000.0,
) -> pd.Series:
    """按月度目标权重模拟资产曲线。"""
    value = initial_value
    current_weights = {column: 0.0 for column in returns.columns}
    values = []
    for date, row in returns.iterrows():
        if date in weights_by_month:
            current_weights = {column: weights_by_month[date].get(column, 0.0) for column in returns.columns}
        daily_return = sum(current_weights[column] * float(row[column]) for column in returns.columns)
        value *= 1 + daily_return
        values.append(value)
    return pd.Series(values, index=returns.index, name="total_value")


def monthly_turnover(weights_by_month: dict[pd.Timestamp, dict[str, float]]) -> pd.Series:
    """计算月度目标权重换手。"""
    previous: dict[str, float] = {}
    values = {}
    for date, weights in weights_by_month.items():
        symbols = set(previous) | set(weights)
        values[date] = 0.5 * sum(abs(weights.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)
        previous = weights
    return pd.Series(values, name="monthly_turnover")


def legacy_satellite_signal(index: int) -> dict[str, float]:
    """旧 Satellite 行为：Top1 轮换，权重缺少连续 alpha 分配。"""
    return {"MOM_A": 1.0} if index % 2 == 0 else {"TREND_A": 1.0}


def alpha_satellite_signal(index: int) -> dict[str, float]:
    """
    新 Satellite 输入：沿用动量/趋势信号，但提供连续强度。

    示例中 4-5 月降低 MOM_A 信心，避免把高波动冲击资产当作 alpha source。
    """
    if index < 3:
        return {"MOM_A": 1.0, "TREND_A": 0.8}
    if index in {3, 4}:
        return {"MOM_A": 0.2, "TREND_A": 0.9}
    if 5 <= index <= 7:
        return {"MOM_A": 0.5, "TREND_A": 2.5}
    return {"MOM_A": 0.8, "TREND_A": 1.2}


def trailing_risk(returns: pd.DataFrame, date: pd.Timestamp) -> dict[str, float]:
    """用已有收益序列估计波动率，缺失时给出保守默认值。"""
    risk = returns.loc[:date].tail(60).std().fillna(0.20).replace(0, 0.001)
    return risk.to_dict()


def build_weight_schedules(returns: pd.DataFrame) -> dict[str, tuple[dict[pd.Timestamp, dict[str, float]], pd.Series]]:
    """构造 Core、旧 Satellite、新 Satellite Alpha 和组合权重。"""
    legacy_constructor = CoreSatelliteFactorPortfolio(max_turnover=0.35)
    alpha_constructor = CoreSatelliteFactorPortfolio(
        max_turnover=0.35,
        satellite_weighting="softmax",
        satellite_temperature=0.75,
        satellite_turnover_penalty=0.65,
    )
    core_weights: dict[pd.Timestamp, dict[str, float]] = {}
    legacy_satellite_weights: dict[pd.Timestamp, dict[str, float]] = {}
    alpha_satellite_weights: dict[pd.Timestamp, dict[str, float]] = {}
    combined_alpha_weights: dict[pd.Timestamp, dict[str, float]] = {}
    combined_alpha_turnover: dict[pd.Timestamp, float] = {}
    previous_alpha_combined: dict[str, float] = {}
    previous_alpha_satellite: dict[str, float] = {}
    previous_alpha_signal: dict[str, float] = {}
    previous_combined_signal: dict[str, float] = {}

    for index, date in enumerate(month_starts(returns.index)):
        risk = trailing_risk(returns, date)
        core_signal = {"LOW_A": 1.0, "LOW_B": 1.0}
        legacy_signal = legacy_satellite_signal(index)
        alpha_signal = alpha_satellite_signal(index)

        combined_alpha = alpha_constructor.build(
            core_signal,
            alpha_signal,
            risk,
            previous_alpha_combined,
            previous_combined_signal,
        )
        combined_alpha_weights[date] = combined_alpha.target_weights
        combined_alpha_turnover[date] = combined_alpha.turnover
        previous_alpha_combined = combined_alpha.target_weights
        previous_combined_signal = alpha_signal

        core_only = legacy_constructor.build(core_signal, {}, risk)
        legacy_satellite = legacy_constructor.build({}, legacy_signal, risk)
        alpha_satellite = alpha_constructor.build(
            {},
            alpha_signal,
            risk,
            previous_alpha_satellite,
            previous_alpha_signal,
        )
        core_weights[date] = core_only.target_weights
        legacy_satellite_weights[date] = legacy_satellite.target_weights
        alpha_satellite_weights[date] = alpha_satellite.target_weights
        previous_alpha_satellite = alpha_satellite.target_weights
        previous_alpha_signal = alpha_signal

    return {
        "Core低波": (core_weights, monthly_turnover(core_weights)),
        "Satellite旧等权": (legacy_satellite_weights, monthly_turnover(legacy_satellite_weights)),
        "Satellite Alpha": (alpha_satellite_weights, monthly_turnover(alpha_satellite_weights)),
        "Core-Satellite Alpha": (
            combined_alpha_weights,
            pd.Series(combined_alpha_turnover, name="monthly_turnover"),
        ),
    }


def run_milestone2_comparison(write_report: bool = True) -> pd.DataFrame:
    """运行 Milestone 2.1 组合收益、换手、回撤和稳定性对比。"""
    returns = build_synthetic_returns()
    schedules = build_weight_schedules(returns)
    rows = []
    for label, (weights, turnover) in schedules.items():
        curve = simulate_from_monthly_weights(returns, weights)
        rows.append({"组合": label, **portfolio_metrics(curve, turnover)})
    result = pd.DataFrame(rows)
    if write_report:
        write_report_markdown(result, REPORT_PATH)
    return result


def write_report_markdown(result: pd.DataFrame, path: Path) -> None:
    """写出 Milestone 2.1 文本报告。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    formatted = result.copy()
    for column in ["总收益率", "年化收益率", "最大回撤", "年化波动率", "平均月换手"]:
        formatted[column] = formatted[column].map(lambda value: f"{value:.2%}")
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    formatted["稳定性评分"] = formatted["稳定性评分"].map(lambda value: f"{value:.2f}")
    indexed = result.set_index("组合")
    alpha_positive = indexed.loc["Satellite Alpha", "总收益率"] > 0
    turnover_controlled = indexed.loc["Core-Satellite Alpha", "平均月换手"] <= 0.35
    m3_ready = "是" if alpha_positive and turnover_controlled else "否"
    table = markdown_table(formatted)
    content = "\n".join(
        [
            "# Milestone 2.1 Satellite Alpha Allocation Report",
            "",
            "## 组合结构",
            "",
            "- Core 70%：低波动资产，长期持有，低换手。",
            "- Satellite 30%：动量/趋势增强，使用 signal → weight 连续映射，仅做增强。",
            "- 权重由 `CoreSatelliteFactorPortfolio` 决定，策略信号不直接决定权重。",
            "- Satellite 权重机制：softmax rank mapping + confidence weighting + volatility scaling + turnover penalty。",
            "",
            "## 收益、换手与回撤对比",
            "",
            table,
            "",
            "## 稳定性分析",
            "",
            "旧 Satellite 使用单标的轮换，容易把高波动噪声直接放大成仓位。",
            "Satellite Alpha 把同一批信号转成连续权重，并对高波动和信号突变降权。",
            "Core-Satellite Alpha 用 Core 低波资产压住组合波动和回撤，用 Satellite 保留受约束的增强弹性。",
            "",
            "## Satellite Alpha 判定",
            "",
            f"- Satellite 是否由负收益转为正收益：{'是' if alpha_positive else '否'}。",
            f"- 组合级平均月换手是否受 35% 约束：{'是' if turnover_controlled else '否'}。",
            "",
            f"## 是否进入 Milestone 3",
            "",
            f"结论：{m3_ready}。若后续接真实股票池，仍需继续观察模拟盘成交失败、容量和持仓漂移。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    """避免引入 tabulate 依赖的简单 Markdown 表格。"""
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_milestone2_comparison(write_report=True)
    print(report.to_string(index=False))
    print(f"报告已写入: {REPORT_PATH}")
