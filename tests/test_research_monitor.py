"""投研机会池每日监控测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from backtest.cache import MarketDataCache
from runtime.opportunity_catalog import register_builtin_opportunity_themes
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.research_monitor import (
    _build_powerlaw_evidence,
    _classify_watch_level,
    format_research_monitor_notification,
    run_research_monitor,
)


def test_research_monitor_updates_opportunity_stock_metrics(tmp_path: Path) -> None:
    """内置种子只做候选监控，未验证前不能污染正式方向排行。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    register_builtin_opportunity_themes(repository)
    _seed_market_cache(paths.data_dir / "market_cache.sqlite3")
    _seed_finance_db(paths.root / "fina_indicator.duckdb")

    result = run_research_monitor(paths)
    theme = repository.load_opportunity_theme("ai_optical_module_powerlaw")
    stock = next(item for item in theme["stocks"] if item["symbol"] == "300308.SZ")
    missing_stock = next(item for item in theme["stocks"] if item["symbol"] == "300394.SZ")

    assert result.theme_count >= 7
    assert result.stock_count >= 35
    assert stock["status"] == "candidate_seed"
    assert stock["source_type"] == "built_in_seed"
    assert stock["verification_status"] == "unverified"
    assert stock["watch_level"] == "案例"
    assert stock["last_monitor_date"] == result.trade_date
    assert stock["metrics"]["data_status"] == "ok"
    assert stock["metrics"]["ret_120d"] > 0.5
    assert stock["metrics"]["relative_strength_250d"] > 0.2
    assert stock["evidence"]["finance_growth_confirmed"] is True
    assert stock["evidence"]["maturity_score"] >= 55
    assert stock["evidence"]["early_signal_score"] <= 45
    assert stock["evidence"]["upgrade_path"] == "CaseStudyCalibration"
    assert missing_stock["metrics"]["data_status"] == "missing"
    assert missing_stock["evidence"]["upgrade_path"] == "Observation"
    assert theme["monitor_runs"][0]["status"] == "SUCCESS"
    assert theme["monitor_runs"][0]["metrics"]["upgrade_candidate"] is False
    rankings = repository.list_opportunity_direction_rankings()
    assert rankings
    assert all(item["metrics"]["eligible_stock_count"] == 0 for item in rankings)
    assert all(item["strength_score"] == 0 for item in rankings)
    assert all(item["upgrade_candidate"] is False for item in rankings)
    assert "已验证入池股票不足" in rankings[0]["summary"]


