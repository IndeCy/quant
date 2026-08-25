# 2026-07-29 完整研究批次元审计 V2

- 实验总数：40
- 策略候选：17
- 新晋级策略：0
- 批次结论：`NO_NEW_STRATEGY_PROMOTION`

| 分组 | 实验 | 结论 | 状态 | 本机产物 |
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
| governance | `research_campaign_20260729_meta_audit_v1` | PASSED_GOVERNANCE_AUDIT | SUCCESS | PASS |

## 一致性检查

- PASS：all_latest_runs_success
- PASS：all_output_directories_exist
- PASS：all_registered_artifacts_exist
- PASS：no_latest_artifact_uses_legacy_admin_path
- PASS：non_strategy_outcomes_not_counted_as_promotion

## 结论

可行性通过只允许进入冻结回测；执行审计通过只说明对应风险在其门槛内；
`INCONCLUSIVE`、`REJECTED`与稳健失败均不计为策略晋级。本轮没有修改生产注册或调度。
