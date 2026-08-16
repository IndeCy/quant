# Quality Balanced Value 截面市值残差 V1

- 数据截止：20260727。
- 原始Quality与估值因子、股票池、风险层和M0保持不变。
- 每月在完整候选池回归 `factor_score ~ 1 + log(可见市值)`，
  仅使用残差做Top20排名。
- 本研究不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
| quality_balanced_value_unbuffered_v1 | 2015_2017 | 24.96% | -25.46% | 1.042 | 75.70% | 10.45x |
| quality_balanced_value_unbuffered_v1 | 2018_2020 | 3.67% | -24.56% | 0.281 | -22.73% | 5.69x |
| quality_balanced_value_unbuffered_v1 | 2021_2023 | 5.34% | -24.84% | 0.376 | 47.64% | 5.82x |
| quality_balanced_value_unbuffered_v1 | 2024_latest | 18.53% | -19.48% | 0.921 | 4.36% | 6.69x |
| quality_balanced_value_unbuffered_v1 | locked_test | 8.25% | -24.84% | 0.499 | 36.20% | 6.33x |
| quality_balanced_value_unbuffered_v1 | full | 12.96% | -25.46% | 0.687 | 231.22% | 6.96x |
| quality_balanced_value_size_residual_v1 | 2015_2017 | 24.17% | -33.97% | 0.920 | 72.22% | 11.80x |
| quality_balanced_value_size_residual_v1 | 2018_2020 | 0.45% | -27.91% | 0.132 | -32.44% | 7.50x |
| quality_balanced_value_size_residual_v1 | 2021_2023 | 8.75% | -22.31% | 0.537 | 58.83% | 7.76x |
| quality_balanced_value_size_residual_v1 | 2024_latest | 13.70% | -23.44% | 0.661 | -10.40% | 9.57x |
| quality_balanced_value_size_residual_v1 | locked_test | 7.78% | -23.97% | 0.453 | 33.53% | 8.89x |
| quality_balanced_value_size_residual_v1 | full | 11.61% | -35.36% | 0.587 | 182.50% | 9.14x |

## 截面中性化诊断

- 市值覆盖：100.00%。
- 原分数与对数市值相关中位数：
  0.3306。
- 残差分数与对数市值相关中位数：
  -0.000000。
- 月度市值斜率中位数：0.238279。
- 最新持仓市值分位中位数：
  41.49%。

## 走步中盘风格残差

| 策略 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正残差年 | 锁定IR | 最差锁定年 | 门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| quality_balanced_value_unbuffered_v1 | 1.170 | 1.247 | -2.25% | 4.45% | 60.0% | 0.230 | -25.22% | FAIL |
| quality_balanced_value_size_residual_v1 | 1.965 | 1.921 | -6.54% | 3.22% | 80.0% | 0.237 | -17.70% | FAIL |

- 候选相对基线锁定Beta降幅：
  -54.05%。
- 20bps压力年化/Sharpe：
  10.02% / 0.526。

## 预注册门槛

- FAIL：locked_style_beta_reduced_by_at_least_30pct
- FAIL：walk_forward_style_residual_gate_passed
- PASS：full_annual_return_at_least_8pct
- PASS：full_sharpe_at_least_055
- FAIL：full_drawdown_within_30pct
- PASS：locked_annual_return_at_least_6pct
- PASS：locked_sharpe_at_least_040
- FAIL：annual_turnover_not_over_baseline_125pct
- PASS：stress_20bps_annual_return_at_least_7pct
- PASS：market_cap_coverage_at_least_95pct
- PASS：median_abs_residual_size_correlation_at_most_002

结论：REJECTED_NO_PRODUCTION_CHANGE。
