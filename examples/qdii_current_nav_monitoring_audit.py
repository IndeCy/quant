"""只读拉取最新QDII基金净值并审计当前折溢价可监控性。"""

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

from examples import nasdaq_gold_qdii_premium_corporate_action_audit_v2 as source
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


EXPERIMENT_ID = "qdii_current_nav_monitoring_audit_v1"
REPORT_PATH = Path("docs/research/qdii-current-nav-monitoring-audit-v1.md")
SYMBOLS = {
    base.NASDAQ: "纳斯达克100ETF",
    base.SP500: "标普500ETF",
}
LOOKBACK_START = "20260601"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="QDII最新净值与折溢价监控可用性 V1",
    category="execution_audit",
    hypothesis=(
        "Tushare最新单位净值能否在7个自然日内覆盖159941和513500，并与"
        "同日场内收盘匹配，以支持当前折溢价监控"
    ),
    definition={
        "source_premium_audit": source.EXPERIMENT_ID,
        "symbols": SYMBOLS,
        "external_read": {
            "provider": "Tushare Pro fund_nav",
            "start_date": LOOKBACK_START,
            "writes_production_database": False,
        },
        "premium_formula": "raw_close_on_nav_end_date/unit_nav-1",
        "frozen_gate": {
            "all_symbols_returned": True,
            "nav_staleness_calendar_days_max": 7,
            "same_date_raw_close_required": True,
            "absolute_latest_premium_max": 0.10,
        },
        "does_not_replace_realtime_iopv": True,
        "does_not_override_source_gate": True,
        "promotion_scope": "monitoring_availability_only",
        "methodology_version": "tushare_nav_same_date_raw_close_v1",
    },
)


class TushareNavClient:
    """最小化只读基金净值客户端。"""

    def __init__(self, token: str) -> None:
        resolved = str(token).strip()
        if not resolved:
            raise ValueError("TUSHARE_TOKEN未配置")
        self._pro = ts.pro_api(resolved)

    def fetch(
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
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_source_passed(paths)
        resolved_client = client or TushareNavClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, observations = calculate(
            paths,
            normalized,
            resolved_client,
        )
        complete_attempt(attempt, result, observations)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
    client: Any,
) -> tuple[dict[str, Any], pd.DataFrame]:
    nav = load_current_nav(client, as_of_date)
    prices = load_raw_closes(paths, nav, as_of_date)
    observations = summarize_observations(nav, prices, as_of_date)
    checks = {
        "all_symbols_returned": set(observations["symbol"]) == set(SYMBOLS),
        "all_nav_staleness_within_seven_days": bool(
            observations["nav_staleness_days"].le(7).all()
        ),
        "all_same_date_raw_close_present": bool(
            observations["raw_close"].notna().all()
        ),
        "all_absolute_latest_premium_within_10pct": bool(
            observations["premium"].abs().le(0.10).all()
        ),
    }
    passed = all(checks.values())
    availability_checks = [
        checks["all_symbols_returned"],
        checks["all_nav_staleness_within_seven_days"],
        checks["all_same_date_raw_close_present"],
    ]
    if passed:
        classification = "CURRENT_NAV_AVAILABLE_PREMIUM_WITHIN_LIMIT"
    elif all(availability_checks):
        classification = "CURRENT_PREMIUM_RISK_FLAGGED"
    else:
        classification = "CURRENT_NAV_MONITORING_UNAVAILABLE"
    result = {
        "as_of_date": as_of_date,
        "observations": observations.to_dict("records"),
        "gate": {"checks": checks, "passed": passed},
        "classification": classification,
        "realtime_iopv_available": False,
        "production_database_written": False,
        "source_gate_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, observations


def load_current_nav(client: Any, as_of_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for symbol in SYMBOLS:
        frame = client.fetch(symbol, LOOKBACK_START, as_of_date).copy()
        if frame.empty:
            continue
        frame["symbol"] = symbol
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "end_date", "unit_nav"]
        )
    nav = pd.concat(frames, ignore_index=True)
    if "end_date" not in nav.columns and "nav_date" in nav.columns:
        nav = nav.rename(columns={"nav_date": "end_date"})
    required = {"symbol", "end_date", "unit_nav"}
    missing = sorted(required - set(nav.columns))
    if missing:
        raise ValueError(f"fund_nav缺少字段: {missing}")
    nav["end_date"] = nav["end_date"].astype(str).str.replace("-", "")
    nav["unit_nav"] = pd.to_numeric(nav["unit_nav"], errors="coerce")
    nav = nav[
        nav["end_date"].le(as_of_date)
        & nav["unit_nav"].gt(0)
    ].copy()
    return (
        nav.sort_values(["symbol", "end_date"])
        .drop_duplicates(["symbol", "end_date"], keep="last")
    )


