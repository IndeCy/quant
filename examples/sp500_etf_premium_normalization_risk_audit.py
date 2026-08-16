"""审计标普500 ETF高溢价后20日的历史归一化收益效应。"""

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
from examples import nasdaq_gold_sp500_hurdle_study as base
from examples import sp500_etf_premium_tracking_attribution_audit as source
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


EXPERIMENT_ID = "sp500_etf_premium_normalization_risk_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-etf-premium-normalization-risk-audit-v1.md"
)
FORWARD_DAYS = 20
PREMIUM_THRESHOLD = 0.05
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普500 ETF高溢价归一化风险 V1",
    category="execution_audit",
    hypothesis=(
        "场内溢价至少5%时，未来20个交易日的溢价变化是否通常形成负收益"
        "效应，从而量化追入高溢价标的的历史执行拖累"
    ),
    definition={
        "source_attribution_audit": source.EXPERIMENT_ID,
        "symbols": list(source.SYMBOLS),
        "start_date": source.source.START_DATE,
        "premium_threshold": PREMIUM_THRESHOLD,
        "forward_trading_days": FORWARD_DAYS,
        "forward_effect_formula": (
            "(1+premium_t_plus_20)/(1+premium_t)-1"
        ),
        "frozen_gate": {
            "valid_observations_each_min": 700,
            "control_high_premium_observations_min": 50,
            "control_high_premium_negative_effect_probability_min": 0.60,
            "control_high_premium_median_effect_max": 0.0,
            "candidate_latest_premium_max": 0.05,
            "control_latest_premium_min": 0.05,
            "absolute_premium_max": 0.50,
        },
        "does_not_use_strategy_returns": True,
        "does_not_authorize_instrument_substitution": True,
        "does_not_define_a_trading_signal": True,
        "promotion_scope": "execution_risk_only",
        "methodology_version": "fixed_5pct_forward_20d_v1",
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
        result, observations = calculate(resolved, normalized, paths)
        complete_attempt(attempt, result, observations)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    client: Any,
    as_of_date: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    summaries: dict[str, dict[str, Any]] = {}
    for symbol in source.SYMBOLS:
        matched = source.normalize_matched(
            client.nav(symbol, source.source.START_DATE, as_of_date),
            client.daily(symbol, source.source.START_DATE, as_of_date),
            symbol,
        )
        observations = build_forward_observations(matched)
        frames.append(observations)
        summaries[symbol] = summarize(symbol, matched, observations)
    combined = pd.concat(frames, ignore_index=True)
    candidate = summaries[source.source.CANDIDATE]
    control = summaries[source.source.CONTROL]
    checks = {
        "each_symbol_has_at_least_700_valid_observations": all(
            item["valid_forward_observations"] >= 700
            for item in summaries.values()
        ),
        "control_has_at_least_50_high_premium_observations": (
            control["high_premium_observations"] >= 50
        ),
        "control_high_premium_negative_probability_at_least_60pct": (
            control["high_premium_negative_effect_probability"] >= 0.60
        ),
        "control_high_premium_median_effect_non_positive": (
            control["high_premium_median_forward_effect"] <= 0.0
        ),
        "candidate_latest_premium_within_5pct": (
            candidate["latest_premium"] <= PREMIUM_THRESHOLD
        ),
        "control_latest_premium_at_least_5pct": (
            control["latest_premium"] >= PREMIUM_THRESHOLD
        ),
        "no_absolute_premium_above_50pct": all(
            item["maximum_absolute_premium"] <= 0.50
            for item in summaries.values()
        ),
    }
    passed = all(checks.values())
    result = {
        "as_of_date": as_of_date,
        "start_date": source.source.START_DATE,
        "forward_trading_days": FORWARD_DAYS,
        "premium_threshold": PREMIUM_THRESHOLD,
        "summaries": summaries,
        "checks": checks,
        "classification": (
            "CONTROL_PREMIUM_NORMALIZATION_RISK_CANDIDATE_CURRENTLY_LOWER"
            if passed
            else "HISTORICAL_NORMALIZATION_RISK_NOT_ESTABLISHED"
        ),
        "strategy_returns_used": False,
        "trading_signal_defined": False,
        "instrument_substitution_authorized": False,
        "production_database_written": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, combined


def build_forward_observations(matched: pd.DataFrame) -> pd.DataFrame:
    data = matched.sort_values("trade_date").copy()
    data = data[data["premium"].abs().le(0.50)].copy()
    data["forward_premium"] = data["premium"].shift(-FORWARD_DAYS)
    data["forward_premium_effect"] = (
        (1.0 + data["forward_premium"]) / (1.0 + data["premium"]) - 1.0
    )
    data["high_premium"] = data["premium"].ge(PREMIUM_THRESHOLD)
    return data[data["forward_premium_effect"].notna()].reset_index(drop=True)


def summarize(
    symbol: str,
    matched: pd.DataFrame,
    observations: pd.DataFrame,
) -> dict[str, Any]:
    if matched.empty or observations.empty:
        raise ValueError(f"{symbol}缺少可用折溢价序列")
    high = observations[observations["high_premium"]]
    effects = high["forward_premium_effect"]
    latest = matched.sort_values("trade_date").iloc[-1]
    return {
        "latest_nav_date": str(latest["trade_date"]),
        "latest_premium": float(latest["premium"]),
        "latest_premium_history_percentile": float(
            matched["premium"].le(float(latest["premium"])).mean()
        ),
        "maximum_absolute_premium": float(matched["premium"].abs().max()),
        "valid_forward_observations": int(len(observations)),
        "high_premium_observations": int(len(high)),
        "high_premium_share": float(len(high) / len(observations)),
        "high_premium_median_forward_effect": (
            float(effects.median()) if len(effects) else float("nan")
        ),
        "high_premium_p05_forward_effect": (
            float(effects.quantile(0.05)) if len(effects) else float("nan")
        ),
        "high_premium_p95_forward_effect": (
            float(effects.quantile(0.95)) if len(effects) else float("nan")
        ),
        "high_premium_negative_effect_probability": (
            float(effects.lt(0).mean()) if len(effects) else float("nan")
        ),
        "high_premium_loss_beyond_2pct_probability": (
            float(effects.le(-0.02).mean()) if len(effects) else float("nan")
        ),
    }


def require_source_completed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("标普500溢价跟踪归因依赖尚未成功")
    if latest.get("outcome") != "PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE":
        raise RuntimeError(
            f"标普500溢价跟踪归因结论不符: {latest.get('outcome')}"
        )


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
    observations_path = attempt.output_dir / "forward_premium_effects.csv"
    observations.to_csv(observations_path, index=False)
    metrics_path = attempt.output_dir / "normalization_risk_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "513500当前高于5%溢价且历史高溢价后的20日归一化效应偏负"
            if result["classification"].startswith("CONTROL_PREMIUM")
            else "冻结样本或统计门槛不足以确认高溢价归一化风险"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "归一化风险报告"),
            ExperimentArtifact(
                "observations",
                observations_path,
                "20日远期溢价效应",
            ),
            ExperimentArtifact("metrics", metrics_path, "归一化风险指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {symbol} | {item['latest_premium']:.2%} | "
        f"{item['latest_premium_history_percentile']:.1%} | "
        f"{item['high_premium_observations']} | "
        f"{item['high_premium_median_forward_effect']:.2%} | "
        f"{item['high_premium_negative_effect_probability']:.1%} | "
        f"{item['high_premium_loss_beyond_2pct_probability']:.1%} |"
        for symbol, item in result["summaries"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 标普500 ETF高溢价归一化风险 V1

- 区间：{result['start_date']} 至 {result['as_of_date']}。
- 固定高溢价阈值：{result['premium_threshold']:.1%}；
  观察未来：{result['forward_trading_days']}个交易日。
- 分类：`{result['classification']}`。

| 代码 | 最新溢价 | 历史分位 | 高溢价样本 | 20日效应中位 | 负效应概率 | 损失超2%概率 |
|---|---:|---:|---:|---:|---:|---:|
{rows}

## 冻结门槛

{checks}

“溢价效应”只隔离场内价格相对单位净值的变化，不是基金总收益，也不构成
择时信号或自动替换授权。
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
