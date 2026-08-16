# Quality Extension Factor Study

- 数据截止：20260722
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- 候选：只在Quality V1上分别增加ROIC、利润率、现金验证、利润成长或营收成长。
- 统一口径：Quality Cleanup、Top20等权、月频、qfq、M0 T+1、5bps及原波动率风险层。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_v1_baseline | validation | 6.22% | -31.87% | 0.419 | 0.195 | 50.47% | 477.14% |
| quality_v1_baseline | locked_test | 22.60% | -16.39% | 1.001 | 1.379 | 16.77% | 591.16% |
| quality_v1_baseline | full | 15.53% | -32.73% | 0.755 | 0.474 | 340.86% | 633.54% |
| quality_roic_extension_v1 | validation | 0.15% | -30.09% | 0.100 | 0.005 | 31.87% | 504.68% |
| quality_roic_extension_v1 | locked_test | 15.08% | -17.97% | 0.728 | 0.839 | -6.88% | 709.57% |
| quality_roic_extension_v1 | full | 8.95% | -50.34% | 0.486 | 0.178 | 101.77% | 638.70% |
| quality_margin_extension_v1 | validation | 5.24% | -25.50% | 0.375 | 0.206 | 47.33% | 439.11% |
| quality_margin_extension_v1 | locked_test | 16.97% | -18.47% | 0.780 | 0.919 | -1.16% | 659.20% |
| quality_margin_extension_v1 | full | 11.13% | -38.98% | 0.575 | 0.286 | 165.92% | 585.66% |
| quality_cash_verification_v1 | validation | 5.42% | -17.67% | 0.383 | 0.307 | 47.88% | 562.15% |
| quality_cash_verification_v1 | locked_test | 12.95% | -19.50% | 0.628 | 0.664 | -13.21% | 666.37% |
| quality_cash_verification_v1 | full | 10.69% | -34.08% | 0.567 | 0.314 | 151.91% | 683.40% |
| quality_profit_growth_v1 | validation | -4.71% | -33.19% | -0.149 | -0.142 | 18.44% | 569.56% |
| quality_profit_growth_v1 | locked_test | 24.32% | -16.94% | 1.054 | 1.436 | 22.47% | 676.09% |
| quality_profit_growth_v1 | full | 6.26% | -61.77% | 0.376 | 0.101 | 38.56% | 796.92% |
| quality_revenue_growth_v1 | validation | 5.43% | -32.70% | 0.354 | 0.166 | 47.92% | 612.05% |
| quality_revenue_growth_v1 | locked_test | 26.01% | -22.36% | 1.043 | 1.163 | 28.19% | 694.48% |
| quality_revenue_growth_v1 | full | 10.94% | -44.75% | 0.547 | 0.244 | 159.57% | 789.99% |

验证集入选：`quality_cash_verification_v1`。

## 锁定测试门槛

- PASS：locked_test_annual_return_at_least_8pct
- PASS：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_25pct
- FAIL：locked_test_positive_excess
- FAIL：locked_test_sharpe_near_quality_v1
- PASS：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：turnover_not_over_quality_v1_125pct

结论：不注册，保留失败指纹。