def test_research_monitor_ranks_only_verified_active_stocks(tmp_path: Path) -> None:
    """只有经过证据校验的正式观察股才能贡献 S/A 和主题强势分。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme(
        {
            "theme_id": "verified_theme",
            "name": "已验证方向",
            "status": "observation",
            "stage": "Seed",
            "thesis_type": "emerging_power_law_candidate",
            "thesis": "用于测试正式入池。",
        }
    )
    for index, symbol in enumerate(["300001.SZ", "300002.SZ", "300003.SZ"], start=1):
        repository.upsert_opportunity_stock(
            {
                "theme_id": "verified_theme",
                "symbol": symbol,
                "name": f"样本{index}",
                "status": "active",
                "watch_level": "B",
                "source_type": "concept_match",
                "source_detail": "概念命中: 测试主题",
                "verification_status": "verified",
                "evidence": {"verification": {"matched": True, "reason": "concept_matched"}},
            }
        )
    _seed_market_cache(paths.data_dir / "market_cache.sqlite3", symbols=["300001.SZ", "300002.SZ", "300003.SZ"], daily_growth=1.0025)
    _seed_finance_db(paths.root / "fina_indicator.duckdb", symbols=["300001.SZ", "300002.SZ", "300003.SZ"])

    run_research_monitor(paths)
    rankings = repository.list_opportunity_direction_rankings()
    verified = next(item for item in rankings if item["theme_id"] == "verified_theme")

    assert verified["metrics"]["eligible_stock_count"] == 3
    assert verified["metrics"]["s_count"] == 3
    assert verified["upgrade_candidate"] is True
    assert verified["strength_score"] > 0
    stock = repository.load_opportunity_stock("verified_theme", "300001.SZ")
    assert stock["evidence"]["verification"]["matched"] is True
    assert stock["evidence"]["priority"]["score"] > 60
    assert stock["evidence"]["priority"]["grade"] in {"S", "A"}
    assert "主题适配" in stock["evidence"]["priority"]["reasons"][0]


def test_powerlaw_evidence_prefers_early_signal_over_mature_winner() -> None:
    """未来机会雷达应奖励早期起势，而不是追逐已经高度兑现的赢家。"""
    metrics = {
        "data_status": "ok",
        "ret_60d": 0.18,
        "ret_120d": 0.32,
        "ret_1y": 0.65,
        "ret_2y": 0.0,
        "relative_strength_250d": 0.35,
        "distance_to_high_250d": -0.08,
        "tr_yoy": 45.0,
        "netprofit_yoy": 60.0,
        "grossprofit_margin": 32.0,
        "ocf_to_or": 0.12,
    }

    evidence = _build_powerlaw_evidence(None, metrics, {"status": "observation", "thesis_type": "power_law_industry"})
    level = _classify_watch_level(metrics, evidence, {"status": "observation", "thesis_type": "power_law_industry"})

    assert evidence["early_signal_score"] >= 75
    assert evidence["maturity_score"] < 55
    assert evidence["crowding_score"] < 55
    assert evidence["opportunity_phase"] == "EarlyPowerLawCandidate"
    assert evidence["upgrade_path"] == "PaperCandidate"
    assert level == "S"


def test_research_monitor_notification_template() -> None:
    """投研监控通知应使用稳定摘要模板。"""
    result = type(
        "Result",
        (),
        {"trade_date": "20260702", "theme_count": 7, "stock_count": 35, "upgrade_candidates": 2},
    )()

    body = format_research_monitor_notification(result)

    assert "投研监控状态：SUCCESS" in body
    assert "交易日：20260702" in body
    assert "观察主题：7" in body
    assert "观察股票：35" in body
    assert "升级候选：2" in body


def _seed_market_cache(path: Path, symbols: list[str] | None = None, daily_growth: float = 1.006) -> None:
    """构造一段明显上行的前复权日线，模拟产业右偏样本。"""
    dates = pd.bdate_range("2025-01-02", periods=320)
    close = pd.Series([10.0 * (daily_growth ** index) for index in range(len(dates))], index=dates)
    bars = pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": 1000000.0,
            "amount": close * 1000000.0,
        },
        index=dates,
    )
    cache = MarketDataCache(path)
    try:
        for symbol in symbols or ["300308.SZ"]:
            cache.upsert_bars("tushare", symbol, "1d", "qfq", bars)
        benchmark = bars.copy()
        benchmark["close"] = 5.0
        benchmark["open"] = 5.0
        benchmark["high"] = 5.0
        benchmark["low"] = 5.0
        benchmark["amount"] = 5000000.0
        cache.upsert_bars("tushare", "510300.SH", "1d", "qfq", benchmark)
    finally:
        cache.close()


def _seed_finance_db(path: Path, symbols: list[str] | None = None) -> None:
    """构造监控所需的最小财务快照。"""
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE default_table(
              ts_code VARCHAR,
              end_date VARCHAR,
              roe DOUBLE,
              roa DOUBLE,
              grossprofit_margin DOUBLE,
              ocf_to_or DOUBLE,
              tr_yoy DOUBLE,
              netprofit_yoy DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO default_table VALUES (?, '20251231', 24.0, 15.0, 36.0, 0.22, 48.0, 72.0)",
            [[symbol] for symbol in (symbols or ["300308.SZ"])],
        )
