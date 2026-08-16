"""公募基金披露持仓的可恢复季度缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import re
from pathlib import Path
from typing import Any, Protocol

import duckdb
import numpy as np
import pandas as pd


PORTFOLIO_FIELDS = (
    "ts_code,ann_date,end_date,symbol,mkv,amount,"
    "stk_mkv_ratio,stk_float_ratio"
)


class FundOwnershipClient(Protocol):
    """声明 Tushare 基金基础信息与持仓分页能力。"""

    def query(self, api_name: str, **kwargs: Any) -> pd.DataFrame:
        """调用指定 Tushare 接口。"""


@dataclass(frozen=True)
class FundOwnershipSyncResult:
    """一次基金持仓缓存同步结果。"""

    requested_periods: tuple[str, ...]
    updated_periods: tuple[str, ...]
    skipped_periods: tuple[str, ...]
    fetched_rows: int
    stored_rows: int
    api_calls: int


def update_fund_ownership_cache(
    client: FundOwnershipClient,
    database_path: Path,
    *,
    start_period: str,
    end_period: str,
    force: bool = False,
    page_size: int = 8000,
) -> FundOwnershipSyncResult:
    """按季度分页生成产品级前十大快照，原始全持仓仅作临时态。"""
    periods = _quarter_periods(start_period, end_period)
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    fetched_rows = 0
    api_calls = 0
    updated: list[str] = []
    skipped: list[str] = []
    try:
        _init_cache_schema(connection)
        api_calls += _sync_fund_basic(client, connection, page_size)
        for period in periods:
            if not force and _period_is_complete(connection, period):
                skipped.append(period)
                continue
            raw, calls = _fetch_pages(
                client,
                "fund_portfolio",
                page_size=page_size,
                period=period,
                fields=PORTFOLIO_FIELDS,
            )
            api_calls += calls
            fetched_rows += len(raw)
            normalized = normalize_fund_positions(raw)
            _replace_period(connection, period, normalized)
            _rebuild_product_top10(connection, period)
            # 长期事实是可复现的产品 Top10；全持仓只用于当期归并，避免缓存膨胀。
            connection.execute(
                "DELETE FROM fund_portfolio_positions WHERE end_date = ?",
                [period],
            )
            connection.execute(
                """
                INSERT INTO fund_portfolio_sync_state(
                    end_date, source_rows, normalized_rows, completed, updated_at
                ) VALUES (?, ?, ?, TRUE, now())
                ON CONFLICT(end_date) DO UPDATE SET
                    source_rows=excluded.source_rows,
                    normalized_rows=excluded.normalized_rows,
                    completed=TRUE,
                    updated_at=now()
                """,
                [period, len(raw), len(normalized)],
            )
            updated.append(period)
        stored_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM fund_portfolio_positions"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return FundOwnershipSyncResult(
        requested_periods=tuple(periods),
        updated_periods=tuple(updated),
        skipped_periods=tuple(skipped),
        fetched_rows=fetched_rows,
        stored_rows=stored_rows,
        api_calls=api_calls,
    )


def normalize_product_name(value: object) -> str:
    """移除基金 A/C/E 等份额后缀，保留产品主体名称。"""
    text = str(value or "").strip().replace("－", "-")
    text = re.sub(r"[- ]?(?:A/B|[A-Z])$", "", text)
    return re.sub(r"[- ]?[A-Z]类$", "", text)


def normalize_fund_positions(frame: pd.DataFrame) -> pd.DataFrame:
    """保留合法披露，并用完整载荷指纹保存源端冲突记录。"""
    required = PORTFOLIO_FIELDS.split(",")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"fund portfolio missing columns: {missing}")
    output = ["position_key", *required, "source"]
    if frame.empty:
        return pd.DataFrame(columns=output)

    data = frame[required].copy()
    ann_dates = pd.to_datetime(data["ann_date"], errors="coerce", format="mixed")
    end_dates = pd.to_datetime(data["end_date"], errors="coerce", format="mixed")
    for column in ["mkv", "amount", "stk_mkv_ratio", "stk_float_ratio"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data["ts_code"].fillna("").astype(str).str.len().gt(0)
        & data["symbol"].fillna("").astype(str).str.len().gt(0)
        & ann_dates.notna()
        & end_dates.notna()
        & end_dates.le(ann_dates)
        & data["mkv"].gt(0)
        & np.isfinite(data["mkv"])
    )
    data = data[valid].copy()
    data["ann_date"] = ann_dates[valid].dt.strftime("%Y%m%d")
    data["end_date"] = end_dates[valid].dt.strftime("%Y%m%d")
    data["ts_code"] = data["ts_code"].astype(str).str.strip()
    data["symbol"] = data["symbol"].astype(str).str.strip()
    data["position_key"] = data.apply(_position_key, axis=1)
    data["source"] = "tushare_fund_portfolio"
    return data.drop_duplicates("position_key", keep="last")[output].reset_index(drop=True)


def _sync_fund_basic(
    client: FundOwnershipClient,
    connection: duckdb.DuckDBPyConnection,
    page_size: int,
) -> int:
    """同步存续和已清盘开放式基金，避免当前存续池偏差。"""
    frames: list[pd.DataFrame] = []
    calls = 0
    for status in ["L", "D"]:
        frame, used = _fetch_pages(
            client,
            "fund_basic",
            page_size=page_size,
            market="O",
            status=status,
        )
        calls += used
        frame["requested_status"] = status
        frames.append(frame)
    basic = pd.concat(frames, ignore_index=True)
    basic = basic.drop_duplicates("ts_code", keep="last").copy()
    basic["normalized_name"] = basic["name"].map(normalize_product_name)
    basic["product_key"] = (
        basic["management"].fillna("").astype(str)
        + "|"
        + basic["normalized_name"]
    )
    columns = [
        "ts_code",
        "name",
        "management",
        "normalized_name",
        "product_key",
        "found_date",
        "due_date",
        "requested_status",
    ]
    connection.register("_fund_basic_frame", basic[columns])
    connection.execute("DELETE FROM fund_product_basic")
    connection.execute(
        """
        INSERT INTO fund_product_basic
        SELECT
            ts_code, name, management, normalized_name, product_key,
            found_date, due_date, requested_status,
            'tushare_fund_basic', now()
        FROM _fund_basic_frame
        """
    )
    connection.unregister("_fund_basic_frame")
    return calls


def _fetch_pages(
    client: FundOwnershipClient,
    api_name: str,
    *,
    page_size: int,
    **params: object,
) -> tuple[pd.DataFrame, int]:
    """读取到短页为止，禁止把接口单页上限误认为全量。"""
    frames: list[pd.DataFrame] = []
    offset = 0
    for page in range(1, 501):
        frame = client.query(
            api_name,
            offset=offset,
            limit=page_size,
            **params,
        )
        frames.append(frame)
        if len(frame) < page_size:
            return pd.concat(frames, ignore_index=True), page
        offset += len(frame)
    raise RuntimeError(f"{api_name} pagination exceeded 500 pages")


def _replace_period(
    connection: duckdb.DuckDBPyConnection,
    period: str,
    frame: pd.DataFrame,
) -> None:
    """在事务内原子替换一个报告期。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM fund_portfolio_positions WHERE end_date = ?",
            [period],
        )
        if not frame.empty:
            connection.register("_fund_position_frame", frame)
            connection.execute(
                """
                INSERT INTO fund_portfolio_positions
                SELECT
                    position_key, ts_code, ann_date, end_date, symbol,
                    mkv, amount, stk_mkv_ratio, stk_float_ratio, source, now()
                FROM _fund_position_frame
                """
            )
            connection.unregister("_fund_position_frame")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _rebuild_product_top10(
    connection: duckdb.DuckDBPyConnection,
    period: str,
) -> None:
    """选择当期代表份额并统一截取产品前十大 A 股。"""
    available_date = _period_available_date(period)
    connection.execute("DELETE FROM fund_product_top10 WHERE end_date = ?", [period])
    connection.execute(
        """
        INSERT INTO fund_product_top10
        WITH candidate_codes AS (
            SELECT DISTINCT
                p.end_date,
                b.product_key,
                p.ts_code,
                COALESCE(b.found_date, '99999999') AS found_date
            FROM fund_portfolio_positions p
            JOIN fund_product_basic b ON p.ts_code = b.ts_code
            WHERE p.end_date = ?
              AND p.ts_code LIKE '%.OF'
              AND b.product_key <> '|'
        ),
        representative AS (
            SELECT * EXCLUDE(choice_rank)
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER(
                        PARTITION BY end_date, product_key
                        ORDER BY found_date, ts_code
                    ) AS choice_rank
                FROM candidate_codes
            )
            WHERE choice_rank = 1
        ),
        aggregated AS (
            SELECT
                p.end_date,
                r.product_key,
                p.ts_code AS representative_code,
                p.symbol,
                MAX(p.ann_date) AS ann_date,
                MAX(p.mkv) AS mkv
            FROM fund_portfolio_positions p
            JOIN representative r
              ON p.end_date = r.end_date
             AND p.ts_code = r.ts_code
             AND r.product_key IS NOT NULL
            WHERE p.end_date = ?
              AND REGEXP_MATCHES(p.symbol, '^\\d{6}\\.(SH|SZ|BJ)$')
            GROUP BY p.end_date, r.product_key, p.ts_code, p.symbol
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER(
                    PARTITION BY end_date, product_key
                    ORDER BY mkv DESC, symbol
                ) AS position_rank
            FROM aggregated
        )
        SELECT
            end_date,
            ? AS available_date,
            product_key,
            representative_code,
            symbol,
            ann_date,
            mkv,
            position_rank
        FROM ranked
        WHERE position_rank <= 10
        """,
        [period, period, available_date],
    )


