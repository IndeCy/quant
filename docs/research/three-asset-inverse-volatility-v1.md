# 三资产逆波动风险预算 V1

- 数据共同截止：20260724。
- 资产：沪深300ETF、黄金ETF、5年国债ETF。
- 月末按过去60个交易日年化波动率倒数归一化，无杠杆、无权重上限。
- 使用统一qfq、M0 T+1、5bps，ETF免印花税，不叠加风险覆盖层。
- 与 Quality 日收益相关性：0.388。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| 2015_2017 | 3.08% | -4.74% | 0.804 | 0.651 | -6.10% | 1.42x |
| 2018_2020 | 6.41% | -3.94% | 1.721 | 1.627 | -14.02% | 1.06x |
| 2021_2023 | 2.52% | -1.79% | 1.080 | 1.412 | 38.89% | 0.56x |
| 2024_latest | 8.19% | -1.03% | 3.047 | 7.961 | -24.60% | 0.70x |
| full | 4.93% | -4.74% | 1.517 | 1.041 | 15.11% | 0.90x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| three_asset_inverse_volatility_v1 | 4.93% | -4.74% | 1.517 |
| 黄金国债50/50 | 7.18% | -16.58% | 0.921 |

## 权重诊断

| 代码 | 资产 | 平均权重 | 最新权重 | 历史最高权重 |
|---|---|---:|---:|---:|
| 510300.SH | 沪深300ETF | 8.6% | 3.7% | 23.8% |
| 511010.SH | 5年国债ETF | 78.0% | 93.2% | 93.7% |
| 518880.SH | 黄金ETF | 13.4% | 3.1% | 28.9% |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 2.64% | -4.18% | 0.551 |
| 2016 | 3.91% | -4.74% | 1.119 |
| 2017 | 3.17% | -2.77% | 1.122 |
| 2018 | 3.59% | -2.18% | 1.314 |
| 2019 | 8.04% | -1.05% | 3.240 |
| 2020 | 8.12% | -3.94% | 1.535 |
| 2021 | 2.43% | -1.78% | 0.964 |
| 2022 | 1.13% | -1.79% | 0.447 |
| 2023 | 4.18% | -1.25% | 2.298 |
| 2024 | 12.10% | -0.76% | 4.001 |
| 2025 | 7.26% | -1.03% | 2.666 |
| 2026 | 2.79% | -0.99% | 1.500 |

## 固定门槛

- FAIL：full_annual_return_at_least_5pct
- PASS：full_drawdown_within_12pct
- PASS：full_sharpe_at_least_090
- PASS：full_calmar_at_least_040
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_15pct
- PASS：median_fold_sharpe_at_least_065
- PASS：annual_turnover_below_15x
- FAIL：quality_correlation_at_most_035
- PASS：at_least_nine_positive_years
- FAIL：return_shortfall_vs_gold_bond_within_2pct
- PASS：drawdown_improvement_vs_gold_bond_at_least_3pct
- PASS：sharpe_shortfall_vs_gold_bond_within_005
- PASS：average_largest_asset_weight_at_most_85pct

结论：未通过固定门槛，终止该路线。
