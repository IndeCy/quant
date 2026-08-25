"""官方源净流入可行性审计的底层数据契约检查。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.order_flow import ORDER_FLOW_ASOF_TABLE


def load_source_diagnostics(
    connection: Any,
    expected_trade_dates: list[str],
) -> dict[str, float]:
    """确认双边分类契约，并审计同步完整性、点时和数值范围。"""
    placeholders = ",".join("?" for _ in expected_trade_dates)
    sync = connection.execute(
        f"""
        SELECT trade_date, status, raw_row_count
        FROM order_flow_db.order_flow_sync_log
        WHERE trade_date IN ({placeholders})
        ORDER BY trade_date
        """,
        expected_trade_dates,
    ).fetchdf()
    source = connection.execute(
        """
        SELECT
            COUNT(*) - COUNT(DISTINCT trade_date || ':' || ts_code),
            AVG(CASE WHEN ABS(all_net_amount_wan) <= 0.05
                     THEN 1.0 ELSE 0.0 END)
        FROM order_flow_db.order_flow_daily
        """
    ).fetchone()
    consistency = connection.execute(
        """
        WITH ratios AS (
            SELECT
                o.classified_amount_wan * 10000.0
                    / NULLIF(f.amount * 1000.0, 0) AS value
            FROM order_flow_db.order_flow_daily o
            JOIN features f
              ON o.trade_date=f.trade_date AND o.ts_code=f.symbol
            WHERE o.classified_amount_wan > 0 AND f.amount > 0
        )
        SELECT QUANTILE_CONT(value,0.01), QUANTILE_CONT(value,0.50),
               QUANTILE_CONT(value,0.99)
        FROM ratios
        """
    ).fetchone()
    asof = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN latest_flow_date > signal_date THEN 1 ELSE 0 END),
            SUM(CASE WHEN source_net_turnover_share NOT BETWEEN -1 AND 1
                     THEN 1 ELSE 0 END)
        FROM {ORDER_FLOW_ASOF_TABLE}
        """
    ).fetchone()
    raw = pd.to_numeric(sync["raw_row_count"], errors="coerce").fillna(0)
    return {
        "checked_trade_day_share": float(
            sync["trade_date"].nunique() / len(expected_trade_dates)
        ),
        "successful_trade_day_share": float(
            sync["status"].eq("SUCCESS").sum() / len(expected_trade_dates)
        ),
        "max_raw_rows": float(raw.max() if not raw.empty else 0),
        "duplicate_daily_rows": float(source[0] or 0),
        "symmetric_bucket_share": float(source[1] or 0),
        "turnover_ratio_p01": float(consistency[0] or 0),
        "turnover_ratio_median": float(consistency[1] or 0),
        "turnover_ratio_p99": float(consistency[2] or 0),
        "visibility_violations": float(asof[0] or 0),
        "source_share_range_violations": float(asof[1] or 0),
    }
