"""汇总2026-07-29策略研究、容量与当前溢价证据的决策备忘录。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import a_share_factor_turnover_statistical_audit as turnover
from examples import factor_research_meta_audit as factor_meta
from examples import factor_zoo_common_mode_study as common_mode
from examples import factor_zoo_size_exposure_study as size_exposure
from examples import factor_zoo_walk_forward_residual_study as residual
from examples import intraday_strength_failure_attribution_audit as intraday
from examples import nasdaq_gold_capacity_failure_attribution_audit as capacity
from examples import nasdaq_gold_post_capacity_recovery_audit as post_capacity
from examples import (
    nasdaq100_domestic_etf_execution_feasibility_study as alternative,
)
from examples import nasdaq100_etf_premium_common_mode_audit as premium_common
from examples import qdii_current_premium_window_audit_v2 as premium
from examples import research_campaign_20260729_meta_audit_v3 as campaign
from examples import sp500_domestic_etf_execution_feasibility_study as sp500
from examples import sp500_etf_instrument_equivalence_audit as sp500_equivalence
from examples import (
    sp500_etf_premium_tracking_attribution_audit as sp500_attribution,
)
from examples import (
    sp500_etf_premium_normalization_risk_audit as sp500_normalization,
)
from examples import (
    sp500_premium_normalization_robustness_audit as sp500_robustness,
)
from examples import sp500_gold_vol_target_study as sp500_gold_vol
from examples import (
    sp500_gold_vol_target_failure_attribution_audit as sp500_gold_failure,
)
from examples import (
    sp500_gold_vol_target_statistical_audit as sp500_gold_statistics,
)
from examples import cross_asset_independent_trend_feasibility_study as trend
from examples import (
    cross_asset_independent_trend_failure_audit as trend_failure,
)
from examples import trading_activity_stability_feasibility_study as activity_data
from examples import trading_activity_stability_study as activity
from examples import (
    trading_activity_stability_failure_audit as activity_failure,
)
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


EXPERIMENT_ID = "research_campaign_20260729_decision_memo_v1"
REPORT_PATH = Path(
    "docs/research/research-campaign-20260729-decision-memo-v1.md"
)
DEPENDENCIES = {
    campaign.EXPERIMENT_ID: "PASSED_GOVERNANCE_AUDIT",
    factor_meta.EXPERIMENT_ID: "COMPLETED",
    common_mode.EXPERIMENT_ID: "COMPLETED",
    size_exposure.EXPERIMENT_ID: "COMPLETED",
    residual.EXPERIMENT_ID: "COMPLETED",
    turnover.EXPERIMENT_ID: (
        "LOWER_TURNOVER_ADVANTAGE_STATISTICALLY_SUPPORTED"
    ),
    capacity.EXPERIMENT_ID: (
        "CURRENT_CAPACITY_RECOVERED_BUT_HISTORICAL_BIAS"
    ),
    post_capacity.EXPERIMENT_ID: "POST_CAPACITY_EVIDENCE_PASSED",
    alternative.EXPERIMENT_ID: "REJECTED",
    premium_common.EXPERIMENT_ID: (
        "SYSTEM_WIDE_NASDAQ100_QDII_PREMIUM_REGIME"
    ),
    premium.EXPERIMENT_ID: "RISK_FLAGGED",
    sp500.EXPERIMENT_ID: "PASSED_FEASIBILITY",
    sp500_equivalence.EXPERIMENT_ID: "INSTRUMENT_RETURN_EQUIVALENCE_FAILED",
    sp500_attribution.EXPERIMENT_ID: (
        "PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE"
    ),
    sp500_normalization.EXPERIMENT_ID: (
        "CONTROL_PREMIUM_NORMALIZATION_RISK_CANDIDATE_CURRENTLY_LOWER"
    ),
    sp500_robustness.EXPERIMENT_ID: (
        "NORMALIZATION_RISK_ROBUST_TO_OVERLAP_CONTROL"
    ),
    sp500_gold_vol.EXPERIMENT_ID: "REJECTED",
    sp500_gold_failure.EXPERIMENT_ID: "CONCENTRATED_BORDERLINE_REJECTION",
    sp500_gold_statistics.EXPERIMENT_ID: "INCONCLUSIVE",
    trend.EXPERIMENT_ID: "REJECTED",
    trend_failure.EXPERIMENT_ID: "LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE",
    activity_data.EXPERIMENT_ID: "PASSED_FEASIBILITY",
    activity.STRATEGY_ID: "REJECTED",
    activity_failure.EXPERIMENT_ID: (
        "BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE"
    ),
    intraday.EXPERIMENT_ID: (
        "ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT"
    ),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="2026-07-29策略研究决策备忘录 V1",
    category="research_governance",
    hypothesis=(
        "将批次门禁、A股因子衰减、换手统计、容量恢复与当前QDII溢价放在"
        "同一决策链后，是否存在足够证据晋级新策略或修改生产配置"
    ),
    definition={
        "dependencies": DEPENDENCIES,
        "reads_repository_metrics_only": True,
        "does_not_recompute_returns": True,
        "does_not_modify_strategy_or_scheduler": True,
        "decision_rules": {
            "new_strategy_requires_campaign_promotion": True,
            "execution_risk_blocks_trade_readiness": True,
            "post_capacity_evidence_does_not_rehabilitate_early_history": True,
            "lower_turnover_does_not_establish_alpha": True,
        },
        "promotion_scope": "decision_memo_only",
        "methodology_version": "evidence_chain_memo_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        metrics = load_dependencies(paths)
        result = calculate(metrics, paths, as_of_date)
        complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_dependencies(
    paths: RuntimePaths,
) -> dict[str, dict[str, Any]]:
    repository = SystemRepository(paths.system_state_path)
    loaded: dict[str, dict[str, Any]] = {}
    for experiment_id, expected_outcome in DEPENDENCIES.items():
        detail = repository.load_experiment_detail(experiment_id)
        latest = detail.get("latest_run") if detail else None
        if not latest or latest.get("status") != "SUCCESS":
            raise RuntimeError(f"决策备忘录依赖未成功: {experiment_id}")
        if latest.get("outcome") != expected_outcome:
            raise RuntimeError(
                f"决策备忘录依赖结论不符: "
                f"{experiment_id}={latest.get('outcome')}"
            )
        loaded[experiment_id] = dict(latest.get("metrics") or {})
    return loaded


def calculate(
    metrics: dict[str, dict[str, Any]],
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, Any]:
    campaign_metrics = metrics[campaign.EXPERIMENT_ID]
    factor_metrics = metrics[factor_meta.EXPERIMENT_ID]
    common_metrics = metrics[common_mode.EXPERIMENT_ID]
    size_metrics = metrics[size_exposure.EXPERIMENT_ID]
    residual_metrics = metrics[residual.EXPERIMENT_ID]
    turnover_metrics = metrics[turnover.EXPERIMENT_ID]
    capacity_metrics = metrics[capacity.EXPERIMENT_ID]
    post_metrics = metrics[post_capacity.EXPERIMENT_ID]
    alternative_metrics = metrics[alternative.EXPERIMENT_ID]
    premium_common_metrics = metrics[premium_common.EXPERIMENT_ID]
    premium_metrics = metrics[premium.EXPERIMENT_ID]
    sp500_metrics = metrics[sp500.EXPERIMENT_ID]
    sp500_equivalence_metrics = metrics[sp500_equivalence.EXPERIMENT_ID]
    sp500_attribution_metrics = metrics[sp500_attribution.EXPERIMENT_ID]
    sp500_normalization_metrics = metrics[sp500_normalization.EXPERIMENT_ID]
    sp500_robustness_metrics = metrics[sp500_robustness.EXPERIMENT_ID]
    sp500_gold_metrics = metrics[sp500_gold_vol.EXPERIMENT_ID]
    sp500_gold_failure_metrics = metrics[sp500_gold_failure.EXPERIMENT_ID]
    sp500_gold_statistics_metrics = metrics[sp500_gold_statistics.EXPERIMENT_ID]
    trend_metrics = metrics[trend.EXPERIMENT_ID]
    trend_failure_metrics = metrics[trend_failure.EXPERIMENT_ID]
    activity_data_metrics = metrics[activity_data.EXPERIMENT_ID]
    activity_metrics = metrics[activity.STRATEGY_ID]
    activity_failure_metrics = metrics[activity_failure.EXPERIMENT_ID]
    intraday_metrics = metrics[intraday.EXPERIMENT_ID]
    nasdaq_premium = premium_metrics["summaries"]["159941.SZ"]
    checks = {
        "campaign_has_zero_new_strategy_promotions": (
            campaign_metrics["strategy_promotion_count"] == 0
        ),
        "campaign_current_execution_risks_open": bool(
            campaign_metrics["risk_flagged_audit_ids"]
        ),
        "no_factor_family_passes_locked_core_gate": (
            factor_metrics["summary"]["locked_core_pass_count"] == 0
        ),
        "midcap_common_mode_confirmed": (
            common_metrics["decision"]
            == "FACTOR_ZOO_MIDCAP_COMMON_MODE_CONFIRMED"
        ),
        "holdings_support_midcap_exposure": (
            size_metrics["decision"]
            == "REPRESENTATIVE_HOLDINGS_SUPPORT_MIDCAP_EXPOSURE"
        ),
        "no_factor_passes_style_residual_gate": (
            residual_metrics["summary"]["gate_pass_count"] == 0
        ),
        "lower_turnover_does_not_establish_alpha": (
            turnover_metrics["establishes_alpha"] is False
        ),
        "capacity_recovery_does_not_remove_historical_bias": (
            capacity_metrics["source_capacity_outcome_unchanged"]
            == "RISK_FLAGGED"
        ),
        "current_nasdaq_premium_exceeds_10pct": (
            nasdaq_premium["latest_premium"] > 0.10
        ),
        "no_execution_feasible_nasdaq100_alternative": (
            alternative_metrics["eligible_count"] == 0
        ),
        "nasdaq100_premium_is_cross_fund_common_mode": (
            premium_common_metrics["classification"]
            == "SYSTEM_WIDE_NASDAQ100_QDII_PREMIUM_REGIME"
        ),
        "sp500_has_one_currently_feasible_instrument": (
            sp500_metrics["eligible_count"] == 1
            and sp500_metrics["eligible_symbols"] == ["513650.SH"]
        ),
        "sp500_candidate_is_not_treated_as_equivalent_replacement": (
            sp500_equivalence_metrics["classification"]
            == "INSTRUMENT_RETURN_EQUIVALENCE_FAILED"
            and sp500_equivalence_metrics["control_replacement_authorized"]
            is False
        ),
        "sp500_price_divergence_is_attributed_without_authorizing_replacement": (
            sp500_attribution_metrics["classification"]
            == "PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE"
            and sp500_attribution_metrics["instrument_substitution_authorized"]
            is False
        ),
        "sp500_high_premium_normalization_risk_is_preserved": (
            sp500_normalization_metrics["classification"].startswith(
                "CONTROL_PREMIUM_NORMALIZATION_RISK"
            )
            and sp500_normalization_metrics[
                "instrument_substitution_authorized"
            ]
            is False
        ),
        "sp500_normalization_risk_survives_overlap_controls": (
            sp500_robustness_metrics["classification"]
            == "NORMALIZATION_RISK_ROBUST_TO_OVERLAP_CONTROL"
            and sp500_robustness_metrics["trading_signal_defined"] is False
        ),
        "sp500_gold_borderline_candidate_remains_rejected": (
            sp500_gold_metrics["decision"] == "REJECTED"
            and sp500_gold_failure_metrics["classification"]
            == "CONCENTRATED_BORDERLINE_REJECTION"
            and sp500_gold_failure_metrics["source_rejection_overridden"]
            is False
        ),
        "sp500_gold_statistics_do_not_override_rejection": (
            sp500_gold_statistics_metrics["classification"] == "INCONCLUSIVE"
            and sp500_gold_statistics_metrics["source_rejection_overridden"]
            is False
        ),
        "independent_trend_is_blocked_before_backtest_by_local_data_gap": (
            trend_metrics["decision"] == "REJECTED_BEFORE_BACKTEST"
            and trend_failure_metrics["classification"]
            == "LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE"
            and trend_failure_metrics["strategy_backtest_run"] is False
        ),
        "trading_activity_strategy_is_robustly_closed_without_variants": (
            activity_data_metrics["passed"] is True
            and activity_metrics["gate"]["passed"] is False
            and activity_failure_metrics["classification"]
            == "BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE"
            and activity_failure_metrics["variants_run"] is False
        ),
        "intraday_candidate_robustly_rejected": (
            intraday_metrics["classification"].startswith(
                "ROBUST_ECONOMIC_SIGN_FAILURE"
            )
        ),
    }
    decision = (
        "KEEP_PRODUCTION_UNCHANGED_NO_NEW_STRATEGY"
        if all(checks.values())
        else "MANUAL_EVIDENCE_REVIEW_REQUIRED"
    )
    return {
        "as_of_date": as_of_date,
        "campaign": {
            "experiment_count": campaign_metrics["experiment_count"],
            "strategy_candidate_count": (
                campaign_metrics["strategy_candidate_count"]
            ),
            "strategy_promotion_count": (
                campaign_metrics["strategy_promotion_count"]
            ),
            "risk_flagged_audit_ids": (
                campaign_metrics["risk_flagged_audit_ids"]
            ),
        },
        "a_share_factor_meta": {
            "family_count": int(
                factor_metrics["summary"]["experiment_count"]
            ),
            "validation_positive_ratio": (
                factor_metrics["summary"]["validation_positive_ratio"]
            ),
            "locked_positive_ratio": (
                factor_metrics["summary"]["locked_positive_ratio"]
            ),
            "validation_false_discovery_ratio": (
                factor_metrics["summary"][
                    "validation_false_discovery_ratio"
                ]
            ),
            "locked_core_pass_count": int(
                factor_metrics["summary"]["locked_core_pass_count"]
            ),
            "midcap_common_mode_r_squared": (
                common_metrics["style_attribution"][
                    "csi500_spread_regression"
                ]["r_squared"]
            ),
            "high_vs_low_group_bottom_half_share_gap": (
                size_metrics["group_comparison"][
                    "high_minus_low_bottom_half_share"
                ]
            ),
            "style_residual_gate_pass_count": int(
                residual_metrics["summary"]["gate_pass_count"]
            ),
        },
        "turnover_evidence": {
            "median_locked_return_advantage": (
                turnover_metrics["original_median_difference"]
            ),
            "bootstrap_positive_probability": (
                turnover_metrics["bootstrap"][
                    "probability_positive_difference"
                ]
            ),
            "permutation_pvalue": (
                turnover_metrics["permutation"]["one_sided_pvalue"]
            ),
            "establishes_alpha": turnover_metrics["establishes_alpha"],
        },
        "nasdaq_gold_evidence": {
            "capacity_recovery_date": (
                capacity_metrics["nasdaq_persistent_recovery_date"]
            ),
            "post_capacity_return_lift_vs_sp500": (
                post_metrics["original"]["return_lift"]
            ),
            "post_capacity_drawdown_improvement_vs_sp500": (
                post_metrics["original"]["drawdown_improvement"]
            ),
            "nasdaq_latest_premium": nasdaq_premium["latest_premium"],
            "nasdaq_two_month_median_premium": (
                nasdaq_premium["median_premium"]
            ),
            "weighted_full_normalization_shock": (
                premium_metrics["weighted_full_normalization_shock"]
            ),
            "alternative_etf_count": (
                alternative_metrics["candidate_count"]
            ),
            "eligible_alternative_count": (
                alternative_metrics["eligible_count"]
            ),
            "cross_fund_median_premium": (
                premium_common_metrics["median_premium"]
            ),
            "cross_fund_share_above_5pct": (
                premium_common_metrics["share_above_5pct_premium"]
            ),
        },
        "intraday_candidate": {
            "full_return": intraday_metrics["period_returns"]["full"],
            "full_drawdown": intraday_metrics["full_max_drawdown"],
            "classification": intraday_metrics["classification"],
        },
        "sp500_execution_evidence": {
            "eligible_count": sp500_metrics["eligible_count"],
            "eligible_symbol": sp500_metrics["eligible_symbols"][0],
            "eligible_latest_premium": next(
                item["latest_premium"]
                for item in sp500_metrics["candidates"]
                if item["symbol"] == sp500_metrics["eligible_symbols"][0]
            ),
            "common_days": sp500_equivalence_metrics["common_days"],
            "daily_return_correlation": (
                sp500_equivalence_metrics["daily_return_correlation"]
            ),
            "beta_vs_513500": sp500_equivalence_metrics["beta_vs_513500"],
            "cumulative_return_difference": (
                sp500_equivalence_metrics["cumulative_return_difference"]
            ),
            "classification": sp500_equivalence_metrics["classification"],
            "replacement_authorized": (
                sp500_equivalence_metrics["control_replacement_authorized"]
            ),
            "unit_nav_return_correlation": (
                sp500_attribution_metrics["unit_nav_return_correlation"]
            ),
            "unit_nav_beta_vs_513500": (
                sp500_attribution_metrics["unit_nav_beta_vs_513500"]
            ),
            "unit_nav_tracking_error": (
                sp500_attribution_metrics[
                    "unit_nav_annualized_tracking_error"
                ]
            ),
            "active_price_vs_premium_effect_correlation": (
                sp500_attribution_metrics[
                    "active_price_vs_active_premium_effect_correlation"
                ]
            ),
            "candidate_latest_premium_history_percentile": (
                sp500_normalization_metrics["summaries"]["513650.SH"][
                    "latest_premium_history_percentile"
                ]
            ),
            "control_high_premium_forward_effect_median": (
                sp500_normalization_metrics["summaries"]["513500.SH"][
                    "high_premium_median_forward_effect"
                ]
            ),
            "control_high_premium_negative_effect_probability": (
                sp500_normalization_metrics["summaries"]["513500.SH"][
                    "high_premium_negative_effect_probability"
                ]
            ),
            "cluster_bootstrap_negative_probability": (
                sp500_robustness_metrics[
                    "bootstrap_probability_cluster_median_negative"
                ]
            ),
            "non_overlapping_event_count": (
                sp500_robustness_metrics["non_overlapping_event_count"]
            ),
            "non_overlapping_median_effect": (
                sp500_robustness_metrics[
                    "non_overlapping_median_forward_effect"
                ]
            ),
            "non_overlapping_negative_probability": (
                sp500_robustness_metrics[
                    "non_overlapping_negative_effect_probability"
                ]
            ),
        },
        "sp500_gold_vol_target_candidate": {
            "decision": sp500_gold_metrics["decision"],
            "oos_annualized_return": (
                sp500_gold_failure_metrics["oos_annualized_return"]
            ),
            "oos_sharpe": sp500_gold_failure_metrics["oos_sharpe"],
            "oos_max_drawdown": (
                sp500_gold_failure_metrics["oos_max_drawdown"]
            ),
            "drawdown_shortfall": (
                sp500_gold_failure_metrics["drawdown_shortfall"]
            ),
            "oos_annual_turnover": (
                sp500_gold_failure_metrics["oos_annual_turnover"]
            ),
            "turnover_excess": sp500_gold_failure_metrics["turnover_excess"],
            "return_lift_vs_same_mechanism_control": (
                sp500_gold_failure_metrics[
                    "return_lift_vs_same_mechanism_control"
                ]
            ),
            "classification": sp500_gold_failure_metrics["classification"],
            "return_lift_probability": (
                sp500_gold_statistics_metrics["bootstrap"]["probabilities"][
                    "return_lift_at_least_1pct"
                ]
            ),
            "sharpe_lift_probability": (
                sp500_gold_statistics_metrics["bootstrap"]["probabilities"][
                    "sharpe_lift_at_least_010"
                ]
            ),
            "drawdown_improvement_probability": (
                sp500_gold_statistics_metrics["bootstrap"]["probabilities"][
                    "drawdown_improvement_positive"
                ]
            ),
            "rolling_positive_return_lift_share": (
                sp500_gold_statistics_metrics["rolling_756d"][
                    "positive_return_lift_share"
                ]
            ),
            "statistical_classification": (
                sp500_gold_statistics_metrics["classification"]
            ),
        },
        "independent_trend_feasibility": {
            "decision": trend_metrics["decision"],
            "failed_checks": trend_failure_metrics["failed_source_checks"],
            "local_missing_row_count": (
                trend_failure_metrics["local_missing_row_count"]
            ),
            "local_missing_dates_by_symbol": (
                trend_failure_metrics["local_missing_dates_by_symbol"]
            ),
            "classification": trend_failure_metrics["classification"],
            "strategy_backtest_run": (
                trend_failure_metrics["strategy_backtest_run"]
            ),
        },
        "trading_activity_stability_candidate": {
            "feasibility_passed": activity_data_metrics["passed"],
            "decision": activity_failure_metrics["source_decision"],
            "full_annualized_return": (
                activity_failure_metrics["full_annualized_return"]
            ),
            "full_sharpe": activity_failure_metrics["full_sharpe"],
            "full_max_drawdown": (
                activity_failure_metrics["full_max_drawdown"]
            ),
            "full_annual_turnover": (
                activity_failure_metrics["full_annual_turnover"]
            ),
            "full_execution_cost_impact": (
                activity_failure_metrics["full_execution_cost_impact"]
            ),
            "recent_fold_annualized_return": (
                activity_failure_metrics["recent_fold_annualized_return"]
            ),
            "latest_year_annualized_return": (
                activity_failure_metrics["latest_year_annualized_return"]
            ),
            "quality_return_correlation": (
                activity_failure_metrics["quality_return_correlation"]
            ),
            "classification": activity_failure_metrics["classification"],
            "variants_run": activity_failure_metrics["variants_run"],
        },
        "checks": checks,
        "decision": decision,
        "production_modified": False,
        "scheduler_modified": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "decision_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            "本轮无新策略晋级，且当前QDII溢价与历史容量风险阻止交易就绪"
            if result["decision"].startswith("KEEP_")
            else "证据链不完整，需要人工复核"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "研究决策备忘录"),
            ExperimentArtifact("metrics", metrics_path, "决策证据指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    campaign_result = result["campaign"]
    factors = result["a_share_factor_meta"]
    turnover_result = result["turnover_evidence"]
    nasdaq = result["nasdaq_gold_evidence"]
    intraday_result = result["intraday_candidate"]
    sp500_result = result["sp500_execution_evidence"]
    sp500_gold = result["sp500_gold_vol_target_candidate"]
    trend_result = result["independent_trend_feasibility"]
    activity_result = result["trading_activity_stability_candidate"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 2026-07-29策略研究决策备忘录 V1

## 决策

`{result['decision']}`

- 生产策略未修改；scheduler未修改。
- 批次共 {campaign_result['experiment_count']} 项，其中策略候选
  {campaign_result['strategy_candidate_count']} 个，新增晋级
  {campaign_result['strategy_promotion_count']} 个。

## A股因子证据

- 31个家族验证期正收益比例：
  {factors['validation_positive_ratio']:.1%}；锁定期：
  {factors['locked_positive_ratio']:.1%}。
- 验证期核心通过者的锁定失效率：
  {factors['validation_false_discovery_ratio']:.1%}；锁定核心通过：
  {factors['locked_core_pass_count']}。
- 中证500相对沪深300价差对共同超额的解释度：
  {factors['midcap_common_mode_r_squared']:.1%}；高相关组相对低相关组的
  持仓底部半数占比差：
  {factors['high_vs_low_group_bottom_half_share_gap']:.1%}。
- 剥离中盘风格后的走步残差门槛通过：
  {factors['style_residual_gate_pass_count']}。
- 低换手相对高换手的锁定收益中位优势：
  {turnover_result['median_locked_return_advantage']:.2%}；
  Bootstrap为正概率：
  {turnover_result['bootstrap_positive_probability']:.1%}；
  置换p值：{turnover_result['permutation_pvalue']:.4f}。
- 低换手优势不建立Alpha：
  {not turnover_result['establishes_alpha']}。

## 纳指黄金与执行风险

- 159941容量持续恢复起点：
  {nasdaq['capacity_recovery_date']}。
- 容量恢复后相对场内标普年化收益差：
  {nasdaq['post_capacity_return_lift_vs_sp500']:.2%}；
  回撤改善：{nasdaq['post_capacity_drawdown_improvement_vs_sp500']:.2%}。
- 159941最新同日净值溢价：
  {nasdaq['nasdaq_latest_premium']:.2%}；
  两个月中位：{nasdaq['nasdaq_two_month_median_premium']:.2%}。
- 按组合60%权重完全归一化冲击：
  {nasdaq['weighted_full_normalization_shock']:.2%}。
- 境内同标的ETF扫描：{nasdaq['alternative_etf_count']}只；
  当前执行门槛通过：{nasdaq['eligible_alternative_count']}只；
  横截面溢价中位：{nasdaq['cross_fund_median_premium']:.2%}，
  超过5%占比：{nasdaq['cross_fund_share_above_5pct']:.1%}。

## 新候选结果

- 日内强度减隔夜情绪全期年化：
  {intraday_result['full_return']:.2%}；
  回撤：{intraday_result['full_drawdown']:.2%}。
- 分类：`{intraday_result['classification']}`。

## 标普500场内执行证据

- 当前执行门槛通过：{sp500_result['eligible_count']}只，即
  `{sp500_result['eligible_symbol']}`；最新同日净值溢价：
  {sp500_result['eligible_latest_premium']:.2%}。
- 与513500在{sp500_result['common_days']}个共同交易日的日收益相关：
  {sp500_result['daily_return_correlation']:.4f}；Beta：
  {sp500_result['beta_vs_513500']:.4f}；累计收益差：
  {sp500_result['cumulative_return_difference']:.2%}。
- 等价性分类：`{sp500_result['classification']}`；允许替换：
  {sp500_result['replacement_authorized']}。
- 单位净值日收益相关：
  {sp500_result['unit_nav_return_correlation']:.4f}；净值Beta：
  {sp500_result['unit_nav_beta_vs_513500']:.4f}；净值年化跟踪误差：
  {sp500_result['unit_nav_tracking_error']:.2%}。
- 场内主动收益与溢价变化差相关：
  {sp500_result['active_price_vs_premium_effect_correlation']:.4f}；
  说明底层净值高度一致，但场内溢价路径仍使直接替换不成立。
- 513650当前溢价处于自身历史分位：
  {sp500_result['candidate_latest_premium_history_percentile']:.1%}。
- 513500历史溢价至少5%时，未来20日溢价效应中位：
  {sp500_result['control_high_premium_forward_effect_median']:.2%}；
  负效应概率：
  {sp500_result['control_high_premium_negative_effect_probability']:.1%}。
- 月度聚类Bootstrap中位为负概率：
  {sp500_result['cluster_bootstrap_negative_probability']:.1%}；
  {sp500_result['non_overlapping_event_count']}个非重叠事件中位效应：
  {sp500_result['non_overlapping_median_effect']:.2%}，负效应频率：
  {sp500_result['non_overlapping_negative_probability']:.1%}。

## 标普黄金波动目标候选

- OOS年化/Sharpe/回撤：
  {sp500_gold['oos_annualized_return']:.2%} /
  {sp500_gold['oos_sharpe']:.3f} /
  {sp500_gold['oos_max_drawdown']:.2%}。
- 相对同波动目标标普收益提升：
  {sp500_gold['return_lift_vs_same_mechanism_control']:.2%}。
- 回撤门槛短缺：{sp500_gold['drawdown_shortfall']:.2%}；
  年换手：{sp500_gold['oos_annual_turnover']:.2f}x，超限：
  {sp500_gold['turnover_excess']:.2f}x。
- 分类：`{sp500_gold['classification']}`；来源决策：
  `{sp500_gold['decision']}`，不晋级。
- Bootstrap收益/Sharpe/回撤优势概率：
  {sp500_gold['return_lift_probability']:.1%} /
  {sp500_gold['sharpe_lift_probability']:.1%} /
  {sp500_gold['drawdown_improvement_probability']:.1%}；
  滚动三年收益提升为正占比：
  {sp500_gold['rolling_positive_return_lift_share']:.1%}。
- 统计分类：`{sp500_gold['statistical_classification']}`。

## 五资产独立趋势方向

- 数据门禁决策：`{trend_result['decision']}`；分类：
  `{trend_result['classification']}`。
- 本地增量缺失：{trend_result['local_missing_row_count']}行；
  {trend_result['local_missing_dates_by_symbol']}。
- 策略回测已运行：{trend_result['strategy_backtest_run']}。

## 交易活跃度稳定性因子

- 数据门禁通过：{activity_result['feasibility_passed']}；策略决策：
  `{activity_result['decision']}`。
- 全期年化/Sharpe/回撤：
  {activity_result['full_annualized_return']:.2%} /
  {activity_result['full_sharpe']:.3f} /
  {activity_result['full_max_drawdown']:.2%}。
- 年换手/累计成本影响：
  {activity_result['full_annual_turnover']:.2f}x /
  {activity_result['full_execution_cost_impact']:.2%}。
- 2024至今/最新年年化：
  {activity_result['recent_fold_annualized_return']:.2%} /
  {activity_result['latest_year_annualized_return']:.2%}；
  与质量策略相关：{activity_result['quality_return_correlation']:.4f}。
- 分类：`{activity_result['classification']}`；运行变体：
  {activity_result['variants_run']}。

## 决策链检查

{checks}

本备忘录只汇总已登记的结构化研究证据，不重算收益、不调整策略、
不启停scheduler，也不构成实盘下单指令。
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
