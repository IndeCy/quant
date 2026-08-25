# 2026-07-29研究批次最终元审计 V3

- 实验总数：71。
- 策略候选：20；晋级：
  0。
- 当前执行风险：nasdaq_gold_60_40_capacity_execution_audit_v1, qdii_current_nav_monitoring_audit_v1, qdii_current_premium_window_audit_v2。
- 决策：`NO_NEW_STRATEGY_PROMOTION_CURRENT_EXECUTION_RISKS_OPEN`。

## 一致性门槛

- PASS：all_latest_runs_success
- PASS：all_output_directories_exist
- PASS：all_registered_artifacts_exist
- PASS：no_latest_artifact_uses_legacy_admin_path
- PASS：only_strategy_group_counted_as_promotion
- PASS：current_execution_risk_flags_preserved

| 分组 | 实验 | 结论 | 状态 | 产物/路径 |
|---|---|---|---|---|
| strategy | `nasdaq_trend_gold_bond_switch_v1` | REJECTED | SUCCESS | PASS |
| strategy | `a_share_tech_etf_weekly_relative_strength_v1` | REJECTED | SUCCESS | PASS |
| strategy | `nasdaq_gold_china_dividend_equal_v1` | REJECTED | SUCCESS | PASS |
| strategy | `china_tech_dividend_gold_equal_v1` | REJECTED | SUCCESS | PASS |
| strategy | `nasdaq_gold_bond_balanced_50_25_25_v1` | REJECTED | SUCCESS | PASS |
| strategy | `limit_up_first_board_seal_strength_v1` | REJECTED | SUCCESS | PASS |
| strategy | `limit_up_first_board_open_executable_v1` | REJECTED | SUCCESS | PASS |
| strategy | `margin_financing_flow_v1` | REJECTED | SUCCESS | PASS |
| strategy | `limit_down_weak_seal_weekly_reversal_v1` | REJECTED | SUCCESS | PASS |
| strategy | `limit_event_sentiment_defensive_allocation_v1` | REJECTED | SUCCESS | PASS |
| strategy | `global_defensive_margin_flow_satellite_90_10_v1` | REJECTED | SUCCESS | PASS |
| strategy | `margin_flow_breadth_defensive_allocation_v1` | REJECTED | SUCCESS | PASS |
| strategy | `global_core_nasdaq_gold_four_asset_50_50_v1` | REJECTED | SUCCESS | PASS |
| strategy | `global_defensive_inverse_volatility_60d_v1` | REJECTED | SUCCESS | PASS |
| strategy | `a_share_tech_etf_weekly_5d_reversal_v1` | REJECTED | SUCCESS | PASS |
| strategy | `global_four_asset_weekly_20d_momentum_top2_v1` | REJECTED | SUCCESS | PASS |
| strategy | `china_semiconductor_gold_bond_equal_v1` | REJECTED | SUCCESS | PASS |
| strategy | `intraday_strength_vs_overnight_20d_v1` | REJECTED | SUCCESS | PASS |
| strategy | `sp500_gold_60_40_vol_target_12_v1` | REJECTED | SUCCESS | PASS |
| strategy | `trading_activity_stability_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `limit_up_first_board_event_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `limit_down_weekly_reversal_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `a_share_ma60_breadth_regime_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `limit_event_five_day_sentiment_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `margin_flow_breadth_regime_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `a_share_etf_weekly_reversal_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `a_share_tech_etf_weekly_reversal_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `a_share_tech_etf_weekly_reversal_liquid_feasibility_v2` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `global_four_asset_weekly_momentum_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `china_dividend_gold_bond_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `global_defensive_china_dividend_90_10_capacity_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `china_semiconductor_gold_bond_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `nasdaq100_domestic_etf_execution_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `sp500_domestic_etf_execution_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `cross_asset_independent_trend_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `trading_activity_stability_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| audit | `borderline_allocation_correlation_audit_v1` | COMPLETED | SUCCESS | PASS |
| audit | `borderline_allocation_correlation_audit_v2` | COMPLETED | SUCCESS | PASS |
| audit | `limit_up_first_board_execution_assumption_audit_v1` | PASSED_EXECUTION_AUDIT | SUCCESS | PASS |
| audit | `global_defensive_mainline_satellite_robustness_v1` | REJECTED | SUCCESS | PASS |
| audit | `global_defensive_margin_flow_correlation_audit_v1` | ROBUST_CORRELATION_FAILURE | SUCCESS | PASS |
| audit | `global_core_four_asset_sp500_opportunity_audit_v1` | INCONCLUSIVE | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_qdii_premium_audit_v1` | PASSED_EXECUTION_AUDIT | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_qdii_premium_corporate_action_audit_v2` | PASSED_EXECUTION_AUDIT | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_sp500_statistical_dominance_audit_v1` | INCONCLUSIVE | SUCCESS | PASS |
| audit | `china_semiconductor_gold_bond_failure_audit_v1` | INCONCLUSIVE | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_capacity_execution_audit_v1` | RISK_FLAGGED | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_capacity_failure_attribution_audit_v1` | CURRENT_CAPACITY_RECOVERED_BUT_HISTORICAL_BIAS | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_post_capacity_recovery_audit_v1` | POST_CAPACITY_EVIDENCE_PASSED | SUCCESS | PASS |
| audit | `nasdaq_gold_60_40_sp500_capacity_comparison_audit_v1` | PASSED_EXECUTION_AUDIT | SUCCESS | PASS |
| audit | `qdii_current_nav_monitoring_audit_v1` | RISK_FLAGGED | SUCCESS | PASS |
| audit | `qdii_current_premium_window_audit_v2` | RISK_FLAGGED | SUCCESS | PASS |
| audit | `intraday_strength_failure_attribution_audit_v1` | ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT | SUCCESS | PASS |
| audit | `nasdaq100_etf_premium_common_mode_audit_v1` | SYSTEM_WIDE_NASDAQ100_QDII_PREMIUM_REGIME | SUCCESS | PASS |
| audit | `sp500_etf_513650_513500_instrument_equivalence_audit_v1` | INSTRUMENT_RETURN_EQUIVALENCE_FAILED | SUCCESS | PASS |
| audit | `sp500_etf_premium_tracking_attribution_audit_v1` | PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE | SUCCESS | PASS |
| audit | `sp500_etf_premium_normalization_risk_audit_v1` | CONTROL_PREMIUM_NORMALIZATION_RISK_CANDIDATE_CURRENTLY_LOWER | SUCCESS | PASS |
| audit | `sp500_premium_normalization_robustness_audit_v1` | NORMALIZATION_RISK_ROBUST_TO_OVERLAP_CONTROL | SUCCESS | PASS |
| audit | `sp500_gold_vol_target_failure_attribution_audit_v1` | CONCENTRATED_BORDERLINE_REJECTION | SUCCESS | PASS |
| audit | `sp500_gold_vol_target_statistical_audit_v1` | INCONCLUSIVE | SUCCESS | PASS |
| audit | `cross_asset_independent_trend_feasibility_failure_audit_v1` | LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE | SUCCESS | PASS |
| audit | `trading_activity_stability_failure_attribution_audit_v1` | BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE | SUCCESS | PASS |
| governance | `research_campaign_20260729_meta_audit_v1` | PASSED_GOVERNANCE_AUDIT | SUCCESS | PASS |
| governance | `research_campaign_20260729_meta_audit_v2` | PASSED_GOVERNANCE_AUDIT | SUCCESS | PASS |
| governance | `factor_research_meta_audit_v1` | COMPLETED | SUCCESS | PASS |
| governance | `a_share_factor_turnover_regime_audit_v1` | LOWER_TURNOVER_HELPS_BUT_IS_NOT_SUFFICIENT | SUCCESS | PASS |
| governance | `a_share_factor_turnover_statistical_audit_v1` | LOWER_TURNOVER_ADVANTAGE_STATISTICALLY_SUPPORTED | SUCCESS | PASS |
| governance | `factor_zoo_common_mode_attribution_v1` | COMPLETED | SUCCESS | PASS |
| governance | `factor_zoo_holdings_size_attribution_v1` | COMPLETED | SUCCESS | PASS |
| governance | `factor_zoo_walk_forward_midcap_residual_v1` | COMPLETED | SUCCESS | PASS |
| governance | `research_campaign_20260729_decision_memo_v1` | COMPLETED | SUCCESS | PASS |
