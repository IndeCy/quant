"""场内 ETF 价格与参考净值折溢价监控，只提醒、不交易。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
import json
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backtest.fetcher import get_realtime_quote
from data.calendar import TradingCalendar
from data.market_snapshot import create_fund_market_snapshot
from runtime.notification_config import NotificationResult, send_bark_notification
from runtime.paths import RuntimePaths


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MARKET_WINDOWS = (
    (time(9, 35), time(11, 30, 59)),
    (time(13, 5), time(14, 55, 59)),
)
ACTIONABLE_SIGNALS = {
    "BUY_REVIEW",
    "BUY_REVIEW_STRONG",
    "BUY_REVIEW_ACCELERATED",
    "HIGH_PREMIUM",
    "ABNORMAL_DISCOUNT",
    "WEEKLY_REVIEW",
    "BELOW_MA5_WARNING",
}


@dataclass(frozen=True)
class EtfPremiumMonitorConfig:
    """单只 ETF 的人工建仓提醒参数。"""

    symbol: str
    display_name: str
    cost: float
    current_weight: float
    target_weight: float
    tranche_weight: float
    buy_review_premium_pct: float
    strong_buy_review_premium_pct: float
    high_premium_warning_pct: float
    max_quote_age_minutes: int = 15
    failure_alert_after: int = 3
    abnormal_discount_warning_pct: float | None = None
    buy_alert_cooldown_days: int = 1
    warning_alert_cooldown_days: int = 1
    trend_symbol: str | None = None
    trend_ma_days: int = 200
    trend_lookback_days: int = 250
    accelerated_drawdown_pct: float | None = None
    max_history_age_days: int = 20
    weekly_status_reminder: bool = False
    quantity: float = 0.0
    below_ma5_warning: bool = False


@dataclass(frozen=True)
class EtfPremiumSnapshot:
    """经一致性校验的场内价格与参考净值快照。"""

    symbol: str
    display_name: str
    quote_time: datetime
    price: float
    change_pct: float
    premium_pct: float
    reference_nav: float
    previous_nav: float


@dataclass(frozen=True)
class EtfTrendSnapshot:
    """ETF 复权净值走势，仅用于调整人工建仓复核节奏。"""

    trade_date: date
    adjusted_close: float
    return_20d_pct: float
    ma5_gap_pct: float
    ma_gap_pct: float
    drawdown_pct: float


def load_monitor_config(path: Path) -> EtfPremiumMonitorConfig:
    """读取非敏感监控参数并做边界校验。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = EtfPremiumMonitorConfig(**payload)
    if len(config.symbol) != 6 or not config.symbol.isdigit():
        raise ValueError("symbol 必须是6位证券代码")
    if not 0 <= config.current_weight < config.target_weight <= 1:
        raise ValueError("仓位必须满足 0 <= current_weight < target_weight <= 1")
    if not 0 < config.tranche_weight <= config.target_weight - config.current_weight:
        raise ValueError("tranche_weight 必须为正且不超过待建仓仓位")
    if not (
        config.strong_buy_review_premium_pct
        <= config.buy_review_premium_pct
        < config.high_premium_warning_pct
    ):
        raise ValueError("溢价阈值顺序无效")
    if config.max_quote_age_minutes <= 0 or config.failure_alert_after <= 0:
        raise ValueError("时效和失败次数阈值必须为正")
    if config.cost < 0 or config.quantity < 0:
        raise ValueError("持仓成本和数量不能为负")
    if (
        config.abnormal_discount_warning_pct is not None
        and config.abnormal_discount_warning_pct >= config.strong_buy_review_premium_pct
    ):
        raise ValueError("异常折价阈值必须低于强复核溢价阈值")
    if config.buy_alert_cooldown_days <= 0 or config.warning_alert_cooldown_days <= 0:
        raise ValueError("提醒冷却天数必须为正")
    if config.trend_symbol is not None:
        if len(config.trend_symbol) != 9 or config.trend_symbol[6:] not in {".SH", ".SZ"}:
            raise ValueError("trend_symbol 必须是带交易所后缀的证券代码")
        if config.trend_ma_days < 20 or config.trend_lookback_days < config.trend_ma_days:
            raise ValueError("走势窗口必须满足 lookback >= ma >= 20")
        if config.accelerated_drawdown_pct is None or config.accelerated_drawdown_pct >= 0:
            raise ValueError("启用走势后 accelerated_drawdown_pct 必须为负数")
        if config.max_history_age_days <= 0:
            raise ValueError("历史行情最大时效必须为正")
    return config


