# 全球防守三资产等权鲁棒性 V1

- 数据截止：20260728
- 所有压力场景在读取行情前冻结，不做事后择优。

| 场景 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| baseline_monthly_5bps | 9.89% | -12.97% | 1.204 | 0.35x |
| sp500_40_gold30_bond30 | 10.38% | -13.77% | 1.172 | 0.35x |
| sp500_30_gold40_bond30 | 10.06% | -14.31% | 1.184 | 0.36x |
| sp500_30_gold30_bond40 | 9.19% | -11.71% | 1.237 | 0.34x |
| cost_20bps | 9.82% | -12.98% | 1.196 | 0.35x |
| quarterly_5bps | 10.11% | -13.09% | 1.215 | 0.22x |
| execution_t2_5bps | 9.92% | -12.44% | 1.210 | 0.36x |

## 冻结门槛

- PASS：baseline_research_gate_passed
- PASS：cost_20bps_return_at_least_8pct
- PASS：cost_20bps_sharpe_at_least_090
- PASS：quarterly_return_at_least_8pct
- PASS：quarterly_drawdown_within_18pct
- PASS：quarterly_sharpe_at_least_090
- PASS：t2_return_at_least_8pct
- PASS：t2_drawdown_within_18pct
- PASS：t2_sharpe_at_least_090
- PASS：all_neighborhood_returns_at_least_8pct
- PASS：all_neighborhood_drawdowns_within_20pct
- PASS：all_neighborhood_sharpes_at_least_090
- PASS：all_neighborhoods_have_three_positive_folds

结论：ROBUSTNESS_PASSED_CONTINUE_FORWARD_OBSERVATION。
