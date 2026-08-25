# 标普500 × 黄金60/40块 12%波动目标 V1

- 候选风险块固定60% 513500.SH、40% 518880.SH。
- 对照风险块为100% 513500.SH。
- 两者使用完全相同的12%年化波动目标、63交易日回看和月频调整。
- 风险块不加杠杆；未使用的预算进入511010.SH。
- 月末信号、下一交易日成交；统一qfq、M0 T+1、5bps。
- 正式评价从2019-01-01开始，2022-01-01后为锁定检验。

| 组合 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
| 标普/黄金60/40块 12%波动目标 | 2019_2021 | 13.92% | -20.31% | 1.238 | 0.686 | 1.22x |
| 标普/黄金60/40块 12%波动目标 | 2022_2024 | 15.99% | -9.19% | 1.400 | 1.739 | 1.23x |
| 标普/黄金60/40块 12%波动目标 | 2025_latest | 15.77% | -11.81% | 1.084 | 1.336 | 2.48x |
| 标普/黄金60/40块 12%波动目标 | locked_test | 16.15% | -11.81% | 1.276 | 1.368 | 1.79x |
| 标普/黄金60/40块 12%波动目标 | oos_full | 15.28% | -20.31% | 1.261 | 0.752 | 1.62x |
| 标普500 12%波动目标简单对照 | 2019_2021 | 15.02% | -23.37% | 1.179 | 0.643 | 1.83x |
| 标普500 12%波动目标简单对照 | 2022_2024 | 12.92% | -13.61% | 1.010 | 0.950 | 1.48x |
| 标普500 12%波动目标简单对照 | 2025_latest | 4.84% | -17.65% | 0.387 | 0.274 | 2.66x |
| 标普500 12%波动目标简单对照 | locked_test | 10.25% | -18.96% | 0.780 | 0.541 | 1.97x |
| 标普500 12%波动目标简单对照 | oos_full | 12.22% | -23.37% | 0.935 | 0.523 | 1.92x |
| 直接持有标普500ETF | 2019_2021 | 23.20% | -29.67% | 1.241 | 0.782 | 0.00x |
| 直接持有标普500ETF | 2022_2024 | 14.64% | -20.04% | 0.837 | 0.730 | 0.00x |
| 直接持有标普500ETF | 2025_latest | 8.96% | -23.04% | 0.528 | 0.389 | 0.00x |
| 直接持有标普500ETF | locked_test | 12.90% | -24.93% | 0.735 | 0.518 | 0.00x |
| 直接持有标普500ETF | oos_full | 17.00% | -29.67% | 0.935 | 0.573 | 0.00x |
| 候选20bps压力 | 2019_2021 | 13.72% | -20.31% | 1.221 | 0.675 | 1.22x |
| 候选20bps压力 | 2022_2024 | 15.78% | -9.27% | 1.384 | 1.702 | 1.23x |
| 候选20bps压力 | 2025_latest | 15.34% | -11.83% | 1.059 | 1.298 | 2.48x |
| 候选20bps压力 | locked_test | 15.87% | -11.83% | 1.257 | 1.342 | 1.79x |
| 候选20bps压力 | oos_full | 15.03% | -20.31% | 1.243 | 0.740 | 1.62x |

## 年度表现

| 年份 | 候选 | 同机制标普对照 | 直接513500 |
|---:|---:|---:|---:|
| 2019 | 29.18% | 25.66% | 35.50% |
| 2020 | 1.10% | -3.40% | 7.95% |
| 2021 | 12.77% | 24.95% | 27.37% |
| 2022 | -3.87% | -9.88% | -14.60% |
| 2023 | 23.94% | 23.41% | 29.56% |
| 2024 | 30.69% | 29.28% | 36.20% |
| 2025 | 25.41% | 6.68% | 11.85% |
| 2026 | -2.25% | -0.16% | 1.19% |

## 风险匹配与机会成本

- 候选评价期年化波动：11.84%。
- 同机制标普对照年化波动：13.28%。
- 直接513500年化波动：18.67%。
- 候选平均风险块占比：88.54%。
- 候选最低/最高风险块占比：
  44.69% /
  100.00%。
- 相对同机制标普对照年化收益差：
  3.06%。
- 相对直接513500年化收益差：
  -1.72%。
- 最差单日：-7.20%。
- 95% Expected Shortfall：-1.76%。
- 最长水下期：337个交易日。
- 与Quality日收益相关性：0.260。

## 冻结门槛

- PASS：oos_annual_return_at_least_10pct
- FAIL：oos_drawdown_within_20pct
- PASS：oos_sharpe_at_least_090
- PASS：oos_calmar_at_least_055
- PASS：return_lift_vs_same_mechanism_control_at_least_1pct
- PASS：sharpe_lift_vs_same_mechanism_control_at_least_010
- PASS：drawdown_worse_vs_same_mechanism_control_within_1pct
- PASS：volatility_worse_vs_same_mechanism_control_within_1pct
- PASS：volatility_reduction_vs_direct_at_least_20pct
- PASS：drawdown_improvement_vs_direct_at_least_5pct
- PASS：return_shortfall_vs_direct_within_3pct
- PASS：all_three_folds_positive
- FAIL：worst_fold_drawdown_within_20pct
- PASS：median_fold_sharpe_at_least_070
- PASS：locked_return_at_least_10pct
- PASS：locked_drawdown_within_18pct
- PASS：locked_sharpe_at_least_085
- PASS：at_least_six_positive_years
- FAIL：annual_turnover_below_15x
- PASS：average_risk_allocation_at_least_60pct
- PASS：stress_return_lift_vs_control_at_least_07pct
- PASS：stress_sharpe_at_least_085
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_25pct
- PASS：quality_correlation_at_most_050

## 结论

未通过同机制机会成本门槛，归档且不注册。本研究不自动注册、不接入scheduler、Paper或实盘。
