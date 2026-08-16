# 连续现金分红增长 V2

- 数据截止：20260724。
- V1 缺陷：多年未再分红的股票会永久保留历史增长资格。
- V2 唯一修复：最新已实施年报必须距信号年1至2个财年。
- 因子、Top40、月频、M0、风险层和样本分段均与V1一致。
- 与 Quality Balanced Value 日收益相关性：0.641。
- 月度有效候选数：最少 168，中位数
  758，最新 733。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | -5.64% | -41.34% | -0.162 | -0.136 | -39.06% | 4.61x |
| validation | 5.87% | -29.31% | 0.367 | 0.200 | 20.23% | 4.54x |
| locked_test | 0.62% | -38.12% | 0.137 | 0.016 | -27.45% | 5.07x |
| full | 0.71% | -43.72% | 0.142 | 0.016 | -54.36% | 4.76x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2017 | 4.76% | -11.28% | 0.366 |
| 2018 | -35.73% | -35.53% | -1.778 |
| 2019 | 28.31% | -19.32% | 1.228 |
| 2020 | 20.19% | -14.83% | 0.858 |
| 2021 | 18.32% | -8.94% | 1.074 |
| 2022 | -19.13% | -29.31% | -0.747 |
| 2023 | -15.93% | -25.08% | -1.140 |
| 2024 | 4.70% | -20.24% | 0.302 |
| 2025 | 32.17% | -16.19% | 1.494 |
| 2026 | -19.46% | -21.15% | -0.855 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：annual_turnover_below_8x
- FAIL：at_least_seven_positive_years
- PASS：quality_correlation_at_most_075

结论：终止，不注册生产策略。
