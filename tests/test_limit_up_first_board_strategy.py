from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import limit_up_first_board_strategy_study as study
from runtime.paths import RuntimePaths


def _events() -> pd.DataFrame:
    rows = []
    for index in range(12):
        rows.append(
            {
                "trade_date": "20260105",
                "ts_code": f"{index:06d}.SZ",
                "name": "普通样本",
                "limit_type": "U",
                "open_times": 0,
                "amount": 100.0 + index,
                "fd_amount": 10.0 + index * 5,
                "first_time": "093000",
            }
        )
    rows.append(
        {
            "trade_date": "20260105",
            "ts_code": "999999.SZ",
            "name": "*ST样本",
            "limit_type": "U",
            "open_times": 0,
            "amount": 9999.0,
            "fd_amount": 9999.0,
            "first_time": "093000",
        }
    )
    return pd.DataFrame(rows)


def test_seal_strength_ranking_is_fixed_top10_and_excludes_st() -> None:
    targets, selected = study.build_daily_targets(
        _events(),
        ranking="seal_strength",
    )

    assert len(targets["20260105"]) == 10
    assert "999999.SZ" not in targets["20260105"]
    assert sum(targets["20260105"].values()) == 1.0
    assert len(selected) == 10


def test_definition_uses_t1_m0_and_no_threshold_search() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["ranking"]["threshold_search"] is False
    assert definition["portfolio"]["execution"] == "next_trading_day_open"
    assert definition["execution"]["model"] == "M0"
    assert definition["execution"]["lag"] == 1


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.base_market_path,
        paths.fund_daily_history_path,
        paths.limit_list_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of=study.RELIABLE_AS_OF,
        data_version=study._data_version(paths),
    )
    study.complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得重复计算")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)
    monkeypatch.setattr(study, "_require_feasibility_passed", lambda _paths: None)

    result = study.run_study(paths, study.RELIABLE_AS_OF)

    assert result["reused"] is True
