"""Quality类策略的固定防守资产袖套组合契约。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from data.market_snapshot import create_fund_market_snapshot
from portfolio.fixed_sleeve import build_core_scoped_sleeve_targets
from runtime.paths import RuntimePaths


@dataclass(frozen=True)
class FixedSleevePlan:
    """声明式固定袖套配置，风险层只调整核心资产暴露。"""

    core_allocation: float
    defensive_weights: dict[str, float]
    defensive_names: dict[str, str]

    @property
    def symbols(self) -> list[str]:
        """返回稳定排序的防守资产代码。"""
        return sorted(self.defensive_weights)


def load_fixed_sleeve_plan(instance: dict[str, Any]) -> FixedSleevePlan | None:
    """从策略组合声明读取固定袖套，不存在时保持原单资产策略。"""
    construction = dict(instance.get("construction") or {})
    payload = construction.get("fixed_sleeves")
    if payload is None:
        return None
    if not isinstance(payload, list) or not payload:
        raise ValueError("construction.fixed_sleeves must be a non-empty list")
    core_allocation = float(construction.get("core_allocation", 0.0))
    weights: dict[str, float] = {}
    names: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("fixed sleeve item must be an object")
        symbol = str(item.get("symbol") or "").strip().upper()
        weight = float(item.get("weight", 0.0))
        if not symbol or symbol in weights or weight <= 0:
            raise ValueError("fixed sleeve symbol and positive unique weight are required")
        weights[symbol] = weight
        names[symbol] = str(item.get("name") or symbol).strip()
    if not math.isclose(core_allocation + sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("core allocation and fixed sleeve weights must sum to 1")
    return FixedSleevePlan(core_allocation, weights, names)


def build_fixed_sleeve_targets(
    instance: dict[str, Any],
    core_targets: dict[str, dict[str, float]],
    core_exposure: pd.Series,
) -> dict[str, dict[str, float]]:
    """按已冻结的核心风险预算生成组合目标；普通策略原样返回核心目标。"""
    plan = load_fixed_sleeve_plan(instance)
    if plan is None:
        return core_targets
    risk_scope = str(dict(instance.get("config") or {}).get("risk_scope") or "")
    if risk_scope != "quality_core_only":
        raise ValueError(f"unsupported fixed sleeve risk scope: {risk_scope}")
    return build_core_scoped_sleeve_targets(
        core_targets,
        core_exposure,
        core_allocation=plan.core_allocation,
        defensive_weights=plan.defensive_weights,
    )


def build_effective_exposure_series(
    targets: dict[str, dict[str, float]],
    calendar: list[pd.Timestamp],
) -> pd.Series:
    """把离散组合目标扩展为逐交易日实际目标仓位。"""
    if not calendar:
        return pd.Series(dtype=float)
    changes = pd.Series(
        {
            pd.Timestamp(date).normalize(): float(sum(weights.values()))
            for date, weights in targets.items()
        },
        dtype=float,
    ).sort_index()
    index = pd.DatetimeIndex(calendar).normalize()
    return changes.reindex(index).ffill().fillna(0.0)


def append_fixed_sleeve_holdings(
    selected: pd.DataFrame,
    target_weights: dict[str, float],
    instance: dict[str, Any],
    selection_date: str,
) -> pd.DataFrame:
    """把固定资产加入标准持仓产物，因子字段保持空值。"""
    plan = load_fixed_sleeve_plan(instance)
    if plan is None:
        return selected
    rows = [
        {
            "signal_date": selection_date,
            "symbol": symbol,
            "name": plan.defensive_names[symbol],
            "target_weight": target_weights[symbol],
            "reason": "固定防守资产预算",
            "sleeve": "defensive_asset",
        }
        for symbol in plan.symbols
    ]
    return pd.concat([selected, pd.DataFrame(rows)], ignore_index=True, sort=False)


def load_fixed_sleeve_latest_prices(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
) -> dict[str, float]:
    """从统一不复权基金快照读取Paper状态展示价格。"""
    plan = load_fixed_sleeve_plan(instance)
    if plan is None:
        return {}
    snapshot = create_fund_market_snapshot(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        trade_date,
        lookback_start=trade_date,
        adjust_policy="none",
    )
    prices: dict[str, float] = {}
    for symbol in plan.symbols:
        bars = snapshot.load_daily_bars(symbol)
        if bars.empty:
            raise RuntimeError(f"quality_fixed_sleeve_missing_price:{symbol}")
        prices[symbol] = float(bars.iloc[-1]["close"])
    return prices
