"""机构调研点时数据门禁测试。"""

import pandas as pd

from examples import institutional_survey_data_feasibility_study as study


class FakeClient:
    """返回不含公开时间戳的官方字段。"""

    def fetch(self, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "surv_date": [start_date],
                "fund_visitors": ["测试机构"],
                "rece_place": ["线上"],
                "rece_mode": ["电话会议"],
                "rece_org": ["测试机构"],
                "org_type": ["基金"],
                "comp_rece": ["测试人员"],
            }
        )


def test_missing_publication_timestamp_blocks_factor(tmp_path) -> None:
    """只有调研日而无公开日时必须在缓存前终止。"""
    result = study.run_study(
        study.RuntimePaths(tmp_path),
        "20260726",
        client_factory=FakeClient,
    )

    assert result["checks"]["public_visibility_timestamp_present"] is False
    assert result["decision"] == "REJECTED_BEFORE_CACHE_OR_BACKTEST"


def test_reused_attempt_does_not_call_tushare(tmp_path, monkeypatch) -> None:
    """相同指纹复用时不访问外部接口。"""
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
        "20260726",
        client_factory=lambda: (_ for _ in ()).throw(
            AssertionError("不应访问Tushare")
        ),
    )

    assert result == {"reused": True}
