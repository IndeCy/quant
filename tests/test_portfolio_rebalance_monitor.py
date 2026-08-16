from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from runtime.notification_config import NotificationResult
from runtime.paths import RuntimePaths
from runtime.portfolio_rebalance_monitor import (
    SHANGHAI_TZ,
    PortfolioAssetConfig,
    PortfolioRebalanceConfig,
    PortfolioWeightSnapshot,
    build_notification,
    classify_snapshot,
    load_rebalance_config,
    run_monitor,
)


def _config() -> PortfolioRebalanceConfig:
    return PortfolioRebalanceConfig(
        portfolio_id="test",
        display_name="测试组合",
        reference_date=date(2026, 7, 31),
        assets=(
            PortfolioAssetConfig("513500.SH", "标普", 0.04, 0.30),
            PortfolioAssetConfig("518880.SH", "黄金", 0.04, 0.25),
            PortfolioAssetConfig("511010.SH", "国债", 0.04, 0.25),
        ),
        cash_current_weight=0.88,
        cash_target_weight=0.20,
        rebalance_band_pp=10.0,
        reminder_cooldown_days=7,
    )


def _snapshot(weights: dict[str, float]) -> PortfolioWeightSnapshot:
    return PortfolioWeightSnapshot(
        trade_date=date(2026, 7, 31),
        weights=weights,
        prices={"513500.SH": 2.5, "518880.SH": 8.4, "511010.SH": 141.0},
    )


def test_project_config_uses_declared_weights_and_targets() -> None:
    path = Path(__file__).resolve().parents[1] / "config/portfolio_rebalance.json"
    config = load_rebalance_config(path)

    assert [asset.current_weight for asset in config.assets] == [
        0.0427548,
        0.0697086,
        0.1128856,
    ]
    assert [asset.target_weight for asset in config.assets] == [0.30, 0.25, 0.25]
    assert [asset.quantity for asset in config.assets] == [7900, 3900, 400]
    assert [asset.cost for asset in config.assets] == [2.505, 8.607, 140.932]
    assert config.cash_current_weight == 0.774651
    assert config.cash_target_weight == 0.20
    assert config.total_capital == 500_000


def test_build_phase_uses_cash_without_sell_rebalance() -> None:
    snapshot = _snapshot(
        {"513500.SH": 0.04, "518880.SH": 0.04, "511010.SH": 0.04, "CASH": 0.88}
    )

    assert classify_snapshot(snapshot, _config()) == "BUILD_REVIEW"
    title, body = build_notification("BUILD_REVIEW", snapshot, _config())
    assert "建仓" in title
    assert "优先使用现金补低配" in body
    assert "不为配平卖出" in body


def test_completed_portfolio_only_rebalances_outside_ten_point_band() -> None:
    within_band = _snapshot(
        {"513500.SH": 0.35, "518880.SH": 0.22, "511010.SH": 0.23, "CASH": 0.20}
    )
    breached = _snapshot(
        {"513500.SH": 0.45, "518880.SH": 0.19, "511010.SH": 0.21, "CASH": 0.15}
    )

    assert classify_snapshot(within_band, _config()) == "OK"
    assert classify_snapshot(breached, _config()) == "REBALANCE_REQUIRED"


def test_rebalance_reminder_repeats_weekly_not_daily(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    notifications: list[str] = []
    snapshot = _snapshot(
        {"513500.SH": 0.04, "518880.SH": 0.04, "511010.SH": 0.04, "CASH": 0.88}
    )

    def notify(title: str, body: str) -> NotificationResult:
        notifications.append(f"{title}:{body}")
        return NotificationResult("SUCCESS", "sent")

    loader = lambda *_: snapshot
    first = run_monitor(
        _config(),
        paths,
        push=True,
        now=datetime(2026, 7, 29, 9, 25, tzinfo=SHANGHAI_TZ),
        snapshot_loader=loader,
        notifier=notify,
    )
    next_day = run_monitor(
        _config(),
        paths,
        push=True,
        now=datetime(2026, 7, 30, 9, 25, tzinfo=SHANGHAI_TZ),
        snapshot_loader=loader,
        notifier=notify,
    )
    next_week = run_monitor(
        _config(),
        paths,
        push=True,
        now=datetime(2026, 8, 5, 9, 25, tzinfo=SHANGHAI_TZ),
        snapshot_loader=loader,
        notifier=notify,
    )

    assert first["notification_status"] == "SUCCESS"
    assert next_day["notification_status"] == "SKIPPED"
    assert next_week["notification_status"] == "SUCCESS"
    assert len(notifications) == 2
    assert next_week["automatic_trade"] is False


def test_annual_review_fires_inside_bands(tmp_path: Path) -> None:
    snapshot = _snapshot(
        {"513500.SH": 0.30, "518880.SH": 0.25, "511010.SH": 0.25, "CASH": 0.20}
    )
    result = run_monitor(
        _config(),
        RuntimePaths(tmp_path),
        push=False,
        dry_run=True,
        now=datetime(2026, 7, 31, 9, 25, tzinfo=SHANGHAI_TZ),
        snapshot_loader=lambda *_: snapshot,
    )

    assert result["signal"] == "ANNUAL_REVIEW"
