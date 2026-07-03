"""Tushare 概念成分缓存测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.tushare_concept_incremental import update_opportunity_concept_cache


class FakeConceptClient:
    """测试用概念客户端。"""

    def ths_index(self) -> pd.DataFrame:
        return pd.DataFrame([{"ts_code": "886050.TI", "name": "算力租赁"}])

    def ths_member(self, ts_code: str) -> pd.DataFrame:
        assert ts_code == "886050.TI"
        return pd.DataFrame([{"ts_code": ts_code, "con_code": "000938.SZ", "con_name": "紫光股份"}])

    def dc_index(self) -> pd.DataFrame:
        return pd.DataFrame([{"ts_code": "BK1134.DC", "name": "算力概念"}])

    def dc_member(self, ts_code: str) -> pd.DataFrame:
        assert ts_code == "BK1134.DC"
        return pd.DataFrame([{"ts_code": ts_code, "con_code": "688256.SH", "name": "寒武纪"}])


def test_update_opportunity_concept_cache_writes_indices_and_members(tmp_path: Path) -> None:
    """概念缓存应按主题关键词保存板块和成分股证据。"""
    db_path = tmp_path / "concept.duckdb"

    result = update_opportunity_concept_cache(
        db_path,
        {"domestic_ai_compute_infrastructure": ["算力"]},
        client=FakeConceptClient(),
    )

    assert result.index_count == 2
    assert result.member_count == 2
    with duckdb.connect(str(db_path), read_only=True) as con:
        members = con.execute("SELECT theme_id, provider, index_name, con_code FROM concept_member ORDER BY con_code").fetchall()

    assert members == [
        ("domestic_ai_compute_infrastructure", "ths", "算力租赁", "000938.SZ"),
        ("domestic_ai_compute_infrastructure", "dc", "算力概念", "688256.SH"),
    ]
