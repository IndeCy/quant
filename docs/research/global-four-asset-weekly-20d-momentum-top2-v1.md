# 全球四资产周频20日动量Top2 V1

- 固定资产：纳指、标普、黄金、5年国债。
- 每周最后交易日按过去20日收益从强到弱排名，Top2各50%。
- 下一交易日M0执行，基础5bps、压力20bps；不做窗口或Top-N网格。
- 数据共同截止：20260728。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2016_2018 | 8.95% | -20.91% | 0.740 | 0.428 | 20.33x |
| 2019_2021 | 12.91% | -25.83% | 0.846 | 0.500 | 24.25x |
| 2022_2024 | 12.49% | -15.84% | 0.957 | 0.789 | 22.58x |
| 2025_latest | 35.34% | -12.47% | 1.862 | 2.833 | 18.59x |
| locked_test | 20.05% | -15.84% | 1.321 | 1.266 | 20.69x |
| full | 14.79% | -28.58% | 1.025 | 0.517 | 21.52x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| global_four_asset_weekly_20d_momentum_top2_v1 | 14.79% | -28.58% | 1.025 |
| global_four_asset_static_equal_control | 13.49% | -16.74% | 1.235 |
| nasdaq_gold_60_40_weekly_momentum_control | 18.47% | -21.43% | 1.179 |
| sp500_direct_weekly_momentum_control | 15.11% | -29.67% | 0.854 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2016 | 23.21% | -9.70% | 1.595 |
| 2017 | 6.73% | -8.80% | 0.749 |
| 2018 | 2.99% | -17.05% | 0.288 |
| 2019 | 21.95% | -4.90% | 1.830 |
| 2020 | 13.98% | -22.69% | 0.695 |
| 2021 | 3.01% | -7.45% | 0.323 |
| 2022 | -9.36% | -15.84% | -0.631 |
| 2023 | 24.14% | -9.06% | 2.040 |
| 2024 | 26.46% | -10.64% | 1.710 |
| 2025 | 41.47% | -6.19% | 2.678 |
| 2026 | 22.81% | -12.47% | 1.038 |

## 最新目标

| 代码 | 资产 | 权重 | 20日收益 |
|---|---|---:|---:|
| 518880.SH | 黄金ETF | 50.0% | 0.26% |
| 513500.SH | 标普500ETF | 50.0% | 0.04% |

## 入选覆盖

| 代码 | 资产 | Top2入选占比 |
|---|---|---:|
| 159941.SZ | 纳斯达克100ETF | 29.6% |
| 513500.SH | 标普500ETF | 30.4% |
| 518880.SH | 黄金ETF | 22.8% |
| 511010.SH | 5年国债ETF | 17.2% |

- 年化波动：14.49%
- 最差单日：-8.08%
- 95% Expected Shortfall：-2.26%
- 与Quality日收益相关性：0.189

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_12pct
- FAIL：full_drawdown_within_25pct
- PASS：full_sharpe_at_least_090
- PASS：full_calmar_at_least_045
- PASS：return_lift_vs_equal_at_least_1pct
- FAIL：sharpe_lift_vs_equal_at_least_005
- FAIL：return_lift_vs_sp500_at_least_05pct
- PASS：sharpe_lift_vs_sp500_at_least_010
- FAIL：drawdown_improvement_vs_sp500_at_least_5pct
- PASS：return_shortfall_vs_growth_within_4pct
- PASS：all_four_folds_positive
- PASS：worst_fold_drawdown_within_30pct
- PASS：median_fold_sharpe_at_least_070
- PASS：locked_return_at_least_12pct
- PASS：locked_drawdown_within_25pct
- PASS：locked_sharpe_at_least_085
- PASS：at_least_eight_positive_years
- FAIL：annual_turnover_below_12x
- PASS：stress_return_at_least_11pct
- FAIL：stress_sharpe_at_least_080
- FAIL：worst_day_within_8pct
- PASS：expected_shortfall_95_within_3pct
- PASS：quality_correlation_at_most_050
- PASS：selection_share_between_10_and_40pct

结论：未通过冻结门槛，归档且不注册。