def is_monitoring_window(now: datetime) -> bool:
    """仅在沪深交易所工作日的指定盘中窗口读取行情。"""
    local = now.astimezone(SHANGHAI_TZ)
    if not TradingCalendar().is_trading_day(local.date()):
        return False
    return any(start <= local.time() <= end for start, end in MARKET_WINDOWS)


def load_trend_snapshot(
    config: EtfPremiumMonitorConfig,
    paths: RuntimePaths,
    observed_at: datetime,
) -> EtfTrendSnapshot | None:
    """通过生产基金快照门面只读计算复权趋势。"""
    if config.trend_symbol is None:
        return None
    required_rows = max(config.trend_ma_days, config.trend_lookback_days, 21) + 1
    lookback_start = f"{observed_at.year - 2:04d}{observed_at.month:02d}{observed_at.day:02d}"
    snapshot = create_fund_market_snapshot(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        observed_at.strftime("%Y%m%d"),
        lookback_start=lookback_start,
        adjust_policy="qfq",
    )
    frame = snapshot.load_daily_bars(config.trend_symbol).tail(required_rows)
    if len(frame) < max(config.trend_ma_days, config.trend_lookback_days, 21):
        raise RuntimeError(f"{config.trend_symbol} 走势历史不足")
    trade_date = frame.index[-1].date()
    if (observed_at.date() - trade_date).days > config.max_history_age_days:
        raise RuntimeError(f"{config.trend_symbol} 走势历史过期: {trade_date.isoformat()}")
    closes = frame["close"].astype(float).tolist()
    adjusted_close = closes[-1]
    ma = sum(closes[-config.trend_ma_days :]) / config.trend_ma_days
    ma5 = sum(closes[-5:]) / 5
    lookback = closes[-config.trend_lookback_days :]
    return EtfTrendSnapshot(
        trade_date=trade_date,
        adjusted_close=adjusted_close,
        return_20d_pct=(adjusted_close / closes[-21] - 1) * 100,
        ma5_gap_pct=(adjusted_close / ma5 - 1) * 100,
        ma_gap_pct=(adjusted_close / ma - 1) * 100,
        drawdown_pct=(adjusted_close / max(lookback) - 1) * 100,
    )


def fetch_snapshot(
    config: EtfPremiumMonitorConfig,
    *,
    now: datetime | None = None,
    quote_loader: Callable[[list[str]], dict[str, dict[str, Any]]] = get_realtime_quote,
) -> EtfPremiumSnapshot:
    """获取实时快照，并校验价格、参考净值、溢价和时间的一致性。"""
    observed_at = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    quote = quote_loader([config.symbol]).get(config.symbol)
    if not quote:
        raise RuntimeError(f"{config.symbol} 实时行情为空")
    quote_time = datetime.strptime(str(quote.get("quote_time", "")), "%Y%m%d%H%M%S").replace(
        tzinfo=SHANGHAI_TZ
    )
    price = float(quote.get("price") or 0)
    reference_nav = float(quote.get("reference_nav") or 0)
    premium_pct = float(quote.get("premium_pct"))
    if price <= 0 or reference_nav <= 0:
        raise RuntimeError("实时价格或参考净值无效")
    if quote_time.date() != observed_at.date():
        raise RuntimeError(f"行情日期过期: {quote_time:%Y-%m-%d}")
    age_minutes = (observed_at - quote_time).total_seconds() / 60
    if age_minutes < -2 or age_minutes > config.max_quote_age_minutes:
        raise RuntimeError(f"行情时间异常: age_minutes={age_minutes:.1f}")
    calculated = (price / reference_nav - 1) * 100
    if abs(calculated - premium_pct) > 0.15:
        raise RuntimeError(
            f"源溢价与价格/参考净值不一致: source={premium_pct:.2f}% calculated={calculated:.2f}%"
        )
    return EtfPremiumSnapshot(
        symbol=config.symbol,
        display_name=str(quote.get("name") or config.display_name),
        quote_time=quote_time,
        price=price,
        change_pct=float(quote.get("change_pct") or 0),
        premium_pct=premium_pct,
        reference_nav=reference_nav,
        previous_nav=float(quote.get("previous_nav") or 0),
    )


