# 纳指×黄金×A股红利低波固定等权 V1

- 数据共同截止：20260728。
- 固定持有纳指100ETF、黄金ETF、红利低波ETF，各三分之一。
- 月末恢复等权；不择时、不做权重网格、不叠加风险层。
- 信号下一交易日经M0执行，统一qfq、5bps，ETF免印花税。
- 直接机会成本：场内标普500、纳指/黄金60/40、全球防守三资产等权。
- 与Quality日收益相关性：0.515。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2020_2021 | 18.51% | -15.31% | 1.253 | 1.208 | 0.85x |
| 2022_2023 | 9.64% | -9.41% | 0.885 | 1.024 | 0.41x |
| 2024_latest | 21.42% | -13.14% | 1.478 | 1.631 | 0.42x |
| locked_test | 21.42% | -13.14% | 1.478 | 1.631 | 0.42x |
| full | 17.02% | -15.31% | 1.255 | 1.112 | 0.51x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| nasdaq_gold_china_dividend_equal_v1 | 17.02% | -15.31% | 1.255 | 1.112 |
| nasdaq_gold_60_40_dividend_control | 18.83% | -21.57% | 1.067 | 0.873 |
| global_defensive_dividend_control | 11.27% | -12.97% | 1.205 | 0.869 |
| sp500_direct_dividend_control | 14.88% | -29.26% | 0.812 | 0.509 |
| dividend_lowvol_direct_control | 12.74% | -14.61% | 0.794 | 0.872 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2020 | 22.27% | -15.31% | 1.213 |
| 2021 | 14.84% | -5.33% | 1.487 |
| 2022 | -5.85% | -9.41% | -0.390 |
| 2023 | 27.37% | -3.28% | 2.936 |
| 2024 | 30.21% | -7.63% | 2.316 |
| 2025 | 25.57% | -7.35% | 1.968 |
| 2026 | -0.89% | -13.14% | 0.050 |

## 尾部诊断

- 年化波动：13.24%
- 最差单日：-6.13%
- 95% Expected Shortfall：-2.01%
- 最长水下期：235个交易日

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_10pct
- PASS：full_drawdown_within_22pct
- PASS：full_sharpe_at_least_090
- PASS：full_calmar_at_least_045
- PASS：return_lift_vs_sp500_at_least_05pct
- PASS：sharpe_lift_vs_sp500_at_least_010
- PASS：return_at_least_global_equal
- PASS：return_shortfall_vs_nasdaq_gold_within_4pct
- PASS：drawdown_worse_vs_nasdaq_gold_within_2pct
- PASS：all_three_folds_positive
- PASS：worst_fold_drawdown_within_24pct
- PASS：median_fold_sharpe_at_least_065
- PASS：locked_return_at_least_9pct
- PASS：locked_drawdown_within_20pct
- PASS：locked_sharpe_at_least_075
- PASS：at_least_five_positive_years
- PASS：annual_turnover_below_1x
- PASS：stress_return_at_least_9pct
- PASS：stress_sharpe_at_least_080
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_3pct
- FAIL：quality_correlation_at_most_050

结论：未通过冻结门槛，归档且不注册。
