"""
市场状态分析框架。

该模块只定义 regime 分析接口层，当前默认不引入任何新数据源，
统一把回测区间标记为 ALL_TIME，供未来 bull/bear/sideways 分类器扩展。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


class RegimeClassifier(ABC):
    """市场状态分类器抽象接口。"""

    @abstractmethod
    def classify(self, date: pd.Timestamp) -> str:
        """返回指定日期对应的市场状态标签。"""


class DefaultRegimeClassifier(RegimeClassifier):
    """默认占位分类器，当前不依赖任何真实 regime 数据。"""

    def classify(self, date: pd.Timestamp) -> str:
        """当前所有日期统一归入 ALL_TIME。"""
        return "ALL_TIME"


@dataclass(frozen=True)
class RegimeMetrics:
    """按单个 regime 净值曲线计算基础绩效指标。"""

    trading_days_per_year: int = 252

    def calculate(self, result: pd.DataFrame) -> dict[str, float]:
        """计算年化收益、最大回撤和 Sharpe。"""
        curve = self._value_curve(result)
        if curve.empty:
            return {"annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}

        returns = curve.pct_change().dropna()
        total_return = float(curve.iloc[-1] / curve.iloc[0] - 1) if curve.iloc[0] else 0.0
        annual_return = float((1 + total_return) ** (self.trading_days_per_year / max(len(curve), 1)) - 1)
        running_max = curve.expanding().max()
        max_drawdown = float(((curve - running_max) / running_max).min())
        sharpe = 0.0
        if not returns.empty and returns.std() and returns.std() > 0:
            sharpe = float((returns.mean() / returns.std()) * (self.trading_days_per_year ** 0.5))
        return {
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
        }

    def _value_curve(self, result: pd.DataFrame) -> pd.Series:
        """从回测结果中提取净值列，兼容常见字段命名。"""
        if "total_value" in result.columns:
            return pd.Series(result["total_value"], dtype="float64").reset_index(drop=True)
        if "portfolio_value" in result.columns:
            return pd.Series(result["portfolio_value"], dtype="float64").reset_index(drop=True)
        if "value" in result.columns:
            return pd.Series(result["value"], dtype="float64").reset_index(drop=True)
        raise ValueError("回测结果必须包含 total_value/portfolio_value/value 之一")


class RegimeSplitter:
    """把回测结果按可插拔 RegimeClassifier 分组。"""

    def __init__(self, classifier: RegimeClassifier | None = None):
        self.classifier = classifier or DefaultRegimeClassifier()

    def split(self, result: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """按 regime 标签拆分回测结果。"""
        if result.empty:
            return {}
        frame = result.copy()
        date_series = self._date_series(frame)
        frame["regime"] = [self.classifier.classify(date) for date in date_series]
        return {
            label: group.reset_index(drop=True)
            for label, group in frame.groupby("regime", sort=True)
        }

    def analyze(self, result: pd.DataFrame, metrics: RegimeMetrics | None = None) -> pd.DataFrame:
        """按 regime 输出基础指标表。"""
        metrics = metrics or RegimeMetrics()
        rows = []
        for label, group in self.split(result).items():
            rows.append({"regime": label, **metrics.calculate(group)})
        return pd.DataFrame(rows, columns=["regime", "annual_return", "max_drawdown", "sharpe"])

    def _date_series(self, frame: pd.DataFrame) -> pd.Series:
        """提取日期序列，兼容 date/trade_date 或索引日期。"""
        if "date" in frame.columns:
            return pd.to_datetime(frame["date"])
        if "trade_date" in frame.columns:
            return pd.to_datetime(frame["trade_date"])
        if isinstance(frame.index, pd.DatetimeIndex):
            return pd.Series(frame.index, index=frame.index)
        raise ValueError("回测结果必须包含 date/trade_date，或使用 DatetimeIndex")
