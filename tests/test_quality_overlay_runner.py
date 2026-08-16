from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.quality_overlay_paper import QualityPaperSnapshot
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.quality_overlay_runner import QualityOverlayComputation, persist_quality_overlay_instance


def test_persist_quality_overlay_writes_unified_strategy_holdings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """冻结 Quality 策略提交后也必须进入统一策略状态表。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    snapshot = QualityPaperSnapshot(
        trade_date="20260728",
        selection_date="20260630",
        exposure=1.0,
        volatility20=0.2,
        risk_state="NORMAL",
        target_weights={"000001.SZ": 0.6, "000002.SZ": 0.4},
        warnings=[],
    )
    run = SimpleNamespace(
        result=SimpleNamespace(
            daily_values=pd.Series(
                [1_000_000.0, 1_250_000.0],
                index=pd.to_datetime(["20260727", "20260728"]),
            )
        )
    )
    computation = QualityOverlayComputation(
        result={
            "strategy_id": "quality_overlay",
            "trade_date": "20260728",
            "selected_count": 2,
            "target_weights": snapshot.target_weights,
            "nav": 1_250_000.0,
        },
        snapshot=snapshot,
        holdings=pd.DataFrame(
            [
                {"symbol": "000001.SZ", "name": "样本一", "target_weight": 0.6},
                {"symbol": "000002.SZ", "name": "样本二", "target_weight": 0.4},
            ]
        ),
        run=run,
        benchmark_curve=pd.Series(dtype=float),
        shanghai_curve=pd.Series(dtype=float),
        latest_prices={"000001.SZ": 10.5, "000002.SZ": 20.5},
    )
    monkeypatch.setattr(
        "examples.run_quality_overlay_paper.update_monitoring_dashboard",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "examples.run_quality_overlay_paper.write_production_artifacts",
        lambda *args, **kwargs: paths.runs_dir / "20260728",
    )
    monkeypatch.setattr(
        "examples.run_quality_overlay_paper.render_report",
        lambda *args, **kwargs: "report",
    )
    monkeypatch.setattr(
        "strategies.quality_overlay_runner.QualityPaperStore.save",
        lambda *args, **kwargs: None,
    )

    persist_quality_overlay_instance(
        {"strategy_id": "quality_overlay"},
        paths,
        computation,
    )

    state = SystemRepository(paths.system_state_path).load_strategy_instance_state("quality_overlay")
    assert state["trade_date"] == "20260728"
    assert state["nav"] == pytest.approx(1.25)
    assert state["holdings"] == [
        {"symbol": "000001.SZ", "weight": 0.6, "last_close": 10.5},
        {"symbol": "000002.SZ", "weight": 0.4, "last_close": 20.5},
    ]
