# Quality Balance Sheet Factor Study

- 数据截止：20260722
- 候选：研究前固定四组，不新增数据源。
- 选择：只按2019-2021验证集的Sharpe、Calmar、回撤、换手率依次排序。
- 锁定测试：2022年至数据截止日，禁止根据测试结果反向换候选或改门槛。
- 统一口径：Quality Cleanup股票池、Top20等权、月频、qfq、M0 T+1、5bps。
- 风险层：20日组合波动率大于45%时仓位降至30%。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_v1_baseline | validation | 30.23% | -16.48% | 1.385 | 1.835 | 40.88% | 483.71% |
| quality_v1_baseline | locked_test | 12.65% | -31.34% | 0.670 | 0.404 | 62.70% | 546.61% |
| quality_v1_baseline | full | 15.53% | -32.73% | 0.755 | 0.474 | 340.86% | 633.54% |
| quality_cash_conversion_v1 | validation | 9.77% | -31.13% | 0.516 | 0.314 | -43.06% | 628.26% |
| quality_cash_conversion_v1 | locked_test | 4.85% | -32.24% | 0.314 | 0.151 | 17.43% | 812.38% |
| quality_cash_conversion_v1 | full | 7.71% | -45.89% | 0.420 | 0.168 | 70.64% | 803.78% |
| quality_conservative_balance_v1 | validation | 23.82% | -17.23% | 1.142 | 1.383 | 11.65% | 564.17% |
| quality_conservative_balance_v1 | locked_test | 5.87% | -22.82% | 0.367 | 0.257 | 22.74% | 677.90% |
| quality_conservative_balance_v1 | full | 12.30% | -32.44% | 0.623 | 0.379 | 205.99% | 673.55% |
| quality_margin_efficiency_v1 | validation | 30.80% | -25.30% | 1.356 | 1.217 | 43.63% | 412.72% |
| quality_margin_efficiency_v1 | locked_test | 4.68% | -26.87% | 0.311 | 0.174 | 16.55% | 571.99% |
| quality_margin_efficiency_v1 | full | 11.44% | -41.98% | 0.562 | 0.273 | 176.09% | 572.13% |
| quality_balanced_fundamental_v1 | validation | 19.88% | -21.27% | 0.959 | 0.934 | -4.96% | 489.85% |
| quality_balanced_fundamental_v1 | locked_test | 3.31% | -27.16% | 0.256 | 0.122 | 9.72% | 681.56% |
| quality_balanced_fundamental_v1 | full | 9.06% | -41.19% | 0.483 | 0.220 | 104.59% | 722.15% |

## 验证集选择

入选候选：`quality_margin_efficiency_v1`。

## 锁定测试晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_30pct
- PASS：locked_test_positive_excess
- PASS：drawdown_not_worse_than_quality_v1_by_5pct
- PASS：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：turnover_not_over_quality_v1_125pct

结论：不注册，保留失败指纹并研究下一组假设。
