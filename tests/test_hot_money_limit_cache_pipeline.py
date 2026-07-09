"""游资涨跌停缓存流水线测试。"""

from pathlib import Path

import pandas as pd

from runtime.hot_money_limit_cache_pipeline import resolve_hot_money_cache_dates, update_hot_money_limit_cache
from runtime.paths import RuntimePaths


class FakeLimitClient:
    """测试用涨跌停客户端，记录请求过的交易日。"""

    def __init__(self) -> None:
        self.requested_dates: list[str] = []

    def limit_list_d(self, trade_date: str) -> pd.DataFrame:
        self.requested_dates.append(trade_date)
        return pd.DataFrame(
            {
                "trade_date": [trade_date],
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "close": [10.0],
                "pct_chg": [10.0],
                "limit": ["U"],
                "amount": [10000.0],
                "fd_amount": [1000.0],
                "first_time": ["09:30"],
                "last_time": ["09:30"],
                "open_times": [0],
            }
        )


def test_update_hot_money_limit_cache_writes_requested_dates(tmp_path: Path) -> None:
    """每日数据更新应把指定交易日涨跌停列表写入本地缓存。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    client = FakeLimitClient()

    result = update_hot_money_limit_cache(paths, ["20260706"], client=client)

    assert result["updated_dates"] == ["20260706"]
    assert result["rows_written"] == 1
    assert client.requested_dates == ["20260706"]
    assert paths.limit_list_increment_path.exists()


def test_update_hot_money_limit_cache_skips_when_no_dates(tmp_path: Path) -> None:
    """没有可用交易日时应跳过外部接口，避免无意义请求。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    client = FakeLimitClient()

    result = update_hot_money_limit_cache(paths, [], client=client)

    assert result["updated_dates"] == []
    assert result["rows_written"] == 0
    assert client.requested_dates == []


def test_resolve_hot_money_cache_dates_uses_latest_daily_when_cache_missing(tmp_path: Path) -> None:
    """日线无新增但涨跌停缓存缺失时，应用最新日线交易日补一次缓存。"""
    import duckdb

    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR)")
        con.execute("INSERT INTO daily VALUES ('000001.SZ', '20260706')")

    dates = resolve_hot_money_cache_dates(paths, [])

    assert dates == ["20260706"]


def test_resolve_hot_money_cache_dates_backfills_missing_limit_dates(tmp_path: Path) -> None:
    """涨跌停缓存已有旧日期时，也应补齐 live_market 中缺失的历史交易日。"""
    import duckdb

    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR)")
        con.execute("INSERT INTO daily VALUES ('000001.SZ', '20260706'), ('000001.SZ', '20260707')")
    with duckdb.connect(str(paths.limit_list_increment_path)) as con:
        con.execute("CREATE TABLE limit_list_daily(trade_date VARCHAR, ts_code VARCHAR)")
        con.execute("INSERT INTO limit_list_daily VALUES ('20260706', '000001.SZ')")

    dates = resolve_hot_money_cache_dates(paths, [])

    assert dates == ["20260707"]


def test_daily_data_update_message_includes_hot_money_cache(monkeypatch, tmp_path: Path) -> None:
    """每日数据更新成功摘要应包含游资涨跌停缓存结果，方便调度和通知排查。"""
    from scripts import run_daily_data_update

    monkeypatch.setattr(run_daily_data_update, "get_runtime_paths", lambda: RuntimePaths(tmp_path))
    monkeypatch.setattr(run_daily_data_update, "update_incremental", lambda run_date: (["20260706"], []))
    monkeypatch.setattr(run_daily_data_update, "update_benchmark_incremental", lambda run_date: [])
    monkeypatch.setattr(run_daily_data_update, "validate_incremental_quality", lambda: None)
    monkeypatch.setattr(run_daily_data_update, "sync_mainline_cache_from_increment", lambda *args, **kwargs: _SyncResult())
    monkeypatch.setattr(run_daily_data_update, "update_hot_money_limit_cache", lambda paths, dates: {"updated_dates": dates, "rows_written": 3})

    message = run_daily_data_update._build_success_message(["20260706"], [])
    result = run_daily_data_update._append_hot_money_cache_message(RuntimePaths(tmp_path), ["20260706"], [message])

    assert result[-1] == "游资涨跌停缓存已同步: 写入3行"


class _SyncResult:
    """主线缓存同步测试替身。"""

    missing_symbols: list[str] = []
    rows_written = 0
