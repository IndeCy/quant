"""CPO 与商业航天起飞前的股票篮子点时证据回放。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "sector_takeoff_case_timeline_audit_v4"
REPORT_PATH = Path("docs/research/sector-takeoff-case-timeline-audit-v4.md")
AS_OF_DATE = "20260728"

CASES = (
    {
        "case_id": "cpo_initial_2023",
        "theme": "CPO/光模块首轮",
        "signal_date": "20230331",
        "board_code": "BK1128.DC",
        "stocks": {
            "300308.SZ": "中际旭创",
            "300502.SZ": "新易盛",
            "300394.SZ": "天孚通信",
            "601138.SH": "工业富联",
            "000063.SZ": "中兴通讯",
        },
    },
    {
        "case_id": "cpo_second_2024",
        "theme": "CPO/光模块第二轮",
        "signal_date": "20240830",
        "board_code": "BK1128.DC",
        "stocks": {
            "300308.SZ": "中际旭创",
            "300502.SZ": "新易盛",
            "300394.SZ": "天孚通信",
            "601138.SH": "工业富联",
            "000063.SZ": "中兴通讯",
        },
    },
    {
        "case_id": "commercial_space_2024",
        "theme": "商业航天",
        "signal_date": "20240830",
        "board_code": "BK0963.DC",
        "stocks": {
            "601698.SH": "中国卫通",
            "600879.SH": "航天电子",
            "300762.SZ": "上海瀚讯",
            "688333.SH": "铂力特",
            "688066.SH": "航天宏图",
        },
    },
)

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="CPO与商业航天起飞前证据时间线 V4",
    category="case_timeline_audit",
    hypothesis=(
        "已知大行情前，政策或需求催化、龙头财务确认、股票价格/成交扩散"
        "是否按可观察顺序出现"
    ),
    definition={
        "cases": [
            {
                "case_id": item["case_id"],
                "theme": item["theme"],
                "signal_date": item["signal_date"],
                "board_code": item["board_code"],
                "stocks": item["stocks"],
            }
            for item in CASES
        ],
        "signal_dates": (
            "统一严格事件研究识别出的月末，不按新闻日手工择时"
        ),
        "market_features": {
            "adjust": "qfq",
            "ret_windows": [20, 60],
            "amount_ratio": "mean20/mean120",
            "visibility": "through signal_date",
        },
        "financial_features": {
            "source": "fina_indicator",
            "latest_row": "ann_date<=signal_date",
            "fields": ["tr_yoy", "netprofit_yoy"],
        },
        "forecast_features": {
            "source": "forecast",
            "window_calendar_days": 180,
            "ann_date_lte_signal_date": True,
        },
        "known_limit": (
            "CPO DC板块指数始于20230210，首轮事件没有120日板块预热历史"
        ),
        "execution": "research_only_no_orders_no_scheduler_no_bark",
        "methodology_version": "v4",
    },
)


def run_audit(
    paths: RuntimePaths,
    source_dataset: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记后逐案例按信号日打开只读快照。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=AS_OF_DATE,
        data_version=(
            f"case_timeline:{source_dataset.stat().st_size}:"
            f"{paths.fina_indicator_path.stat().st_size}:"
            f"{paths.forecast_path.stat().st_size}"
        ),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        board_events = _load_board_events(source_dataset)
        stock_rows: list[pd.DataFrame] = []
        for case in CASES:
            stock_rows.append(_load_case_stocks(paths, case))
        stocks = pd.concat(stock_rows, ignore_index=True)
        summary = summarize_cases(stocks, board_events)
        result = _persist(paths, attempt, summary, stocks)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def summarize_cases(
    stocks: pd.DataFrame,
    board_events: pd.DataFrame,
) -> pd.DataFrame:
    """汇总每个案例在信号日前已知的市场与财务宽度。"""
    board_map = board_events.set_index("case_id").to_dict("index")
    rows: list[dict[str, Any]] = []
    for (case_id, theme, signal_date), group in stocks.groupby(
        ["case_id", "theme", "signal_date"],
        sort=False,
    ):
        market = group[group["market_visible"]]
        finance = group[group["finance_visible"]]
        board = board_map.get(str(case_id), {})
        rows.append(
            {
                "case_id": case_id,
                "theme": theme,
                "signal_date": signal_date,
                "stock_count": int(len(group)),
                "market_coverage": float(group["market_visible"].mean()),
                "price_20_positive_share": (
                    float(market["ret_20"].gt(0).mean()) if len(market) else 0.0
                ),
                "price_60_positive_share": (
                    float(market["ret_60"].gt(0).mean()) if len(market) else 0.0
                ),
                "amount_expansion_share": (
                    float(market["amount_ratio_20_120"].gt(1).mean())
                    if len(market)
                    else 0.0
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
                "positive_forecast_share": float(
                    group["positive_forecast"].mean()
                ),
                "board_evidence_score": board.get("evidence_score"),
                "board_ret_60": board.get("ret_60"),
                "board_amount_ratio": board.get("amount_ratio_20_120"),
                "future_board_return_60": board.get("future_ret_60"),
                "future_board_excess_60": board.get("future_excess_60"),
            }
        )
    return pd.DataFrame(rows)


def _load_board_events(source_dataset: Path) -> pd.DataFrame:
    rows = []
    with duckdb.connect(str(source_dataset), read_only=True) as con:
        for case in CASES:
            row = con.execute(
                """
                SELECT
                    evidence_score, ret_60, amount_ratio_20_120,
                    future_ret_60, future_excess_60
                FROM monthly_sector_samples
                WHERE ts_code=? AND trade_date=?
                """,
                [case["board_code"], case["signal_date"]],
            ).fetchone()
            if row is None:
                raise RuntimeError(f"缺少案例板块样本: {case['case_id']}")
            rows.append(
                {
                    "case_id": case["case_id"],
                    "evidence_score": row[0],
                    "ret_60": row[1],
                    "amount_ratio_20_120": row[2],
                    "future_ret_60": row[3],
                    "future_excess_60": row[4],
                }
            )
    return pd.DataFrame(rows)


def _load_case_stocks(
    paths: RuntimePaths,
    case: dict[str, Any],
) -> pd.DataFrame:
    symbols = pd.DataFrame({"symbol": list(case["stocks"])})
    market = _load_market(paths, symbols, str(case["signal_date"]))
    finance = _load_finance(paths, symbols, str(case["signal_date"]))
    forecasts = _load_forecasts(paths, symbols, str(case["signal_date"]))
    base = symbols.copy()
    base["name"] = base["symbol"].map(case["stocks"])
    result = (
        base.merge(market, on="symbol", how="left")
        .merge(finance, on="symbol", how="left")
        .merge(forecasts, on="symbol", how="left")
    )
    result["case_id"] = case["case_id"]
    result["theme"] = case["theme"]
    result["signal_date"] = case["signal_date"]
    result["market_visible"] = result["close_120"].notna()
    result["finance_visible"] = result["finance_ann_date"].notna()
    result["positive_forecast"] = (
        result["positive_forecast"].fillna(False).astype(bool)
    )
    return result


def _load_market(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
    signal_date: str,
) -> pd.DataFrame:
    con = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start="20210101",
        as_of_date=signal_date,
    )
    try:
        con.register("case_symbols", symbols)
        frame = con.execute(
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
                JOIN case_symbols s ON s.symbol=d.ts_code
            )
            SELECT
                symbol,
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
    frame["ret_20"] = frame["close_latest"] / frame["close_20"] - 1.0
    frame["ret_60"] = frame["close_latest"] / frame["close_60"] - 1.0
    return frame


def _load_finance(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
    signal_date: str,
) -> pd.DataFrame:
    with duckdb.connect(str(paths.fina_indicator_path), read_only=True) as con:
        con.register("case_symbols", symbols)
        return con.execute(
            """
            WITH ranked AS (
                SELECT
                    f.ts_code AS symbol,
                    f.ann_date,
                    f.end_date,
                    f.tr_yoy,
                    f.netprofit_yoy,
                    ROW_NUMBER() OVER(
                        PARTITION BY f.ts_code
                        ORDER BY f.ann_date DESC, f.end_date DESC
                    ) AS rn
                FROM default_table f
                JOIN case_symbols s ON s.symbol=f.ts_code
                WHERE f.ann_date<=?
            )
            SELECT
                symbol,
                ann_date AS finance_ann_date,
                end_date AS finance_end_date,
                tr_yoy,
                netprofit_yoy
            FROM ranked
            WHERE rn=1
            """,
            [signal_date],
        ).fetchdf()


def _load_forecasts(
    paths: RuntimePaths,
    symbols: pd.DataFrame,
    signal_date: str,
) -> pd.DataFrame:
    start = (
        datetime.strptime(signal_date, "%Y%m%d") - timedelta(days=180)
    ).strftime("%Y%m%d")
    with duckdb.connect(str(paths.forecast_path), read_only=True) as con:
        con.register("case_symbols", symbols)
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
            JOIN case_symbols s ON s.symbol=f.ts_code
            WHERE f.ann_date BETWEEN ? AND ?
            GROUP BY f.ts_code
            """,
            [start, signal_date],
        ).fetchdf()
    frame["positive_forecast"] = frame["positive_forecast_count"].gt(0)
    return frame


