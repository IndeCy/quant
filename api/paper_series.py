"""策略 Paper 曲线和风险执行归因合并工具。"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

from backtest.paper_execution import BrokerConfig
from runtime.risk_policy import RiskPolicyRepository


def attach_paper_nav(
    frame: pd.DataFrame,
    paper_path: Path,
    strategy_id: str,
    system_state_path: Path | None = None,
) -> pd.DataFrame:
    """拼接 Paper 事实，并把策略与 Paper 收益差拆成风险、执行和成本。"""
    if frame.empty or not paper_path.exists():
        return frame
    paper = _load_paper_nav(paper_path, strategy_id)
    if paper.empty:
        return frame
    result = frame.copy()
    result["trade_date"] = result["trade_date"].astype(str)
    result = result.merge(paper, on="trade_date", how="left")
    caps = _risk_caps(result, strategy_id, system_state_path)
    result["risk_cap"] = result["trade_date"].map(caps).fillna(1.0)
    alpha_exposure = pd.to_numeric(result["exposure"], errors="coerce").fillna(0.0).clip(lower=0.0)
    result["effective_exposure"] = pd.concat([alpha_exposure, result["risk_cap"]], axis=1).min(axis=1)
    scale = pd.Series(1.0, index=result.index)
    positive = alpha_exposure > 0
    scale.loc[positive] = result.loc[positive, "effective_exposure"] / alpha_exposure.loc[positive]
    alpha_return = pd.to_numeric(result["daily_return"], errors="coerce").fillna(0.0)
    result["risk_adjusted_daily_return"] = alpha_return * scale
    result["risk_adjusted_nav"] = _rebuild_nav(result["nav"], result["risk_adjusted_daily_return"])
    result["risk_overlay_contribution"] = result["risk_adjusted_daily_return"] - alpha_return
    result["trading_cost_contribution"] = -pd.to_numeric(
        result["estimated_trading_cost_return"], errors="coerce"
    ).fillna(0.0)
    result["execution_tracking_contribution"] = (
        pd.to_numeric(result["paper_daily_return"], errors="coerce")
        - result["risk_adjusted_daily_return"]
        - result["trading_cost_contribution"]
    )
    result["risk_attribution_type"] = result["risk_overlay_contribution"].map(_risk_attribution_type)
    return result


def _load_paper_nav(paper_path: Path, strategy_id: str) -> pd.DataFrame:
    """读取指定策略最新 Paper 账户，并生成净值、仓位和估算成本。"""
    try:
        with sqlite3.connect(paper_path) as con:
            frame = pd.read_sql_query(
                """
                SELECT s.trade_date, s.total_value, s.position_value,
                       a.initial_cash, a.id AS account_id
                FROM paper_daily_snapshot s
                JOIN paper_account a ON a.id = s.account_id
                WHERE a.strategy_code = ?
                  AND a.id = (SELECT MAX(id) FROM paper_account WHERE strategy_code = ?)
                ORDER BY s.trade_date
                """,
                con,
                params=[strategy_id, strategy_id],
            )
            costs = _load_estimated_costs(con, int(frame.iloc[0]["account_id"])) if not frame.empty else {}
    except sqlite3.Error:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False)
    frame["total_value"] = pd.to_numeric(frame["total_value"], errors="coerce")
    frame = frame.dropna(subset=["total_value"])
    frame = frame[frame["total_value"] > 0]
    if frame.empty:
        return frame
    base_value = float(frame.iloc[0]["total_value"])
    if base_value <= 0:
        return pd.DataFrame()
    frame["paper_nav"] = frame["total_value"] / base_value
    frame["paper_daily_return"] = frame["total_value"].pct_change(fill_method=None).fillna(0.0)
    frame["paper_exposure"] = frame["position_value"] / frame["total_value"]
    previous_value = frame["total_value"].shift(1).fillna(frame["initial_cash"])
    frame["estimated_trading_cost_return"] = frame["trade_date"].map(costs).fillna(0.0) / previous_value
    return frame[
        [
            "trade_date",
            "paper_nav",
            "paper_daily_return",
            "paper_exposure",
            "estimated_trading_cost_return",
        ]
    ]


def _load_estimated_costs(con: sqlite3.Connection, account_id: int) -> dict[str, float]:
    """按模拟券商固定滑点反推成交冲击；佣金当前配置为零。"""
    try:
        rows = con.execute(
            """
            SELECT fill_date, side, fill_price, filled_quantity
            FROM paper_order
            WHERE account_id = ? AND status IN ('FILLED', 'PARTIAL_FILLED')
              AND fill_date <> '' AND fill_price > 0 AND filled_quantity > 0
            """,
            [account_id],
        ).fetchall()
    except sqlite3.Error:
        # 老快照库尚未增加部分成交列时，成本归因留空但净值仍可展示。
        return {}
    bps = BrokerConfig().slippage_bps / 10_000
    costs: dict[str, float] = {}
    for fill_date, side, fill_price, quantity in rows:
        direction = 1 if str(side) == "BUY" else -1
        open_price = float(fill_price) / (1 + direction * bps)
        impact = abs(float(fill_price) - open_price) * int(quantity)
        compact = str(fill_date).replace("-", "")[:8]
        costs[compact] = costs.get(compact, 0.0) + impact
    return costs


def _risk_caps(
    frame: pd.DataFrame,
    strategy_id: str,
    system_state_path: Path | None,
) -> dict[str, float]:
    """从不可变风险事件读取每日 as-of 上限；无状态库时保持满额。"""
    dates = frame["trade_date"].astype(str).tolist()
    if system_state_path is None:
        return {date: 1.0 for date in dates}
    return RiskPolicyRepository(system_state_path).exposure_caps(strategy_id, dates)


def _rebuild_nav(raw_nav: pd.Series, daily_return: pd.Series) -> pd.Series:
    """以原曲线首日净值为锚，累乘风险调整后日收益。"""
    numeric_nav = pd.to_numeric(raw_nav, errors="coerce")
    if numeric_nav.empty:
        return numeric_nav
    base = float(numeric_nav.iloc[0]) if pd.notna(numeric_nav.iloc[0]) else 1.0
    growth = (1.0 + daily_return.fillna(0.0)).cumprod()
    return base * growth / float(growth.iloc[0] or 1.0)


def _risk_attribution_type(value: float) -> str:
    """风险贡献正负分别表示避免损失和反弹机会成本。"""
    if value > 1e-12:
        return "RISK_AVOIDED_LOSS"
    if value < -1e-12:
        return "RISK_REENTRY_DRAG"
    return "NEUTRAL"
