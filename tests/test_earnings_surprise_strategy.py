"""标准化意外盈利事件策略测试。"""

from __future__ import annotations

import pandas as pd

from examples import earnings_surprise_strategy_study as study


def _candidates(count: int, signal_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [f"{index:06d}.SZ" for index in range(count)],
            "name": [f"股票{index}" for index in range(count)],
            "signal_date": [signal_date] * count,
            "end_date": ["20231231"] * count,
            "publish_date": ["20240330"] * count,
            "basic_eps": [1.0] * count,
            "eps_change": [0.01 * (index + 1) for index in range(count)],
            "historical_change_std": [0.1] * count,
            "history_observations": [8] * count,
            "sue": [0.1 * (index + 1) for index in range(count)],
            "event_age_days": [10] * count,
            "ret120": [0.01 * index for index in range(count)],
        }
    )


def test_event_target_skips_unconstructible_month() -> None:
    """候选不足时不得发空目标清仓，而应沿用原持仓。"""
    candidates = pd.concat(
        [
            _candidates(25, "20240131"),
            _candidates(10, "20240229"),
        ],
        ignore_index=True,
    )

    targets, holdings, diagnostics = study.build_event_targets(
        candidates,
        ["20240131", "20240229"],
    )

    assert "20240131" in targets
    assert "20240229" not in targets
    assert len(targets["20240131"]) == 20
    assert set(holdings["signal_date"]) == {"20240131"}
    assert diagnostics["carried_months"] == 1.0


def test_event_target_selects_highest_sue() -> None:
    """Top20必须按冻结的SUE分位分数稳定选择。"""
    candidates = _candidates(25, "20240131")

    targets, _, _ = study.build_event_targets(
        candidates,
        ["20240131"],
    )

    assert "000024.SZ" in targets["20240131"]
    assert "000000.SZ" not in targets["20240131"]


def test_cached_strategy_attempt_skips_backtest(monkeypatch) -> None:
    """相同运行指纹存在时不得再次执行M0回测。"""

    class CachedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: CachedAttempt(),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test")
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应运行回测")
        ),
    )

    result = study.run_study(object(), "20260724")  # type: ignore[arg-type]

    assert result == {"reused": True}