def _init_cache_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化基金基础、临时持仓、可比快照和同步游标。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_product_basic(
            ts_code VARCHAR PRIMARY KEY,
            name VARCHAR,
            management VARCHAR,
            normalized_name VARCHAR NOT NULL,
            product_key VARCHAR NOT NULL,
            found_date VARCHAR,
            due_date VARCHAR,
            status VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS fund_portfolio_positions(
            position_key VARCHAR PRIMARY KEY,
            ts_code VARCHAR NOT NULL,
            ann_date VARCHAR NOT NULL,
            end_date VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            mkv DOUBLE NOT NULL,
            amount DOUBLE,
            stk_mkv_ratio DOUBLE,
            stk_float_ratio DOUBLE,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS fund_product_top10(
            end_date VARCHAR NOT NULL,
            available_date VARCHAR NOT NULL,
            product_key VARCHAR NOT NULL,
            representative_code VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            ann_date VARCHAR NOT NULL,
            mkv DOUBLE NOT NULL,
            position_rank INTEGER NOT NULL,
            PRIMARY KEY(end_date, product_key, symbol)
        );
        CREATE TABLE IF NOT EXISTS fund_portfolio_sync_state(
            end_date VARCHAR PRIMARY KEY,
            source_rows BIGINT NOT NULL,
            normalized_rows BIGINT NOT NULL,
            completed BOOLEAN NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _period_is_complete(
    connection: duckdb.DuckDBPyConnection,
    period: str,
) -> bool:
    row = connection.execute(
        "SELECT completed FROM fund_portfolio_sync_state WHERE end_date = ?",
        [period],
    ).fetchone()
    return bool(row and row[0])


def _quarter_periods(start_period: str, end_period: str) -> list[str]:
    """生成闭区间季度末列表。"""
    start = datetime.strptime(_normalize_date(start_period), "%Y%m%d").date()
    end = datetime.strptime(_normalize_date(end_period), "%Y%m%d").date()
    if start > end:
        raise ValueError("start_period cannot be later than end_period")
    periods: list[str] = []
    for year in range(start.year, end.year + 1):
        for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            value = date(year, month, day)
            if start <= value <= end:
                periods.append(value.strftime("%Y%m%d"))
    if not periods:
        raise ValueError("period range does not contain quarter end")
    return periods


def _period_available_date(period: str) -> str:
    """使用保守法定披露截止日，避免按报告期前移信息。"""
    value = datetime.strptime(_normalize_date(period), "%Y%m%d").date()
    if value.month == 3:
        return date(value.year, 4, 30).strftime("%Y%m%d")
    if value.month == 6:
        return date(value.year, 8, 31).strftime("%Y%m%d")
    if value.month == 9:
        return date(value.year, 10, 31).strftime("%Y%m%d")
    return date(value.year + 1, 4, 30).strftime("%Y%m%d")


def _position_key(row: pd.Series) -> str:
    values = []
    for column in PORTFOLIO_FIELDS.split(","):
        value = row[column]
        values.append("" if pd.isna(value) else str(value))
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    datetime.strptime(normalized, "%Y%m%d")
    return normalized
