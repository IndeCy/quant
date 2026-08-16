# Quality LowBeta Study

## 固定定义

- 因子：ROA、OCF_TO_OR、120日低Beta、60日低波，1%/99%缩尾后Z-score等权。
- 股票池：Quality Cleanup，Top40等权，月频调仓。
- 风险层：20日组合波动率大于45%时降至30%，否则100%。
- 执行：qfq、M0 ExecutionModel、T+1、5bps滑点。

## 全历史结果

| 年化收益 | 最大回撤 | Sharpe | Calmar | 总收益 | 超额收益 | 年化换手率 |
|---:|---:|---:|---:|---:|---:|---:|
| 2.74% | -38.82% | 0.245 | 0.071 | 35.16% | -22.87% | 774.71% |

## 年度收益

| 年份 | 收益 |
|---:|---:|
| 2015 | -10.20% |
| 2016 | 3.72% |
| 2017 | 0.42% |
| 2018 | -27.55% |
| 2019 | 17.35% |
| 2020 | 1.11% |
| 2021 | 31.03% |
| 2022 | -6.06% |
| 2023 | 8.54% |
| 2024 | 21.23% |
| 2025 | 2.32% |
| 2026 | 5.85% |

## 固定晋级门槛

- FAIL：annualized_return_at_least_10pct
- FAIL：max_drawdown_within_25pct
- FAIL：sharpe_at_least_065
- FAIL：calmar_at_least_045
- FAIL：positive_excess_return

结论：终止，不注册生产策略。
