"""未来产业候选的当前成员、财务、预告、两融与行情确认审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from runtime.config import get_config_value
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "sector_candidate_confirmation_audit_v3"
REPORT_PATH = Path("docs/research/sector-candidate-confirmation-audit-v3.md")
AS_OF_DATE = "20260728"
FORECAST_START = "20260101"

THEMES = (
    ("innovative_drug", "创新药", "BK1106.DC"),
    ("commercial_space", "商业航天", "BK0963.DC"),
    ("humanoid_robotics", "人形机器人", "BK1184.DC"),
    ("advanced_packaging", "先进封装", "BK1101.DC"),
    ("synthetic_biology", "合成生物", "BK1174.DC"),
    ("brain_computer_proxy", "人脑工程（脑机接口代理）", "BK0706.DC"),
    ("six_g", "6G", "BK0964.DC"),
    ("quantum_technology", "量子科技", "BK0710.DC"),
)

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="未来产业候选多源确认审计 V3",
    category="current_candidate_audit",
    hypothesis=(
        "政策或产业催化只有与当前成员的行情扩散、财务增长、业绩预告和融资行为"
        "形成多源确认，才值得从主题清单升级为重点研究方向"
    ),
    definition={
        "themes": [
            {"theme_id": theme_id, "name": name, "board_code": board_code}
            for theme_id, name, board_code in THEMES
        ],
        "membership": {
            "provider": "tushare.dc_member",
            "as_of": AS_OF_DATE,
            "historical_use_forbidden": True,
        },
        "market": {
            "adjust": "qfq",
            "as_of": AS_OF_DATE,
            "lookbacks": [20, 60, 120],
            "amount_expansion": "mean_amount_20/mean_amount_120",
        },
        "financial": {
            "provider": "local fina_indicator",
            "visibility": "ann_date<=as_of",
            "fields": ["tr_yoy", "netprofit_yoy", "q_gr_yoy", "q_netprofit_yoy"],
            "latest_visible_row_only": True,
        },
        "forecast": {
            "provider": "local forecast",
            "visibility": "ann_date<=as_of",
            "window_start": FORECAST_START,
            "positive": "mean(p_change_min,p_change_max)>0",
        },
        "margin": {
            "provider": "local margin_detail",
            "latest_available_20_trading_days": True,
            "interpretation": "auxiliary_due_source_lag",
        },
        "stock_evidence_count": {
            "components": [
                "ret_20>0",
                "amount_ratio_20_120>1",
                "tr_yoy>0",
                "netprofit_yoy>0",
                "positive_forecast",
                "margin_net_buy_20d>0",
            ],
            "ranking_is_research_priority_not_trade_score": True,
        },
        "execution": "research_only_no_orders_no_scheduler_no_bark",
        "methodology_version": "v3",
    },
)


def run_audit(
    paths: RuntimePaths,
    source_dataset: Path,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """登记研究后，抓取当前成员并读取本地只读状态库。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=AS_OF_DATE,
        data_version=(
            f"local_multisource_20260728:"
            f"{source_dataset.stat().st_size}:"
            f"{paths.fina_indicator_path.stat().st_size}:"
            f"{paths.forecast_path.stat().st_size}:"
            f"{paths.margin_trade_path.stat().st_size}"
        ),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        pro = client or _build_client()
        members = _load_current_members(pro)
        board_states = _load_board_states(source_dataset)
        stock_evidence, source_dates = _load_stock_evidence(paths, members)
        theme_summary = summarize_themes(
            stock_evidence,
            board_states,
        )
        priorities = rank_research_stocks(stock_evidence)
        result = _persist(
            paths,
            attempt,
            members,
            stock_evidence,
            theme_summary,
            priorities,
            source_dates,
        )
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def summarize_themes(
    stocks: pd.DataFrame,
    board_states: pd.DataFrame,
) -> pd.DataFrame:
    """聚合各方向的多源确认宽度。"""
    rows: list[dict[str, Any]] = []
    state_map = board_states.set_index("board_code").to_dict("index")
    for (theme_id, theme_name, board_code), group in stocks.groupby(
        ["theme_id", "theme_name", "board_code"],
        sort=False,
    ):
        finance = group[group["finance_visible"]]
        margin = group[group["margin_visible"]]
        state = state_map.get(str(board_code), {})
        rows.append(
            {
                "theme_id": theme_id,
                "theme_name": theme_name,
                "board_code": board_code,
                "board_state": state.get("state", "missing"),
                "board_ret_20": state.get("ret_20"),
                "board_ret_60": state.get("ret_60"),
                "board_amount_ratio": state.get("amount_ratio_20_120"),
                "board_breadth_20": state.get("breadth_20"),
                "board_breadth_acceleration": state.get(
                    "breadth_acceleration"
                ),
                "member_count": int(len(group)),
                "market_coverage": float(group["market_visible"].mean()),
                "price_20_positive_share": float(
                    group["ret_20"].gt(0).mean()
                ),
                "amount_expansion_share": float(
                    group["amount_ratio_20_120"].gt(1).mean()
                ),
                "finance_coverage": float(group["finance_visible"].mean()),
                "revenue_growth_positive_share": (
                    float(finance["tr_yoy"].gt(0).mean())
                    if len(finance)
                    else 0.0
                ),
                "profit_growth_positive_share": (
                    float(finance["netprofit_yoy"].gt(0).mean())
                    if len(finance)
                    else 0.0
                ),
                "positive_forecast_member_share": float(
                    group["positive_forecast"].mean()
                ),
                "margin_coverage": float(group["margin_visible"].mean()),
                "margin_positive_share": (
                    float(margin["margin_net_buy_20d"].gt(0).mean())
                    if len(margin)
                    else 0.0
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["confirmation_count"] = (
        result["price_20_positive_share"].ge(0.50).astype(int)
        + result["amount_expansion_share"].ge(0.50).astype(int)
        + result["revenue_growth_positive_share"].ge(0.50).astype(int)
        + result["profit_growth_positive_share"].ge(0.50).astype(int)
        + result["positive_forecast_member_share"].ge(0.10).astype(int)
        + result["margin_positive_share"].ge(0.50).astype(int)
    )
    return result.sort_values(
        ["confirmation_count", "price_20_positive_share"],
        ascending=False,
    ).reset_index(drop=True)


def rank_research_stocks(stocks: pd.DataFrame) -> pd.DataFrame:
    """按独立证据条数排序，仅用于后续公告核验优先级。"""
    result = stocks.copy()
    result["evidence_count"] = (
        result["ret_20"].gt(0).astype(int)
        + result["amount_ratio_20_120"].gt(1).astype(int)
        + result["tr_yoy"].gt(0).astype(int)
        + result["netprofit_yoy"].gt(0).astype(int)
        + result["positive_forecast"].astype(int)
        + result["margin_net_buy_20d"].gt(0).astype(int)
    )
    return (
        result.sort_values(
            [
                "theme_id",
                "evidence_count",
                "ret_20",
                "amount_ratio_20_120",
            ],
            ascending=[True, False, False, False],
        )
        .groupby("theme_id", sort=False)
        .head(10)
        .reset_index(drop=True)
    )


def _load_current_members(pro: Any) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for theme_id, theme_name, board_code in THEMES:
        frame = pro.dc_member(ts_code=board_code)
        if frame.empty:
            raise RuntimeError(f"{theme_name}({board_code}) 当前成分为空")
        if "trade_date" in frame.columns:
            frame = frame[frame["trade_date"].astype(str).eq(AS_OF_DATE)].copy()
        if frame.empty:
            raise RuntimeError(
                f"{theme_name}({board_code}) 缺少 {AS_OF_DATE} 成分快照"
            )
        code_column = "con_code" if "con_code" in frame else "ts_code"
        name_column = "name" if "name" in frame else "con_name"
        current = pd.DataFrame(
            {
                "theme_id": theme_id,
                "theme_name": theme_name,
                "board_code": board_code,
                "symbol": frame[code_column].astype(str),
                "name": frame[name_column].astype(str),
            }
        )
        frames.append(current)
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(["theme_id", "symbol"], keep="last")
        .reset_index(drop=True)
    )


def _load_board_states(source_dataset: Path) -> pd.DataFrame:
    codes = [board_code for _, _, board_code in THEMES]
    placeholders = ",".join("?" for _ in codes)
    with duckdb.connect(str(source_dataset), read_only=True) as con:
        frame = con.execute(
            f"""
            SELECT *
            FROM monthly_sector_samples
            WHERE trade_date = ? AND ts_code IN ({placeholders})
            """,
            [AS_OF_DATE, *codes],
        ).fetchdf()
    frame = _classify_board_state(frame)
    return frame.rename(columns={"ts_code": "board_code"})


def _classify_board_state(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["state"] = "no_signal"
    quiet = (
        result["ret_60"].between(-0.15, 0.15)
        & result["ret_20"].gt(0)
        & result["amount_ratio_20_120"].between(1.05, 2.50)
        & result["turnover_ratio_20_120"].between(1.00, 2.50)
        & result["distance_to_high_120"].ge(-0.25)
    )
    confirming = (
        result["ret_60"].between(0.05, 0.35)
        & result["ret_20"].gt(0)
        & result["amount_ratio_20_120"].between(1.10, 2.50)
        & result["turnover_ratio_20_120"].between(1.00, 2.50)
        & result["distance_to_high_120"].ge(-0.10)
    )
    overheated = result["ret_60"].gt(0.50) | result["ret_120"].gt(1.0)
    result.loc[quiet, "state"] = "quiet_accumulation"
    result.loc[confirming, "state"] = "confirming"
    result.loc[overheated, "state"] = "overheated"
    return result


def _load_stock_evidence(
    paths: RuntimePaths,
    members: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    symbols = members[["symbol"]].drop_duplicates().reset_index(drop=True)
    con = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start="20250101",
        as_of_date=AS_OF_DATE,
    )
    try:
        con.register("member_symbols", symbols)
        market = con.execute(
            """
            WITH ranked AS (
                SELECT
                    d.ts_code AS symbol,
                    d.trade_date,
                    a.close_qfq AS close,
                    d.amount,
                    ROW_NUMBER() OVER(
                        PARTITION BY d.ts_code ORDER BY d.trade_date DESC
                    ) AS rn
                FROM daily d
                JOIN daily_adj_cache a
                  ON a.ts_code=d.ts_code AND a.trade_date=d.trade_date
                JOIN member_symbols m ON m.symbol=d.ts_code
            )
            SELECT
                symbol,
                MAX(trade_date) AS market_latest_date,
                MAX(close) FILTER(WHERE rn=1) AS close_latest,
                MAX(close) FILTER(WHERE rn=21) AS close_20,
                MAX(close) FILTER(WHERE rn=61) AS close_60,
                MAX(close) FILTER(WHERE rn=121) AS close_120,
                AVG(amount) FILTER(WHERE rn BETWEEN 1 AND 20)
                    / NULLIF(AVG(amount) FILTER(WHERE rn BETWEEN 1 AND 120),0)
                    AS amount_ratio_20_120
            FROM ranked
            GROUP BY symbol
            """
        ).fetchdf()
    finally:
        con.close()
    market["ret_20"] = market["close_latest"] / market["close_20"] - 1.0
    market["ret_60"] = market["close_latest"] / market["close_60"] - 1.0
    market["ret_120"] = market["close_latest"] / market["close_120"] - 1.0
    market["market_visible"] = market["close_120"].notna()

    financial = _load_financial(paths, symbols)
    forecasts, forecast_latest = _load_forecasts(paths, symbols)
    margin, margin_start, margin_end = _load_margin(paths, symbols)
    result = (
        members.merge(market, on="symbol", how="left")
        .merge(financial, on="symbol", how="left")
        .merge(forecasts, on="symbol", how="left")
        .merge(margin, on="symbol", how="left")
    )
    result["market_visible"] = result["market_visible"].fillna(False)
    result["finance_visible"] = result["finance_ann_date"].notna()
    result["positive_forecast"] = (
        result["positive_forecast"].fillna(False).astype(bool)
    )
    result["margin_visible"] = result["margin_observations"].fillna(0).gt(0)
    return result, {
        "market_latest_date": str(market["market_latest_date"].max()),
        "financial_latest_announcement": str(
            financial["finance_ann_date"].max()
        ),
        "forecast_latest_announcement": forecast_latest,
        "margin_window_start": margin_start,
        "margin_window_end": margin_end,
    }


def _load_financial(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
) -> pd.DataFrame:
    with duckdb.connect(str(paths.fina_indicator_path), read_only=True) as con:
        con.register("member_symbols", symbols)
        return con.execute(
            """
            WITH ranked AS (
                SELECT
                    f.ts_code AS symbol,
                    f.ann_date,
                    f.end_date,
                    f.tr_yoy,
                    f.netprofit_yoy,
                    f.q_gr_yoy,
                    f.q_netprofit_yoy,
                    ROW_NUMBER() OVER(
                        PARTITION BY f.ts_code
                        ORDER BY f.ann_date DESC, f.end_date DESC
                    ) AS rn
                FROM default_table f
                JOIN member_symbols m ON m.symbol=f.ts_code
                WHERE f.ann_date <= ?
            )
            SELECT
                symbol,
                ann_date AS finance_ann_date,
                end_date AS finance_end_date,
                tr_yoy,
                netprofit_yoy,
                q_gr_yoy,
                q_netprofit_yoy
            FROM ranked
            WHERE rn=1
            """,
            [AS_OF_DATE],
        ).fetchdf()


def _load_forecasts(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    with duckdb.connect(str(paths.forecast_path), read_only=True) as con:
        con.register("member_symbols", symbols)
        latest = con.execute(
            "SELECT COALESCE(MAX(ann_date),'') FROM default_table WHERE ann_date<=?",
            [AS_OF_DATE],
        ).fetchone()[0]
        frame = con.execute(
            """
            SELECT
                f.ts_code AS symbol,
                COUNT(*) AS forecast_count,
                COUNT(*) FILTER(
                    WHERE (COALESCE(f.p_change_min,f.p_change_max)
                         + COALESCE(f.p_change_max,f.p_change_min))/2 > 0
                ) AS positive_forecast_count
            FROM default_table f
            JOIN member_symbols m ON m.symbol=f.ts_code
            WHERE f.ann_date BETWEEN ? AND ?
            GROUP BY f.ts_code
            """,
            [FORECAST_START, AS_OF_DATE],
        ).fetchdf()
    frame["positive_forecast"] = frame["positive_forecast_count"].gt(0)
    return frame, str(latest or "")


def _load_margin(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
) -> tuple[pd.DataFrame, str, str]:
    with duckdb.connect(str(paths.margin_trade_path), read_only=True) as con:
        con.register("member_symbols", symbols)
        dates = [
            str(row[0])
            for row in con.execute(
                """
                SELECT DISTINCT trade_date
                FROM margin_detail
                WHERE trade_date<=?
                ORDER BY trade_date DESC
                LIMIT 20
                """,
                [AS_OF_DATE],
            ).fetchall()
        ]
        if not dates:
            return pd.DataFrame(columns=["symbol"]), "", ""
        frame = con.execute(
            """
            SELECT
                d.ts_code AS symbol,
                COUNT(*) AS margin_observations,
                SUM(COALESCE(d.rzmre,0)-COALESCE(d.rzche,0))
                    AS margin_net_buy_20d
            FROM margin_detail d
            JOIN member_symbols m ON m.symbol=d.ts_code
            WHERE d.trade_date BETWEEN ? AND ?
            GROUP BY d.ts_code
            """,
            [min(dates), max(dates)],
        ).fetchdf()
    return frame, min(dates), max(dates)


def _persist(
    paths: RuntimePaths,
    attempt: ResearchAttempt,
    members: pd.DataFrame,
    stocks: pd.DataFrame,
    themes: pd.DataFrame,
    priorities: pd.DataFrame,
    source_dates: dict[str, str],
) -> dict[str, Any]:
    member_path = attempt.output_dir / "current_members.csv"
    stock_path = attempt.output_dir / "stock_evidence.csv"
    theme_path = attempt.output_dir / "theme_confirmation.csv"
    priority_path = attempt.output_dir / "stock_research_priorities.csv"
    members.to_csv(member_path, index=False)
    stocks.to_csv(stock_path, index=False)
    themes.to_csv(theme_path, index=False)
    priorities.to_csv(priority_path, index=False)
    metrics = {
        "source_dates": source_dates,
        "theme_count": int(len(themes)),
        "unique_member_count": int(members["symbol"].nunique()),
        "membership_rows": int(len(members)),
        "theme_confirmation": _records(themes),
        "stock_research_priorities": _records(priorities),
        "decision": "CURRENT_RESEARCH_QUEUE_ONLY",
        "strategy_promoted": False,
    }
    report = render_report(metrics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report, encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=metrics,
        outcome="CURRENT_RESEARCH_QUEUE_ONLY",
        decision_reason=(
            "多源确认仅形成研究队列；没有方向达到可自动升级为交易策略的证据标准"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "候选确认摘要"),
            ExperimentArtifact("report", report_path, "候选确认报告"),
            ExperimentArtifact("members", member_path, "当前板块成员"),
            ExperimentArtifact("stock_evidence", stock_path, "个股多源证据"),
            ExperimentArtifact("theme_confirmation", theme_path, "方向确认宽度"),
            ExperimentArtifact(
                "stock_priorities",
                priority_path,
                "股票后续公告核验优先级",
            ),
        ],
    )
    return {**metrics, "reused": False}


def render_report(metrics: dict[str, Any]) -> str:
    theme_rows = "\n".join(
        f"| {row['theme_name']} | {row['board_state']} | {row['member_count']} | "
        f"{_pct(row['price_20_positive_share'])} | "
        f"{_pct(row['amount_expansion_share'])} | "
        f"{_pct(row['revenue_growth_positive_share'])} | "
        f"{_pct(row['profit_growth_positive_share'])} | "
        f"{_pct(row['positive_forecast_member_share'])} | "
        f"{_pct(row['margin_positive_share'])} | "
        f"{row['confirmation_count']} |"
        for row in metrics["theme_confirmation"]
    )
    stock_rows = "\n".join(
        f"| {row['theme_name']} | {row['name']} | {row['symbol']} | "
        f"{row['evidence_count']} | {_pct(row.get('ret_20'))} | "
        f"{_num(row.get('tr_yoy'))} | {_num(row.get('netprofit_yoy'))} | "
        f"{'是' if row.get('positive_forecast') else '否'} |"
        for row in metrics["stock_research_priorities"][:40]
    )
    dates = metrics["source_dates"]
    return f"""# 未来产业候选多源确认审计 V3

本审计使用 2026-07-28 的当前板块成分，只服务当前研究映射，禁止反向用于历史回测。

## 数据时点

- 行情：`{dates['market_latest_date']}`，前复权。
- 财务公告最新可见：`{dates['financial_latest_announcement']}`。
- 业绩预告库最新公告：`{dates['forecast_latest_announcement']}`。
- 两融辅助窗口：`{dates['margin_window_start']}` 至 `{dates['margin_window_end']}`。

## 方向确认宽度

| 方向 | 板块状态 | 成员 | 20日上涨宽度 | 放量宽度 | 营收增长宽度 | 利润增长宽度 | 正向预告宽度 | 融资净买宽度 | 确认项 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{theme_rows}

“确认项”仅统计六类独立证据是否超过预设宽度，不代表收益预测。

## 个股公告核验优先级

| 方向 | 股票 | 代码 | 证据条数 | 20日收益 | 营收同比% | 利润同比% | 正向预告 |
|---|---|---|---:|---:|---:|---:|---|
{stock_rows}

## 结论边界

- 当前成员存在幸存者偏差，只能用于“现在研究谁”，不能证明历史上提前可知。
- 财务指标严格使用 `ann_date<=20260728` 的最新可见记录。
- 两融与业绩预告源早于行情截止日，报告已显式列出滞后日期。
- 个股证据条数只是公告核验顺序，不是交易评分，不接入策略或调度。
"""


def _build_client() -> Any:
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN")
    return ts.pro_api(token)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1%}"


def _num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_audit(
        get_runtime_paths(),
        args.source_dataset,
        force=args.force,
    )
    print(
        {
            "decision": result.get("decision"),
            "theme_confirmation": result.get("theme_confirmation"),
            "top_stocks": result.get("stock_research_priorities", [])[:20],
            "reused": result.get("reused"),
        }
    )


if __name__ == "__main__":
    main()
