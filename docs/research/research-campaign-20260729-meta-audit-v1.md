# 2026-07-29 新策略研究批次元审计 V1

- 实验总数：17
- 策略/组合候选：9
- 新晋级策略：0
- 批次结论：`NO_NEW_STRATEGY_PROMOTION`

| 类别 | 实验 | 结论 | 状态 | 本机产物 |
|---|---|---|---|---|
| allocation_strategy | `nasdaq_gold_china_dividend_equal_v1` | REJECTED | SUCCESS | PASS |
| allocation_strategy | `china_tech_dividend_gold_equal_v1` | REJECTED | SUCCESS | PASS |
| allocation_strategy | `nasdaq_gold_bond_balanced_50_25_25_v1` | REJECTED | SUCCESS | PASS |
| allocation_strategy | `limit_event_sentiment_defensive_allocation_v1` | REJECTED | SUCCESS | PASS |
| event_strategy | `limit_up_first_board_seal_strength_v1` | REJECTED | SUCCESS | PASS |
| event_strategy | `limit_up_first_board_open_executable_v1` | REJECTED | SUCCESS | PASS |
| event_strategy | `limit_down_weak_seal_weekly_reversal_v1` | REJECTED | SUCCESS | PASS |
| factor_strategy | `margin_financing_flow_v1` | REJECTED | SUCCESS | PASS |
| portfolio_strategy | `global_defensive_margin_flow_satellite_90_10_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `limit_up_first_board_event_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `limit_down_weekly_reversal_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| feasibility | `a_share_ma60_breadth_regime_data_feasibility_v1` | REJECTED | SUCCESS | PASS |
| feasibility | `limit_event_five_day_sentiment_data_feasibility_v1` | PASSED_FEASIBILITY | SUCCESS | PASS |
| audit | `borderline_allocation_correlation_audit_v2` | COMPLETED | SUCCESS | PASS |
| audit | `limit_up_first_board_execution_assumption_audit_v1` | PASSED_EXECUTION_AUDIT | SUCCESS | PASS |
| audit | `global_defensive_mainline_satellite_robustness_v1` | REJECTED | SUCCESS | PASS |
| audit | `global_defensive_margin_flow_correlation_audit_v1` | ROBUST_CORRELATION_FAILURE | SUCCESS | PASS |

## 一致性检查

- PASS `all_latest_runs_success`
- PASS `all_output_directories_exist`
- PASS `all_registered_artifacts_exist`
- PASS `no_latest_artifact_uses_legacy_admin_path`

## 结论

本批次没有新策略通过全部冻结门槛。通过的数据可行性和执行审计只允许继续研究，
不能等同于策略晋级；所有拒绝结果保持归档，不修改生产策略或调度。
