# Quality Value Extension Study

- 数据截止：20260722
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- Quality主体70%-85%，估值增强使用点时E/P、B/P和可选低波。
- 公司行动门禁：检查295782条，剔除25254条重大变化。
- 统一Top20月频、qfq、M0 T+1、5bps及原风险层。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_v1_baseline | validation | 0.92% | -31.22% | 0.142 | 0.029 | 34.11% | 523.58% |
| quality_v1_baseline | locked_test | 21.91% | -17.63% | 0.970 | 1.243 | 14.49% | 611.78% |
| quality_v1_baseline | full | 14.36% | -34.12% | 0.719 | 0.421 | 287.30% | 662.37% |
| quality_earnings_yield_extension_v1 | validation | 3.48% | -25.31% | 0.280 | 0.137 | 41.81% | 528.30% |
| quality_earnings_yield_extension_v1 | locked_test | 26.86% | -19.52% | 1.229 | 1.376 | 31.11% | 657.36% |
| quality_earnings_yield_extension_v1 | full | 13.50% | -28.48% | 0.697 | 0.474 | 251.62% | 671.50% |
| quality_book_yield_extension_v1 | validation | 0.32% | -26.01% | 0.107 | 0.012 | 32.37% | 528.07% |
| quality_book_yield_extension_v1 | locked_test | 23.42% | -17.73% | 1.103 | 1.321 | 19.48% | 693.29% |
| quality_book_yield_extension_v1 | full | 12.77% | -33.40% | 0.675 | 0.382 | 223.19% | 685.41% |
| quality_balanced_value_extension_v1 | validation | 5.34% | -24.84% | 0.376 | 0.215 | 47.64% | 582.12% |
| quality_balanced_value_extension_v1 | locked_test | 18.59% | -19.48% | 0.926 | 0.954 | 3.89% | 673.51% |
| quality_balanced_value_extension_v1 | full | 12.96% | -25.46% | 0.687 | 0.509 | 230.57% | 697.70% |
| quality_defensive_value_extension_v1 | validation | 10.35% | -19.23% | 0.650 | 0.538 | 64.30% | 689.07% |
| quality_defensive_value_extension_v1 | locked_test | 13.96% | -16.85% | 0.776 | 0.828 | -10.22% | 682.98% |
| quality_defensive_value_extension_v1 | full | 13.08% | -25.55% | 0.717 | 0.512 | 234.85% | 737.27% |
| quality_value_30_extension_v1 | validation | 6.76% | -21.98% | 0.438 | 0.307 | 52.21% | 629.12% |
| quality_value_30_extension_v1 | locked_test | 17.66% | -21.77% | 0.891 | 0.811 | 0.99% | 657.04% |
| quality_value_30_extension_v1 | full | 11.59% | -32.33% | 0.623 | 0.359 | 181.21% | 715.48% |

验证集入选：`quality_defensive_value_extension_v1`。

## 锁定测试门槛

- PASS：locked_test_annual_return_at_least_8pct
- PASS：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_25pct
- FAIL：locked_test_positive_excess
- FAIL：locked_test_sharpe_near_quality_v1
- PASS：full_annual_return_at_least_10pct
- PASS：full_sharpe_at_least_065
- PASS：full_drawdown_within_32pct
- PASS：turnover_not_over_quality_v1_125pct

结论：不注册，保留失败指纹。
