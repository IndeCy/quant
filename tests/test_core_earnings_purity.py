"""核心利润纯度因子的点时、多折与研究指纹测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import core_earnings_purity_study as study
from examples.core_earnings_purity_support import (
    build_candidates,
    build_diagnostics,
    build_monthly_coverage,
)
from factors.core_earnings_purity import score_core_earnings_purity_frame
from runtime.paths import RuntimePaths
from runtime.research_attempts import complete_research_attempt


def test_factor_scores_higher_core_profit_share_higher() -> None:
    """更高扣非利润占比必须获得更高因子得分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["LOW", "MID", "HIGH"],
            "dtprofit_to_profit": [20.0, 80.0, 120.0],
        }
    )

    scored = score_core_earnings_purity_frame(frame).set_index("symbol")

    assert scored.loc["HIGH", "factor_score"] > scored.loc["MID", "factor_score"]
    assert scored.loc["MID", "factor_score"] > scored.loc["LOW", "factor_score"]


def test_candidates_enforce_asof_profitability_and_status() -> None:
    """未来公告、亏损和ST记录不能进入研究截面。"""
    source = pd.DataFrame(
        [
            _candidate("VALID"),
            _candidate("FUTURE", f_ann_date="20240701"),
            _candidate("LOSS", roa=-1.0),
            _candidate("STOCK", name="*ST测试"),
        ]
    )

    candidates, diagnostics = build_candidates(source)

    assert candidates["symbol"].tolist() == ["VALID"]
    assert diagnostics["visibility_violations"] == 0
    assert diagnostics["duplicate_rows"] == 0


def test_monthly_coverage_preserves_empty_expected_month() -> None:
    """无候选月份必须保留，不能从覆盖率分母消失。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131", "20240131"],
            "symbol": ["A", "B"],
            "dtprofit_to_profit": [80.0, 100.0],
            "adv_rmb": [30_000_000.0, 40_000_000.0],
        }
    )

    monthly = build_monthly_coverage(
        candidates,
        ["20240131", "20240229"],
    )

    assert monthly["candidate_count"].tolist() == [2, 0]
    assert monthly["top40_count"].tolist() == [2, 0]


def test_multifold_gate_checks_locked_period_without_selection() -> None:
    """锁定段失败必须拒绝，不能用历史折表现覆盖。"""
    passing = {
        "fold_2015_2017": _metrics(),
        "fold_2018_2020": _metrics(),
        "fold_2021_2023": _metrics(),
        "locked_2024_latest": _metrics(),
        "full": _metrics(),
    }

    passed = study.evaluate_multifold_gate(passing, 0.40)
    passing["locked_2024_latest"] = _metrics(annualized_return=-0.01)
    rejected = study.evaluate_multifold_gate(passing, 0.40)

    assert passed["passed"] is True
    assert rejected["passed"] is False
    assert (
        rejected["checks"]["locked_annual_return_at_least_5pct"]
        is False
    )


def test_diagnostics_exposes_above_100_semantic_shift() -> None:
    """诊断必须揭示高值方向是否变成非经常损失暴露。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 3,
            "symbol": ["A", "B", "C"],
            "dtprofit_to_profit": [90.0, 150.0, 300.0],
            "roa": [0.5, 2.0, 3.0],
            "ocf_to_or": [0.1, 0.2, 0.3],
            "salescash_to_or": [0.9, 1.0, 1.1],
            "ret120": [0.0, 0.1, 0.2],
        }
    )
    holdings = score_core_earnings_purity_frame(candidates).assign(
        signal_date="20240131"
    )

    diagnostics = build_diagnostics(candidates, holdings)

    assert diagnostics["selected_factor_above_100_share"] == 2 / 3
    assert diagnostics["selected_factor_above_200_share"] == 1 / 3
    assert diagnostics["selected_roa_below_1_share"] == 1 / 3


def test_research_definition_freezes_grid_and_no_search() -> None:
    """风险层、分段和参数冻结必须进入确定性研究指纹。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["factor"]["source_field"] == "dtprofit_to_profit"
    assert definition["factor"]["eligibility"] == "roa_positive"
    assert definition["risk_overlay"]["scheme"] == "GRID"
    assert definition["portfolio"]["top_n"] == 40
    assert definition["evaluation"]["folds"] == study.FOLDS
    assert definition["evaluation"]["no_parameter_search"] is True


def test_same_fingerprint_skips_financial_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同语义和数据快照必须复用历史结果。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260726",
        data_version=study._data_version(paths),
    )
    complete_research_attempt(
        attempt,
        metrics={"decision": "REJECTED"},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得扫描财务大表")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260726")

    assert result["reused"] is True


def _candidate(
    symbol: str,
    *,
    f_ann_date: str = "20240430",
    roa: float = 5.0,
    name: str = "测试股份",
) -> dict[str, object]:
    """构造满足标准股票池的最小财务候选。"""
    return {
        "signal_date": "20240628",
        "symbol": symbol,
        "name": name,
        "list_date": "20200101",
        "delist_date": None,
        "st_name": None,
        "end_date": "20231231",
        "f_ann_date": f_ann_date,
        "dtprofit_to_profit": 90.0,
        "roa": roa,
        "roe": 10.0,
        "ocf_to_or": 12.0,
        "salescash_to_or": 100.0,
        "ret120": 0.10,
        "amount20": 50_000.0,
        "amount": 60_000.0,
        "amount_p20": 10_000.0,
        "volume": 1_000.0,
        "close": 10.0,
    }


def _metrics(
    *,
    annualized_return: float = 0.10,
) -> dict[str, float]:
    """构造通过多折门槛的指标。"""
    return {
        "annualized_return": annualized_return,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": 5.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.01,
    }
