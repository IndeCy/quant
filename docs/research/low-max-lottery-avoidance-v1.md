# 低 MAX 彩票偏好规避 V1

- 数据截止：20260724。
- 固定因子：过去20个交易日最大单日qfq收益，越低越好。
- 执行：Top40月频等权，qfq、M0 T+1、5bps滑点及固定风险层。
- 与 Quality Balanced Value 日收益相关性：0.822。
- 与60日波动率截面Spearman中位数：
  0.611。
- 与低波Top40持仓重叠中位数：
  32.5%，最新
  12.5%。
- 月度有效候选数：最少 1456，中位数
  2476，最新 4030。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | -5.33% | -62.66% | -0.144 | -0.085 | -6.60% | 21.76x |
| validation | 8.35% | -18.75% | 0.604 | 0.445 | -47.90% | 19.31x |
| locked_test | -1.38% | -29.19% | -0.008 | -0.047 | -10.08% | 20.86x |
| full | -0.37% | -65.75% | 0.069 | -0.006 | -59.97% | 20.90x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 65.56% | -37.84% | 1.723 |
| 2016 | -3.37% | -17.17% | -0.093 |
| 2017 | -7.11% | -13.39% | -0.707 |
| 2018 | -42.31% | -43.58% | -3.053 |
| 2019 | 18.77% | -14.68% | 1.173 |
| 2020 | -6.08% | -14.57% | -0.263 |
| 2021 | 13.03% | -8.66% | 1.150 |
| 2022 | -19.69% | -24.07% | -1.217 |
| 2023 | -1.23% | -13.57% | -0.059 |
| 2024 | 16.96% | -14.66% | 0.851 |
| 2025 | 8.92% | -7.03% | 0.776 |
| 2026 | -14.73% | -15.95% | -0.894 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：annual_turnover_below_8x
- FAIL：at_least_nine_positive_years
- FAIL：quality_correlation_at_most_075

结论：终止，不注册生产策略。
