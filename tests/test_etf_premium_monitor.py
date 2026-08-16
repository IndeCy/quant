"""513500 价格与溢价提醒测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from runtime.etf_premium_monitor import (
    SHANGHAI_TZ,
    EtfPremiumMonitorConfig,
    EtfTrendSnapshot,
    build_notification,
    classify_snapshot,
    fetch_snapshot,
    is_monitoring_window,
    run_monitor,
)
from runtime.notification_config import NotificationResult
from runtime.paths import RuntimePaths


def _config() -> EtfPremiumMonitorConfig:
    return EtfPremiumMonitorConfig(
        symbol="513500",
        display_name="标普500ETF博时",
        cost=2.505,
        current_weight=0.04,
        target_weight=0.30,
        tranche_weight=0.02,
        buy_review_premium_pct=2.0,
        strong_buy_review_premium_pct=1.0,
        high_premium_warning_pct=6.0,
        max_quote_age_minutes=15,
        failure_alert_after=3,
    )


def _quote(
    premium_pct: float = 1.8,
    quote_time: str = "20260729100000",
) -> dict[str, dict[str, object]]:
    reference_nav = 2.4
    return {
        "513500": {
            "name": "标普500ETF博时",
            "price": reference_nav * (1 + premium_pct / 100),
            "change_pct": 0.5,
            "quote_time": quote_time,
            "premium_pct": premium_pct,
            "reference_nav": reference_nav,
            "previous_nav": 2.39,
        }
    }


def _trend(drawdown_pct: float, ma5_gap_pct: float = 1.0) -> EtfTrendSnapshot:
    return EtfTrendSnapshot(
        trade_date=date(2026, 7, 28),
        adjusted_close=8.4,
        return_20d_pct=-2.0,
        ma5_gap_pct=ma5_gap_pct,
        ma_gap_pct=3.0,
        drawdown_pct=drawdown_pct,
    )


def test_monitoring_window_excludes_opening_and_lunch() -> None:
    assert not is_monitoring_window(datetime(2026, 7, 29, 9, 30, tzinfo=SHANGHAI_TZ))
    assert is_monitoring_window(datetime(2026, 7, 29, 9, 35, tzinfo=SHANGHAI_TZ))
    assert not is_monitoring_window(datetime(2026, 7, 29, 12, 0, tzinfo=SHANGHAI_TZ))
    assert is_monitoring_window(datetime(2026, 7, 29, 14, 55, tzinfo=SHANGHAI_TZ))
    assert is_monitoring_window(datetime(2026, 7, 29, 14, 55, 59, tzinfo=SHANGHAI_TZ))
    assert not is_monitoring_window(datetime(2026, 10, 1, 10, 0, tzinfo=SHANGHAI_TZ))


def test_snapshot_checks_source_premium_against_price_and_reference_nav() -> None:
    snapshot = fetch_snapshot(
        _config(),
        now=datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ),
        quote_loader=lambda _: _quote(1.8),
    )
    assert snapshot.price == 2.4432
    assert snapshot.premium_pct == 1.8
    assert classify_snapshot(snapshot, _config()) == "BUY_REVIEW"


def test_signal_thresholds_are_stable() -> None:
    now = datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ)
    assert classify_snapshot(fetch_snapshot(_config(), now=now, quote_loader=lambda _: _quote(1.0)), _config()) == "BUY_REVIEW_STRONG"
    assert classify_snapshot(fetch_snapshot(_config(), now=now, quote_loader=lambda _: _quote(2.0)), _config()) == "BUY_REVIEW"
    assert classify_snapshot(fetch_snapshot(_config(), now=now, quote_loader=lambda _: _quote(5.0)), _config()) == "WAIT"
    assert classify_snapshot(fetch_snapshot(_config(), now=now, quote_loader=lambda _: _quote(6.0)), _config()) == "HIGH_PREMIUM"


def test_local_etf_signal_checks_abnormal_discount_and_drawdown_pace() -> None:
    now = datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ)
    config = replace(
        _config(),
        buy_review_premium_pct=0.2,
        strong_buy_review_premium_pct=-0.15,
        high_premium_warning_pct=0.5,
        abnormal_discount_warning_pct=-0.5,
        trend_symbol="518880.SH",
        accelerated_drawdown_pct=-8.0,
    )
    abnormal = fetch_snapshot(config, now=now, quote_loader=lambda _: _quote(-0.6))
    fair = fetch_snapshot(config, now=now, quote_loader=lambda _: _quote(0.1))

    assert classify_snapshot(abnormal, config, _trend(-10.0)) == "ABNORMAL_DISCOUNT"
    assert classify_snapshot(fair, config, _trend(-9.0)) == "BUY_REVIEW_ACCELERATED"
    assert classify_snapshot(fair, config, _trend(-3.0)) == "BUY_REVIEW"


def test_completed_close_below_ma5_has_daily_risk_priority() -> None:
    now = datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ)
    config = replace(_config(), below_ma5_warning=True)
    snapshot = fetch_snapshot(config, now=now, quote_loader=lambda _: _quote(1.8))
    trend = _trend(-3.0, ma5_gap_pct=-0.6)

    assert classify_snapshot(snapshot, config, trend) == "BELOW_MA5_WARNING"
    title, body = build_notification("BELOW_MA5_WARNING", snapshot, config, trend)
    assert "跌破MA5" in title
    assert "低于MA5 0.60%" in body
    assert "不等于自动卖出" in body


def test_action_notification_requires_manual_iopv_check() -> None:
    snapshot = fetch_snapshot(
        _config(),
        now=datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ),
        quote_loader=lambda _: _quote(1.8),
    )
    title, body = build_notification("BUY_REVIEW", snapshot, _config())
    assert "建仓窗口" in title
    assert "券商端再次核对实时IOPV" in body
    assert "不会自动交易" in body


def test_wait_zone_still_sends_weekly_status_when_enabled(tmp_path: Path) -> None:
    config = replace(
        _config(),
        weekly_status_reminder=True,
        buy_alert_cooldown_days=7,
    )
    notifications: list[str] = []

    def notify(title: str, body: str) -> NotificationResult:
        notifications.append(f"{title}:{body}")
        return NotificationResult("SUCCESS", "sent")

    result = run_monitor(
        config,
        RuntimePaths(tmp_path),
        push=True,
        now=datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ),
        quote_loader=lambda _: _quote(5.0),
        notifier=notify,
    )

    assert result["signal"] == "WEEKLY_REVIEW"
    assert result["notification_status"] == "SUCCESS"
    assert "每周建仓复核" in notifications[0]
    assert "由你自行判断" in notifications[0]
    assert result["automatic_trade"] is False


def test_same_signal_pushes_at_most_once_per_day(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    notifications: list[str] = []

    def notify(title: str, body: str) -> NotificationResult:
        notifications.append(f"{title}:{body}")
        return NotificationResult("SUCCESS", "sent")

    kwargs = {
        "push": True,
        "now": datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ),
        "quote_loader": lambda _: _quote(1.8),
        "notifier": notify,
    }
    first = run_monitor(_config(), paths, **kwargs)
    second = run_monitor(_config(), paths, **kwargs)

    assert first["notification_status"] == "SUCCESS"
    assert second["notification_status"] == "SKIPPED"
    assert len(notifications) == 1
    assert first["automatic_trade"] is False


def test_buy_signal_honors_multi_day_cooldown(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    notifications: list[str] = []
    config = replace(_config(), buy_alert_cooldown_days=28)

    def notify(title: str, body: str) -> NotificationResult:
        notifications.append(f"{title}:{body}")
        return NotificationResult("SUCCESS", "sent")

    first = run_monitor(
        config,
        paths,
        now=datetime(2026, 7, 1, 10, 1, tzinfo=SHANGHAI_TZ),
        push=True,
        quote_loader=lambda _: _quote(1.8, "20260701100000"),
        notifier=notify,
    )
    cooling_down = run_monitor(
        config,
        paths,
        now=datetime(2026, 7, 20, 10, 1, tzinfo=SHANGHAI_TZ),
        quote_loader=lambda _: _quote(1.8, "20260720100000"),
        push=True,
        notifier=notify,
    )
    after_cooldown = run_monitor(
        config,
        paths,
        now=datetime(2026, 7, 29, 10, 1, tzinfo=SHANGHAI_TZ),
        push=True,
        quote_loader=lambda _: _quote(1.8),
        notifier=notify,
    )

    assert first["notification_status"] == "SUCCESS"
    assert cooling_down["notification_status"] == "SKIPPED"
    assert after_cooldown["notification_status"] == "SUCCESS"
    assert len(notifications) == 2
