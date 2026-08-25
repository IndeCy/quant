# Quality Tradability Extension Study

- 数据截止：20260722
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- 增强只使用既有行情的20日成交额、60日下行波动和最差单日收益。
- Quality主体80%-85%，统一Top20月频、qfq、M0 T+1、5bps和原风险层。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_v1_baseline | validation | 6.22% | -31.87% | 0.419 | 0.195 | 50.47% | 477.14% |
| quality_v1_baseline | locked_test | 22.60% | -16.39% | 1.001 | 1.379 | 16.77% | 591.16% |
| quality_v1_baseline | full | 15.53% | -32.73% | 0.755 | 0.474 | 340.86% | 633.54% |
| quality_liquidity_extension_v1 | validation | -8.36% | -33.71% | -0.334 | -0.248 | 9.18% | 572.82% |
| quality_liquidity_extension_v1 | locked_test | 21.91% | -24.06% | 0.888 | 0.910 | 14.48% | 754.33% |
| quality_liquidity_extension_v1 | full | 10.01% | -36.57% | 0.517 | 0.274 | 131.19% | 710.94% |
| quality_downside_risk_extension_v1 | validation | 5.34% | -30.96% | 0.395 | 0.172 | 47.63% | 657.24% |
| quality_downside_risk_extension_v1 | locked_test | 13.25% | -16.14% | 0.746 | 0.821 | -12.30% | 788.89% |
| quality_downside_risk_extension_v1 | full | 11.23% | -35.87% | 0.630 | 0.313 | 169.04% | 818.49% |
| quality_liquidity_downside_v1 | validation | -3.21% | -32.00% | -0.092 | -0.100 | 22.46% | 641.69% |
| quality_liquidity_downside_v1 | locked_test | 26.93% | -16.93% | 1.214 | 1.590 | 31.37% | 747.71% |
| quality_liquidity_downside_v1 | full | 11.51% | -42.94% | 0.615 | 0.268 | 178.28% | 748.63% |
| quality_liquidity_tail_v1 | validation | -6.73% | -32.07% | -0.294 | -0.210 | 13.25% | 668.73% |
| quality_liquidity_tail_v1 | locked_test | 25.54% | -18.04% | 1.152 | 1.416 | 26.59% | 814.15% |
| quality_liquidity_tail_v1 | full | 10.79% | -33.74% | 0.585 | 0.320 | 155.09% | 789.25% |
| quality_downside_tail_v1 | validation | 1.06% | -30.63% | 0.147 | 0.035 | 34.53% | 766.70% |
| quality_downside_tail_v1 | locked_test | 11.65% | -15.19% | 0.688 | 0.767 | -16.95% | 844.93% |
| quality_downside_tail_v1 | full | 10.54% | -30.63% | 0.608 | 0.344 | 147.06% | 857.85% |

验证集入选：`quality_downside_risk_extension_v1`。

## 锁定测试门槛

- PASS：locked_test_annual_return_at_least_8pct
- PASS：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_25pct
- FAIL：locked_test_positive_excess
- FAIL：locked_test_sharpe_near_quality_v1
- PASS：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：turnover_not_over_quality_v1_125pct

结论：不注册，保留失败指纹。
