"""境内纳指100 ETF替代交易载体的当前执行可行性研究。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import qdii_current_premium_window_audit_v2 as source
from examples import nasdaq_gold_sp500_hurdle_study as base
from runtime.config import get_config_value
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


EXPERIMENT_ID = "nasdaq100_domestic_etf_execution_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq100-domestic-etf-execution-feasibility-v1.md"
)
LOOKBACK_START = "20260401"
REFERENCE_CAPITAL = 1_000_000.0
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="境内纳指100 ETF替代交易载体可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "境内上市且明确跟踪纳斯达克100的ETF中，是否存在最新溢价不超过5%、"
        "近20日成交额中位不低于1亿元且100万元参与率不超过1%的替代载体"
    ),
    definition={
        "source_premium_risk": source.EXPERIMENT_ID,
        "universe": {
            "provider": "Tushare fund_basic market=E status=L",
            "name_or_benchmark_rule": (
                "ETF name matches 纳指/纳斯达克100 and benchmark confirms "
                "纳斯达克100/NASDAQ 100 when benchmark is available"
            ),
            "manual_symbol_allowlist": False,
            "strategy_returns_used": False,
        },
        "external_read": {
            "fund_basic": True,
            "fund_nav": True,
            "fund_daily": True,
            "writes_production_database": False,
        },
        "premium_formula": "raw_close_on_latest_nav_date/unit_nav-1",
        "capacity": {
            "reference_capital": REFERENCE_CAPITAL,
            "participation_formula": "capital/(median_20d_amount*1000)",
        },
        "frozen_gate": {
            "listed_days_min": 365,
            "nav_staleness_days_max": 7,
            "absolute_latest_premium_max": 0.05,
            "median_20d_amount_cny_min": 100_000_000.0,
            "one_million_participation_max": 0.01,
        },
        "decision": "execution_feasibility_only_no_strategy_backtest",
        "does_not_authorize_instrument_substitution": True,
        "does_not_override_source_strategy": True,
        "methodology_version": "live_basic_nav_daily_v1",
    },
)


class TushareFundClient:
    """只读基金基本信息、净值和日线客户端。"""

    def __init__(self, token: str) -> None:
        resolved = str(token).strip()
        if not resolved:
            raise ValueError("TUSHARE_TOKEN未配置")
        self._pro = ts.pro_api(resolved)

    def basic(self) -> pd.DataFrame:
        return self._pro.fund_basic(market="E", status="L")

    def nav(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return self._pro.fund_nav(
            ts_code=symbol,
            start_date=start_date,
            end_date=end_date,
        )

    def daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return self._pro.fund_daily(
            ts_code=symbol,
            start_date=start_date,
            end_date=end_date,
        )


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    normalized = min(str(as_of_date).replace("-", ""), base.RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized,
        data_version=data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_source_risk(paths)
        resolved = client or TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, candidates, daily = calculate(resolved, normalized, paths)
        complete_attempt(attempt, result, candidates, daily)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    client: Any,
    as_of_date: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    basic = client.basic()
    candidates = select_nasdaq100_etfs(basic)
    if candidates.empty:
        raise ValueError("Tushare基金基本信息中没有识别到境内纳指100 ETF")
    rows: list[dict[str, Any]] = []
    daily_frames: list[pd.DataFrame] = []
    for item in candidates.itertuples(index=False):
        symbol = str(item.ts_code)
        nav = normalize_nav(
            client.nav(symbol, LOOKBACK_START, as_of_date)
        )
        daily = normalize_daily(
            client.daily(symbol, LOOKBACK_START, as_of_date)
        )
        if not daily.empty:
            daily["symbol"] = symbol
            daily_frames.append(daily)
        rows.append(
            summarize_candidate(
                item,
                nav,
                daily,
                as_of_date,
            )
        )
    evaluated = pd.DataFrame(rows).sort_values(
        ["eligible", "latest_premium", "median_20d_amount_cny"],
        ascending=[False, True, False],
        na_position="last",
    )
    eligible = evaluated[evaluated["eligible"]].copy()
    result = {
        "as_of_date": as_of_date,
        "candidate_count": int(len(evaluated)),
        "eligible_count": int(len(eligible)),
        "eligible_symbols": eligible["symbol"].astype(str).tolist(),
        "best_available_symbol": (
            str(eligible.iloc[0]["symbol"]) if len(eligible) else None
        ),
        "candidates": evaluated.to_dict("records"),
        "decision": (
            "EXECUTION_FEASIBLE_ALTERNATIVE_EXISTS"
            if len(eligible)
            else "NO_EXECUTION_FEASIBLE_ALTERNATIVE"
        ),
        "strategy_returns_used": False,
        "production_database_written": False,
        "instrument_substitution_authorized": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    all_daily = (
        pd.concat(daily_frames, ignore_index=True)
        if daily_frames
        else pd.DataFrame()
    )
    return result, evaluated, all_daily


def select_nasdaq100_etfs(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"ts_code", "name", "list_date"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"fund_basic缺少字段: {missing}")
    data = frame.copy()
    names = data["name"].fillna("").astype(str)
    benchmark = data.get(
        "benchmark",
        pd.Series("", index=data.index, dtype=str),
    ).fillna("").astype(str)
    name_match = names.str.contains(
        r"(?:纳指(?:100)?|纳斯达克100|NASDAQ ?100)",
        case=False,
        regex=True,
    )
    benchmark_known = benchmark.str.strip().ne("")
    benchmark_match = benchmark.str.contains(
        r"(?:纳斯达克100|NASDAQ ?100|NDX)",
        case=False,
        regex=True,
    )
    etf_match = names.str.contains("ETF", case=False, regex=False)
    non_etf_wrapper = names.str.contains(
        r"(?:LOF|联接)",
        case=False,
        regex=True,
    )
    selected = data[
        name_match
        & etf_match
        & ~non_etf_wrapper
        & (~benchmark_known | benchmark_match)
    ].copy()
    selected["name"] = selected["name"].astype(str)
    selected["benchmark"] = benchmark.loc[selected.index]
    return selected.sort_values("ts_code").reset_index(drop=True)


def normalize_nav(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["nav_date", "unit_nav"])
    data = frame.copy()
    if "nav_date" not in data.columns and "end_date" in data.columns:
        data = data.rename(columns={"end_date": "nav_date"})
    required = {"nav_date", "unit_nav"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"fund_nav缺少字段: {missing}")
    data["nav_date"] = data["nav_date"].astype(str).str.replace("-", "")
    data["unit_nav"] = pd.to_numeric(data["unit_nav"], errors="coerce")
    return data[data["unit_nav"].gt(0)].sort_values("nav_date")


def normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", "close", "amount"])
    required = {"trade_date", "close", "amount"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"fund_daily缺少字段: {missing}")
    data = frame.copy()
    data["trade_date"] = (
        data["trade_date"].astype(str).str.replace("-", "")
    )
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data["amount"] = pd.to_numeric(data["amount"], errors="coerce")
    return data[
        data["close"].gt(0) & data["amount"].gt(0)
    ].sort_values("trade_date")


def summarize_candidate(
    item: Any,
    nav: pd.DataFrame,
    daily: pd.DataFrame,
    as_of_date: str,
) -> dict[str, Any]:
    list_date = str(item.list_date).replace("-", "")[:8]
    listed_days = (
        pd.Timestamp(as_of_date) - pd.Timestamp(list_date)
    ).days
    latest_nav_date: str | None = None
    unit_nav = float("nan")
    raw_close = float("nan")
    premium = float("nan")
    nav_staleness = 9999
    if not nav.empty:
        latest_nav = nav.iloc[-1]
        latest_nav_date = str(latest_nav["nav_date"])
        unit_nav = float(latest_nav["unit_nav"])
        nav_staleness = (
            pd.Timestamp(as_of_date) - pd.Timestamp(latest_nav_date)
        ).days
        price = daily[daily["trade_date"].eq(latest_nav_date)]["close"]
        if len(price):
            raw_close = float(price.iloc[-1])
            premium = raw_close / unit_nav - 1.0
    recent_amount = daily.tail(20)["amount"] * 1_000.0
    median_amount = float(recent_amount.median()) if len(recent_amount) else 0.0
    participation = (
        REFERENCE_CAPITAL / median_amount
        if median_amount > 0
        else float("inf")
    )
    checks = {
        "listed_at_least_365_days": listed_days >= 365,
        "nav_fresh_within_seven_days": 0 <= nav_staleness <= 7,
        "same_date_raw_close_present": pd.notna(raw_close),
        "absolute_latest_premium_within_5pct": (
            pd.notna(premium) and abs(premium) <= 0.05
        ),
        "median_20d_amount_at_least_100m": (
            median_amount >= 100_000_000.0
        ),
        "one_million_participation_within_1pct": (
            participation <= 0.01
        ),
    }
    return {
        "symbol": str(item.ts_code),
        "name": str(item.name),
        "benchmark": str(getattr(item, "benchmark", "") or ""),
        "list_date": list_date,
        "listed_days": int(listed_days),
        "latest_nav_date": latest_nav_date,
        "nav_staleness_days": int(nav_staleness),
        "unit_nav": unit_nav,
        "raw_close": raw_close,
        "latest_premium": premium,
        "daily_rows": int(len(daily)),
        "median_20d_amount_cny": median_amount,
        "one_million_participation": participation,
        "checks": checks,
        "eligible": all(checks.values()),
    }


def require_source_risk(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("当前QDII溢价窗口审计依赖尚未成功")
    if latest.get("outcome") != "RISK_FLAGGED":
        raise RuntimeError(
            f"当前QDII溢价窗口未标记风险: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    candidates_path = attempt.output_dir / "candidate_etfs.csv"
    candidates.to_csv(candidates_path, index=False)
    daily_path = attempt.output_dir / "candidate_daily_window.csv"
    daily.to_csv(daily_path, index=False)
    metrics_path = attempt.output_dir / "feasibility_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = bool(result["eligible_count"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "至少一只境内纳指100ETF通过当前溢价、流动性和容量门槛"
            if passed
            else "没有境内纳指100ETF同时通过当前溢价、流动性和容量门槛"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "替代载体可行性报告"),
            ExperimentArtifact("candidates", candidates_path, "候选ETF明细"),
            ExperimentArtifact("daily", daily_path, "候选近期日线"),
            ExperimentArtifact("metrics", metrics_path, "可行性指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['symbol']} | {item['name']} | "
        f"{item['latest_nav_date'] or '-'} | "
        f"{item['latest_premium']:.2%} | "
        f"{item['median_20d_amount_cny']:,.0f} | "
        f"{item['one_million_participation']:.3%} | "
        f"{'PASS' if item['eligible'] else 'FAIL'} |"
        for item in result["candidates"]
    )
    return f"""# 境内纳指100 ETF替代交易载体可行性 V1

- 截止：{result['as_of_date']}。
- 识别候选：{result['candidate_count']}；通过：
  {result['eligible_count']}。
- 决策：`{result['decision']}`。
- 本研究未读取策略收益、未写生产库、未授权替换生产标的。

| 代码 | 名称 | 最新净值日 | 同日溢价 | 20日成交额中位 | 100万参与率 | 门槛 |
|---|---|---|---:|---:|---:|---|
{rows}

通过要求：上市满365日、净值滞后不超过7天、同日原始收盘存在、绝对溢价
不超过5%、20日成交额中位不低于1亿元、100万元参与率不超过1%。

即使有候选通过，也只表示执行载体可行；跟踪误差、基金合同、申赎状态、
盘中IOPV和策略替换仍需独立审计与人工批准。
"""


def data_version(paths: RuntimePaths) -> str:
    state = paths.system_state_path.stat()
    return f"{state.st_size}:{state.st_mtime_ns}"


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
