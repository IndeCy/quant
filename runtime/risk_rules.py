"""实盘风险触发与恢复共用规则。"""

from __future__ import annotations

from typing import Any


CRITICAL_MAX_EXPOSURE = 0.30
WARNING_MAX_EXPOSURE = 0.70


def classify_strategy_risk(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    """按既有阈值识别策略风险，不改变 Alpha 或策略自身仓位。"""
    daily_return = float(metrics.get("daily_return") or 0.0)
    drawdown = float(metrics.get("drawdown") or 0.0)
    volatility = float(metrics.get("volatility_20") or 0.0)
    reasons: list[str] = []
    critical = False
    warning = False
    if daily_return <= -0.08:
        critical = True
        reasons.append(f"当日收益 {daily_return:.2%} <= -8%")
    elif daily_return <= -0.05:
        warning = True
        reasons.append(f"当日收益 {daily_return:.2%} <= -5%")
    if drawdown <= -0.20:
        critical = True
        reasons.append(f"当前回撤 {drawdown:.2%} <= -20%")
    elif drawdown <= -0.10:
        warning = True
        reasons.append(f"当前回撤 {drawdown:.2%} <= -10%")
    if volatility >= 0.50:
        critical = True
        reasons.append(f"20日波动率 {volatility:.2%} >= 50%")
    return ("CRITICAL" if critical else "WARNING" if warning else "NORMAL", reasons)


def risk_exposure_limit(severity: str) -> float:
    """把风险级别转换成组合级最大暴露。"""
    if severity == "CRITICAL":
        return CRITICAL_MAX_EXPOSURE
    if severity == "WARNING":
        return WARNING_MAX_EXPOSURE
    return 1.0
