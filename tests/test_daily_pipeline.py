"""统一每日交易流水线测试。"""

from pathlib import Path

import pandas as pd
import pytest

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.daily_pipeline import PIPELINE_STRATEGY_ID, run_production_daily_pipeline
from runtime.notification_config import NotificationResult
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_daily_pipeline_runs_data_then_strategy_batch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """手动补跑和调度应共享同一条原子流水线。"""
    paths = RuntimePaths(tmp_path / "runtime")
    calls: list[str] = []
    notifications: list[str] = []

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: calls.append(f"data:{trade_date}") or "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr(
        "runtime.daily_pipeline.run_strategy_batch",
        lambda paths, push=False, trade_date=None: calls.append(f"strategy:{push}:{trade_date}") or _strategy_summary(trade_date),
    )
    def capture_notification(title: str, body: str) -> NotificationResult:
        notifications.append(body)
        return NotificationResult("SUCCESS", "sent")

    monkeypatch.setattr("runtime.daily_pipeline.send_bark_notification", capture_notification)

    summary = run_production_daily_pipeline(paths=paths, push=True, source="manual")
    repository = SystemRepository(paths.system_state_path)
    run = repository.latest_run(PIPELINE_STRATEGY_ID)

    assert len(calls) == 2
    assert calls[0].startswith("data:")
    assert calls[1].startswith("strategy:False:")
    assert summary["status"] == "SUCCESS"
    assert run is not None
    assert run["status"] == "SUCCESS"
    assert "notification=SUCCESS" in run["message"]
    assert [item["step_name"] for item in repository.list_run_steps(PIPELINE_STRATEGY_ID, summary["trade_date"])] == [
        "data_update",
        "data_notification",
        "data_quality_gate",
        "strategy_batch",
        "notification",
    ]
    assert "数据更新" in notifications[0]


def test_daily_pipeline_stops_strategy_when_data_update_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """数据失败时必须停止策略执行，避免用旧数据生成交易建议。"""
    paths = RuntimePaths(tmp_path / "runtime")
    strategy_called = False

    def fail_data_update(trade_date: str | None = None) -> str:
        raise RuntimeError("tushare failed")

    def run_strategy(paths: RuntimePaths, push: bool = False, trade_date: str | None = None) -> dict[str, object]:
        nonlocal strategy_called
        strategy_called = True
        return _strategy_summary(trade_date)

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", fail_data_update)
    monkeypatch.setattr("runtime.daily_pipeline.run_strategy_batch", run_strategy)
    monkeypatch.setattr(
        "runtime.daily_pipeline.send_bark_notification",
        lambda title, body: NotificationResult("SUCCESS", "sent"),
    )

    with pytest.raises(RuntimeError, match="tushare failed"):
        run_production_daily_pipeline(paths=paths, push=True, source="scheduler")

    repository = SystemRepository(paths.system_state_path)
    run = repository.latest_run(PIPELINE_STRATEGY_ID)
    assert strategy_called is False
    assert run is not None
    assert run["status"] == "FAILED"
    steps = repository.list_run_steps(PIPELINE_STRATEGY_ID, run["trade_date"])
    assert steps[0]["step_name"] == "data_update"
    assert steps[0]["status"] == "FAILED"
    assert steps[1]["step_name"] == "data_notification"
    assert steps[2]["step_name"] == "notification"


def test_daily_pipeline_stops_strategy_when_data_quality_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """数据更新成功但质量门禁失败时，也必须停止策略执行。"""
    paths = RuntimePaths(tmp_path / "runtime")
    strategy_called = False

    def fail_quality_gate(*args, **kwargs) -> dict[str, object]:
        raise RuntimeError("复权因子缺失")

    def run_strategy(paths: RuntimePaths, push: bool = False, trade_date: str | None = None) -> dict[str, object]:
        nonlocal strategy_called
        strategy_called = True
        return _strategy_summary(trade_date)

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", fail_quality_gate)
    monkeypatch.setattr("runtime.daily_pipeline.run_strategy_batch", run_strategy)
    monkeypatch.setattr(
        "runtime.daily_pipeline.send_bark_notification",
        lambda title, body: NotificationResult("SUCCESS", "sent"),
    )

    with pytest.raises(RuntimeError, match="复权因子缺失"):
        run_production_daily_pipeline(paths=paths, push=True, source="scheduler")

    repository = SystemRepository(paths.system_state_path)
    run = repository.latest_run(PIPELINE_STRATEGY_ID)
    assert strategy_called is False
    assert run is not None
    assert run["status"] == "FAILED"
    steps = repository.list_run_steps(PIPELINE_STRATEGY_ID, run["trade_date"])
    assert [item["step_name"] for item in steps] == [
        "data_update",
        "data_notification",
        "data_quality_gate",
        "notification",
    ]
    assert steps[2]["status"] == "FAILED"


