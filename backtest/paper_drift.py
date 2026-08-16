"""回测目标与Paper实际执行结果的偏离分析。"""

from __future__ import annotations

from typing import Any

import pandas as pd


class DriftAnalyzer:
    """比较回测目标与模拟盘实际执行结果。"""

    def compare_curves(
        self,
        backtest_curve: pd.Series,
        paper_curve: pd.Series,
    ) -> dict[str, float]:
        """计算回测与模拟盘净值曲线差异。"""
        backtest_returns = backtest_curve.pct_change().dropna()
        paper_returns = paper_curve.pct_change().dropna()
        diff = (paper_returns - backtest_returns).dropna()
        tracking_error = (
            float(diff.std(ddof=0) * (252**0.5))
            if not diff.empty
            else 0.0
        )
        return {
            "tracking_error": tracking_error,
            "backtest_total_return": float(
                backtest_curve.iloc[-1] / backtest_curve.iloc[0] - 1
            ),
            "paper_total_return": float(
                paper_curve.iloc[-1] / paper_curve.iloc[0] - 1
            ),
        }

    def compare_positions(
        self,
        target: dict[str, int],
        actual: dict[str, int],
    ) -> dict[str, float]:
        """计算持仓数量偏离。"""
        symbols = set(target) | set(actual)
        deviation = sum(
            abs(actual.get(symbol, 0) - target.get(symbol, 0))
            for symbol in symbols
        )
        target_total = sum(abs(quantity) for quantity in target.values()) or 1
        return {"position_deviation": float(deviation / target_total)}

    def compare_turnover(
        self,
        target_turnover: float,
        actual_turnover: float,
    ) -> dict[str, float]:
        """计算目标换手与实际换手偏离。"""
        return {
            "target_turnover": float(target_turnover),
            "actual_turnover": float(actual_turnover),
            "turnover_deviation": float(
                abs(target_turnover - actual_turnover)
            ),
        }

    def execution_cost_impact(
        self,
        executions: list[Any],
        initial_cash: float,
    ) -> float:
        """汇总滑点等执行冲击占初始资金比例。"""
        impact = sum(
            log.execution_impact
            for log in executions
            if log.status != "REJECTED"
        )
        return float(impact / initial_cash) if initial_cash else 0.0