def _persist(
    paths: RuntimePaths,
    attempt: ResearchAttempt,
    summary: pd.DataFrame,
    stocks: pd.DataFrame,
) -> dict[str, Any]:
    summary_path = attempt.output_dir / "case_summary.csv"
    stocks_path = attempt.output_dir / "case_stock_evidence.csv"
    summary.to_csv(summary_path, index=False)
    stocks.to_csv(stocks_path, index=False)
    metrics = {
        "case_count": int(len(summary)),
        "case_summary": _records(summary),
        "stock_evidence": _records(stocks),
        "decision": "CASE_PATH_EVIDENCE_ONLY",
        "strategy_promoted": False,
    }
    report = render_report(metrics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    report_copy = attempt.output_dir / "summary.md"
    report_copy.write_text(report, encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=metrics,
        outcome="CASE_PATH_EVIDENCE_ONLY",
        decision_reason=(
            "案例显示催化、财务与市场确认顺序并不固定；保留为雷达流程证据，不升级策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", report_copy, "案例时间线摘要"),
            ExperimentArtifact("report", report_path, "案例时间线报告"),
            ExperimentArtifact("case_summary", summary_path, "案例宽度摘要"),
            ExperimentArtifact("stock_evidence", stocks_path, "案例股票点时证据"),
        ],
    )
    return {**metrics, "reused": False}


