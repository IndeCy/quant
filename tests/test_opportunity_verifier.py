"""机会池入池证据校验测试。"""

from pathlib import Path

import duckdb

from runtime.opportunity_catalog import register_builtin_opportunity_themes
from runtime.opportunity_verifier import verify_opportunity_seed_stocks
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_verify_opportunity_seed_stocks_promotes_industry_and_concept_matched_seed(tmp_path: Path) -> None:
    """候选种子只有同时命中行业和概念证据后，才能升级为正式观察股。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    register_builtin_opportunity_themes(repository)
    _seed_industry_cache(paths.data_dir / "industry_increment.duckdb")
    _seed_concept_cache(paths.data_dir / "opportunity_concept_increment.duckdb")

    result = verify_opportunity_seed_stocks(paths)
    promoted = repository.load_opportunity_stock("domestic_ai_compute_infrastructure", "000938.SZ")
    rejected = repository.load_opportunity_stock("domestic_ai_compute_infrastructure", "688256.SH")

    assert result["verified_count"] == 1
    assert result["unverified_count"] >= 1
    assert promoted["status"] == "active"
    assert promoted["verification_status"] == "verified"
    assert promoted["source_type"] == "industry_concept_match"
    assert "IT设备" in promoted["source_detail"]
    assert promoted["evidence"]["verification"]["matched"] is True
    assert promoted["evidence"]["verification"]["concept_matches"][0]["index_name"] == "算力概念"
    assert promoted["evidence"]["verification"]["theme_fit_score"] >= 75
    assert promoted["evidence"]["verification"]["theme_fit_grade"] == "A"
    assert "行业证据" in promoted["evidence"]["verification"]["selection_reasons"][0]
    assert promoted["evidence"]["verification"]["evidence_gaps"] == []
    assert rejected["status"] == "candidate_seed"
    assert rejected["verification_status"] == "unverified"
    assert rejected["evidence"]["verification"]["matched"] is False
    assert any("缺少主题概念成分证据" in item for item in rejected["evidence"]["verification"]["evidence_gaps"])


def test_verify_opportunity_seed_stocks_keeps_case_study_as_seed(tmp_path: Path) -> None:
    """历史校准案例即使行业匹配，也不能升级为正式机会候选。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    register_builtin_opportunity_themes(repository)
    _seed_industry_cache(paths.data_dir / "industry_increment.duckdb", include_case=True)

    verify_opportunity_seed_stocks(paths)
    stock = repository.load_opportunity_stock("ai_optical_module_powerlaw", "300308.SZ")
    theme = repository.load_opportunity_theme("ai_optical_module_powerlaw")

    assert theme["status"] == "case_study"
    assert stock["status"] == "candidate_seed"
    assert stock["verification_status"] == "unverified"
    assert stock["evidence"]["verification"]["reason"] == "case_study_theme"


def test_verify_opportunity_seed_stocks_refreshes_verified_evidence(tmp_path: Path) -> None:
    """已验证观察股也应刷新证据，防止每日监控覆盖后丢失来源。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme(
        {
            "theme_id": "domestic_ai_compute_infrastructure",
            "name": "国产算力基础设施",
            "status": "observation",
            "stage": "Seed",
            "thesis_type": "emerging_power_law_candidate",
        }
    )
    repository.upsert_opportunity_stock(
        {
            "theme_id": "domestic_ai_compute_infrastructure",
            "symbol": "000938.SZ",
            "name": "紫光股份",
            "status": "active",
            "verification_status": "verified",
            "source_type": "industry_match",
        }
    )
    _seed_industry_cache(paths.data_dir / "industry_increment.duckdb")
    _seed_concept_cache(paths.data_dir / "opportunity_concept_increment.duckdb")

    verify_opportunity_seed_stocks(paths)
    stock = repository.load_opportunity_stock("domestic_ai_compute_infrastructure", "000938.SZ")

    assert stock["status"] == "active"
    assert stock["verification_status"] == "verified"
    assert stock["evidence"]["verification"]["industry"] == "IT设备"
    assert stock["source_type"] == "industry_concept_match"


def test_verify_opportunity_seed_stocks_downgrades_when_concept_evidence_disappears(tmp_path: Path) -> None:
    """已验证股票如果缺少概念证据，应降回候选种子，避免旧状态污染观察池。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme(
        {
            "theme_id": "domestic_ai_compute_infrastructure",
            "name": "国产算力基础设施",
            "status": "observation",
            "stage": "Seed",
            "thesis_type": "emerging_power_law_candidate",
        }
    )
    repository.upsert_opportunity_stock(
        {
            "theme_id": "domestic_ai_compute_infrastructure",
            "symbol": "000938.SZ",
            "name": "紫光股份",
            "status": "active",
            "verification_status": "verified",
            "source_type": "industry_concept_match",
        }
    )
    _seed_industry_cache(paths.data_dir / "industry_increment.duckdb")

    verify_opportunity_seed_stocks(paths)
    stock = repository.load_opportunity_stock("domestic_ai_compute_infrastructure", "000938.SZ")

    assert stock["status"] == "candidate_seed"
    assert stock["verification_status"] == "unverified"
    assert stock["evidence"]["verification"]["reason"] == "concept_missing"


def _seed_industry_cache(path: Path, include_case: bool = False) -> None:
    """构造最小 Tushare 行业缓存。"""
    with duckdb.connect(str(path)) as con:
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
        rows = [
            ("688256.SH", "688256", "寒武纪", "北京", "互联网", "科创板", "20200720", "L", "2026-07-01"),
            ("000938.SZ", "000938", "紫光股份", "北京", "IT设备", "主板", "19991104", "L", "2026-07-01"),
        ]
        if include_case:
            rows.append(("300308.SZ", "300308", "中际旭创", "山东", "通信设备", "创业板", "20120410", "L", "2026-07-01"))
        else:
            rows.append(("300308.SZ", "300308", "中际旭创", "山东", "通信设备", "创业板", "20120410", "L", "2026-07-01"))
        con.executemany("INSERT INTO stock_industry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _seed_concept_cache(path: Path) -> None:
    """构造最小概念成分缓存。"""
    with duckdb.connect(str(path)) as con:
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
            ('domestic_ai_compute_infrastructure', 'dc', 'BK1134.DC', '算力概念', '000938.SZ', '紫光股份', '算力', '2026-07-01')
            """
        )
