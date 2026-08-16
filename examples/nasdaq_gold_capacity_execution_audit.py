"""纳指黄金60/40的资金容量、整手取整与最新成交额审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_sp500_hurdle_study as base
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "nasdaq_gold_60_40_capacity_execution_audit_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-capacity-execution-audit-v1.md"
)
SYMBOLS = [base.NASDAQ, base.GOLD]
WEIGHTS = dict(base.CANDIDATE_WEIGHTS)
CAPITAL_LEVELS = (100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0)
LOAD_START = "20190101"
AMOUNT_MULTIPLIER = 1_000.0
LOT_SIZE = 100
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金60/40资金容量与整手审计 V1",
    category="execution_audit",
    hypothesis=(
        "通过研究门槛的固定60/40组合，在10万至500万元资金下是否具备"
        "足够成交容量，且100股整手取整不会造成不可接受的组合偏离"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "weights": WEIGHTS,
        "capital_levels": list(CAPITAL_LEVELS),
        "capacity": {
            "amount_unit_in_source": "thousand_cny",
            "amount_multiplier": AMOUNT_MULTIPLIER,
            "participation_formula": "capital*weight/(daily_amount*1000)",
            "full_target_order_is_conservative_vs_monthly_rebalance_delta": True,
        },
        "lot_rounding": {
            "price": "latest_raw_close",
            "lot_size": LOT_SIZE,
            "method": "floor_to_whole_lot_leave_residual_cash",
        },
        "frozen_gate": {
            "staleness_days_max": 5,
            "valid_days_each_min": 1800,
            "one_million_p90_participation_max": 0.01,
            "one_million_latest_participation_max": 0.01,
            "five_million_median_participation_max": 0.01,
            "five_million_p90_participation_max": 0.02,
            "one_hundred_thousand_tracking_total_variation_max": 0.005,
            "all_capital_cases_hold_both_assets": True,
        },
        "does_not_override_source_gate": True,
        "promotion_scope": "execution_capacity_audit_only",
        "methodology_version": "raw_amount_whole_lot_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized = min(str(as_of_date).replace("-", ""), base.RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_source_passed(paths)
        result, capacity, lots = calculate(paths, normalized)
        complete_attempt(attempt, result, capacity, lots)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    raw = load_raw_bars(paths, as_of_date)
    latest_common_date = min(
        str(raw.loc[raw["symbol"].eq(symbol), "trade_date"].max())
        for symbol in SYMBOLS
    )
    raw = raw[raw["trade_date"].le(latest_common_date)].copy()
    capacity = build_capacity_statistics(raw)
    latest = (
        raw[raw["trade_date"].eq(latest_common_date)]
        .set_index("symbol")
        .loc[SYMBOLS]
    )
    lots = build_lot_cases(latest)
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(latest_common_date)
    ).days
    checks = evaluate_checks(capacity, lots, staleness)
    passed = all(checks.values())
    result = {
        "as_of_date": as_of_date,
        "latest_common_date": latest_common_date,
        "staleness_days": int(staleness),
        "capacity": capacity.to_dict("records"),
        "lot_cases": lots.to_dict("records"),
        "gate": {"checks": checks, "passed": passed},
        "decision": (
            "PASSED_EXECUTION_AUDIT" if passed else "CAPACITY_RISK_FLAGGED"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, capacity, lots


def load_raw_bars(paths: RuntimePaths, as_of_date: str) -> pd.DataFrame:
    """只读拼接历史与增量库，同日以增量原始量价覆盖历史。"""
    frames: list[pd.DataFrame] = []
    placeholders = ",".join("?" for _ in SYMBOLS)
    if Path(paths.fund_daily_history_path).exists():
        with duckdb.connect(
            str(paths.fund_daily_history_path), read_only=True
        ) as connection:
            frames.append(
                connection.execute(
                    f"""
                    SELECT trade_date, ts_code AS symbol, close, amount,
                           0 AS source_priority
                    FROM etf_lof_reits_daily_adj
                    WHERE ts_code IN ({placeholders})
                      AND trade_date BETWEEN ? AND ?
                    """,
                    [*SYMBOLS, LOAD_START, as_of_date],
                ).fetchdf()
            )
    if Path(paths.benchmark_increment_path).exists():
        with duckdb.connect(
            str(paths.benchmark_increment_path), read_only=True
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            if "fund_daily" in tables:
                frames.append(
                    connection.execute(
                        f"""
                        SELECT trade_date, ts_code AS symbol, close, amount,
                               1 AS source_priority
                        FROM fund_daily
                        WHERE ts_code IN ({placeholders})
                          AND trade_date BETWEEN ? AND ?
                        """,
                        [*SYMBOLS, LOAD_START, as_of_date],
                    ).fetchdf()
                )
    if not frames:
        raise ValueError("历史库和增量库均无目标基金行情")
    frame = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["symbol", "trade_date", "source_priority"])
        .drop_duplicates(["symbol", "trade_date"], keep="last")
    )
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame = frame[
        frame["symbol"].isin(SYMBOLS)
        & frame["close"].gt(0)
        & frame["amount"].gt(0)
    ].copy()
    missing = sorted(set(SYMBOLS) - set(frame["symbol"]))
    if missing:
        raise ValueError(f"容量审计缺少行情: {missing}")
    return frame


def build_capacity_statistics(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        values = raw[raw["symbol"].eq(symbol)].sort_values("trade_date")
        amount_cny = values["amount"] * AMOUNT_MULTIPLIER
        row: dict[str, Any] = {
            "symbol": symbol,
            "weight": WEIGHTS[symbol],
            "valid_days": int(len(values)),
            "latest_date": str(values["trade_date"].iloc[-1]),
            "latest_raw_close": float(values["close"].iloc[-1]),
            "latest_daily_amount": float(amount_cny.iloc[-1]),
            "median_daily_amount": float(amount_cny.median()),
            "p10_daily_amount": float(amount_cny.quantile(0.10)),
        }
        for capital in CAPITAL_LEVELS:
            label = f"capital_{int(capital)}"
            participation = capital * WEIGHTS[symbol] / amount_cny
            row[f"{label}_median_participation"] = float(
                participation.median()
            )
            row[f"{label}_p90_participation"] = float(
                participation.quantile(0.90)
            )
            row[f"{label}_latest_participation"] = float(
                participation.iloc[-1]
            )
        rows.append(row)
    return pd.DataFrame(rows)


def build_lot_cases(latest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for capital in CAPITAL_LEVELS:
        holdings: dict[str, dict[str, float | int]] = {}
        invested = 0.0
        for symbol in SYMBOLS:
            price = float(latest.loc[symbol, "close"])
            shares = int(
                (capital * WEIGHTS[symbol] / price) // LOT_SIZE * LOT_SIZE
            )
            value = shares * price
            holdings[symbol] = {
                "shares": shares,
                "price": price,
                "value": value,
            }
            invested += value
        cash = capital - invested
        actual = {
            symbol: float(item["value"]) / capital
            for symbol, item in holdings.items()
        }
        tracking_tv = 0.5 * (
            sum(abs(actual[symbol] - WEIGHTS[symbol]) for symbol in SYMBOLS)
            + cash / capital
        )
        rows.append(
            {
                "capital": capital,
                "nasdaq_shares": int(holdings[base.NASDAQ]["shares"]),
                "gold_shares": int(holdings[base.GOLD]["shares"]),
                "held_assets": sum(
                    int(item["shares"] > 0) for item in holdings.values()
                ),
                "cash": float(cash),
                "cash_weight": float(cash / capital),
                "tracking_total_variation": float(tracking_tv),
            }
        )
    return pd.DataFrame(rows)


def evaluate_checks(
    capacity: pd.DataFrame,
    lots: pd.DataFrame,
    staleness_days: int,
) -> dict[str, bool]:
    one_million = "capital_1000000"
    five_million = "capital_5000000"
    smallest = lots.loc[lots["capital"].eq(100_000.0)].iloc[0]
    return {
        "fresh_within_five_days": 0 <= staleness_days <= 5,
        "each_asset_has_at_least_1800_valid_days": bool(
            capacity["valid_days"].ge(1800).all()
        ),
        "one_million_p90_participation_within_1pct": bool(
            capacity[f"{one_million}_p90_participation"].le(0.01).all()
        ),
        "one_million_latest_participation_within_1pct": bool(
            capacity[f"{one_million}_latest_participation"].le(0.01).all()
        ),
        "five_million_median_participation_within_1pct": bool(
            capacity[f"{five_million}_median_participation"].le(0.01).all()
        ),
        "five_million_p90_participation_within_2pct": bool(
            capacity[f"{five_million}_p90_participation"].le(0.02).all()
        ),
        "one_hundred_thousand_tracking_tv_within_05pct": bool(
            smallest["tracking_total_variation"] <= 0.005
        ),
        "all_capital_cases_hold_both_assets": bool(
            lots["held_assets"].eq(2).all()
        ),
    }


def require_source_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("纳指黄金V3依赖尚未成功完成")
    if latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("纳指黄金V3依赖未通过研究门槛")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    capacity: pd.DataFrame,
    lots: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    capacity_path = attempt.output_dir / "capacity_by_asset.csv"
    capacity.to_csv(capacity_path, index=False)
    lots_path = attempt.output_dir / "whole_lot_cases.csv"
    lots.to_csv(lots_path, index=False)
    metrics_path = attempt.output_dir / "capacity_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_EXECUTION_AUDIT" if passed else "RISK_FLAGGED",
        decision_reason=(
            "100万与500万容量门槛及10万整手跟踪门槛全部通过"
            if passed
            else "固定容量或整手门槛未通过，源策略历史门槛不覆盖"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "容量与整手审计报告"),
            ExperimentArtifact("capacity", capacity_path, "逐资产容量统计"),
            ExperimentArtifact("whole_lots", lots_path, "整手取整情景"),
            ExperimentArtifact("metrics", metrics_path, "容量审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    capacity_rows = "\n".join(
        f"| {item['symbol']} | {item['weight']:.0%} | "
        f"{item['valid_days']} | {item['median_daily_amount']:,.0f} | "
        f"{item['capital_1000000_p90_participation']:.3%} | "
        f"{item['capital_1000000_latest_participation']:.3%} | "
        f"{item['capital_5000000_p90_participation']:.3%} |"
        for item in result["capacity"]
    )
    lot_rows = "\n".join(
        f"| {item['capital']:,.0f} | {item['nasdaq_shares']:,} | "
        f"{item['gold_shares']:,} | {item['cash_weight']:.3%} | "
        f"{item['tracking_total_variation']:.3%} |"
        for item in result["lot_cases"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 纳指黄金60/40资金容量与整手审计 V1

- 截止日：{result['as_of_date']}；共同最新交易日：
  {result['latest_common_date']}。
- 成交额使用未复权日线 amount，源单位千元，换算为人民币元。
- 参与率按一次性建立完整目标仓位计算，比月度再平衡差额更保守。
- 结论：{result['decision']}。

| 标的 | 权重 | 有效日 | 日成交额中位 | 100万P90 | 100万最新 | 500万P90 |
|---|---:|---:|---:|---:|---:|---:|
{capacity_rows}

| 本金 | 纳指份额 | 黄金份额 | 余留现金 | 组合总变差 |
|---:|---:|---:|---:|---:|
{lot_rows}

## 冻结门槛

{checks}

本审计不改源策略权重或历史研究结论，也不代表已具备实时申购赎回、
IOPV或盘中折溢价控制。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                get_runtime_paths(),
                args.as_of_date,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
