# 连续现金分红增长 V1

- 数据截止：20260724；研究起点由三年标准分红覆盖决定为2017-05。
- 固定定义：连续三个已实施年报现金分红，两次同比都不下降。
- 分数：两次增长率较小值，经5%/95%缩尾和Z-score；Top40月频等权。
- 与旧 Dividend Quality V2 不同：不使用股息率、ROE、ROA或现金流质量。
- 执行：qfq、M0 T+1、5bps滑点；固定20日组合波动率风险层。
- 与 Quality Balanced Value 日收益相关性：0.631。
- 月度有效候选数：最少 168，中位数
  864，最新 851。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | -5.71% | -41.34% | -0.165 | -0.138 | -39.23% | 4.74x |
| validation | 6.19% | -26.98% | 0.378 | 0.230 | 21.28% | 4.21x |
| locked_test | 1.30% | -37.11% | 0.171 | 0.035 | -25.09% | 6.12x |
| full | 1.09% | -44.43% | 0.161 | 0.025 | -50.66% | 5.10x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2017 | 4.76% | -11.28% | 0.366 |
| 2018 | -35.73% | -35.53% | -1.778 |
| 2019 | 28.06% | -19.04% | 1.217 |
| 2020 | 21.85% | -13.38% | 0.897 |
| 2021 | 19.89% | -10.55% | 1.122 |
| 2022 | -20.87% | -26.98% | -0.846 |
| 2023 | -11.80% | -21.21% | -0.807 |
| 2024 | 12.65% | -22.81% | 0.539 |
| 2025 | 22.51% | -17.31% | 1.077 |
| 2026 | -22.00% | -22.00% | -0.968 |

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
