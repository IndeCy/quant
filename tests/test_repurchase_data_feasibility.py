"""公司回购数据可行性研究测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import repurchase_data_feasibility_study as study


def test_repurchase_feasibility_reuses_identical_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同审计年度、数据版本和定义不得重复调用外部接口。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "decision": "REJECTED_BEFORE_BACKTEST"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复调用接口"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def test_repurchase_report_explains_semantic_rejection() -> None:
    """报告必须明确记录未进入回测的原因。"""
    result = {
        "audit_year": 2024,
        "as_of_date": "20260724",
        "rows": 100,
        "symbols": 20,
        "valid_completed_rows": 80,
        "valid_completed_symbols": 15,
        "same_symbol_announcement_multi_groups": 3,
        "symbols_with_at_least_four_completed_rows": 4,
        "checks": {
            "announcement_date_visibility": True,
            "stable_plan_identity": False,
        },
    }

    report = study.render_report(result)

    assert "未进入回测" in report
    assert "FAIL：stable_plan_identity" in report
