# 多因子固定 Ridge Ranker V1

- 数据截止：20260724。
- 特征：ROA、OCF_TO_OR、E/P、B/P、60日低波。
- 模型固定为 Ridge(alpha=1)，不选择模型、不搜索参数。
- 2019年起逐年扩展 Walk Forward，训练标签退出日必须早于测试年。
- Top20等权、月频、原20日波动率风险层、qfq、M0 T+1。
- 样本外平均 RankIC：0.0695；
  正IC月份：58.4%。
- 与 Quality Balanced Value 日收益相关性：
  0.850；
  平均持仓重叠：16.7%。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2019_2021 | 15.78% | -24.90% | 0.890 | 0.634 | 9.35x |
| 2022_2023 | 5.68% | -12.46% | 0.444 | 0.456 | 10.88x |
| 2024_latest | 5.32% | -19.49% | 0.377 | 0.273 | 10.05x |
| full_oos | 9.89% | -24.90% | 0.628 | 0.397 | 10.07x |

## 同口径对照

| 策略 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| multifactor_ridge_walk_forward_v1 | 9.89% | -24.90% | 0.628 | 10.07x |
| five_factor_equal_weight_control | 13.05% | -24.07% | 0.742 | 7.60x |
| quality_balanced_value_control | 13.19% | -24.81% | 0.731 | 6.16x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2019 | 13.84% | -18.32% | 0.793 |
| 2020 | -1.82% | -17.36% | 0.021 |
| 2021 | 37.97% | -11.15% | 2.285 |
| 2022 | -2.16% | -12.46% | -0.033 |
| 2023 | 13.76% | -8.88% | 1.186 |
| 2024 | 26.82% | -15.02% | 1.210 |
| 2025 | 0.25% | -10.77% | 0.092 |
| 2026 | -14.04% | -17.68% | -0.860 |

## 系数稳定性

| 特征 | 平均系数 | 正系数年份占比 | 最新系数 |
|---|---:|---:|---:|
| book_yield | 0.0052 | 100.0% | 0.0031 |
| earnings_yield | 0.0007 | 62.5% | -0.0003 |
| low_volatility_60d | 0.0195 | 100.0% | 0.0231 |
| ocf_to_or | 0.0016 | 100.0% | 0.0011 |
| roa | 0.0041 | 100.0% | 0.0011 |

## 失败归因

- 最高分组未来月平均收益：
  0.87%。
- 第4至8分组平均收益：
  1.55%。
- Top尾部相对中段收益差：
  -0.68%。
- 低波因子占平均绝对系数：
  62.7%。
- 换手相对五因子等权：
  1.33倍。
- 额外执行成本影响：
  3.64%。

## 固定门槛

- PASS：mean_rank_ic_at_least_002
- PASS：positive_ic_months_at_least_55pct
- FAIL：full_annual_return_at_least_10pct
- PASS：full_drawdown_within_30pct
- FAIL：full_sharpe_at_least_065
- PASS：full_calmar_at_least_030
- FAIL：annual_turnover_below_8x
- FAIL：at_least_six_positive_years
- PASS：all_three_periods_positive
- FAIL：median_period_sharpe_at_least_050
- FAIL：equal_control_sharpe_improves_005
- FAIL：equal_control_return_shortfall_within_2pct
- PASS：equal_control_drawdown_deterioration_within_3pct
- FAIL：equal_control_turnover_within_125x
- FAIL：quality_sharpe_shortfall_within_005
- FAIL：quality_return_shortfall_within_2pct
- PASS：quality_drawdown_deterioration_within_3pct
- PASS：quality_return_correlation_at_most_085
- PASS：quality_holding_overlap_at_most_70pct
- PASS：at_least_four_stable_positive_features

结论：未通过固定样本外门槛，不注册策略。
