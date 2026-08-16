"""异常存货积累因子的点时语义与研究门禁测试。"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pandas as pd

from data.abnormal_inventory import (
    AbnormalInventoryPaths,
    attach_abnormal_inventory_databases,
    create_abnormal_inventory_signal_dates,
    materialize_abnormal_inventory_asof,
)
from examples import abnormal_inventory_accumulation_study as study
from examples.abnormal_inventory_accumulation_support import (
    build_diagnostics,
    build_monthly_coverage,
)
from factors.abnormal_inventory import score_abnormal_inventory_frame
from runtime.paths import RuntimePaths
from runtime.research_attempts import complete_research_attempt


def test_asof_excludes_financial_revision_published_after_signal(
    tmp_path: Path,
) -> None:
    """信号日之后披露的同年修订不得进入历史截面。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balance.duckdb"
    _seed_financial_database(income, balance)
    connection = duckdb.connect(":memory:")
    try:
        create_abnormal_inventory_signal_dates(
            connection,
            ["20230430", "20230630"],
        )
        attach_abnormal_inventory_databases(
            connection,
            AbnormalInventoryPaths(income, balance),
        )
        table = materialize_abnormal_inventory_asof(connection)
        result = connection.execute(
            f"""
            SELECT signal_date, publish_date, revenue, inventories,
                   abnormal_inventory_accumulation
            FROM {table}
            ORDER BY signal_date
            """
        ).fetchdf()
    finally:
        connection.close()

    assert result["publish_date"].tolist() == ["20230301", "20230501"]
    assert result["revenue"].tolist() == [120.0, 240.0]
    assert result["inventories"].tolist() == [90.0, 180.0]
    expected = math.log(90.0 / 50.0) - math.log(120.0 / 100.0)
    assert math.isclose(
        float(result.iloc[0]["abnormal_inventory_accumulation"]),
        expected,
    )


def test_factor_scores_lower_abnormal_accumulation_higher() -> None:
    """存货相对销售积累更少的股票必须获得更高分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["LOW", "MID", "HIGH"],
            "abnormal_inventory_accumulation": [-0.2, 0.0, 0.4],
        }
    )

    scored = score_abnormal_inventory_frame(frame).set_index("symbol")

    assert scored.loc["LOW", "factor_score"] > scored.loc["MID", "factor_score"]
    assert scored.loc["MID", "factor_score"] > scored.loc["HIGH", "factor_score"]


def test_monthly_coverage_keeps_investable_denominator() -> None:
    """财务缺失股票必须保留在覆盖率分母，不能静默消失。"""
    panel = pd.DataFrame(
        {
            "signal_date": ["20220131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "abnormal_inventory_accumulation": [0.1, 0.2, None, None],
        }
    )

    monthly = build_monthly_coverage(panel).iloc[0]

    assert monthly["investable_count"] == 4
    assert monthly["candidate_count"] == 2
    assert monthly["coverage"] == 0.5


def test_research_definition_is_fixed_and_not_a_ccc_alias() -> None:
    """研究定义必须冻结，并明确区别现金转换周期。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["factor"] == {
        "formula": "ln(inventory_t/inventory_t_1)-ln(revenue_t/revenue_t_1)",
        "direction": "lower_is_better",
        "transform": "winsorize_1_99_then_cross_sectional_percentile_rank",
        "positive_inputs_required": True,
    }
    assert definition["evaluation"]["no_follow_up_variants"] is True
    assert "cash_conversion_cycle" in definition["prior_research_distinction"]


def test_diagnostics_exposes_winsorized_top_ties() -> None:
    """TopN落入缩尾并列区时必须显式归因，不能伪装成精确排名。"""
    size = 200
    candidates = pd.DataFrame(
        {
            "signal_date": ["20220131"] * size,
            "symbol": [f"S{index:03d}" for index in range(size)],
            "abnormal_inventory_accumulation": list(range(size)),
            "inventory_log_growth": list(range(size)),
            "revenue_log_growth": [index / size for index in range(size)],
            "ret120": list(reversed(range(size))),
        }
    )
    scored = score_abnormal_inventory_frame(candidates)
    holdings = scored.nlargest(40, "factor_score").copy()

    result = build_diagnostics(candidates, holdings)

    assert result["maximum_top_score_tie_count"] == 2
    assert result["median_selected_clipped_tie_share"] == 0.05


def test_same_fingerprint_skips_financial_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同定义与数据版本必须复用，不能再次扫描财务大表。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.base_market_path,
        paths.live_market_increment_path,
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
        metrics={"decision": "REJECTED_BEFORE_BACKTEST"},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得读取财务数据")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260726")

    assert result["reused"] is True


def _seed_financial_database(income: Path, balance: Path) -> None:
    """构造信号日前后两个版本的最小年报数据库。"""
    income_connection = duckdb.connect(str(income))
    balance_connection = duckdb.connect(str(balance))
    try:
        income_connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                report_type VARCHAR,
                comp_type VARCHAR,
                update_flag VARCHAR,
                revenue DOUBLE
            )
            """
        )
        balance_connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                report_type VARCHAR,
                comp_type VARCHAR,
                update_flag VARCHAR,
                inventories DOUBLE
            )
            """
        )
        income_connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("000001.SZ", "20211231", "20220301", "20220301", "1", "1", "0", 100.0),
                ("000001.SZ", "20221231", "20230301", "20230301", "1", "1", "0", 120.0),
                ("000001.SZ", "20221231", "20230501", "20230501", "1", "1", "1", 240.0),
            ],
        )
        balance_connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("000001.SZ", "20211231", "20220301", "20220301", "1", "1", "0", 50.0),
                ("000001.SZ", "20221231", "20230301", "20230301", "1", "1", "0", 90.0),
                ("000001.SZ", "20221231", "20230501", "20230501", "1", "1", "1", 180.0),
            ],
        )
    finally:
        income_connection.close()
        balance_connection.close()
