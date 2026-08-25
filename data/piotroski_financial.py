"""Piotroski F-Score 年报数据的公告日 as-of 门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


PIOTROSKI_ASOF_TABLE = "piotroski_financial_asof"


class DuckDBConnection(Protocol):
    """声明点时财务物化所需的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class PiotroskiFinancialPaths:
    """F-Score 需要的三张标准财务报表。"""

    income: Path
    balance: Path
    cashflow: Path

    def validate(self) -> None:
        """连接前一次性检查数据文件，避免生成不完整截面。"""
        missing = [
            str(path.resolve())
            for path in (self.income, self.balance, self.cashflow)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少 Piotroski 财务数据文件: {missing}")


def attach_piotroski_financial_databases(
    connection: DuckDBConnection,
    paths: PiotroskiFinancialPaths,
) -> None:
    """只读挂载利润表、资产负债表和现金流量表。"""
    paths.validate()
    aliases = {
        "pi_income_db": paths.income,
        "pi_balance_db": paths.balance,
        "pi_cashflow_db": paths.cashflow,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)")


def create_piotroski_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表，所有财报可见性都以此为上界。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE piotroski_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO piotroski_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_piotroski_financial_asof(
    connection: DuckDBConnection,
) -> str:
    """物化每个信号日可见的最新连续三年 F-Score。

    每张报表独立执行 ``f_ann_date <= signal_date``，再按报告期取当时最新
    修订版。只有三张表同一报告期均已披露，才允许进入九项计算。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {PIOTROSKI_ASOF_TABLE} AS
        WITH income_visible AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.n_income_attr_p AS DOUBLE) AS net_income,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.oper_cost AS DOUBLE) AS operating_cost,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, i.ts_code, i.end_date
                    ORDER BY i.f_ann_date DESC, i.update_flag DESC, i.ann_date DESC
                ) AS revision_rank
            FROM piotroski_signal_dates d
            JOIN pi_income_db.default_table i
              ON i.f_ann_date <= d.signal_date
            WHERE RIGHT(i.end_date, 4) = '1231'
              AND i.f_ann_date IS NOT NULL
        ),
        balance_visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                COALESCE(CAST(b.lt_borr AS DOUBLE), 0.0) AS long_term_debt,
                CAST(b.total_cur_assets AS DOUBLE) AS current_assets,
                CAST(b.total_cur_liab AS DOUBLE) AS current_liabilities,
                CAST(b.total_share AS DOUBLE) AS total_shares,
                CAST(b.total_hldr_eqy_exc_min_int AS DOUBLE) AS book_equity,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code, b.end_date
                    ORDER BY b.f_ann_date DESC, b.update_flag DESC, b.ann_date DESC
                ) AS revision_rank
            FROM piotroski_signal_dates d
            JOIN pi_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
        ),
        cashflow_visible AS (
            SELECT
                d.signal_date,
                c.ts_code AS symbol,
                c.end_date,
                c.f_ann_date,
                CAST(c.n_cashflow_act AS DOUBLE) AS operating_cashflow,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, c.ts_code, c.end_date
                    ORDER BY c.f_ann_date DESC, c.update_flag DESC, c.ann_date DESC
                ) AS revision_rank
            FROM piotroski_signal_dates d
            JOIN pi_cashflow_db.default_table c
              ON c.f_ann_date <= d.signal_date
            WHERE RIGHT(c.end_date, 4) = '1231'
              AND c.f_ann_date IS NOT NULL
        ),
        common_reports AS (
            SELECT
                i.signal_date,
                i.symbol,
                i.end_date,
                GREATEST(i.f_ann_date, b.f_ann_date, c.f_ann_date) AS publish_date,
                i.net_income,
                i.revenue,
                i.operating_cost,
                b.total_assets,
                b.long_term_debt,
                b.current_assets,
                b.current_liabilities,
                b.total_shares,
                b.book_equity,
                c.operating_cashflow
            FROM income_visible i
            JOIN balance_visible b
              ON i.signal_date = b.signal_date
             AND i.symbol = b.symbol
             AND i.end_date = b.end_date
            JOIN cashflow_visible c
              ON i.signal_date = c.signal_date
             AND i.symbol = c.symbol
             AND i.end_date = c.end_date
            WHERE i.revision_rank = 1
              AND b.revision_rank = 1
              AND c.revision_rank = 1
        ),
        history AS (
            SELECT
                *,
                LAG(net_income, 1) OVER window_spec AS prior_net_income,
                LAG(revenue, 1) OVER window_spec AS prior_revenue,
                LAG(operating_cost, 1) OVER window_spec AS prior_operating_cost,
                LAG(total_assets, 1) OVER window_spec AS prior_total_assets,
                LAG(total_assets, 2) OVER window_spec AS prior2_total_assets,
                LAG(long_term_debt, 1) OVER window_spec AS prior_long_term_debt,
                LAG(current_assets, 1) OVER window_spec AS prior_current_assets,
                LAG(current_liabilities, 1) OVER window_spec
                    AS prior_current_liabilities,
                LAG(total_shares, 1) OVER window_spec AS prior_total_shares,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC
                ) AS latest_rank
            FROM common_reports
            WINDOW window_spec AS (
                PARTITION BY signal_date, symbol ORDER BY end_date
            )
        ),
        ratios AS (
            SELECT
                *,
                net_income / NULLIF(prior_total_assets, 0) AS roa,
                prior_net_income / NULLIF(prior2_total_assets, 0) AS prior_roa,
                operating_cashflow / NULLIF(prior_total_assets, 0) AS cfo_roa,
                long_term_debt / NULLIF(total_assets, 0) AS leverage,
                prior_long_term_debt / NULLIF(prior_total_assets, 0)
                    AS prior_leverage,
                current_assets / NULLIF(current_liabilities, 0)
                    AS current_ratio,
                prior_current_assets / NULLIF(prior_current_liabilities, 0)
                    AS prior_current_ratio,
                (revenue - operating_cost) / NULLIF(revenue, 0)
                    AS gross_margin,
                (prior_revenue - prior_operating_cost) / NULLIF(prior_revenue, 0)
                    AS prior_gross_margin,
                revenue / NULLIF((total_assets + prior_total_assets) / 2.0, 0)
                    AS asset_turnover,
                prior_revenue
                    / NULLIF((prior_total_assets + prior2_total_assets) / 2.0, 0)
                    AS prior_asset_turnover
            FROM history
            WHERE latest_rank = 1
        ),
        components AS (
            SELECT
                *,
                CASE WHEN roa IS NULL THEN NULL
                     WHEN roa > 0 THEN 1 ELSE 0 END AS f_positive_roa,
                CASE WHEN cfo_roa IS NULL THEN NULL
                     WHEN cfo_roa > 0 THEN 1 ELSE 0 END AS f_positive_cfo,
                CASE WHEN roa IS NULL OR prior_roa IS NULL THEN NULL
                     WHEN roa > prior_roa THEN 1 ELSE 0 END AS f_delta_roa,
                CASE WHEN cfo_roa IS NULL OR roa IS NULL THEN NULL
                     WHEN cfo_roa > roa THEN 1 ELSE 0 END AS f_accrual,
                CASE WHEN leverage IS NULL OR prior_leverage IS NULL THEN NULL
                     WHEN leverage < prior_leverage THEN 1 ELSE 0 END
                    AS f_delta_leverage,
                CASE WHEN current_ratio IS NULL OR prior_current_ratio IS NULL
                     THEN NULL
                     WHEN current_ratio > prior_current_ratio THEN 1 ELSE 0 END
                    AS f_delta_liquidity,
                CASE WHEN total_shares IS NULL OR prior_total_shares IS NULL
                     THEN NULL
                     WHEN total_shares <= prior_total_shares THEN 1 ELSE 0 END
                    AS f_no_dilution,
                CASE WHEN gross_margin IS NULL OR prior_gross_margin IS NULL
                     THEN NULL
                     WHEN gross_margin > prior_gross_margin THEN 1 ELSE 0 END
                    AS f_delta_margin,
                CASE WHEN asset_turnover IS NULL
                           OR prior_asset_turnover IS NULL THEN NULL
                     WHEN asset_turnover > prior_asset_turnover THEN 1 ELSE 0 END
                    AS f_delta_turnover
            FROM ratios
        )
        SELECT
            signal_date,
            symbol,
            end_date AS report_period,
            publish_date,
            roa,
            cfo_roa,
            leverage,
            current_ratio,
            gross_margin,
            asset_turnover,
            book_equity,
            total_shares,
            f_positive_roa,
            f_positive_cfo,
            f_delta_roa,
            f_accrual,
            f_delta_leverage,
            f_delta_liquidity,
            f_no_dilution,
            f_delta_margin,
            f_delta_turnover,
            CASE
                WHEN f_positive_roa IS NULL
                  OR f_positive_cfo IS NULL
                  OR f_delta_roa IS NULL
                  OR f_accrual IS NULL
                  OR f_delta_leverage IS NULL
                  OR f_delta_liquidity IS NULL
                  OR f_no_dilution IS NULL
                  OR f_delta_margin IS NULL
                  OR f_delta_turnover IS NULL
                THEN NULL
                ELSE f_positive_roa + f_positive_cfo + f_delta_roa + f_accrual
                   + f_delta_leverage + f_delta_liquidity + f_no_dilution
                   + f_delta_margin + f_delta_turnover
            END AS f_score
        FROM components
        """
    )
    return PIOTROSKI_ASOF_TABLE


def load_piotroski_financial_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取只含公告日可见信息的 F-Score 截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {PIOTROSKI_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """统一交易日格式，避免数据库隐式类型转换。"""
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
