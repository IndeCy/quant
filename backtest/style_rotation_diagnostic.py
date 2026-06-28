"""风格轮动诊断使用的纯计算函数。"""

from __future__ import annotations

import pandas as pd


def calculate_pb(raw_close: float, bps: float) -> float | None:
    """使用未复权价格与正的每股净资产计算PB。"""
    if raw_close <= 0 or bps <= 0:
        return None
    return float(raw_close / bps)


def find_longest_underwater(values: pd.Series) -> dict[str, object]:
    """找出连续未创新高时间最长的水下区间。"""
    curve = values.dropna().sort_index().astype(float)
    if curve.empty:
        return {}
    drawdown = curve / curve.cummax() - 1
    underwater = drawdown < 0
    if not underwater.any():
        return {}
    groups = underwater.ne(underwater.shift()).cumsum()
    episodes = [group for _, group in drawdown[underwater].groupby(groups[underwater])]
    longest = max(episodes, key=len)
    start_position = curve.index.get_loc(longest.index[0])
    end_position = curve.index.get_loc(longest.index[-1])
    high_position = max(start_position - 1, 0)
    recovery_position = end_position + 1
    recovery_date = curve.index[recovery_position] if recovery_position < len(curve) else pd.NaT
    return {
        "高点日期": pd.Timestamp(curve.index[high_position]),
        "开始日期": pd.Timestamp(longest.index[0]),
        "结束日期": pd.Timestamp(longest.index[-1]),
        "恢复日期": recovery_date,
        "持续交易日": len(longest),
        "区间最深回撤": float(longest.min()),
    }


def relative_strength_signals(
    curves: dict[str, pd.Series],
    signal_dates: list[pd.Timestamp],
    lookback: int = 126,
) -> pd.DataFrame:
    """按信号日可见的历史净值选择相对强度最高风格。"""
    aligned = pd.concat({name: curve for name, curve in curves.items()}, axis=1).dropna().sort_index()
    records: list[dict[str, object]] = []
    for requested_date in signal_dates:
        visible_dates = aligned.index[aligned.index <= pd.Timestamp(requested_date)]
        if not len(visible_dates):
            continue
        signal_date = pd.Timestamp(visible_dates[-1])
        position = aligned.index.get_loc(signal_date)
        if position < lookback or position + 1 >= len(aligned):
            continue
        scores = aligned.iloc[position] / aligned.iloc[position - lookback] - 1
        selected = str(scores.sort_values(ascending=False, kind="stable").index[0])
        record: dict[str, object] = {
            "信号日期": signal_date,
            "信号可用日期": pd.Timestamp(aligned.index[position + 1]),
            "选择风格": selected,
            "最高126日收益": float(scores[selected]),
        }
        record.update({f"{name}_126日收益": float(value) for name, value in scores.items()})
        records.append(record)
    if not records:
        return pd.DataFrame(columns=["信号可用日期", "选择风格", "最高126日收益"])
    return pd.DataFrame(records).set_index("信号日期").sort_index()


def build_lagged_rotation_curve(
    curves: dict[str, pd.Series],
    signals: pd.DataFrame,
    initial_value: float = 1.0,
) -> pd.Series:
    """严格从信号可用日开始采用所选风格的当日收益。"""
    aligned = pd.concat({name: curve for name, curve in curves.items()}, axis=1).dropna().sort_index()
    returns = aligned.pct_change().fillna(0.0)
    selections = pd.Series(index=aligned.index, dtype=object)
    for row in signals.itertuples():
        available_date = pd.Timestamp(row.信号可用日期)
        if available_date in selections.index:
            selections.loc[available_date] = row.选择风格
    selections = selections.ffill()
    values = [float(initial_value)]
    for position in range(1, len(aligned)):
        style = selections.iloc[position]
        daily_return = float(returns.iloc[position][style]) if pd.notna(style) else 0.0
        values.append(values[-1] * (1 + daily_return))
    return pd.Series(values, index=aligned.index, name="RelativeStrengthRotation")