def load_raw_closes(
    paths: RuntimePaths,
    nav: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in SYMBOLS)
    frames: list[pd.DataFrame] = []
    with duckdb.connect(
        str(paths.fund_daily_history_path), read_only=True
    ) as connection:
        frames.append(
            connection.execute(
                f"""
                SELECT trade_date, ts_code AS symbol, close,
                       0 AS source_priority
                FROM etf_lof_reits_daily_adj
                WHERE ts_code IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                """,
                [*SYMBOLS, LOOKBACK_START, as_of_date],
            ).fetchdf()
        )
    with duckdb.connect(
        str(paths.benchmark_increment_path), read_only=True
    ) as connection:
        frames.append(
            connection.execute(
                f"""
                SELECT trade_date, ts_code AS symbol, close,
                       1 AS source_priority
                FROM fund_daily
                WHERE ts_code IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                """,
                [*SYMBOLS, LOOKBACK_START, as_of_date],
            ).fetchdf()
        )
    prices = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["symbol", "trade_date", "source_priority"])
        .drop_duplicates(["symbol", "trade_date"], keep="last")
    )
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    return prices


def summarize_observations(
    nav: pd.DataFrame,
    prices: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        values = nav[nav["symbol"].eq(symbol)].sort_values("end_date")
        if values.empty:
            continue
        latest = values.iloc[-1]
        end_date = str(latest["end_date"])
        close = prices[
            prices["symbol"].eq(symbol)
            & prices["trade_date"].astype(str).eq(end_date)
        ]["close"]
        raw_close = float(close.iloc[-1]) if len(close) else float("nan")
        unit_nav = float(latest["unit_nav"])
        rows.append(
            {
                "symbol": symbol,
                "name": SYMBOLS[symbol],
                "nav_end_date": end_date,
                "nav_staleness_days": int(
                    (pd.Timestamp(as_of_date) - pd.Timestamp(end_date)).days
                ),
                "unit_nav": unit_nav,
                "raw_close": raw_close,
                "premium": (
                    raw_close / unit_nav - 1.0
                    if pd.notna(raw_close)
                    else float("nan")
                ),
                "nav_rows_in_window": int(len(values)),
            }
        )
    return pd.DataFrame(rows)


def require_source_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("QDII公司行动修订审计依赖尚未成功")
    if latest.get("outcome") != "PASSED_EXECUTION_AUDIT":
        raise RuntimeError("QDII公司行动修订审计未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    observations: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    observations_path = attempt.output_dir / "latest_nav_observations.csv"
    observations.to_csv(observations_path, index=False)
    metrics_path = attempt.output_dir / "monitoring_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "PASSED_EXECUTION_AUDIT"
            if result["gate"]["passed"]
            else "RISK_FLAGGED"
        ),
        decision_reason=(
            "最新单位净值可用于日频折溢价监控，但不能替代盘中IOPV"
            if result["gate"]["passed"]
            else (
                "最新单位净值可用，但至少一只QDII同日场内溢价超过10%"
                if result["classification"] == "CURRENT_PREMIUM_RISK_FLAGGED"
                else "最新单位净值不够新或无法匹配同日场内价格"
            )
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "最新净值监控报告"),
            ExperimentArtifact("observations", observations_path, "净值观测"),
            ExperimentArtifact("metrics", metrics_path, "监控门槛指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['symbol']} | {item['name']} | {item['nav_end_date']} | "
        f"{item['nav_staleness_days']} | {item['unit_nav']:.4f} | "
        f"{item['raw_close']:.4f} | {item['premium']:.2%} |"
        for item in result["observations"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# QDII最新净值与折溢价监控可用性 V1

- 截止：{result['as_of_date']}；分类：{result['classification']}。
- 本次仅调用Tushare只读接口，未写生产数据库。
- 日频单位净值不能替代盘中IOPV。

| 代码 | 名称 | 净值日 | 滞后日 | 单位净值 | 同日收盘 | 折溢价 |
|---|---|---|---:|---:|---:|---:|
{rows}

## 冻结门槛

{checks}

源历史折溢价审计结论保持不变；实盘下单前仍必须检查盘中IOPV、申赎状态、
涨跌停和实时买卖价差。
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
