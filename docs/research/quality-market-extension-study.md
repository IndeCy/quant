# Quality Market Extension Study

- 数据截止：20260722
- 训练：2015-2020；验证选择：2021-2023；锁定测试：2024至今。
- Quality V1主体权重80%-85%，市场增强仅占15%-20%。
- 统一口径：Quality Cleanup、Top20等权、月频、qfq、M0 T+1、5bps及原风险层。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_v1_baseline | validation | 6.22% | -31.87% | 0.419 | 0.195 | 50.47% | 477.14% |
| quality_v1_baseline | locked_test | 22.60% | -16.39% | 1.001 | 1.379 | 16.77% | 591.16% |
| quality_v1_baseline | full | 15.53% | -32.73% | 0.755 | 0.474 | 340.86% | 633.54% |
| quality_momentum_120_extension_v1 | validation | -11.70% | -38.35% | -0.469 | -0.305 | 1.29% | 860.13% |
| quality_momentum_120_extension_v1 | locked_test | 11.91% | -29.70% | 0.539 | 0.401 | -16.21% | 1250.69% |
| quality_momentum_120_extension_v1 | full | 7.27% | -43.48% | 0.403 | 0.167 | 60.33% | 1037.42% |
| quality_trend_strength_extension_v1 | validation | -8.35% | -33.97% | -0.328 | -0.246 | 9.21% | 805.83% |
| quality_trend_strength_extension_v1 | locked_test | 5.80% | -29.01% | 0.345 | 0.200 | -33.12% | 946.01% |
| quality_trend_strength_extension_v1 | full | 9.53% | -40.17% | 0.490 | 0.237 | 117.49% | 873.38% |
| quality_lowvol_extension_v1 | validation | 2.70% | -29.61% | 0.246 | 0.091 | 39.43% | 635.24% |
| quality_lowvol_extension_v1 | locked_test | 15.67% | -13.17% | 0.914 | 1.189 | -5.12% | 831.36% |
| quality_lowvol_extension_v1 | full | 10.40% | -40.62% | 0.609 | 0.256 | 142.88% | 806.80% |
| quality_momentum_lowvol_extension_v1 | validation | 4.43% | -27.32% | 0.334 | 0.162 | 44.75% | 664.15% |
| quality_momentum_lowvol_extension_v1 | locked_test | 22.26% | -14.85% | 1.100 | 1.499 | 15.63% | 804.91% |
| quality_momentum_lowvol_extension_v1 | full | 15.40% | -37.46% | 0.786 | 0.411 | 334.65% | 806.62% |
| quality_trend_lowvol_extension_v1 | validation | 3.29% | -27.89% | 0.274 | 0.118 | 41.24% | 639.23% |
| quality_trend_lowvol_extension_v1 | locked_test | 15.96% | -15.99% | 0.837 | 0.998 | -4.23% | 993.85% |
| quality_trend_lowvol_extension_v1 | full | 13.37% | -34.65% | 0.709 | 0.386 | 246.28% | 825.52% |

验证集入选：`quality_momentum_lowvol_extension_v1`。

## 锁定测试门槛

- PASS：locked_test_annual_return_at_least_8pct
- PASS：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_25pct
- PASS：locked_test_positive_excess
- PASS：locked_test_sharpe_near_quality_v1
- PASS：full_annual_return_at_least_10pct
- PASS：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：turnover_not_over_quality_v1_125pct

结论：不注册，保留失败指纹。
