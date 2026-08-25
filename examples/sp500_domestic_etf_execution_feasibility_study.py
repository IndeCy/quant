"""境内标普500 ETF当前溢价、流动性与容量可行性研究。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq100_domestic_etf_execution_feasibility_study as support
from examples import qdii_current_nav_monitoring_audit as source
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


EXPERIMENT_ID = "sp500_domestic_etf_execution_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/sp500-domestic-etf-execution-feasibility-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="境内标普500 ETF当前执行可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "境内上市且明确跟踪标普500的纯ETF中，是否存在最新溢价不超过5%、"
        "近20日成交额中位不低于1亿元且100万元参与率不超过1%的交易载体"
    ),
    definition={
        "source_current_nav_audit": source.EXPERIMENT_ID,
        "universe": {
            "provider": "Tushare fund_basic market=E status=L",
            "name_or_benchmark_rule": "pure ETF tracks 标普500/S&P 500",
            "exclude": ["LOF", "联接"],
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
            "reference_capital": support.REFERENCE_CAPITAL,
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
        "does_not_override_opportunity_cost_control": True,
        "methodology_version": "live_basic_nav_daily_v1",
    },
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
        require_source_completed(paths)
        resolved = client or support.TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, candidates, daily = calculate(
            resolved,
            normalized,
            paths,
        )
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
    candidates = select_sp500_etfs(client.basic())
    if candidates.empty:
        raise ValueError("Tushare基金基本信息中没有识别到境内标普500 ETF")
    rows: list[dict[str, Any]] = []
    daily_frames: list[pd.DataFrame] = []
    for item in candidates.itertuples(index=False):
        symbol = str(item.ts_code)
        nav = support.normalize_nav(
            client.nav(symbol, support.LOOKBACK_START, as_of_date)
        )
        daily = support.normalize_daily(
            client.daily(symbol, support.LOOKBACK_START, as_of_date)
        )
        if not daily.empty:
            daily["symbol"] = symbol
            daily_frames.append(daily)
        rows.append(
            support.summarize_candidate(
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
        "lowest_premium_symbol": (
            str(evaluated.iloc[0]["symbol"]) if len(evaluated) else None
        ),
        "candidates": evaluated.to_dict("records"),
        "decision": (
            "EXECUTION_FEASIBLE_SP500_ETF_EXISTS"
            if len(eligible)
            else "NO_EXECUTION_FEASIBLE_SP500_ETF"
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


def select_sp500_etfs(frame: pd.DataFrame) -> pd.DataFrame:
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
        r"(?:标普500|S&P ?500|SP500)",
        case=False,
        regex=True,
    )
    benchmark_known = benchmark.str.strip().ne("")
    benchmark_match = benchmark.str.contains(
        r"(?:标普500|S&P ?500|SP500)",
        case=False,
        regex=True,
    )
    pure_etf = (
        names.str.contains("ETF", case=False, regex=False)
        & ~names.str.contains(r"(?:LOF|联接)", case=False, regex=True)
    )
    selected = data[
        name_match
        & pure_etf
        & (~benchmark_known | benchmark_match)
    ].copy()
    selected["name"] = selected["name"].astype(str)
    selected["benchmark"] = benchmark.loc[selected.index]
    return selected.sort_values("ts_code").reset_index(drop=True)


def require_source_completed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("QDII当前净值监控依赖尚未成功")
    if latest.get("outcome") != "RISK_FLAGGED":
        raise RuntimeError(
            f"QDII当前净值监控结论不符: {latest.get('outcome')}"
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
            "至少一只境内标普500ETF通过当前溢价、流动性和容量门槛"
            if passed
            else "没有境内标普500ETF同时通过当前溢价、流动性和容量门槛"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "标普载体可行性报告"),
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
    return f"""# 境内标普500 ETF当前执行可行性 V1

- 截止：{result['as_of_date']}。
- 识别候选：{result['candidate_count']}；通过：
  {result['eligible_count']}。
- 决策：`{result['decision']}`。
- 本研究未读取策略收益、未写生产库、未授权替换机会成本对照。

| 代码 | 名称 | 最新净值日 | 同日溢价 | 20日成交额中位 | 100万参与率 | 门槛 |
|---|---|---|---:|---:|---:|---|
{rows}

通过要求与纳指100载体研究完全一致。通过仅表示当前执行载体可行，
不代表未来收益、跟踪误差或盘中IOPV风险通过。
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
