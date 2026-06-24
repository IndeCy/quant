"""冻结Quality Overlay策略的Paper状态测试。"""

from pathlib import Path

import pytest

from backtest.quality_overlay_paper import QualityPaperSnapshot, QualityPaperStore, build_target_weights
from examples import run_quality_overlay_paper


def test_target_weights_respect_overlay_exposure() -> None:
    weights = build_target_weights(["A", "B", "C"], exposure=0.3)

    assert weights == pytest.approx({"A": 0.1, "B": 0.1, "C": 0.1})
    assert abs(sum(weights.values()) - 0.3) < 1e-12


def test_snapshot_store_is_idempotent_by_trade_date(tmp_path: Path) -> None:
    store = QualityPaperStore(tmp_path / "paper.sqlite3")
    first = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.30, "NORMAL", {"A": 1.0}, [])
    revised = QualityPaperSnapshot("20260618", "20260529", 0.3, 0.50, "REDUCED", {"A": 0.3}, ["test"])

    store.save(first)
    store.save(revised)
    loaded = store.load("20260618")

    assert store.count() == 1
    assert loaded is not None
    assert loaded.exposure == 0.3
    assert loaded.target_weights == {"A": 0.3}
    assert loaded.warnings == ["test"]


def test_snapshot_store_loads_latest_before_trade_date(tmp_path: Path) -> None:
    """调仓计划需要拿到目标日前最近一次快照做权重差异。"""
    store = QualityPaperStore(tmp_path / "paper.sqlite3")
    first = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.20, "NORMAL", {"A": 1.0}, [])
    second = QualityPaperSnapshot("20260620", "20260529", 0.3, 0.50, "REDUCED", {"A": 0.3}, [])
    store.save(first)
    store.save(second)

    loaded = store.load_latest_before("20260620")

    assert loaded is not None
    assert loaded.trade_date == "20260618"
    assert loaded.target_weights == {"A": 1.0}


def test_push_report_uses_notification_message(monkeypatch) -> None:
    sent = []

    class FakeNotifier:
        def send(self, message) -> None:
            sent.append(message)

    monkeypatch.setattr(run_quality_overlay_paper, "build_notifier", lambda provider, endpoint: FakeNotifier())
    snapshot = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.2, "NORMAL", {"A": 1.0}, [])

    run_quality_overlay_paper.push_report(snapshot, "https://example.test/key")

    assert sent[0].title == "Quality Overlay Paper"
    assert "目标仓位100%" in sent[0].body
