"""游资板块映射缓存测试。"""

from pathlib import Path

import duckdb

from runtime.hot_money_sector_map import load_hot_money_sector_map


def test_load_hot_money_sector_map_prefers_concept_and_falls_back_to_industry(tmp_path: Path) -> None:
    """概念成分优先，缺少概念时使用 Tushare 行业兜底。"""
    concept_path = tmp_path / "concept.duckdb"
    industry_path = tmp_path / "industry.duckdb"
    with duckdb.connect(str(concept_path)) as con:
        con.execute(
            """
            CREATE TABLE concept_member(
              theme_id VARCHAR,
              provider VARCHAR,
              index_code VARCHAR,
              index_name VARCHAR,
              con_code VARCHAR,
              con_name VARCHAR,
              keyword VARCHAR,
              updated_at VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO concept_member VALUES
            ('ai_compute', 'dc', 'BK1134.DC', '算力概念', '000001.SZ', 'A1', '算力', '2026-07-06')
            """
        )
    with duckdb.connect(str(industry_path)) as con:
        con.execute(
            """
            CREATE TABLE stock_industry(
              ts_code VARCHAR,
              symbol VARCHAR,
              name VARCHAR,
              area VARCHAR,
              industry VARCHAR,
              market VARCHAR,
              list_date VARCHAR,
              list_status VARCHAR,
              updated_at VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO stock_industry VALUES
            ('000001.SZ', '000001', 'A1', '深圳', '银行', '主板', '19910403', 'L', '2026-07-06'),
            ('000002.SZ', '000002', 'A2', '深圳', '房地产', '主板', '19910129', 'L', '2026-07-06')
            """
        )

    result = load_hot_money_sector_map(concept_path, industry_path)

    assert {"ts_code": "000001.SZ", "sector_name": "算力概念"} in result.to_dict("records")
    assert {"ts_code": "000002.SZ", "sector_name": "房地产"} in result.to_dict("records")
    assert {"ts_code": "000001.SZ", "sector_name": "银行"} not in result.to_dict("records")
