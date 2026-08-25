# 境内纳指100 × 黄金60/40相对标普500鲁棒性 V1

- 数据截止：20260617
- 标的：159941.SZ、518880.SH；机会成本：513500.SH。
- 权重邻域、调仓频率、50bps成本和T+2场景均在读取结果前冻结。
- 使用场内ETF真实复权价格，QDII溢价/折价已包含在513500与159941价格中。

| 场景 | 年化收益 | 对标普提升 | 最大回撤 | 年化波动 | Sharpe |
|---|---:|---:|---:|---:|---:|
| baseline_60_40_monthly_5bps | 22.59% | +4.70% | -21.71% | 16.81% | 1.297 |
| nasdaq55_gold45_monthly_5bps | 22.25% | +4.36% | -20.43% | 16.13% | 1.328 |
| nasdaq65_gold35_monthly_5bps | 22.92% | +5.02% | -22.96% | 17.58% | 1.263 |
| nasdaq60_gold40_quarterly_5bps | 22.87% | +4.97% | -21.65% | 16.92% | 1.303 |
| nasdaq60_gold40_monthly_50bps | 22.40% | +4.50% | -21.72% | 16.80% | 1.288 |
| nasdaq60_gold40_monthly_t2_5bps | 22.86% | +4.97% | -21.71% | 16.79% | 1.312 |
| sp500_direct_robustness_control | 17.89% | +0.00% | -29.67% | 18.71% | 0.974 |

## 冻结门槛

- PASS：source_v2_gate_passed
- PASS：all_scenarios_return_lift_vs_sp500_at_least_05pct
- PASS：all_scenarios_sharpe_lift_vs_sp500_at_least_005
- PASS：all_scenarios_volatility_gap_vs_sp500_within_1pct
- PASS：all_scenarios_drawdown_gap_vs_sp500_within_2pct
- PASS：all_scenarios_have_three_positive_folds

结论：ROBUSTNESS_PASSED_RESEARCH_ONLY。
