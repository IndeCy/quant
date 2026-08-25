"""Quality 风险层稳健性研究的纯分析函数。"""

from __future__ import annotations

import math

import pandas as pd


def rank_parameters(frame: pd.DataFrame) -> pd.DataFrame:
    """按用户锁定的四级规则选择训练集参数。"""
    ranked = frame.copy()
    ranked["回撤绝对值"] = ranked["最大回撤"].abs()
    ranked = ranked.sort_values(
        ["夏普比率", "Calmar", "回撤绝对值", "平均仓位"],
        ascending=[False, False, True, False],
        kind="stable",
    )
    return ranked.drop(columns="回撤绝对值").reset_index(drop=True)


def slice_performance(
    values: pd.Series,
    benchmark: pd.Series,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> dict[str, float]:
    """计算指定区间指标，策略和基准均以区间首日重新归一。"""
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    curve = values.sort_index().loc[start_date:end_date].dropna().astype(float)
    benchmark_curve = benchmark.sort_index().loc[start_date:end_date].dropna().astype(float)
    if len(curve) < 2:
        return _empty_metrics()

    returns = curve.pct_change().dropna()
    total_return = float(curve.iloc[-1] / curve.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (252 / len(curve)) - 1)
    drawdown = curve / curve.cummax() - 1
    volatility = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / volatility * math.sqrt(252)) if volatility > 0 else 0.0
    max_drawdown = float(drawdown.min())
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    benchmark_return = (
        float(benchmark_curve.iloc[-1] / benchmark_curve.iloc[0] - 1)
        if len(benchmark_curve) >= 2
        else 0.0
    )
    return {
        "区间收益": total_return,
        "年化收益": annual_return,
        "最大回撤": max_drawdown,
        "夏普比率": sharpe,
        "Calmar": calmar,
        "基准收益": benchmark_return,
        "超额收益": total_return - benchmark_return,
    }


def build_trigger_episodes(
    exposure: pd.Series,
    volatility: pd.Series,
    threshold: float,
    window: int,
) -> pd.DataFrame:
    """把连续降仓交易日合并成独立风险触发事件。"""
    aligned = pd.concat(
        [exposure.rename("仓位"), volatility.rename("组合波动率")], axis=1
    ).sort_index()
    active = aligned[aligned["仓位"] < 1.0]
    columns = ["触发日期", "结束日期", "持续交易日", "触发原因", "降仓仓位", "触发波动率", "期间最高波动率"]
    if active.empty:
        return pd.DataFrame(columns=columns)

    index_positions = pd.Series(range(len(aligned)), index=aligned.index)
    active_positions = index_positions.loc[active.index]
    groups = active_positions.diff().ne(1).cumsum()
    records: list[dict[str, object]] = []
    for _, episode in active.groupby(groups):
        trigger_date = pd.Timestamp(episode.index[0])
        trigger_volatility = float(episode.iloc[0]["组合波动率"])
        records.append(
            {
                "触发日期": trigger_date,
                "结束日期": pd.Timestamp(episode.index[-1]),
                "持续交易日": len(episode),
                "触发原因": f"{window}日组合年化波动率{trigger_volatility:.2%}超过阈值{threshold:.2%}",
                "降仓仓位": float(episode.iloc[0]["仓位"]),
                "触发波动率": trigger_volatility,
                "期间最高波动率": float(episode["组合波动率"].max()),
            }
        )
    return pd.DataFrame(records, columns=columns)


def calculate_avoided_loss(
    episodes: pd.DataFrame,
    overlay_values: pd.Series,
    baseline_values: pd.Series,
) -> pd.DataFrame:
    """用相同事件窗口比较风险层与原策略，估算避免的损失。"""
    result = episodes.copy()
    if result.empty:
        result["风险层区间收益"] = pd.Series(dtype=float)
        result["原策略区间收益"] = pd.Series(dtype=float)
        result["避免损失"] = pd.Series(dtype=float)
        return result

    curves = pd.concat(
        [overlay_values.rename("overlay"), baseline_values.rename("baseline")],
        axis=1,
        join="inner",
    ).dropna().sort_index()
    overlay_returns: list[float] = []
    baseline_returns: list[float] = []
    for row in result.itertuples(index=False):
        start_position = curves.index.searchsorted(pd.Timestamp(row.触发日期))
        # 信号在触发日收盘生成，T+1 执行；归因需覆盖最后一次低仓位信号的下一交易日。
        end_signal_position = curves.index.searchsorted(pd.Timestamp(row.结束日期), side="right") - 1
        end_position = min(end_signal_position + 1, len(curves) - 1)
        anchor = curves.iloc[start_position]
        end_values = curves.iloc[end_position]
        overlay_returns.append(float(end_values["overlay"] / anchor["overlay"] - 1))
        baseline_returns.append(float(end_values["baseline"] / anchor["baseline"] - 1))
    result["风险层区间收益"] = overlay_returns
    result["原策略区间收益"] = baseline_returns
    result["避免损失"] = result["风险层区间收益"] - result["原策略区间收益"]
    return result


def _empty_metrics() -> dict[str, float]:
    """返回固定结构的空区间指标。"""
    return {
        "区间收益": 0.0,
        "年化收益": 0.0,
        "最大回撤": 0.0,
        "夏普比率": 0.0,
        "Calmar": 0.0,
        "基准收益": 0.0,
        "超额收益": 0.0,
    }