def render_report(metrics: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {row['theme']} | {row['signal_date']} | "
        f"{_pct(row['price_20_positive_share'])} | "
        f"{_pct(row['amount_expansion_share'])} | "
        f"{_pct(row['revenue_growth_positive_share'])} | "
        f"{_pct(row['profit_growth_positive_share'])} | "
        f"{_pct(row['positive_forecast_share'])} | "
        f"{_num(row.get('board_evidence_score'))} | "
        f"{_pct(row.get('future_board_return_60'))} |"
        for row in metrics["case_summary"]
    )
    return f"""# CPO 与商业航天起飞前证据时间线 V4

信号日来自统一严格事件定义，不按新闻日期手工选择。

| 案例 | 信号日 | 20日上涨宽度 | 放量宽度 | 营收增长宽度 | 利润增长宽度 | 正向预告宽度 | 板块证据分 | 后续60日收益 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{rows}

## 如何解释

- CPO 首轮板块指数在 2023-02-10 才建立，2023-02/03 的严格事件没有
  120 日板块历史，任何完整“提前高分”都是不可证明的。
- 股票篮子财务只使用信号日前已公告数据；后续财报不能倒灌。
- 同一主题不同轮次可能是“需求催化先、财务后确认”，也可能是
  “财务已确认、价格回撤后第二轮”，不能压成单一静态分数。
- 商业航天政策与发射事件属于外部催化，需要与本表的市场/财务宽度按日期拼接。
"""


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
            "case_summary": result.get("case_summary"),
            "reused": result.get("reused"),
        }
    )


if __name__ == "__main__":
    main()
