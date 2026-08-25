# 全球防守三资产60日逆波动 V1

- 数据共同截止：20260728。
- 资产固定为标普500ETF、黄金ETF和5年国债ETF。
- 月末按过去60个交易日年化波动率倒数归一化；无杠杆、无权重上限、无参数网格。
- M0 T+1、qfq、基础5bps并独立验证20bps压力；ETF免印花税。
- 与Quality日收益相关性：0.132。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2015_2017 | 3.47% | -3.02% | 0.961 | 1.148 | 1.53x |
| 2018_2020 | 5.30% | -5.47% | 1.399 | 0.969 | 1.04x |
| 2021_2023 | 4.77% | -1.38% | 1.980 | 3.454 | 0.60x |
| 2024_latest | 7.19% | -2.17% | 2.668 | 3.314 | 0.69x |
| full | 5.10% | -5.47% | 1.588 | 0.933 | 0.93x |

## 同口径对照与压力

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| global_defensive_inverse_volatility_60d_v1 | 5.10% | -5.47% | 1.588 |
| global_defensive_inverse_volatility_60d_20bps | 4.95% | -5.49% | 1.542 |
| global_defensive_equal_same_panel_control | 9.89% | -12.97% | 1.204 |
| global_defensive_inverse_vol_sp500_control | 14.29% | -29.67% | 0.826 |

## 动态权重诊断

| 代码 | 平均权重 | 最新权重 | 历史最高权重 |
|---|---:|---:|---:|
| 511010.SH | 76.8% | 93.1% | 94.4% |
| 513500.SH | 10.0% | 3.8% | 25.5% |
| 518880.SH | 13.2% | 3.1% | 33.0% |

## 冻结门槛

- FAIL：full_return_at_least_85pct
- PASS：full_drawdown_within_15pct
- PASS：full_sharpe_at_least_105
- PASS：full_calmar_at_least_055
- FAIL：return_shortfall_vs_equal_within_15pct
- PASS：drawdown_improvement_vs_equal_at_least_05pct
- PASS：sharpe_shortfall_vs_equal_within_005
- PASS：drawdown_improvement_vs_sp500_at_least_10pct
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_18pct
- PASS：median_fold_sharpe_at_least_075
- PASS：at_least_eight_positive_years
- PASS：annual_turnover_below_15x
- PASS：quality_correlation_at_most_030
- FAIL：largest_average_weight_at_most_70pct
- FAIL：stress_return_at_least_8pct
- PASS：stress_drawdown_within_16pct
- PASS：stress_sharpe_at_least_100

结论：未通过固定门槛，终止该路线且不生成参数变体。
