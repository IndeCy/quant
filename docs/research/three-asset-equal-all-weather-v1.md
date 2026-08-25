# 三资产固定等权全天候策略 V1

- 数据共同截止：20260724。
- 固定资产：沪深300ETF、黄金ETF、5年国债ETF，各三分之一。
- 月频恢复等权，不做趋势选择，不叠加风险覆盖层。
- 执行口径：统一qfq、M0 T+1、5bps，ETF免印花税。
- 与 Quality 日收益相关性：0.619。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| 2015_2017 | 4.77% | -16.20% | 0.511 | 0.294 | -0.84% | 0.65x |
| 2018_2020 | 9.44% | -10.29% | 1.107 | 0.918 | -3.87% | 0.30x |
| 2021_2023 | -0.82% | -11.65% | -0.085 | -0.070 | 29.09% | 0.27x |
| 2024_latest | 16.32% | -12.24% | 1.446 | 1.333 | -0.98% | 0.35x |
| full | 7.01% | -16.20% | 0.785 | 0.433 | 56.84% | 0.38x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| three_asset_equal_all_weather_v1 | 7.01% | -16.20% | 0.785 | 0.433 |
| 沪深300单资产 | 4.82% | -45.43% | 0.324 | 0.106 |
| 黄金国债50/50 | 7.18% | -16.58% | 0.921 | 0.433 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 2.21% | -16.20% | 0.221 |
| 2016 | 6.18% | -4.96% | 0.813 |
| 2017 | 7.87% | -3.81% | 1.614 |
| 2018 | -6.07% | -10.29% | -0.813 |
| 2019 | 21.46% | -3.93% | 2.740 |
| 2020 | 15.16% | -8.12% | 1.410 |
| 2021 | -2.32% | -7.06% | -0.267 |
| 2022 | -2.86% | -7.35% | -0.353 |
| 2023 | 3.10% | -4.61% | 0.599 |
| 2024 | 19.45% | -3.73% | 2.032 |
| 2025 | 26.65% | -3.44% | 2.748 |
| 2026 | -6.19% | -12.24% | -0.319 |

## 最新目标

| 代码 | 资产 | 目标权重 |
|---|---|---:|
| 510300.SH | 沪深300ETF | 33.3% |
| 518880.SH | 黄金ETF | 33.3% |
| 511010.SH | 5年国债ETF | 33.3% |

## 固定研究门槛

- PASS：full_annual_return_at_least_7pct
- PASS：full_drawdown_within_25pct
- PASS：full_sharpe_at_least_075
- PASS：full_calmar_at_least_030
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_25pct
- PASS：median_fold_sharpe_at_least_050
- PASS：annual_turnover_below_1x
- FAIL：quality_correlation_at_most_050
- PASS：at_least_eight_positive_years
- FAIL：return_uplift_vs_gold_bond_at_least_05pct
- PASS：drawdown_deterioration_vs_gold_bond_within_6pct
- PASS：sharpe_shortfall_vs_gold_bond_within_015
- PASS：drawdown_improvement_vs_equity_at_least_10pct

结论：未通过固定门槛，终止该路线。
