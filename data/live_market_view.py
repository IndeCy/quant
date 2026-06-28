"""把只读历史基线与Tushare增量库合并为统一行情视图。"""

from __future__ import annotations

from pathlib import Path


def open_live_market_connection(
    base_path: str | Path,
    increment_path: str | Path,
    lookback_start: str = "20140701",
):
    """创建内存连接，并提供策略研究兼容的表名。"""
    import duckdb

    base = _quote_path(Path(base_path))
    increment = _quote_path(Path(increment_path))
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH DATABASE '{base}' AS base_db (READ_ONLY)")
    con.execute(f"ATTACH DATABASE '{increment}' AS live_db (READ_ONLY)")
    con.execute(
        f"""
        CREATE VIEW daily AS
        SELECT b.* FROM base_db.daily b
        WHERE b.trade_date >= '{lookback_start}'
          AND NOT EXISTS (
              SELECT 1 FROM live_db.daily i
              WHERE i.ts_code = b.ts_code AND i.trade_date = b.trade_date
          )
        UNION ALL
        SELECT * FROM live_db.daily WHERE trade_date >= '{lookback_start}'
        """
    )
    con.execute(
        f"""
        CREATE VIEW adj_factor AS
        SELECT b.* FROM base_db.adj_factor b
        WHERE b.trade_date >= '{lookback_start}'
          AND NOT EXISTS (
              SELECT 1 FROM live_db.adj_factor i
              WHERE i.ts_code = b.ts_code AND i.trade_date = b.trade_date
          )
        UNION ALL
        SELECT * FROM live_db.adj_factor WHERE trade_date >= '{lookback_start}'
        """
    )
    # 复权因子并非每个行情日都有记录，使用有效区间向后延续最近因子。
    con.execute(
        """
        CREATE VIEW daily_adj_cache AS
        WITH factor_ranges AS (
            SELECT
                ts_code,
                trade_date AS factor_start,
                LEAD(trade_date) OVER(PARTITION BY ts_code ORDER BY trade_date) AS factor_end,
                adj_factor
            FROM adj_factor
        ),
        factor_bounds AS (
            SELECT
                ts_code,
                MIN(adj_factor) FILTER (
                    trade_date = first_date
                ) AS first_adj,
                MAX(adj_factor) FILTER (
                    trade_date = last_date
                ) AS last_adj
            FROM (
                SELECT
                    *,
                    MIN(trade_date) OVER(PARTITION BY ts_code) AS first_date,
                    MAX(trade_date) OVER(PARTITION BY ts_code) AS last_date
                FROM adj_factor
            ) factors
            GROUP BY ts_code
        ),
        joined AS (
            SELECT d.*, f.adj_factor, b.first_adj, b.last_adj
            FROM daily d
            JOIN factor_ranges f
              ON d.ts_code = f.ts_code
             AND d.trade_date >= f.factor_start
             AND (f.factor_end IS NULL OR d.trade_date < f.factor_end)
            JOIN factor_bounds b ON d.ts_code = b.ts_code
        )
        SELECT
            ts_code, trade_date, adj_factor, first_adj, last_adj,
            open * adj_factor / last_adj AS open_qfq,
            high * adj_factor / last_adj AS high_qfq,
            low * adj_factor / last_adj AS low_qfq,
            close * adj_factor / last_adj AS close_qfq,
            pre_close * adj_factor / last_adj AS pre_close_qfq,
            change * adj_factor / last_adj AS change_qfq,
            pct_chg AS pct_chg_qfq,
            open * adj_factor AS open_hfq,
            high * adj_factor AS high_hfq,
            low * adj_factor AS low_hfq,
            close * adj_factor AS close_hfq,
            pre_close * adj_factor AS pre_close_hfq,
            change * adj_factor AS change_hfq,
            pct_chg AS pct_chg_hfq
        FROM joined
        """
    )
    # 基础信息和历史ST状态仍来自基线库；无权限更新时由日报显式提示降级。
    for table in ["stock_basic", "stock_st", "stock_namechange", "stock_name_manual"]:
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM base_db.{table}")
    return con


def _quote_path(path: Path) -> str:
    """DuckDB ATTACH 路径中的单引号需要转义。"""
    if not path.exists():
        raise FileNotFoundError(f"DuckDB文件不存在: {path}")
    return str(path.resolve()).replace("'", "''")
