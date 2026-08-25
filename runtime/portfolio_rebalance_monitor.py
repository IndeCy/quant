"""多资产组合建仓与重平衡提醒，只读行情、只发通知。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from data.calendar import TradingCalendar
from data.market_snapshot import create_fund_market_snapshot
from runtime.notification_config import NotificationResult, send_bark_notification
from runtime.paths import RuntimePaths


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
ACTIONABLE_SIGNALS = {"BUILD_REVIEW", "REBALANCE_REQUIRED", "ANNUAL_REVIEW"}


@dataclass(frozen=True)
class PortfolioAssetConfig:
    symbol: str
    display_name: str
    current_weight: float
    target_weight: float
    quantity: float = 0.0
    cost: float = 0.0


@dataclass(frozen=True)
class PortfolioRebalanceConfig:
    portfolio_id: str
    display_name: str
    reference_date: date
    assets: tuple[PortfolioAssetConfig, ...]
    cash_current_weight: float
    cash_target_weight: float
    rebalance_band_pp: float
    total_capital: float = 500_000.0
    reminder_cooldown_days: int = 7
    annual_review_month: int = 7
    annual_review_day: int = 31
    failure_alert_after: int = 3


@dataclass(frozen=True)
class PortfolioWeightSnapshot:
    trade_date: date
    weights: dict[str, float]
    prices: dict[str, float]


def load_rebalance_config(path: Path) -> PortfolioRebalanceConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = tuple(PortfolioAssetConfig(**item) for item in payload.pop("assets"))
    reference_date = date.fromisoformat(str(payload.pop("reference_date")))
    config = PortfolioRebalanceConfig(
        **payload,
        reference_date=reference_date,
        assets=assets,
    )
    if not config.portfolio_id or not assets:
        raise ValueError("组合标识和资产不能为空")
    if any(len(asset.symbol) != 9 for asset in assets):
        raise ValueError("资产代码必须带交易所后缀")
    current_total = sum(asset.current_weight for asset in assets) + config.cash_current_weight
    target_total = sum(asset.target_weight for asset in assets) + config.cash_target_weight
    if abs(current_total - 1.0) > 1e-8 or abs(target_total - 1.0) > 1e-8:
        raise ValueError("当前权重和目标权重必须分别等于1")
    if any(
        not 0 <= value <= 1
        for asset in assets
        for value in (asset.current_weight, asset.target_weight)
    ) or not 0 <= config.cash_current_weight <= 1 or not 0 <= config.cash_target_weight <= 1:
        raise ValueError("权重必须位于0到1之间")
    if config.total_capital <= 0:
        raise ValueError("总资产基准必须为正")
    if any(asset.quantity < 0 or asset.cost < 0 for asset in assets):
        raise ValueError("持仓数量和成本不能为负")
    if not 0 < config.rebalance_band_pp < 50:
        raise ValueError("重平衡带必须位于0到50个百分点之间")
    if config.reminder_cooldown_days <= 0 or config.failure_alert_after <= 0:
        raise ValueError("提醒冷却和失败阈值必须为正")
    try:
        date(2000, config.annual_review_month, config.annual_review_day)
    except ValueError as error:
        raise ValueError("年度复核日期无效") from error
    return config


def load_weight_snapshot(
    config: PortfolioRebalanceConfig,
    paths: RuntimePaths,
    observed_at: datetime,
) -> PortfolioWeightSnapshot:
    """按用户最近确认的权重和当时价格，使用生产快照估算当前市值权重。"""
    snapshot = create_fund_market_snapshot(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        observed_at.strftime("%Y%m%d"),
        lookback_start=config.reference_date.strftime("%Y%m%d"),
        adjust_policy="none",
    )
    values: dict[str, float] = {"CASH": config.cash_current_weight}
    prices: dict[str, float] = {}
    latest_dates: list[date] = []
    reference_text = config.reference_date.strftime("%Y%m%d")
    for asset in config.assets:
        frame = snapshot.load_daily_bars(asset.symbol)
        if frame.empty:
            raise RuntimeError(f"{asset.symbol} 没有可用行情")
        reference = frame.loc[frame.index.strftime("%Y%m%d") == reference_text]
        if reference.empty:
            raise RuntimeError(f"{asset.symbol} 缺少权重确认日行情 {reference_text}")
        reference_price = float(reference.iloc[-1]["close"])
        current_price = float(frame.iloc[-1]["close"])
        if reference_price <= 0 or current_price <= 0:
            raise RuntimeError(f"{asset.symbol} 价格无效")
        values[asset.symbol] = asset.current_weight * current_price / reference_price
        prices[asset.symbol] = current_price
        latest_dates.append(frame.index[-1].date())
    total = sum(values.values())
    if total <= 0:
        raise RuntimeError("组合估值合计无效")
    return PortfolioWeightSnapshot(
        trade_date=min(latest_dates),
        weights={symbol: value / total for symbol, value in values.items()},
        prices=prices,
    )


def classify_snapshot(
    snapshot: PortfolioWeightSnapshot,
    config: PortfolioRebalanceConfig,
) -> str:
    """建仓期优先用现金补低配；完成建仓后才触发双向重平衡。"""
    band = config.rebalance_band_pp / 100
    target_by_symbol = {asset.symbol: asset.target_weight for asset in config.assets}
    target_by_symbol["CASH"] = config.cash_target_weight
    breaches = {
        symbol
        for symbol, target in target_by_symbol.items()
        if snapshot.weights[symbol] < max(0.0, target - band)
        or snapshot.weights[symbol] > min(1.0, target + band)
    }
    building = (
        snapshot.weights["CASH"] > config.cash_target_weight + band
        and all(
            snapshot.weights[asset.symbol] <= asset.target_weight + band
            for asset in config.assets
        )
    )
    if breaches and building:
        return "BUILD_REVIEW"
    if breaches:
        return "REBALANCE_REQUIRED"
    return "OK"


def build_notification(
    signal: str,
    snapshot: PortfolioWeightSnapshot,
    config: PortfolioRebalanceConfig,
) -> tuple[str, str]:
    target_by_symbol = {asset.symbol: asset.target_weight for asset in config.assets}
    target_by_symbol["CASH"] = config.cash_target_weight
    name_by_symbol = {asset.symbol: asset.display_name for asset in config.assets}
    name_by_symbol["CASH"] = "现金"
    allocation = "；".join(
        (
            f"{name_by_symbol[symbol]} {snapshot.weights[symbol]:.1%}/{target_by_symbol[symbol]:.0%}"
            + (
                f"（{next(asset.quantity for asset in config.assets if asset.symbol == symbol):g}份）"
                if symbol != "CASH"
                else ""
            )
        )
        for symbol in (*[asset.symbol for asset in config.assets], "CASH")
    )
    if signal == "BUILD_REVIEW":
        gaps = sorted(
            (
                (asset.target_weight - snapshot.weights[asset.symbol], asset.display_name)
                for asset in config.assets
                if snapshot.weights[asset.symbol] < asset.target_weight
            ),
            reverse=True,
        )
        gap_text = "、".join(f"{name}缺口{gap:.1%}" for gap, name in gaps)
        title = f"{config.display_name} 建仓配平复核"
        action = f"仍处建仓阶段：{gap_text}。优先使用现金补低配，不为配平卖出现有资产；具体成交等待单品溢价提醒。"
    elif signal == "REBALANCE_REQUIRED":
        title = f"{config.display_name} 触发重平衡带"
        action = (
            f"至少一类资产偏离目标超过 {config.rebalance_band_pp:.0f} 个百分点。"
            "请复核把全组合恢复到目标权重；仅提醒，不会自动下单。"
        )
    elif signal == "ANNUAL_REVIEW":
        title = f"{config.display_name} 年度重平衡复核"
        action = "已到年度检查日；即使尚未越过偏离带，也请核对实际券商仓位、分红和现金余额。"
    else:
        raise ValueError(f"不可通知的信号: {signal}")
    body = (
        f"{action} 总资产基准 {config.total_capital:,.0f} 元；"
        f"截至 {snapshot.trade_date:%Y-%m-%d}：{allocation}。"
    )
    return title, body


def run_monitor(
    config: PortfolioRebalanceConfig,
    paths: RuntimePaths,
    *,
    push: bool,
    dry_run: bool = False,
    now: datetime | None = None,
    snapshot_loader: Callable[
        [PortfolioRebalanceConfig, RuntimePaths, datetime], PortfolioWeightSnapshot
    ] = load_weight_snapshot,
    notifier: Callable[[str, str], NotificationResult] = send_bark_notification,
) -> dict[str, object]:
    observed_at = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    if not dry_run and not TradingCalendar().is_trading_day(observed_at.date()):
        return {"status": "SKIPPED", "reason": "not_trading_day"}
    snapshot = snapshot_loader(config, paths, observed_at)
    signal = classify_snapshot(snapshot, config)
    state_path = paths.state_dir / f"portfolio_rebalance_monitor_{config.portfolio_id}.json"
    state = _load_state(state_path)
    annual_due = (
        (observed_at.month, observed_at.day)
        >= (config.annual_review_month, config.annual_review_day)
        and int(state.get("last_annual_review_year") or 0) < observed_at.year
    )
    if signal == "OK" and annual_due:
        signal = "ANNUAL_REVIEW"
    last_alert = state.get("last_alert_date_by_signal", {}).get(signal)
    cooling_down = _is_cooling_down(last_alert, observed_at.date(), config.reminder_cooldown_days)
    notification = NotificationResult("SKIPPED", "当前无需重平衡通知")
    if signal in ACTIONABLE_SIGNALS and push and not dry_run and not cooling_down:
        notification = notifier(*build_notification(signal, snapshot, config))
        if notification.status == "SUCCESS":
            alerts = dict(state.get("last_alert_date_by_signal", {}))
            alerts[signal] = observed_at.date().isoformat()
            state["last_alert_date_by_signal"] = alerts
            if signal == "ANNUAL_REVIEW":
                state["last_annual_review_year"] = observed_at.year
    result: dict[str, object] = {
        "status": "SUCCESS",
        "signal": signal,
        "snapshot": {
            **asdict(snapshot),
            "trade_date": snapshot.trade_date.isoformat(),
        },
        "notification_status": notification.status,
        "automatic_trade": False,
    }
    if not dry_run:
        state.update(
            {
                "last_observation": result,
                "consecutive_failures": 0,
                "updated_at": observed_at.isoformat(),
            }
        )
        _save_state(state_path, state)
    return result


def record_failure_and_maybe_notify(
    config: PortfolioRebalanceConfig,
    paths: RuntimePaths,
    error: Exception,
    *,
    push: bool,
    now: datetime | None = None,
    notifier: Callable[[str, str], NotificationResult] = send_bark_notification,
) -> NotificationResult:
    observed_at = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    state_path = paths.state_dir / f"portfolio_rebalance_monitor_{config.portfolio_id}.json"
    state = _load_state(state_path)
    failures = int(state.get("consecutive_failures") or 0) + 1
    state["consecutive_failures"] = failures
    state["last_error"] = str(error)
    state["updated_at"] = observed_at.isoformat()
    notification = NotificationResult("SKIPPED", "尚未达到连续失败提醒阈值")
    if (
        push
        and failures >= config.failure_alert_after
        and state.get("last_failure_alert_date") != observed_at.date().isoformat()
    ):
        notification = notifier(
            f"{config.display_name} 重平衡监控异常",
            f"已连续失败 {failures} 次：{error}。任务只监控、不交易，请人工检查行情和仓位基准。",
        )
        if notification.status == "SUCCESS":
            state["last_failure_alert_date"] = observed_at.date().isoformat()
    _save_state(state_path, state)
    return notification


def _is_cooling_down(last_alert_date: object, observed_date: date, cooldown_days: int) -> bool:
    try:
        last_date = date.fromisoformat(str(last_alert_date))
    except ValueError:
        return False
    elapsed = (observed_date - last_date).days
    return 0 <= elapsed < cooldown_days


def _load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