def classify_snapshot(
    snapshot: EtfPremiumSnapshot,
    config: EtfPremiumMonitorConfig,
    trend: EtfTrendSnapshot | None = None,
) -> str:
    """把观测映射为人工复核信号，不产生订单。"""
    premium = snapshot.premium_pct
    if (
        config.abnormal_discount_warning_pct is not None
        and premium <= config.abnormal_discount_warning_pct
    ):
        return "ABNORMAL_DISCOUNT"
    if premium >= config.high_premium_warning_pct:
        return "HIGH_PREMIUM"
    if config.below_ma5_warning and trend is not None and trend.ma5_gap_pct < 0:
        return "BELOW_MA5_WARNING"
    if premium > config.buy_review_premium_pct:
        return "WAIT"
    if (
        trend is not None
        and config.accelerated_drawdown_pct is not None
        and trend.drawdown_pct <= config.accelerated_drawdown_pct
    ):
        return "BUY_REVIEW_ACCELERATED"
    if premium <= config.strong_buy_review_premium_pct:
        return "BUY_REVIEW_STRONG"
    return "BUY_REVIEW"


def build_notification(
    signal: str,
    snapshot: EtfPremiumSnapshot,
    config: EtfPremiumMonitorConfig,
    trend: EtfTrendSnapshot | None = None,
) -> tuple[str, str]:
    """生成明确要求人工核对 IOPV 的 Bark 内容。"""
    gap = config.target_weight - config.current_weight
    common = (
        f"{snapshot.symbol} 价格 {snapshot.price:.3f}，涨跌 {snapshot.change_pct:+.2f}%，"
        f"源参考净值/IOPV {snapshot.reference_nav:.4f}，溢价 {snapshot.premium_pct:.2f}%，"
        f"行情时间 {snapshot.quote_time:%H:%M:%S}。当前仓位 {config.current_weight:.0%}，"
        f"目标 {config.target_weight:.0%}，待建 {gap:.0%}。"
    )
    if config.quantity > 0:
        common += f"当前持有 {config.quantity:g} 份，显示成本 {config.cost:.3f}。"
    trend_text = ""
    if trend is not None:
        trend_text = (
            f"走势截至 {trend.trade_date:%Y-%m-%d}：20日 {trend.return_20d_pct:+.2f}%，"
            f"相对MA5 {trend.ma5_gap_pct:+.2f}%，"
            f"相对{config.trend_ma_days}日均线 {trend.ma_gap_pct:+.2f}%，"
            f"{config.trend_lookback_days}日高点回撤 {trend.drawdown_pct:.2f}%。"
        )
    manual_check = "仅作建仓复核提醒；下单前请在券商端再次核对实时IOPV、申赎和成交价，不会自动交易。"
    two_tranches = min(config.tranche_weight * 2, gap)
    if signal == "BUY_REVIEW_STRONG":
        title = f"{snapshot.symbol} 低溢价：复核两档"
        action = f"溢价已不高于 {config.strong_buy_review_premium_pct:.2f}%，可复核最多 {two_tranches:.1%} 总资产的一次建仓。"
    elif signal == "BUY_REVIEW_ACCELERATED":
        title = f"{snapshot.symbol} 回撤加仓窗口复核"
        action = (
            f"溢价合格且走势回撤达到 {config.accelerated_drawdown_pct:.1f}% 节奏线，"
            f"可复核最多 {two_tranches:.1%} 总资产的加仓；不要一次补满目标仓位。"
        )
    elif signal == "BUY_REVIEW":
        title = f"{snapshot.symbol} 建仓窗口复核"
        action = f"溢价已不高于 {config.buy_review_premium_pct:.2f}%，可复核 {config.tranche_weight:.1%} 总资产的一档建仓。"
    elif signal == "HIGH_PREMIUM":
        title = f"{snapshot.symbol} 高溢价提醒"
        action = f"溢价已达到 {config.high_premium_warning_pct:.2f}% 风险线，继续暂停加仓。"
    elif signal == "ABNORMAL_DISCOUNT":
        title = f"{snapshot.symbol} 异常折价提醒"
        action = (
            f"折价已达到 {config.abnormal_discount_warning_pct:.2f}% 异常线，先暂停加仓并核对"
            "IOPV、停牌、申赎与行情时点，不能把异常折价直接当便宜。"
        )
    elif signal == "WEEKLY_REVIEW":
        title = f"{snapshot.symbol} 每周建仓复核"
        action = (
            f"本周溢价尚未进入不高于 {config.buy_review_premium_pct:.2f}% 的常规窗口。"
            "仍按激进周频提供状态，由你自行判断是否买入；这不是自动交易信号。"
        )
    elif signal == "BELOW_MA5_WARNING":
        title = f"{snapshot.symbol} 收盘跌破MA5风险提醒"
        action = (
            f"截至 {trend.trade_date:%Y-%m-%d} 的复权收盘价低于MA5 "
            f"{abs(trend.ma5_gap_pct):.2f}%，短期走势转弱。"
            "这是风险复核，不等于自动卖出或禁止加仓；若继续买入，请缩小档位并结合溢价判断。"
        )
    else:
        raise ValueError(f"不可通知的信号: {signal}")
    return title, f"{action}{common}{trend_text}{manual_check}"


