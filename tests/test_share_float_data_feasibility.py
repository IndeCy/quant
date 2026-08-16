"""限售解禁点时数据可行性审计测试。"""

from pathlib import Path

import pandas as pd

from examples import share_float_data_feasibility_study as study


def _row(ann_date: str, float_date: str) -> dict[str, object]:
    """构造字段完整的解禁计划。"""
    return {
        "ts_code": "000001.SZ",
        "ann_date": ann_date,
        "float_date": float_date,
        "float_share": 1_000_000.0,
        "float_ratio": 1.5,
        "holder_name": "测试股东",
        "share_type": "定增股份",
    }


class FakeClient:
    """返回可控公告时序的测试客户端。"""

    def __init__(self, late_announcement: bool = False) -> None:
        self.late_announcement = late_announcement

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        ann_date = "20270101" if self.late_announcement else "20140101"
        return pd.DataFrame([_row(ann_date, start_date)])


def test_late_announcement_blocks_point_in_time_use(tmp_path: Path) -> None:
    """解禁后才公告的数据不能用于事前供给压力。"""
    result = study.run_study(
        study.RuntimePaths(tmp_path),
        "20260724",
        client_factory=lambda: FakeClient(late_announcement=True),
    )

    assert result["checks"]["known_before_event"] is False
    assert result["decision"] == "REJECTED_BEFORE_BACKTEST"


def test_clean_windows_pass_data_gate(tmp_path: Path) -> None:
    """完整且提前公告的事件可以进入后续因子设计。"""
    result = study.run_study(
        study.RuntimePaths(tmp_path),
        "20260724",
        client_factory=FakeClient,
    )

    assert result["passed"] is True
    assert result["decision"] == "ELIGIBLE_FOR_FACTOR_DESIGN"


def test_reused_attempt_skips_external_probe(tmp_path: Path, monkeypatch) -> None:
    """相同运行指纹复用时不再访问外部接口。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    result = study.run_study(
        study.RuntimePaths(tmp_path),
        "20260724",
        client_factory=lambda: (_ for _ in ()).throw(
            AssertionError("不应访问Tushare")
        ),
    )

    assert result == {"reused": True}
