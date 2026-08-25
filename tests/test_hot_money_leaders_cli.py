"""游资主线龙头报告 CLI 测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from scripts.run_hot_money_leaders import main


def test_run_hot_money_leaders_writes_report(tmp_path: Path) -> None:
    """CLI 应读取本地缓存并输出主线龙头报告。"""
    db_path = tmp_path / "limit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE limit_list_daily AS
            SELECT * FROM (
                VALUES
                ('20260706','000001.SZ','A1',10.0,10.0,'U',100.0,0.0,'09:30','09:30',0),
                ('20260706','000002.SZ','A2',10.0,10.0,'U',80.0,0.0,'09:31','09:31',1)
            ) AS t(trade_date, ts_code, name, close, pct_chg, limit_type, amount, fd_amount, first_time, last_time, open_times)
            """
        )
    sector_csv = tmp_path / "sector.csv"
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000002.SZ", "sector_name": "算力"},
        ]
    ).to_csv(sector_csv, index=False)
    output = tmp_path / "report.md"

    code = main(["--db-path", str(db_path), "--sector-map-csv", str(sector_csv), "--output", str(output)])

    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "游资主线与龙头识别报告" in text
    assert "算力" in text
    assert "A1" in text
