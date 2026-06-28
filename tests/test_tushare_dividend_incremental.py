"""Tushare 分红增量缓存测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.tushare_dividend_incremental import DIVIDEND_COLUMNS, DividendDuckDBStore


def test_dividend_store_upserts_and_loads_rows(tmp_path: Path) -> None:
    """分红缓存按股票、报告期、公告日和进度幂等覆盖。"""
    store = DividendDuckDBStore(tmp_path / "dividend.duckdb")
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "end_date": "20251231",
                "ann_date": "20260321",
                "div_proc": "实施",
                "stk_div": 0.0,
                "stk_bo_rate": None,
                "stk_co_rate": None,
                "cash_div": 0.36,
                "cash_div_tax": 0.36,
                "record_date": "20260611",
                "ex_date": "20260612",
                "pay_date": "20260612",
                "div_listdate": None,
                "imp_ann_date": "20260605",
                "base_date": "20260605",
                "base_share": 1940591.8198,
            }
        ],
        columns=DIVIDEND_COLUMNS,
    )

    store.upsert(frame)
    store.upsert(frame)
    loaded = store.load()

    assert store.count_rows() == 1
    assert loaded.loc[0, "cash_div_tax"] == 0.36
    assert loaded.loc[0, "ex_date"] == "20260612"


def test_dividend_store_rejects_missing_required_columns(tmp_path: Path) -> None:
    """缺少关键字段时不能写入缓存。"""
    store = DividendDuckDBStore(tmp_path / "dividend.duckdb")
    frame = pd.DataFrame({"ts_code": ["000001.SZ"]})

    try:
        store.upsert(frame)
    except ValueError as exc:
        assert "缺少字段" in str(exc)
    else:
        raise AssertionError("expected ValueError")
