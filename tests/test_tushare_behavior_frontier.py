"""Tushare 个股行为数据前沿审计测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import tushare_behavior_frontier_study as study


class ProbeClient:
    """构造覆盖不同的三类行为数据。"""

    def hk_hold(self, trade_date: str) -> pd.DataFrame:
        if trade_date == study.PROBE_DATES[0]:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "trade_date": [trade_date],
                "ts_code": ["000001.SZ"],
                "ratio": [1.2],
            }
        )

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_date],
                "ts_code": ["000001.SZ"],
                "buy": [10.0],
                "sell": [5.0],
                "net_buy": [5.0],
            }
        )

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_date],
                "ts_code": ["000001.SZ"],
                "buy_lg_amount": [10.0],
                "sell_lg_amount": [5.0],
                "buy_elg_amount": [3.0],
                "sell_elg_amount": [1.0],
            }
        )


def test_probe_selects_first_usable_source_by_frozen_priority() -> None:
    """多个来源可用时必须选择预先排序最高的北向持仓。"""
    records = study.probe_sources(ProbeClient())
    summaries = study.summarize_sources(records)

    assert summaries["hk_hold"]["nonempty_dates"] == 3
    assert summaries["hk_hold"]["usable"] is True
    assert summaries["top_inst"]["usable"] is True
    assert study.select_candidate(summaries) == "hk_hold"


def test_missing_required_columns_blocks_source() -> None:
    """接口可访问但缺少必要字段时不得进入后续研究。"""
    records = [
        study.ProbeRecord(
            source=source,
            trade_date=trade_date,
            status="OK",
            row_count=1,
            columns=("trade_date", "ts_code"),
        )
        for source in study.SOURCE_PRIORITY
        for trade_date in study.PROBE_DATES
    ]

    summaries = study.summarize_sources(records)

    assert all(not summary["usable"] for summary in summaries.values())
    assert study.select_candidate(summaries) is None


def test_probe_records_external_error_without_aborting_other_sources() -> None:
    """单个接口权限错误应成为审计结果，不能中断全部探针。"""

    class FailingClient(ProbeClient):
        def hk_hold(self, trade_date: str) -> pd.DataFrame:
            raise RuntimeError("没有接口权限")

    records = study.probe_sources(FailingClient())
    summaries = study.summarize_sources(records)

    assert summaries["hk_hold"]["access_dates"] == 0
    assert summaries["hk_hold"]["usable"] is False
    assert summaries["top_inst"]["usable"] is True
    assert study.select_candidate(summaries) == "top_inst"
    assert all("没有接口权限" in record.error for record in records[:4])


def test_calculate_persists_metadata_only(tmp_path: Path) -> None:
    """前沿审计不得把接口原始业务行写入结构化结果。"""
    paths = study.RuntimePaths(tmp_path)

    result = study._calculate(paths, ProbeClient)

    assert result["selected_source"] == "hk_hold"
    assert result["raw_rows_persisted"] is False
    assert all("ratio" not in record for record in result["records"])
    assert Path(result["report_path"]).exists()


def test_reuses_fingerprint_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据前沿指纹必须复用，不再访问外部接口。"""

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
        lambda *args, **kwargs: pytest.fail("不应访问Tushare"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
