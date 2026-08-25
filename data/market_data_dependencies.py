"""平台级行情依赖配置与逐标的数据完整性检查。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "market_data_dependencies.json"


class FundDateStore(Protocol):
    """基金增量缓存只需暴露逐标的最新日期。"""

    def latest_date(self, table: str, ts_code: str) -> str | None: ...


@dataclass(frozen=True)
class FundDependency:
    """一只需要每日维护的基金类标的。"""

    symbol: str
    name: str
    purpose: str


@dataclass(frozen=True)
class MarketDataDependencies:
    """平台固定维护的行情依赖集合。"""

    funds: tuple[FundDependency, ...]

    @property
    def fund_symbols(self) -> tuple[str, ...]:
        """返回稳定去重后的基金代码。"""
        return tuple(dict.fromkeys(item.symbol for item in self.funds))


def load_market_data_dependencies(path: str | Path | None = None) -> MarketDataDependencies:
    """读取固定行情依赖，配置错误时立即阻断数据流水线。"""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = payload.get("funds")
    if not isinstance(rows, list):
        raise ValueError("market_data_dependencies.funds 必须是数组")
    funds: list[FundDependency] = []
    for row in rows:
        if not isinstance(row, dict) or not bool(row.get("enabled", True)):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not _is_fund_symbol(symbol):
            raise ValueError(f"非法基金代码: {symbol}")
        funds.append(
            FundDependency(
                symbol=symbol,
                name=str(row.get("name") or symbol).strip(),
                purpose=str(row.get("purpose") or "平台行情依赖").strip(),
            )
        )
    if not funds:
        raise ValueError("至少需要配置一个启用的基金行情依赖")
    symbols = [item.symbol for item in funds]
    if len(symbols) != len(set(symbols)):
        raise ValueError("基金行情依赖存在重复代码")
    return MarketDataDependencies(tuple(funds))


def validate_fund_incremental_coverage(
    store: FundDateStore,
    symbols: tuple[str, ...] | list[str],
    expected_date: str,
) -> list[str]:
    """逐标的校验日线与复权因子，防止整表最新但局部资产缺失。"""
    target = _compact_date(expected_date)
    issues: list[str] = []
    for symbol in sorted(set(symbols)):
        daily_date = store.latest_date("fund_daily", symbol)
        adj_date = store.latest_date("fund_adj", symbol)
        if daily_date != target:
            issues.append(f"{symbol}.fund_daily 最新{daily_date or '无'}，要求{target}")
        if adj_date != target:
            issues.append(f"{symbol}.fund_adj 最新{adj_date or '无'}，要求{target}")
    return issues


def _is_fund_symbol(symbol: str) -> bool:
    code, separator, exchange = symbol.partition(".")
    return bool(separator and len(code) == 6 and code.isdigit() and exchange in {"SH", "SZ"})


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"非法交易日: {value}")
    return text
