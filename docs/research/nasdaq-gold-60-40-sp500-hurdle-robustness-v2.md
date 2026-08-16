# 境内纳指100 × 黄金60/40相对标普500鲁棒性 V2

- 数据截止：20260728
- 标的：159941.SZ、518880.SH；机会成本：513500.SH。
- 权重邻域、调仓频率、50bps成本和T+2场景均在读取结果前冻结。
- 使用场内ETF真实复权价格，QDII溢价/折价已包含在513500与159941价格中。

| 场景 | 年化收益 | 对标普提升 | 最大回撤 | 年化波动 | Sharpe |
|---|---:|---:|---:|---:|---:|
| baseline_60_40_monthly_5bps | 20.79% | +3.80% | -21.71% | 16.83% | 1.208 |
| nasdaq55_gold45_monthly_5bps | 20.50% | +3.50% | -20.43% | 16.16% | 1.236 |
| nasdaq65_gold35_monthly_5bps | 21.08% | +4.08% | -22.96% | 17.60% | 1.176 |
| nasdaq60_gold40_quarterly_5bps | 21.13% | +4.14% | -21.65% | 16.95% | 1.217 |
| nasdaq60_gold40_monthly_50bps | 20.60% | +3.60% | -21.72% | 16.83% | 1.198 |
| nasdaq60_gold40_monthly_t2_5bps | 21.04% | +4.05% | -21.71% | 16.81% | 1.221 |
| sp500_direct_robustness_control | 17.00% | +0.00% | -29.67% | 18.67% | 0.935 |

## 冻结门槛

- PASS：source_v2_gate_passed
- PASS：all_scenarios_return_lift_vs_sp500_at_least_05pct
- PASS：all_scenarios_sharpe_lift_vs_sp500_at_least_005
- PASS：all_scenarios_volatility_gap_vs_sp500_within_1pct
- PASS：all_scenarios_drawdown_gap_vs_sp500_within_2pct
- PASS：all_scenarios_have_three_positive_folds

结论：ROBUSTNESS_PASSED_RESEARCH_ONLY。
