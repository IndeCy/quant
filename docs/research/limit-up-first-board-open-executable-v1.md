# 首板封单强度开盘可执行复核 V1

- 区间：20230101 至 20260615
- 组合定义保持首轮不变；唯一修正是开盘委托只在开盘已经封住涨跌停时拦截。
- 该修正由独立执行审计触发，参数在修正后收益加载前冻结。
- 本结果仍仅用于研究，不自动注册生产策略。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| 2023 | -93.75% | -93.57% | -7.806 | 368.7x |
| 2024 | -60.39% | -58.93% | -5.429 | 76.8x |
| 2025_latest | -0.09% | -0.13% | -1.641 | 0.0x |
| locked_test | -0.09% | -0.13% | -1.641 | 0.0x |
| full | -65.78% | -97.32% | -4.778 | 336.5x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2023 | -93.75% | -93.57% | -7.806 |
| 2024 | -60.39% | -58.93% | -5.429 |
| 2025 | -0.13% | -0.13% | -1.971 |
| 2026 | 0.00% | 0.00% | 0.000 |

## 执行诊断

- 成交：4595；失败委托：5963
- 失败率：56.48%
- 失败原因：`{"limit_up": 465, "missing_bar": 720, "cash_insufficient": 4729, "limit_down": 49}`
- 最差单日：-6.95%
- 95% Expected Shortfall：-4.52%
- 与 Quality 相关性：0.049

## 冻结门槛

- FAIL `full_return_at_least_10pct`
- FAIL `full_drawdown_within_30pct`
- FAIL `full_sharpe_at_least_075`
- FAIL `full_calmar_at_least_035`
- FAIL `positive_excess_vs_hs300`
- PASS `return_lift_vs_amount_control_at_least_2pct`
- PASS `sharpe_lift_vs_amount_control_at_least_010`
- FAIL `at_least_two_positive_folds`
- FAIL `worst_fold_drawdown_within_35pct`
- FAIL `median_fold_sharpe_at_least_055`
- FAIL `locked_return_at_least_8pct`
- PASS `locked_drawdown_within_30pct`
- FAIL `locked_sharpe_at_least_065`
- FAIL `at_least_three_positive_years`
- FAIL `annual_turnover_below_250x`
- FAIL `stress_return_at_least_5pct`
- FAIL `stress_sharpe_at_least_055`
- FAIL `failed_order_rate_at_most_20pct`
- PASS `active_signal_share_at_least_90pct`
- PASS `worst_day_within_10pct`
- PASS `expected_shortfall_95_within_5pct`
- PASS `quality_correlation_at_most_050`

结论：未通过研究门槛，归档且不注册。
