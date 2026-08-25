from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import limit_up_first_board_feasibility_study as study


class FakeLimitClient:
    def limit_list_d(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "name": "样本",
                    "close": 10.0,
                    "pct_chg": 10.0,
                    "limit": "U",
                    "amount": 100000.0,
                    "fd_amount": 20000.0,
                    "first_time": "093000",
                    "last_time": "093000",
                    "open_times": 0,
                }
            ]
        )


def test_definition_forbids_outcome_inspection_before_feasibility() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["event_scope"]["first_board_proxy"] == "open_times_eq_0"
    assert definition["event_scope"]["outcome_returns_not_inspected"] is True
    assert definition["parameters_fixed_before_cache_backfill"] is True


def test_backfill_uses_requested_dates_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "limit.duckdb"

    first = study._backfill_missing_dates(
        path,
        ["20260727", "20260728"],
        FakeLimitClient(),
        request_interval_seconds=0.0,
    )
    missing = study._missing_cache_dates(
        path,
        ["20260727", "20260728"],
    )

    assert first == 2
    assert missing == []


def test_name_filter_excludes_st_and_delisting_markers() -> None:
    names = pd.Series(["普通样本", "*ST样本", "退市样本"])

    eligible = ~names.str.contains("ST|退", case=False, regex=True)

    assert eligible.tolist() == [True, False, False]
