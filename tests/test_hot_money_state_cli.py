import subprocess
import sys
from pathlib import Path

import pandas as pd

from data.tushare_limit_incremental import LimitListDuckDBStore


def test_hot_money_state_cli_writes_report(tmp_path: Path) -> None:
    store = LimitListDuckDBStore(tmp_path / "limit.duckdb")
    store.upsert(
        pd.DataFrame(
            [
                {
                    "trade_date": "20260707",
                    "ts_code": "000001.SZ",
                    "name": "样本A",
                    "close": 10,
                    "pct_chg": 10,
                    "limit": "U",
                    "amount": 100,
                    "fd_amount": 10,
                    "first_time": "093000",
                    "last_time": "145700",
                    "open_times": 0,
                }
            ]
        )
    )
    output_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_hot_money_state.py",
            "--cache-path",
            str(store.path),
            "--start-date",
            "20260707",
            "--end-date",
            "20260707",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = output_dir / "market_state_report.md"
    assert report.exists()
    assert "市场状态" in report.read_text(encoding="utf-8")
    assert "market_state_report.md" in result.stdout