def test_daily_pipeline_records_missing_bark_when_push_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """push 开启但 Bark 未配置时，应写入日志而不是静默跳过。"""
    paths = RuntimePaths(tmp_path / "runtime")

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr("runtime.daily_pipeline.run_strategy_batch", lambda paths, push=False, trade_date=None: _strategy_summary(trade_date))
    monkeypatch.setattr(
        "runtime.daily_pipeline.send_bark_notification",
        lambda title, body: NotificationResult("SKIPPED", "Bark未配置"),
    )

    summary = run_production_daily_pipeline(paths=paths, push=True, source="manual")
    repository = SystemRepository(paths.system_state_path)
    steps = repository.list_run_steps(PIPELINE_STRATEGY_ID, str(summary["trade_date"]))

    notification_step = [item for item in steps if item["step_name"] == "notification"][0]
    assert notification_step["status"] == "SKIPPED"
    assert "Bark未配置" in notification_step["message"]


def test_daily_pipeline_notification_uses_unified_operation_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bark 摘要应展示每个策略统一关注字段，而不是只报成功失败。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_monitoring(paths)
    captured: list[dict[str, str]] = []

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr("runtime.daily_pipeline.run_strategy_batch", lambda paths, push=False, trade_date=None: _strategy_summary(trade_date))

    def capture_notification(title: str, body: str) -> NotificationResult:
        captured.append({"title": title, "body": body})
        return NotificationResult("SUCCESS", "sent")

    monkeypatch.setattr("runtime.daily_pipeline.send_bark_notification", capture_notification)

    run_production_daily_pipeline(paths=paths, push=True, source="manual")

    body = captured[-1]["body"]
    assert "是否需要操作" in body
    assert "Quality Alpha V1" in body
    assert "主线链动因子 V1" in body
    assert "仓位：100.00%" in body
    assert "当日收益：-2.00%" in body
    assert "当前回撤：-12.00%" in body
    assert "风险状态：HIGH_VOL" in body