def run_monitor(
    config: EtfPremiumMonitorConfig,
    paths: RuntimePaths,
    *,
    push: bool,
    dry_run: bool = False,
    now: datetime | None = None,
    quote_loader: Callable[[list[str]], dict[str, dict[str, Any]]] = get_realtime_quote,
    notifier: Callable[[str, str], NotificationResult] = send_bark_notification,
    trend_loader: Callable[
        [EtfPremiumMonitorConfig, RuntimePaths, datetime], EtfTrendSnapshot | None
    ] = load_trend_snapshot,
) -> dict[str, Any]:
    """执行一次观测；普通信号按周冷却，风险信号每天最多提醒一次。"""
    observed_at = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    if not dry_run and not is_monitoring_window(observed_at):
        return {"status": "SKIPPED", "reason": "outside_monitoring_window"}
    snapshot = fetch_snapshot(config, now=observed_at, quote_loader=quote_loader)
    trend = trend_loader(config, paths, observed_at)
    signal = classify_snapshot(snapshot, config, trend)
    if signal == "WAIT" and config.weekly_status_reminder:
        signal = "WEEKLY_REVIEW"
    state_path = paths.state_dir / f"etf_premium_monitor_{config.symbol}.json"
    state = _load_state(state_path)
    cooldown_days = (
        config.warning_alert_cooldown_days
        if signal in {"HIGH_PREMIUM", "ABNORMAL_DISCOUNT", "BELOW_MA5_WARNING"}
        else config.buy_alert_cooldown_days
    )
    already_sent = _alert_is_cooling_down(
        state.get("last_alert_date_by_signal", {}).get(signal),
        observed_at.date(),
        cooldown_days,
    )
    notification = NotificationResult("SKIPPED", "当前无动作信号")
    if signal in ACTIONABLE_SIGNALS and push and not dry_run and not already_sent:
        notification = notifier(*build_notification(signal, snapshot, config, trend))
        if notification.status == "SUCCESS":
            alerts = dict(state.get("last_alert_date_by_signal", {}))
            alerts[signal] = observed_at.date().isoformat()
            state["last_alert_date_by_signal"] = alerts
    result = {
        "status": "SUCCESS",
        "signal": signal,
        "snapshot": {
            **asdict(snapshot),
            "quote_time": snapshot.quote_time.isoformat(),
        },
        "trend": (
            {
                **asdict(trend),
                "trade_date": trend.trade_date.isoformat(),
            }
            if trend is not None
            else None
        ),
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
    config: EtfPremiumMonitorConfig,
    paths: RuntimePaths,
    error: Exception,
    *,
    push: bool,
    now: datetime | None = None,
    notifier: Callable[[str, str], NotificationResult] = send_bark_notification,
) -> NotificationResult:
    """连续失败达到阈值时每天发送一次数据故障提醒。"""
    observed_at = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    state_path = paths.state_dir / f"etf_premium_monitor_{config.symbol}.json"
    state = _load_state(state_path)
    failures = int(state.get("consecutive_failures", 0)) + 1
    state["consecutive_failures"] = failures
    state["last_error"] = str(error)
    state["updated_at"] = observed_at.isoformat()
    notification = NotificationResult("SKIPPED", "尚未达到连续失败提醒阈值")
    last_failure_alert = str(state.get("last_failure_alert_date", ""))
    if (
        push
        and failures >= config.failure_alert_after
        and last_failure_alert != observed_at.date().isoformat()
    ):
        notification = notifier(
            f"{config.symbol} 溢价监控数据异常",
            f"已连续失败 {failures} 次：{error}。任务只监控、不交易，请人工检查行情源。",
        )
        if notification.status == "SUCCESS":
            state["last_failure_alert_date"] = observed_at.date().isoformat()
    _save_state(state_path, state)
    return notification


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _alert_is_cooling_down(
    last_alert_date: object,
    observed_date: date,
    cooldown_days: int,
) -> bool:
    try:
        last_date = date.fromisoformat(str(last_alert_date))
    except ValueError:
        return False
    elapsed_days = (observed_date - last_date).days
    return 0 <= elapsed_days < cooldown_days


def _save_state(path: Path, state: dict[str, Any]) -> None:
    """原子替换仅供提醒去重的运行状态，不作为交易事实输入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
