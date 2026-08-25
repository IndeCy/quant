"""游资主线龙头研究 API 测试。"""

import duckdb
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_hot_money_research_api_exposes_latest_view(tmp_path) -> None:
    """研究页 API 应暴露最新游资主线和龙头摘要。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    db_path = paths.data_dir / "limit_list_increment.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE limit_list_daily AS
            SELECT * FROM (
                VALUES
                ('20260706','000001.SZ','A1',10.0,10.0,'U',120.0,0.0,'09:30','09:30',0)
            ) AS t(trade_date, ts_code, name, close, pct_chg, limit_type, amount, fd_amount, first_time, last_time, open_times)
            """
        )
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/research/hot-money-leaders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["latest_trade_date"] == "20260706"
    assert payload["leaders"][0]["name"] == "A1"