def test_daily_pipeline_operation_summary_marks_observer_as_non_trading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """观察策略进入日报摘要时必须明确不可交易。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    dates = pd.to_datetime(["2026-07-01", "2026-07-02"])
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(
        build_strategy_monitor_frame(
            strategy_id="innovative_drug_globalization_observer_v0",
            strategy_name="创新药出海观察策略 V0",
            daily_values=pd.Series([1.0, 1.02], index=dates),
            exposure=pd.Series([1.0, 1.0], index=dates),
        )
    )
    captured: list[dict[str, str]] = []

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr(
        "runtime.daily_pipeline.run_strategy_batch",
        lambda paths, push=False, trade_date=None: {
            "trade_date": trade_date or "20260702",
            "enabled_count": 1,
            "success_count": 1,
            "failed_count": 0,
            "results": [{"strategy_id": "innovative_drug_globalization_observer_v0", "status": "SUCCESS", "message": "ok"}],
        },
    )

    def capture_notification(title: str, body: str) -> NotificationResult:
        captured.append({"title": title, "body": body})
        return NotificationResult("SUCCESS", "sent")

    monkeypatch.setattr("runtime.daily_pipeline.send_bark_notification", capture_notification)

    run_production_daily_pipeline(paths=paths, push=True, source="manual")

    body = captured[-1]["body"]
    assert "创新药出海观察策略 V0" in body
    assert "状态：观察策略，不构成调仓建议" in body
    assert "操作建议：不操作" in body


def test_daily_pipeline_sends_data_update_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """数据更新步骤也应有独立 Bark 模板，方便判断数据是否可信。"""
    paths = RuntimePaths(tmp_path / "runtime")
    notifications: list[dict[str, str]] = []

    monkeypatch.setattr(
        "runtime.daily_pipeline.run_data_update",
        lambda trade_date=None: "A股新增交易日 0 个，主线链动缓存已同步: 写入11502行，游资涨跌停缓存已同步: 写入85行",
    )
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr("runtime.daily_pipeline.run_strategy_batch", lambda paths, push=False, trade_date=None: _strategy_summary(trade_date))

    def capture_notification(title: str, body: str) -> NotificationResult:
        notifications.append({"title": title, "body": body})
        return NotificationResult("SUCCESS", "sent")

    monkeypatch.setattr("runtime.daily_pipeline.send_bark_notification", capture_notification)

    run_production_daily_pipeline(paths=paths, push=True, source="manual")

    assert notifications[0]["title"] == "量化数据更新SUCCESS"
    assert "数据更新状态：SUCCESS" in notifications[0]["body"]
    assert "A股日线：已是最新，无新增交易日" in notifications[0]["body"]
    assert "游资涨跌停缓存：写入85行" in notifications[0]["body"]
    assert "策略执行：数据成功后继续执行" in notifications[0]["body"]


def test_daily_pipeline_backfill_uses_requested_trade_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """指定交易日补跑时，数据更新、策略批处理和运行记录都必须使用同一日期。"""
    paths = RuntimePaths(tmp_path / "runtime")
    calls: list[str] = []

    monkeypatch.setattr("runtime.daily_pipeline.run_data_update", lambda trade_date=None: calls.append(f"data:{trade_date}") or "data ok")
    monkeypatch.setattr("runtime.daily_pipeline.run_data_quality_gate", lambda paths: _quality_pass())
    monkeypatch.setattr(
        "runtime.daily_pipeline.run_strategy_batch",
        lambda paths, push=False, trade_date=None: calls.append(f"strategy:{trade_date}") or _strategy_summary(trade_date),
    )
    monkeypatch.setattr(
        "runtime.daily_pipeline.send_bark_notification",
        lambda title, body: NotificationResult("SUCCESS", "sent"),
    )

    summary = run_production_daily_pipeline(paths=paths, push=True, source="api", trade_date="20260707")
    repository = SystemRepository(paths.system_state_path)
    run = repository.get_run(PIPELINE_STRATEGY_ID, "20260707")

    assert summary["trade_date"] == "20260707"
    assert calls == ["data:20260707", "strategy:20260707"]
    assert run is not None
    assert run["run_dir"].endswith("runs/20260707")


def _strategy_summary(trade_date: str | None = None) -> dict[str, object]:
    return {
        "trade_date": trade_date or "20260702",
        "enabled_count": 2,
        "success_count": 2,
        "failed_count": 0,
        "results": [
            {"strategy_id": "quality_overlay", "status": "SUCCESS", "message": "ok"},
            {"strategy_id": "mainline_chain_factor_v1", "status": "SUCCESS", "message": "ok"},
        ],
    }


def _quality_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "check_count": 2,
        "failed_count": 0,
        "checks": [
            {"dataset_id": "live_market_increment_duckdb", "table_name": "daily", "status": "PASS"},
            {"dataset_id": "benchmark_increment_duckdb", "table_name": "fund_daily", "status": "PASS"},
        ],
    }


def _seed_monitoring(paths: RuntimePaths) -> None:
    dates = pd.to_datetime(["2026-07-01", "2026-07-02"])
    monitoring = MonitoringRepository(paths.monitoring_path)
    monitoring.upsert_strategy_daily(
        build_strategy_monitor_frame(
            strategy_id="quality_overlay",
            strategy_name="Quality Alpha V1",
            daily_values=pd.Series([100.0, 98.0], index=dates),
            benchmark_values=pd.Series([1.0, 0.99], index=dates),
            exposure=pd.Series([1.0, 1.0], index=dates),
        )
    )
    frame = build_strategy_monitor_frame(
        strategy_id="mainline_chain_factor_v1",
        strategy_name="主线链动因子 V1",
        daily_values=pd.Series([100.0, 88.0], index=dates),
        benchmark_values=pd.Series([1.0, 0.99], index=dates),
        exposure=pd.Series([0.95, 0.96], index=dates),
    )
    frame.loc[frame.index[-1], "volatility_20"] = 0.68
    monitoring.upsert_strategy_daily(frame)
