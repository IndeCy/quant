# Quality Balanced Value 市值分层中性 V1

- 数据截止：20260727。
- Alpha、标准股票池、月频信号、日频风险层和M0均保持不变。
- 四个市值分位各选5只，市值只使用信号日已披露总股本。
- 本研究不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
| quality_balanced_value_unbuffered_v1 | 2015_2017 | 24.96% | -25.46% | 1.042 | 75.70% | 10.45x |
| quality_balanced_value_unbuffered_v1 | 2018_2020 | 3.67% | -24.56% | 0.281 | -22.73% | 5.69x |
| quality_balanced_value_unbuffered_v1 | 2021_2023 | 5.34% | -24.84% | 0.376 | 47.64% | 5.82x |
| quality_balanced_value_unbuffered_v1 | 2024_latest | 18.53% | -19.48% | 0.921 | 4.36% | 6.69x |
| quality_balanced_value_unbuffered_v1 | locked_test | 8.25% | -24.84% | 0.499 | 36.20% | 6.33x |
| quality_balanced_value_unbuffered_v1 | full | 12.96% | -25.46% | 0.687 | 231.22% | 6.96x |
| quality_balanced_value_size_neutral_v1 | 2015_2017 | 21.70% | -35.65% | 0.882 | 61.58% | 15.05x |
| quality_balanced_value_size_neutral_v1 | 2018_2020 | 0.93% | -28.31% | 0.151 | -31.03% | 8.51x |
| quality_balanced_value_size_neutral_v1 | 2021_2023 | 5.95% | -23.81% | 0.410 | 49.58% | 8.90x |
| quality_balanced_value_size_neutral_v1 | 2024_latest | 6.94% | -25.13% | 0.410 | -29.61% | 10.86x |
| quality_balanced_value_size_neutral_v1 | locked_test | 2.85% | -27.95% | 0.240 | 7.79% | 10.07x |
| quality_balanced_value_size_neutral_v1 | full | 8.97% | -35.65% | 0.498 | 102.96% | 10.76x |

## 走步中盘风格残差

| 策略 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正残差年 | 锁定IR | 最差锁定年 | 门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| quality_balanced_value_unbuffered_v1 | 1.170 | 1.247 | -2.25% | 4.45% | 60.0% | 0.230 | -25.22% | FAIL |
| quality_balanced_value_size_neutral_v1 | 1.512 | 1.534 | -5.96% | -1.12% | 40.0% | -0.078 | -23.35% | FAIL |

- 候选相对基线锁定Beta降幅：
  -23.03%。

## 数据与组合诊断

- 市值覆盖：100.00%。
- 四分位均可完整选满月份：100.00%。
- 候选持仓市值分位中位数：
  50.01%。
- 20bps压力年化/Sharpe：
  7.17% / 0.423。

## 预注册门槛

- FAIL：locked_style_beta_reduced_by_at_least_30pct
- FAIL：walk_forward_style_residual_gate_passed
- PASS：full_annual_return_at_least_8pct
- FAIL：full_sharpe_at_least_055
- FAIL：full_drawdown_within_30pct
- FAIL：locked_annual_return_at_least_6pct
- FAIL：locked_sharpe_at_least_040
- FAIL：annual_turnover_not_over_baseline_115pct
- PASS：stress_20bps_annual_return_at_least_7pct
- PASS：market_cap_coverage_at_least_95pct
- PASS：all_months_have_four_complete_buckets

结论：REJECTED_NO_PRODUCTION_CHANGE。
