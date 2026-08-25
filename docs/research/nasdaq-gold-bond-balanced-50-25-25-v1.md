# 纳指50×黄金25×国债25增长防守平衡 V1

- 数据共同截止：20260728。
- 固定持有纳指100ETF 50%、黄金ETF 25%、五年国债ETF 25%。
- 月末恢复固定权重；不择时、不做权重搜索、不使用杠杆或风险层。
- 信号下一交易日经M0执行，统一qfq、5bps，ETF免印花税。
- 对照：纳指/黄金60/40、全球防守三资产等权、场内标普500。
- 与Quality日收益相关性：0.258。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2016_2018 | 10.15% | -10.23% | 1.124 | 0.992 | 0.50x |
| 2019_2021 | 19.95% | -17.98% | 1.424 | 1.110 | 0.37x |
| 2022_2023 | 7.78% | -13.55% | 0.675 | 0.574 | 0.37x |
| 2024_latest | 19.91% | -12.32% | 1.351 | 1.616 | 0.38x |
| locked_test | 19.91% | -12.32% | 1.351 | 1.616 | 0.38x |
| full | 14.69% | -17.98% | 1.177 | 0.817 | 0.40x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| nasdaq_gold_bond_balanced_50_25_25_v1 | 14.69% | -17.98% | 1.177 | 0.817 |
| nasdaq_gold_60_40_balanced_control | 18.26% | -21.71% | 1.168 | 0.841 |
| global_defensive_balanced_control | 10.77% | -12.96% | 1.285 | 0.831 |
| sp500_direct_balanced_control | 15.20% | -29.67% | 0.860 | 0.512 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2016 | 21.74% | -3.44% | 2.435 |
| 2017 | 6.46% | -4.37% | 0.931 |
| 2018 | 3.48% | -10.23% | 0.364 |
| 2019 | 26.28% | -4.14% | 2.949 |
| 2020 | 21.21% | -17.98% | 1.081 |
| 2021 | 12.52% | -6.26% | 1.276 |
| 2022 | -11.55% | -13.55% | -0.770 |
| 2023 | 31.22% | -4.28% | 3.031 |
| 2024 | 26.84% | -8.88% | 2.001 |
| 2025 | 20.71% | -10.53% | 1.530 |
| 2026 | 3.45% | -12.32% | 0.275 |

## 尾部诊断

- 年化波动：12.29%
- 最差单日：-5.65%
- 95% Expected Shortfall：-1.83%
- 最长水下期：360个交易日

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_10pct
- PASS：full_drawdown_within_20pct
- PASS：full_sharpe_at_least_100
- PASS：full_calmar_at_least_055
- FAIL：return_lift_vs_sp500_at_least_05pct
- FAIL：return_shortfall_vs_nasdaq_gold_within_35pct
- PASS：drawdown_improvement_vs_nasdaq_gold_at_least_2pct
- PASS：sharpe_at_least_nasdaq_gold
- PASS：return_at_least_global_equal
- PASS：all_four_folds_positive
- PASS：worst_fold_drawdown_within_22pct
- PASS：median_fold_sharpe_at_least_075
- PASS：locked_return_at_least_9pct
- PASS：locked_drawdown_within_18pct
- PASS：locked_sharpe_at_least_080
- PASS：at_least_eight_positive_years
- PASS：annual_turnover_below_1x
- PASS：stress_return_at_least_9pct
- PASS：stress_sharpe_at_least_085
- PASS：worst_day_within_7pct
- PASS：expected_shortfall_95_within_25pct
- PASS：quality_correlation_at_most_035

结论：未通过冻结门槛，归档且不注册。
