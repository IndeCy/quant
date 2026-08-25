# 主线链动趋势状态归因 V1

## 数据边界

- 共同区间：20200615 至 20260724，
  1482 个已分类交易日。
- 状态覆盖率：100.00%。
- 完整 Beta 状态仅有 11 天，未用于历史归因。
- 状态全部滞后一日：T 日收盘识别，解释 T+1 收益。

## 全样本条件表现

| 状态 | 天数 | 占比 | 卫星条件年化 | 卫星条件回撤 | 卫星Sharpe | Core条件年化 | 70/30条件年化 |
|---|---:|---:|---:|---:|---:|---:|---:|
| UP_POSITIVE | 536 | 36.2% | -11.01% | -50.72% | -0.120 | 16.33% | 10.24% |
| UP_NONPOSITIVE | 414 | 27.9% | 33.91% | -23.68% | 1.004 | 11.92% | 19.98% |
| RISK_POSITIVE | 224 | 15.1% | 41.37% | -24.45% | 1.135 | 37.71% | 40.67% |
| RISK_NONPOSITIVE | 308 | 20.8% | 29.20% | -34.15% | 0.805 | -5.89% | 4.82% |

## 分阶段表现

| 阶段 | 状态 | 天数 | 卫星累计 | Core累计 | 70/30累计 |
|---|---|---:|---:|---:|---:|
| 2020_2021 | UP_POSITIVE | 194 | -20.38% | 5.67% | -2.08% |
| 2020_2021 | UP_NONPOSITIVE | 133 | 11.29% | 17.63% | 17.38% |
| 2020_2021 | RISK_POSITIVE | 42 | 1.66% | 9.38% | 7.34% |
| 2020_2021 | RISK_NONPOSITIVE | 10 | 18.81% | -0.85% | 5.02% |
| 2022_2023 | UP_POSITIVE | 60 | -22.61% | 3.75% | -4.91% |
| 2022_2023 | UP_NONPOSITIVE | 118 | 4.04% | -3.75% | -1.33% |
| 2022_2023 | RISK_POSITIVE | 114 | 12.69% | 3.43% | 6.83% |
| 2022_2023 | RISK_NONPOSITIVE | 192 | -12.58% | -2.58% | -5.54% |
| 2024_latest | UP_POSITIVE | 282 | 26.62% | 25.85% | 32.15% |
| 2024_latest | UP_NONPOSITIVE | 163 | 39.54% | 6.28% | 16.47% |
| 2024_latest | RISK_POSITIVE | 68 | 18.75% | 17.48% | 18.11% |
| 2024_latest | RISK_NONPOSITIVE | 106 | 31.69% | -3.88% | 6.78% |

## 连续状态段与门槛

| 状态 | 结论 | 至少5日状态段 | 正收益状态段占比 | 失败项 |
|---|---|---:|---:|---|
| UP_POSITIVE | FAIL | 28 | 25.0% | positive_satellite_return、satellite_sharpe_above_05、satellite_beats_core、conditional_drawdown_within_25pct、all_folds_positive、episode_breadth |
| UP_NONPOSITIVE | FAIL | 26 | 30.8% | episode_breadth |
| RISK_POSITIVE | PASS | 12 | 58.3% | - |
| RISK_NONPOSITIVE | FAIL | 15 | 33.3% | conditional_drawdown_within_25pct、all_folds_positive、episode_breadth |

共识别 170 个连续状态段。

## 结论

状态 RISK_POSITIVE 具备另开条件式卫星研究的资格；本报告本身不改变任何生产仓位。
