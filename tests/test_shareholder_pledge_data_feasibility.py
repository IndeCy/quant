"""股东质押点时数据可行性审计测试。"""

from pathlib import Path

import pandas as pd

from examples import shareholder_pledge_data_feasibility_study as study


def _row(ann_date: str, release_date: str | None = None) -> dict[str, object]:
    """构造一条字段完整的质押事件。"""
    return {
        "ts_code": "000001.SZ",
        "ann_date": ann_date,
        "holder_name": "测试股东",
        "pledge_amount": 100.0,
        "start_date": ann_date,
        "end_date": None,
        "is_release": "1" if release_date else "0",
        "release_date": release_date,
        "pledgor": "测试机构",
        "holding_amount": 500.0,
        "pledged_amount": 100.0,
        "p_total_ratio": 1.0,
        "h_total_ratio": 5.0,
        "is_buyback": "0",
    }


class FakeClient:
    """按固定窗口返回测试数据。"""

    def __init__(self, future_release: bool = False) -> None:
        self.future_release = future_release

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        release_date = "20200101" if self.future_release else None
        return pd.DataFrame([_row(start_date, release_date)])


def test_future_release_state_blocks_as_of_reconstruction(tmp_path: Path) -> None:
    """历史公告行带有后来解押日期时必须在回测前失败。"""
    paths = study.RuntimePaths(tmp_path)
    result = study.run_study(
        paths,
        "20260724",
        client_factory=lambda: FakeClient(future_release=True),
    )

    assert result["checks"]["release_state_point_in_time_safe"] is False
    assert result["decision"] == "REJECTED_BEFORE_BACKTEST"


def test_clean_probe_is_eligible_for_factor_design(tmp_path: Path) -> None:
    """所有冻结门禁通过时只允许进入因子设计阶段。"""
    paths = study.RuntimePaths(tmp_path)
    result = study.run_study(
        paths,
        "20260724",
        client_factory=FakeClient,
    )

    assert result["passed"] is True
    assert result["decision"] == "ELIGIBLE_FOR_FACTOR_DESIGN"


def test_reused_attempt_does_not_call_tushare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同指纹复用结果时不得再次访问外部接口。"""
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
