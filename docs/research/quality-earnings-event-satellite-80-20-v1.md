# Quality慢核心 × 意外盈利事件卫星 80/20 V1

- 数据截止：20260727。
- Core 80%：冻结的 Quality Balanced Value。
- Satellite 20%：冻结的 SUE 原始秩 Top20；不可构造月份沿用。
- 组合月频更新，日频统一风险层，M0 T+1执行。
- 没有权重网格，不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
| quality_balanced_value_unbuffered_v1 | 2015_2017 | 24.96% | -25.46% | 1.042 | 75.70% | 10.45x |
| quality_balanced_value_unbuffered_v1 | 2018_2020 | 3.67% | -24.56% | 0.281 | -22.73% | 5.69x |
| quality_balanced_value_unbuffered_v1 | 2021_2023 | 5.34% | -24.84% | 0.376 | 47.64% | 5.82x |
| quality_balanced_value_unbuffered_v1 | 2024_latest | 18.53% | -19.48% | 0.921 | 4.36% | 6.69x |
| quality_balanced_value_unbuffered_v1 | locked_test | 8.25% | -24.84% | 0.499 | 36.20% | 6.33x |
| quality_balanced_value_unbuffered_v1 | full | 12.96% | -25.46% | 0.687 | 231.22% | 6.96x |
| earnings_surprise_event_rank_same_snapshot_v2 | 2015_2017 | 17.08% | -30.23% | 0.697 | 42.80% | 15.51x |
| earnings_surprise_event_rank_same_snapshot_v2 | 2018_2020 | 0.03% | -31.97% | 0.137 | -33.67% | 12.83x |
| earnings_surprise_event_rank_same_snapshot_v2 | 2021_2023 | -8.21% | -45.93% | -0.279 | 9.54% | 13.31x |
| earnings_surprise_event_rank_same_snapshot_v2 | 2024_latest | 28.93% | -21.43% | 1.076 | 39.30% | 10.27x |
| earnings_surprise_event_rank_same_snapshot_v2 | locked_test | 5.14% | -42.77% | 0.326 | 19.25% | 11.29x |
| earnings_surprise_event_rank_same_snapshot_v2 | full | 8.25% | -50.82% | 0.434 | 84.25% | 12.97x |
| quality_earnings_event_satellite_80_20_v1 | 2015_2017 | 24.45% | -25.88% | 0.993 | 73.46% | 11.46x |
| quality_earnings_event_satellite_80_20_v1 | 2018_2020 | 4.37% | -25.72% | 0.312 | -20.54% | 6.90x |
| quality_earnings_event_satellite_80_20_v1 | 2021_2023 | 3.11% | -25.00% | 0.262 | 40.69% | 7.15x |
| quality_earnings_event_satellite_80_20_v1 | 2024_latest | 22.29% | -19.68% | 1.113 | 16.52% | 7.37x |
| quality_earnings_event_satellite_80_20_v1 | locked_test | 8.82% | -25.00% | 0.540 | 39.53% | 7.23x |
| quality_earnings_event_satellite_80_20_v1 | full | 13.21% | -25.88% | 0.695 | 241.02% | 8.01x |

## 袖套与执行诊断

- SUE实际重选/沿用月份：
  127 / 11。
- 事件卫星有效月份占比：99.28%。
- 两袖套持仓代码重叠中位数：
  0.00%。
- 事件与核心日收益相关：
  0.738。
- 组合与核心/事件相关：
  0.965 /
  0.825。
- 20bps压力年化/Sharpe：
  11.83% / 0.638。

## 组合走步中盘风格残差

- 验证/锁定Beta：
  1.336 / 1.365。
- 验证/锁定平均残差：
  -1.43% /
  5.10%。
- 锁定正残差年占比/IR/最差年：
  60.0% /
  0.292 /
  -20.45%。
- 残差门槛：FAIL。

## 预注册门槛

- PASS：full_return_drag_within_1pct
- PASS：full_sharpe_at_least_core
- PASS：full_drawdown_worsening_within_2pct
- PASS：locked_return_at_least_core
- PASS：locked_sharpe_at_least_core
- PASS：locked_drawdown_worsening_within_2pct
- FAIL：walk_forward_style_residual_gate_passed
- PASS：annual_turnover_not_over_core_125pct
- PASS：event_core_daily_correlation_at_most_075
- PASS：stress_20bps_annual_return_at_least_9pct
- PASS：stress_20bps_sharpe_at_least_055

结论：REJECTED_NO_PRODUCTION_CHANGE。
