"""策略运行、目标组合与执行结果的稳定领域契约。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re


TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class TargetPosition:
    """组合层输出的单标的目标权重。"""

    symbol: str
    target_weight: float
    name: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("target position symbol is required")
        if not math.isfinite(self.target_weight) or not 0 <= self.target_weight <= 1:
            raise ValueError("target position weight must be between 0 and 1")


@dataclass(frozen=True)
class TargetPortfolio:
    """策略信号经过组合与风险层后形成的目标组合。"""

    strategy_id: str
    trade_date: str
    positions: tuple[TargetPosition, ...]
    target_exposure: float

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("target portfolio strategy_id is required")
        if not TRADE_DATE_PATTERN.fullmatch(self.trade_date):
            raise ValueError("target portfolio trade_date must use YYYYMMDD")
        if not math.isfinite(self.target_exposure) or not 0 <= self.target_exposure <= 1:
            raise ValueError("target exposure must be between 0 and 1")
        symbols = [position.symbol for position in self.positions]
        if len(symbols) != len(set(symbols)):
            raise ValueError("target portfolio symbols must be unique")
        total_weight = sum(position.target_weight for position in self.positions)
        if not math.isclose(total_weight, self.target_exposure, abs_tol=1e-9):
            raise ValueError("target weights must equal target exposure")

    @property
    def weights(self) -> dict[str, float]:
        """返回供订单规划和 Paper Broker 使用的目标权重映射。"""
        return {position.symbol: position.target_weight for position in self.positions}

    @classmethod
    def from_weights(
        cls,
        strategy_id: str,
        trade_date: str,
        weights: dict[str, float],
        names: dict[str, str] | None = None,
        reasons: dict[str, str] | None = None,
    ) -> "TargetPortfolio":
        """从策略组合层的权重映射构造标准目标组合。"""
        positions = tuple(
            TargetPosition(
                symbol=symbol,
                target_weight=float(weight),
                name=(names or {}).get(symbol, ""),
                reason=(reasons or {}).get(symbol, ""),
            )
            for symbol, weight in sorted(weights.items())
            if float(weight) > 0
        )
        return cls(
            strategy_id=strategy_id,
            trade_date=trade_date,
            positions=positions,
            target_exposure=sum(position.target_weight for position in positions),
        )


@dataclass(frozen=True)
class StrategyExecutionResult:
    """任意策略执行器必须返回的统一结果。"""

    strategy_id: str
    trade_date: str
    status: str
    message: str
    selected_count: int = 0
    nav: float | None = None
    target_portfolio: TargetPortfolio | None = None
    observation_only: bool = False

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy execution strategy_id is required")
        if not TRADE_DATE_PATTERN.fullmatch(self.trade_date):
            raise ValueError("strategy execution trade_date must use YYYYMMDD")
        if self.status not in {"SUCCESS", "FAILED"}:
            raise ValueError(f"unsupported strategy execution status: {self.status}")
        if self.selected_count < 0:
            raise ValueError("selected_count must be non-negative")
        if self.target_portfolio is not None and self.target_portfolio.strategy_id != self.strategy_id:
            raise ValueError("target portfolio strategy_id mismatch")

    @classmethod
    def success(
        cls,
        strategy_id: str,
        trade_date: str,
        message: str,
        *,
        selected_count: int = 0,
        nav: float | None = None,
        target_portfolio: TargetPortfolio | None = None,
        observation_only: bool = False,
    ) -> "StrategyExecutionResult":
        """构造成功结果，减少各执行器重复字段。"""
        return cls(
            strategy_id=strategy_id,
            trade_date=trade_date,
            status="SUCCESS",
            message=message,
            selected_count=selected_count,
            nav=nav,
            target_portfolio=target_portfolio,
            observation_only=observation_only,
        )

    def to_summary(self) -> dict[str, str]:
        """转换成现有批处理与通知兼容的摘要结构。"""
        return {"strategy_id": self.strategy_id, "status": self.status, "message": self.message}
