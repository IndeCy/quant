# 黄金趋势国债切换 V1

- 数据共同截止：20260724。
- 月末黄金 MA60 > MA120 时持有黄金，否则持有5年国债。
- 信号在月末收盘形成，下一交易日经 M0 成交。
- 统一qfq、5bps、ETF免印花税，不叠加额外风险层。
- 与 Quality 日收益相关性：0.074。
- 最新状态：国债防守，
  MA60=9.436，MA120=9.882。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| 2015_2017 | -0.54% | -15.88% | -0.010 | -0.034 | -16.88% | 6.46x |
| 2018_2020 | 10.28% | -17.17% | 0.840 | 0.599 | -0.98% | 4.60x |
| 2021_2023 | 9.08% | -11.38% | 1.052 | 0.798 | 59.93% | 3.30x |
| 2024_latest | 26.27% | -30.59% | 1.178 | 0.859 | 31.42% | 0.94x |
| full | 10.34% | -30.59% | 0.785 | 0.338 | 143.47% | 3.22x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| gold_trend_bond_switch_v1 | 10.34% | -30.59% | 0.785 | 0.338 |
| 黄金单资产 | 11.15% | -30.52% | 0.772 | 0.365 |
| 黄金国债50/50 | 7.18% | -16.58% | 0.921 | 0.433 |

## 状态归因

| 状态 | 交易日 | 时间占比 | 累计收益 | 状态年化 | 日胜率 |
|---|---:|---:|---:|---:|---:|
| BOND_DEFENSIVE | 898 | 32.2% | 9.71% | 2.63% | 56.0% |
| GOLD_ACTIVE | 1890 | 67.8% | 172.88% | 14.32% | 53.8% |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 1.56% | -5.79% | 0.253 |
| 2016 | -0.23% | -13.85% | 0.051 |
| 2017 | -2.51% | -7.03% | -0.441 |
| 2018 | 6.68% | -2.44% | 1.999 |
| 2019 | 19.97% | -9.31% | 1.432 |
| 2020 | 5.12% | -17.17% | 0.380 |
| 2021 | 5.27% | -4.65% | 1.100 |
| 2022 | 5.12% | -11.38% | 0.540 |
| 2023 | 17.32% | -5.35% | 1.685 |
| 2024 | 28.31% | -7.49% | 1.886 |
| 2025 | 58.18% | -11.53% | 2.518 |
| 2026 | -22.77% | -30.59% | -0.569 |

## 固定门槛

- PASS：full_annual_return_at_least_65pct
- FAIL：full_drawdown_within_15pct
- FAIL：full_sharpe_at_least_090
- FAIL：full_calmar_at_least_040
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- FAIL：worst_fold_drawdown_within_20pct
- PASS：median_fold_sharpe_at_least_055
- FAIL：annual_turnover_below_3x
- PASS：quality_correlation_at_most_030
- PASS：at_least_eight_positive_years
- FAIL：gold_drawdown_improvement_at_least_10pct
- PASS：gold_return_shortfall_within_25pct
- PASS：gold_bond_return_shortfall_within_1pct
- FAIL：gold_bond_drawdown_improvement_at_least_2pct
- FAIL：gold_bond_sharpe_not_lower
- PASS：active_day_share_between_25_and_80pct

结论：未通过固定门槛，终止该路线。
