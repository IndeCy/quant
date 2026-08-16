"""归因五资产独立趋势可行性失败是否为本地增量数据缺口。"""

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

from examples import cross_asset_independent_trend_feasibility_study as source
from examples import nasdaq100_domestic_etf_execution_feasibility_study as support
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


EXPERIMENT_ID = "cross_asset_independent_trend_feasibility_failure_audit_v1"
REPORT_PATH = Path(
    "docs/research/cross-asset-independent-trend-feasibility-failure-audit-v1.md"
)
SYMBOLS = [*source.RISKY_ASSETS, source.DEFENSIVE_ASSET]
LOOKBACK_START = "20260720"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="五资产独立趋势数据门禁失败归因 V1",
    category="data_audit",
    hypothesis=(
        "五资产最新日期不一致，是否由本机增量库遗漏而非上游无交易或策略"
        "样本本身不可用造成"
    ),
    definition={
        "source_feasibility": source.EXPERIMENT_ID,
        "symbols": SYMBOLS,
        "local_read": {
            "database": "benchmark_increment.duckdb",
            "table": "fund_daily",
            "writes_database": False,
        },
        "external_read": {
            "provider": "Tushare Pro fund_daily",
            "start_date": LOOKBACK_START,
            "writes_database": False,
        },
        "frozen_checks": {
            "source_only_latest_date_check_failed": True,
            "upstream_all_symbols_reach_as_of": True,
            "at_least_one_local_row_missing_upstream_available": True,
            "common_sample_remains_fresh": True,
        },
        "does_not_patch_local_database": True,
        "does_not_bypass_feasibility_gate": True,
        "does_not_run_strategy_backtest": True,
        "promotion_scope": "data_failure_attribution_only",
        "methodology_version": "local_increment_vs_upstream_dates_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    normalized = str(as_of_date).replace("-", "")
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
        source_metrics = load_source_metrics(paths)
        resolved = client or support.TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        local = load_local_dates(paths, normalized)
        upstream = load_upstream_dates(resolved, normalized)
        result, comparison = calculate(
            source_metrics,
            local,
            upstream,
            paths,
            normalized,
        )
        complete_attempt(attempt, result, comparison)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_source_metrics(paths: RuntimePaths) -> dict[str, Any]:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("五资产独立趋势数据可行性依赖尚未成功")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError(
            f"五资产独立趋势数据门禁未拒绝: {latest.get('outcome')}"
        )
    return dict(latest.get("metrics") or {})


def load_local_dates(
    paths: RuntimePaths,
    as_of_date: str,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in SYMBOLS)
    with duckdb.connect(
        str(paths.benchmark_increment_path),
        read_only=True,
    ) as connection:
        return connection.execute(
            f"""
            SELECT ts_code AS symbol, trade_date
            FROM fund_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY ts_code, trade_date
            """,
            [*SYMBOLS, LOOKBACK_START, as_of_date],
        ).fetchdf()


def load_upstream_dates(
    client: Any,
    as_of_date: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for symbol in SYMBOLS:
        frame = client.daily(symbol, LOOKBACK_START, as_of_date)
        if frame.empty:
            continue
        values = frame[["trade_date"]].copy()
        values["symbol"] = symbol
        frames.append(values)
    if not frames:
        return pd.DataFrame(columns=["symbol", "trade_date"])
    data = pd.concat(frames, ignore_index=True)
    data["trade_date"] = (
        data["trade_date"].astype(str).str.replace("-", "")
    )
    return data[["symbol", "trade_date"]].drop_duplicates()


def calculate(
    source_metrics: dict[str, Any],
    local: pd.DataFrame,
    upstream: pd.DataFrame,
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    comparison = compare_dates(local, upstream)
    failed_source_checks = sorted(
        name
        for name, passed in source_metrics["checks"].items()
        if not passed
    )
    local_missing = comparison[comparison["local_missing"]]
    upstream_latest = (
        upstream.groupby("symbol")["trade_date"].max().to_dict()
    )
    checks = {
        "source_only_latest_date_check_failed": (
            failed_source_checks == ["all_assets_latest_same_date"]
        ),
        "upstream_all_symbols_reach_as_of": all(
            upstream_latest.get(symbol) == as_of_date for symbol in SYMBOLS
        ),
        "at_least_one_local_row_missing_upstream_available": (
            len(local_missing) > 0
        ),
        "every_missing_row_exists_upstream": bool(
            local_missing["upstream_present"].all()
        ),
        "common_sample_remains_fresh": (
            int(source_metrics["staleness_days"])
            <= source.MAX_STALENESS_CALENDAR_DAYS
        ),
    }
    passed = all(checks.values())
    missing_by_symbol = {
        symbol: sorted(
            local_missing.loc[
                local_missing["symbol"].eq(symbol),
                "trade_date",
            ].astype(str)
        )
        for symbol in SYMBOLS
        if local_missing["symbol"].eq(symbol).any()
    }
    result = {
        "as_of_date": as_of_date,
        "source_decision": source_metrics["decision"],
        "failed_source_checks": failed_source_checks,
        "local_missing_row_count": int(len(local_missing)),
        "local_missing_dates_by_symbol": missing_by_symbol,
        "upstream_latest_dates": upstream_latest,
        "checks": checks,
        "classification": (
            "LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE"
            if passed
            else "DATA_GAP_ORIGIN_UNRESOLVED"
        ),
        "local_database_written": False,
        "feasibility_gate_bypassed": False,
        "strategy_backtest_run": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, comparison


def compare_dates(
    local: pd.DataFrame,
    upstream: pd.DataFrame,
) -> pd.DataFrame:
    local_keys = local[["symbol", "trade_date"]].copy()
    local_keys["local_present"] = True
    upstream_keys = upstream[["symbol", "trade_date"]].copy()
    upstream_keys["upstream_present"] = True
    comparison = upstream_keys.merge(
        local_keys,
        on=["symbol", "trade_date"],
        how="outer",
        validate="one_to_one",
    )
    comparison["local_present"] = (
        comparison["local_present"].fillna(False).astype(bool)
    )
    comparison["upstream_present"] = (
        comparison["upstream_present"].fillna(False).astype(bool)
    )
    comparison["local_missing"] = (
        comparison["upstream_present"] & ~comparison["local_present"]
    )
    return comparison.sort_values(["symbol", "trade_date"]).reset_index(
        drop=True
    )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    comparison: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    comparison_path = attempt.output_dir / "local_upstream_date_comparison.csv"
    comparison.to_csv(comparison_path, index=False)
    metrics_path = attempt.output_dir / "failure_attribution_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "上游数据已存在但本地增量库遗漏，正式数据门禁保持阻断"
            if result["classification"].startswith("LOCAL_INCREMENT")
            else "本地与上游日期对比不足以解释数据门禁失败"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "数据失败归因报告"),
            ExperimentArtifact(
                "date_comparison",
                comparison_path,
                "本地与上游日期比较",
            ),
            ExperimentArtifact("metrics", metrics_path, "失败归因指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    missing = "\n".join(
        f"- `{symbol}`：{', '.join(dates)}"
        for symbol, dates in result["local_missing_dates_by_symbol"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 五资产独立趋势数据门禁失败归因 V1

- 来源决策：`{result['source_decision']}`。
- 分类：`{result['classification']}`。
- 本地缺失、上游可用行：{result['local_missing_row_count']}。

## 缺失日期

{missing}

## 冻结检查

{checks}

本审计仅只读比较日期，不补写本地数据库、不绕过可行性门禁，也未运行策略回测。
"""


def data_version(paths: RuntimePaths) -> str:
    state = paths.system_state_path.stat()
    increment = paths.benchmark_increment_path.stat()
    return (
        f"state:{state.st_size}:{state.st_mtime_ns}|"
        f"increment:{increment.st_size}:{increment.st_mtime_ns}"
    )


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
