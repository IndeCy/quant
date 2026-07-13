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


def test_update_opportunity_concept_cache_deduplicates_daily_members(tmp_path: Path) -> None:
    """东方财富板块成分可能按日期重复返回，同一板块同一股票只能保留一条证据。"""

    class DuplicateClient(FakeConceptClient):
        def dc_member(self, ts_code: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"trade_date": "20260703", "ts_code": ts_code, "con_code": "688256.SH", "name": "寒武纪"},
                    {"trade_date": "20260706", "ts_code": ts_code, "con_code": "688256.SH", "name": "寒武纪"},
                ]
            )

    db_path = tmp_path / "concept.duckdb"
    update_opportunity_concept_cache(
        db_path,
        {"domestic_ai_compute_infrastructure": ["算力"]},
        client=DuplicateClient(),
    )

    with duckdb.connect(str(db_path), read_only=True) as con:
        count = con.execute(
            """
            SELECT COUNT(*)
            FROM concept_member
            WHERE theme_id = 'domestic_ai_compute_infrastructure'
              AND provider = 'dc'
              AND con_code = '688256.SH'
            """
        ).fetchone()[0]

    assert count == 1


def test_update_opportunity_concept_cache_uses_project_config_token(monkeypatch, tmp_path: Path) -> None:
    """概念更新应支持读取 .env.properties，不能只依赖进程环境变量。"""
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    config_path = tmp_path / ".env.properties"
    config_path.write_text("TUSHARE_TOKEN=test-token\n", encoding="utf-8")
    monkeypatch.setattr("runtime.config.default_config_path", lambda: config_path)
    captured: dict[str, str] = {}

    class CapturingClient(FakeConceptClient):
        def __init__(self, token: str) -> None:
            captured["token"] = token

    monkeypatch.setattr("data.tushare_concept_incremental.TushareConceptClient", CapturingClient)

    update_opportunity_concept_cache(tmp_path / "concept.duckdb", {})

    assert captured["token"] == "test-token"
