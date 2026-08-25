"""策略目标组合到本地 Paper Broker 桥接测试。"""

import duckdb
import pandas as pd
import pytest

from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, FUND_ADJ_COLUMNS, MARKET_COLUMNS
from runtime.local_paper_bridge import (
    load_live_market_for_symbols,
    market_data_from_bars,
    sync_strategy_target_to_local_paper,
)
from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicyRepository


def test_market_data_from_bars_preserves_execution_constraints() -> None:
    """统一行情转换不能覆盖策略数据携带的停牌和涨跌停标记。"""
    bars = {
        "000001.SZ": pd.DataFrame(
            [
                {
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 0.0,
                    "amount": 0.0,
                    "is_suspended": True,
                    "limit_up": True,
                    "limit_down": False,
                }
            ],
            index=pd.to_datetime(["2026-07-15"]),
        )
    }

    frame = market_data_from_bars(bars, "20260715")

    assert bool(frame.iloc[0]["is_suspended"]) is True
    assert bool(frame.iloc[0]["limit_up"]) is True
    assert bool(frame.iloc[0]["limit_down"]) is False


def test_live_market_loader_supports_fund_snapshot(tmp_path) -> None:
    """混合资产目标中的 ETF 必须从基金快照读取，不能被股票行情门面静默丢弃。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    fund_history_path = paths.root / "etf_lof_reits_daily_adj_20041220_20260617.duckdb"
    with duckdb.connect(str(fund_history_path)) as con:
        con.execute(
            """
            CREATE TABLE etf_lof_reits_daily_adj(
                ts_code VARCHAR, trade_date VARCHAR,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE,
                vol DOUBLE, amount DOUBLE, adj_factor DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO etf_lof_reits_daily_adj VALUES
            ('518880.SH','20260722',8.8,8.9,8.7,8.8,8.7,0.1,1,100,880,1)
            """
        )
    store = BenchmarkIncrementalStore(paths.benchmark_increment_path)
    store.upsert_fund(
        pd.DataFrame(
            [["518880.SH", "20260723", 9.0, 9.1, 8.9, 9.0, 8.8, 0.2, 2.2, 1000, 9000]],
            columns=MARKET_COLUMNS,
        )
    )
    store.upsert_fund_adj(
        pd.DataFrame([["518880.SH", "20260723", 1.0]], columns=FUND_ADJ_COLUMNS)
    )

    frame = load_live_market_for_symbols(
        paths,
        "20260723",
        ["518880.SH"],
        {"518880.SH": "黄金ETF"},
    )

    assert frame["symbol"].tolist() == ["518880.SH"]
    assert frame.iloc[0]["name"] == "黄金ETF"
    assert frame.iloc[0]["open"] == 9.0
    assert frame.iloc[0]["volume"] == 100_000.0
    assert bool(frame.iloc[0]["is_suspended"]) is False


def test_live_market_loader_converts_stock_lots_to_shares(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """股票日线vol同样必须从Tushare手数转换为Broker股数。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    stock = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": "20260723",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 123.0,
                "amount": 123_000.0,
            }
        ]
    )
    monkeypatch.setattr(
        "runtime.local_paper_bridge._load_stock_market",
        lambda *args, **kwargs: stock,
    )

    frame = load_live_market_for_symbols(
        paths,
        "20260723",
        ["000001.SZ"],
    )

    assert frame.iloc[0]["volume"] == 12_300.0


def test_sync_target_applies_active_risk_cap_before_creating_orders(tmp_path) -> None:
    """盘后目标必须先经过持续风险上限，不能在下一日自动回补满仓。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    RiskPolicyRepository(paths.system_state_path).activate("strategy-a", "20260720", 0.3)
    market = pd.DataFrame(
        [
            {
                "trade_date": "20260720",
                "symbol": "000001.SZ",
                "name": "平安银行",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 1_000_000,
                "amount": 10_000_000,
                "is_suspended": False,
                "limit_up": False,
                "limit_down": False,
            }
        ]
    )

    sync_strategy_target_to_local_paper(
        paths,
        "strategy-a",
        "策略A",
        "20260720",
        {"000001.SZ": 0.9},
        market,
        100_000.0,
        "510300",
        "沪深300",
    )

    import sqlite3

    with sqlite3.connect(paths.paper_trading_path) as con:
        quantity = con.execute("SELECT quantity FROM paper_order WHERE status = 'PENDING'").fetchone()[0]
    with sqlite3.connect(paths.system_state_path) as con:
        target_weight = con.execute(
            "SELECT target_weight FROM account_positions WHERE strategy_id = 'strategy-a'"
        ).fetchone()[0]
    assert quantity == 3_000
    assert target_weight == 0.9


def test_risk_policy_replan_replaces_pending_orders_with_new_cap(tmp_path) -> None:
    """恢复确认后应取消旧目标单，并按下一交易日的新上限重建委托。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    policies = RiskPolicyRepository(paths.system_state_path)
    policies.activate("strategy-a", "20260708", 0.3)
    market = pd.DataFrame(
        [
            {
                "trade_date": "20260708",
                "symbol": "000001.SZ",
                "name": "平安银行",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 1_000_000,
                "amount": 10_000_000,
                "is_suspended": False,
                "limit_up": False,
                "limit_down": False,
            }
        ]
    )
    sync_strategy_target_to_local_paper(
        paths,
        "strategy-a",
        "策略A",
        "20260708",
        {"000001.SZ": 0.9},
        market,
        100_000.0,
        "510300",
        "沪深300",
    )
    policies.activate("strategy-a", "20260709", 0.5)

    result = sync_strategy_target_to_local_paper(
        paths,
        "strategy-a",
        "策略A",
        "20260708",
        {"000001.SZ": 0.9},
        market,
        100_000.0,
        "510300",
        "沪深300",
        risk_as_of_date="20260709",
        replace_pending_orders=True,
    )

    import sqlite3

    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute("SELECT status, quantity FROM paper_order ORDER BY id").fetchall()
    assert result.cancelled_orders == 1
    assert result.created_orders == 1
    assert rows == [("CANCELLED", 3_000), ("PENDING", 5_000)]
