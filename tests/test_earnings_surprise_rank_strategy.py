"""SUE原始秩策略研究门禁测试。"""

from __future__ import annotations

from examples import earnings_surprise_rank_strategy_study as study


def test_cached_rank_attempt_skips_backtest(monkeypatch) -> None:
    """相同V2指纹存在时不得重复执行回测。"""

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
