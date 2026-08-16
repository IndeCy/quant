# Quality Balanced Value 缓冲调仓 V2

- 数据截止：20260727。
- Alpha、股票池、月频信号、M0 T+1 和日频风险层均保持不变。
- 唯一改动：Top20进入，已有持仓跌出Top40后退出；没有参数网格。
- 本研究只产生实验记录，不修改生产策略与调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_balanced_value_unbuffered_v1 | 2015_2017 | 24.96% | -25.46% | 1.042 | 0.980 | 75.70% | 10.45x |
| quality_balanced_value_unbuffered_v1 | 2018_2020 | 3.67% | -24.56% | 0.281 | 0.150 | -22.73% | 5.69x |
| quality_balanced_value_unbuffered_v1 | 2021_2023 | 5.34% | -24.84% | 0.376 | 0.215 | 47.64% | 5.82x |
| quality_balanced_value_unbuffered_v1 | 2024_latest | 18.53% | -19.48% | 0.921 | 0.951 | 4.36% | 6.69x |
| quality_balanced_value_unbuffered_v1 | locked_test | 8.25% | -24.84% | 0.499 | 0.332 | 36.20% | 6.33x |
| quality_balanced_value_unbuffered_v1 | full | 12.96% | -25.46% | 0.687 | 0.509 | 231.22% | 6.96x |
| quality_balanced_value_buffered_v2 | 2015_2017 | 24.74% | -26.36% | 1.048 | 0.939 | 74.75% | 8.22x |
| quality_balanced_value_buffered_v2 | 2018_2020 | 1.23% | -27.98% | 0.161 | 0.044 | -30.14% | 3.61x |
| quality_balanced_value_buffered_v2 | 2021_2023 | 2.96% | -24.37% | 0.250 | 0.122 | 40.24% | 3.90x |
| quality_balanced_value_buffered_v2 | 2024_latest | 17.55% | -21.45% | 0.892 | 0.818 | 1.31% | 4.46x |
| quality_balanced_value_buffered_v2 | locked_test | 9.07% | -24.37% | 0.538 | 0.372 | 40.95% | 4.28x |
| quality_balanced_value_buffered_v2 | full | 11.37% | -27.98% | 0.622 | 0.406 | 174.40% | 4.92x |

## 持仓稳定性

- 原策略月度替换比例中位数：
  20.00%。
- 缓冲策略月度替换比例中位数：
  10.00%。
- 缓冲策略平均持仓保留率：
  84.82%。
- M0成交口径年化换手降幅：
  29.29%。

## 20bps成本压力

- 年化收益：10.39%。
- 最大回撤：-28.49%。
- Sharpe：0.579。

## 中盘风格诊断

- 原策略对“510500－510300”年度收益相关/Beta：
  0.635 /
  0.831。
- 缓冲策略对“510500－510300”年度收益相关/Beta：
  0.587 /
  0.790。
- 该项仅做归因，不因缓冲组合预期外地承担风格中性化功能。

## 缓冲策略年度表现

| 年份 | 年化收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 72.64% | -24.51% | 1.823 |
| 2016 | 9.97% | -13.96% | 0.558 |
| 2017 | 9.63% | -9.45% | 0.919 |
| 2018 | -22.45% | -27.98% | -1.235 |
| 2019 | 24.27% | -19.32% | 1.299 |
| 2020 | 8.08% | -18.20% | 0.464 |
| 2021 | 10.95% | -16.32% | 0.660 |
| 2022 | -21.21% | -24.37% | -0.922 |
| 2023 | 20.23% | -8.44% | 1.452 |
| 2024 | 13.92% | -18.35% | 0.655 |
| 2025 | 10.81% | -11.84% | 0.739 |
| 2026 | 41.79% | -13.63% | 1.823 |

## 预注册门槛

- PASS：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- PASS：full_drawdown_within_30pct
- PASS：locked_annual_return_at_least_8pct
- FAIL：locked_sharpe_at_least_055
- PASS：locked_drawdown_within_30pct
- FAIL：turnover_reduced_by_at_least_30pct
- FAIL：full_return_drag_within_1pct
- PASS：locked_return_drag_within_1pct
- FAIL：full_drawdown_worsening_within_2pct
- PASS：locked_drawdown_worsening_within_2pct
- PASS：stress_20bps_annual_return_at_least_9pct
- PASS：stress_20bps_sharpe_at_least_055
- PASS：positive_three_year_fold_share_at_least_75pct
- PASS：median_monthly_replacement_at_most_25pct

结论：REJECTED_NO_PRODUCTION_CHANGE。
