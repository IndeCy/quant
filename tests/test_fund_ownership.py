"""公募基金持仓广度缓存、点时门面和因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.fund_ownership import (
    attach_fund_ownership_database,
    create_fund_ownership_signal_date_table,
    load_fund_ownership_snapshot,
    materialize_fund_ownership_breadth_asof,
)
from data.fund_ownership_cache import (
    normalize_fund_positions,
    normalize_product_name,
    update_fund_ownership_cache,
)
from examples import fund_ownership_breadth_study as study
from factors.fund_ownership_breadth import score_fund_ownership_breadth_frame


class FakeFundOwnershipClient:
    """按 offset 返回基金基础与季度持仓切片。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.basic = {
            "L": pd.DataFrame(
                [
                    _basic("000001.OF", "质量基金-A", "20100101"),
                    _basic("000002.OF", "质量基金-C", "20120101"),
                ]
            ),
            "D": pd.DataFrame(
                [_basic("000003.OF", "历史基金-A", "20090101")]
            ),
        }
        positions = []
        for code, scale in [("000001.OF", 1.0), ("000002.OF", 0.8)]:
            for index in range(12):
                positions.append(
                    _position(code, f"{index + 1:06d}.SZ", 120 - index * scale)
                )
        self.positions = pd.DataFrame(positions)

    def query(self, api_name: str, **kwargs: object) -> pd.DataFrame:
        self.calls.append((api_name, dict(kwargs)))
        offset = int(kwargs["offset"])
        limit = int(kwargs["limit"])
        source = (
            self.basic[str(kwargs["status"])]
            if api_name == "fund_basic"
            else self.positions
        )
        return source.iloc[offset : offset + limit].copy()


def _basic(code: str, name: str, found_date: str) -> dict[str, object]:
    return {
        "ts_code": code,
        "name": name,
        "management": "示例管理人",
        "found_date": found_date,
        "due_date": None,
    }


def _position(code: str, symbol: str, mkv: float) -> dict[str, object]:
    return {
        "ts_code": code,
        "ann_date": "20240420",
        "end_date": "20240331",
        "symbol": symbol,
        "mkv": mkv,
        "amount": 100.0,
        "stk_mkv_ratio": 1.0,
        "stk_float_ratio": 0.1,
    }


def test_cache_paginates_merges_share_classes_and_keeps_top10(
    tmp_path: Path,
) -> None:
    """分页后应按产品选择代表份额，并把披露深度统一为前十大。"""
    database = tmp_path / "fund.duckdb"
    result = update_fund_ownership_cache(
        FakeFundOwnershipClient(),
        database,
        start_period="20240331",
        end_period="20240331",
        force=True,
        page_size=5,
    )

    assert result.updated_periods == ("20240331",)
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT representative_code, COUNT(*), MAX(position_rank)
            FROM fund_product_top10
            GROUP BY representative_code
            """
        ).fetchall()
    assert rows == [("000001.OF", 10, 10)]


def test_normalization_preserves_conflicting_payload_but_drops_exact_copy() -> None:
    """同键冲突金额要保留，完全相同的源记录只保存一次。"""
    first = _position("000001.OF", "000001.SZ", 100.0)
    second = {**first, "mkv": 101.0}
    frame = pd.DataFrame([first, first, second])

    result = normalize_fund_positions(frame)

    assert len(result) == 2
    assert sorted(result["mkv"].tolist()) == [100.0, 101.0]


def test_asof_waits_for_deadline_and_uses_visible_announcements(
    tmp_path: Path,
) -> None:
    """Q1 持仓在 4 月 30 日前不可见，截止日后才能参与广度变化。"""
    database = tmp_path / "fund.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE fund_product_top10(
                end_date VARCHAR,
                available_date VARCHAR,
                product_key VARCHAR,
                representative_code VARCHAR,
                symbol VARCHAR,
                ann_date VARCHAR,
                mkv DOUBLE,
                position_rank INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO fund_product_top10 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("20231231", "20240430", "P1", "F1", "A", "20240320", 10, 1),
                ("20231231", "20240430", "P2", "F2", "B", "20240321", 10, 1),
                ("20240331", "20240430", "P1", "F1", "A", "20240420", 10, 1),
                ("20240331", "20240430", "P2", "F2", "A", "20240421", 10, 1),
            ],
        )

    memory = duckdb.connect()
    try:
        create_fund_ownership_signal_date_table(
            memory,
            ["20240429", "20240430"],
        )
        attach_fund_ownership_database(memory, database)
        materialize_fund_ownership_breadth_asof(memory)
        result = load_fund_ownership_snapshot(memory)
    finally:
        memory.close()

    assert set(result["signal_date"]) == {"20240430"}
    stock_a = result[result["symbol"].eq("A")].iloc[0]
    assert stock_a["current_product_holders"] == 2
    assert stock_a["prior_product_holders"] == 1
    assert stock_a["breadth_change"] == pytest.approx(0.5)


def test_product_name_and_factor_scoring_are_deterministic() -> None:
    """份额后缀归并和正向广度排名不能依赖展示名称。"""
    assert normalize_product_name("质量基金-A") == "质量基金"
    assert normalize_product_name("质量基金-C") == "质量基金"
    frame = pd.DataFrame(
        {
            "symbol": ["FAST", "SLOW", "OUT"],
            "breadth_change": [0.03, 0.01, -0.02],
        }
    )
    scored = score_fund_ownership_breadth_frame(frame).set_index("symbol")
    assert set(scored.index) == {"FAST", "SLOW"}
    assert scored.loc["FAST", "factor_score"] > scored.loc["SLOW", "factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义与数据版本必须直接复用，禁止重复回测。"""
    for path in [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
        tmp_path / "data" / "fund_ownership_increment.duckdb",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260725")

    assert result["reused"] is True
