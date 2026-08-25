"""归因513650与513500历史收益不等价来自净值跟踪还是场内溢价。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq100_domestic_etf_execution_feasibility_study as support
from examples import nasdaq_gold_sp500_hurdle_study as base
from examples import sp500_etf_instrument_equivalence_audit as source
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


EXPERIMENT_ID = "sp500_etf_premium_tracking_attribution_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-etf-premium-tracking-attribution-audit-v1.md"
)
SYMBOLS = (source.CANDIDATE, source.CONTROL)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普500 ETF溢价与净值跟踪归因 V1",
    category="execution_audit",
    hypothesis=(
        "513650与513500场内日收益等价性失败，是否主要由两只基金的溢价"
        "变化差异解释，而非单位净值层面的标普500跟踪差异"
    ),
    definition={
        "source_equivalence_audit": source.EXPERIMENT_ID,
        "symbols": list(SYMBOLS),
        "start_date": source.START_DATE,
        "external_read": {
            "provider": "Tushare Pro fund_nav and fund_daily",
            "writes_production_database": False,
        },
        "decomposition": (
            "1+close_return=(1+unit_nav_return)"
            "*(1+premium_normalization_effect)"
        ),
        "frozen_gate": {
            "common_intervals_min": 700,
            "raw_close_return_correlation_below": 0.98,
            "unit_nav_return_correlation_min": 0.98,
            "unit_nav_beta_range": [0.95, 1.05],
            "unit_nav_tracking_error_max": 0.03,
            "active_price_vs_active_premium_effect_abs_correlation_min": 0.70,
            "decomposition_max_absolute_error_max": 1e-10,
        },
        "does_not_authorize_instrument_substitution": True,
        "does_not_override_source_failure": True,
        "promotion_scope": "failure_attribution_only",
        "methodology_version": "matched_nav_close_decomposition_v1",
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
        require_source_failed(paths)
        resolved = client or support.TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, panel = calculate(resolved, normalized, paths)
        complete_attempt(attempt, result, panel)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    client: Any,
    as_of_date: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    matched = {
        symbol: normalize_matched(
            client.nav(symbol, source.START_DATE, as_of_date),
            client.daily(symbol, source.START_DATE, as_of_date),
            symbol,
        )
        for symbol in SYMBOLS
    }
    panel = build_panel(matched[source.CANDIDATE], matched[source.CONTROL])
    if panel.empty:
        raise ValueError("513650与513500没有共同净值区间")
    candidate_nav = panel["nav_return_candidate"]
    control_nav = panel["nav_return_control"]
    candidate_price = panel["price_return_candidate"]
    control_price = panel["price_return_control"]
    active_price = candidate_price - control_price
    active_premium = (
        panel["premium_effect_candidate"] - panel["premium_effect_control"]
    )
    control_variance = float(control_nav.var(ddof=1))
    nav_beta = (
        float(candidate_nav.cov(control_nav) / control_variance)
        if control_variance > 0
        else float("nan")
    )
    nav_tracking_error = float(
        (candidate_nav - control_nav).std(ddof=1) * math.sqrt(252)
    )
    raw_correlation = float(candidate_price.corr(control_price))
    nav_correlation = float(candidate_nav.corr(control_nav))
    attribution_correlation = float(active_price.corr(active_premium))
    reconstruction_error = float(
        max(
            panel["reconstruction_error_candidate"].abs().max(),
            panel["reconstruction_error_control"].abs().max(),
        )
    )
    checks = {
        "at_least_700_common_intervals": len(panel) >= 700,
        "source_raw_correlation_remains_below_098": raw_correlation < 0.98,
        "unit_nav_return_correlation_at_least_098": nav_correlation >= 0.98,
        "unit_nav_beta_between_095_and_105": 0.95 <= nav_beta <= 1.05,
        "unit_nav_tracking_error_within_3pct": nav_tracking_error <= 0.03,
        "active_price_is_linked_to_active_premium_effect": (
            abs(attribution_correlation) >= 0.70
        ),
        "decomposition_error_within_1e_10": reconstruction_error <= 1e-10,
    }
    if all(checks.values()):
        classification = "PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE"
    elif (
        checks["at_least_700_common_intervals"]
        and checks["decomposition_error_within_1e_10"]
    ):
        classification = "RETURN_DIVERGENCE_NOT_FULLY_EXPLAINED_BY_PREMIUM"
    else:
        classification = "ATTRIBUTION_DATA_INSUFFICIENT"
    result = {
        "as_of_date": as_of_date,
        "start_date": source.START_DATE,
        "common_intervals": int(len(panel)),
        "raw_close_return_correlation": raw_correlation,
        "unit_nav_return_correlation": nav_correlation,
        "unit_nav_beta_vs_513500": nav_beta,
        "unit_nav_annualized_tracking_error": nav_tracking_error,
        "active_price_vs_active_premium_effect_correlation": (
            attribution_correlation
        ),
        "candidate_latest_premium": float(panel["premium_candidate"].iloc[-1]),
        "control_latest_premium": float(panel["premium_control"].iloc[-1]),
        "latest_premium_spread": float(
            panel["premium_candidate"].iloc[-1]
            - panel["premium_control"].iloc[-1]
        ),
        "decomposition_max_absolute_error": reconstruction_error,
        "checks": checks,
        "classification": classification,
        "source_failure_overridden": False,
        "instrument_substitution_authorized": False,
        "production_database_written": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, panel


def normalize_matched(
    nav: pd.DataFrame,
    daily: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    normalized_nav = support.normalize_nav(nav)
    normalized_daily = support.normalize_daily(daily)
    if normalized_nav.empty or normalized_daily.empty:
        return pd.DataFrame(
            columns=["trade_date", "unit_nav", "close", "premium"]
        )
    matched = normalized_nav[["nav_date", "unit_nav"]].merge(
        normalized_daily[["trade_date", "close"]],
        left_on="nav_date",
        right_on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    matched["premium"] = matched["close"] / matched["unit_nav"] - 1.0
    matched["symbol"] = symbol
    return matched[
        ["symbol", "trade_date", "unit_nav", "close", "premium"]
    ].sort_values("trade_date")


def build_panel(
    candidate: pd.DataFrame,
    control: pd.DataFrame,
) -> pd.DataFrame:
    common = candidate.merge(
        control,
        on="trade_date",
        how="inner",
        suffixes=("_candidate", "_control"),
        validate="one_to_one",
    ).sort_values("trade_date")
    for label in ("candidate", "control"):
        nav = common[f"unit_nav_{label}"]
        close = common[f"close_{label}"]
        premium = common[f"premium_{label}"]
        common[f"nav_return_{label}"] = nav.pct_change()
        common[f"price_return_{label}"] = close.pct_change()
        common[f"premium_effect_{label}"] = (
            (1.0 + premium) / (1.0 + premium.shift(1)) - 1.0
        )
        reconstructed = (
            (1.0 + common[f"nav_return_{label}"])
            * (1.0 + common[f"premium_effect_{label}"])
            - 1.0
        )
        common[f"reconstruction_error_{label}"] = (
            common[f"price_return_{label}"] - reconstructed
        )
    required = [
        column
        for column in common.columns
        if column.startswith(
            ("nav_return_", "price_return_", "premium_effect_")
        )
    ]
    return common.dropna(subset=required).reset_index(drop=True)


def require_source_failed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("标普500载体等价性审计依赖尚未成功")
    if latest.get("outcome") != "INSTRUMENT_RETURN_EQUIVALENCE_FAILED":
        raise RuntimeError(
            f"标普500载体等价性并未失败: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    panel: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    panel_path = attempt.output_dir / "premium_tracking_panel.csv"
    panel.to_csv(panel_path, index=False)
    metrics_path = attempt.output_dir / "attribution_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "场内收益偏差主要来自溢价变化，但原等价性失败结论保持"
            if result["classification"].startswith("PREMIUM_DYNAMICS")
            else "净值跟踪或样本证据不足，不能把收益偏差完全归因于溢价"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "溢价跟踪归因报告"),
            ExperimentArtifact("panel", panel_path, "共同日期分解序列"),
            ExperimentArtifact("metrics", metrics_path, "归因指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 标普500 ETF溢价与净值跟踪归因 V1

- 区间：{result['start_date']} 至 {result['as_of_date']}；共同净值区间：
  {result['common_intervals']}。
- 场内价格日收益相关：{result['raw_close_return_correlation']:.4f}；
  单位净值日收益相关：{result['unit_nav_return_correlation']:.4f}。
- 单位净值Beta：{result['unit_nav_beta_vs_513500']:.4f}；
  年化跟踪误差：{result['unit_nav_annualized_tracking_error']:.2%}。
- 场内主动收益与溢价变化差的相关：
  {result['active_price_vs_active_premium_effect_correlation']:.4f}。
- 最新513650/513500溢价：
  {result['candidate_latest_premium']:.2%} /
  {result['control_latest_premium']:.2%}；差：
  {result['latest_premium_spread']:.2%}。
- 分解最大绝对误差：
  {result['decomposition_max_absolute_error']:.3e}。
- 分类：`{result['classification']}`。

## 冻结门槛

{checks}

本审计只归因已观察到的收益偏差，不推翻等价性失败，不授权替换标的，
也不使用或修改生产数据库。
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
