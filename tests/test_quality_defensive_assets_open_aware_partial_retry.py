"""Open-aware单票缺价部分重试研究测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import (
    quality_defensive_assets_open_aware_partial_retry_study as study,
)


def test_partial_retry_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同V9执行口径不得重复完整历史回放。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "experiment_id": study.EXPERIMENT_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复历史回放"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
