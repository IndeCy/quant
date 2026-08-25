# 主线链动 RISK_POSITIVE 条件式卫星 V1

## 固定定义

- 状态：前一交易日 `MA60 < MA120` 且上证20日收益为正。
- 状态满足时：Quality Core 70% + 主线链动30%。
- 其他时间：Quality Core 100%。
- 状态在 T 日收盘可见，T+1 切换；调拨成本10bps。
- 共同区间：20200615 至 20260724。
- 卫星启用交易日占比：15.11%，发生 49 次切换。

## 组合对照

| 阶段 | 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额 | 调拨换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| 2020_2021 | conditional | 20.26% | -10.87% | 1.422 | 1.864 | 3.60% | 1.39x |
| 2020_2021 | fixed_70_30 | 18.85% | -7.43% | 1.471 | 2.535 | 1.29% | 0.22x |
| 2020_2021 | core | 22.03% | -10.87% | 1.500 | 2.027 | 6.53% | 0.00x |
| 2022_2023 | conditional | 0.67% | -15.78% | 0.117 | 0.042 | 28.96% | 3.77x |
| 2022_2023 | fixed_70_30 | -3.32% | -17.48% | -0.148 | -0.190 | 21.41% | 0.14x |
| 2022_2023 | core | -0.53% | -16.83% | 0.024 | -0.032 | 26.66% | 0.00x |
| 2024_latest | conditional | 17.89% | -13.54% | 1.060 | 1.322 | 3.77% | 2.20x |
| 2024_latest | fixed_70_30 | 30.16% | -13.94% | 1.444 | 2.164 | 44.94% | 0.26x |
| 2024_latest | core | 17.68% | -13.54% | 1.113 | 1.306 | 3.11% | 0.00x |
| full | conditional | 13.08% | -15.78% | 0.891 | 0.829 | 72.83% | 2.50x |
| full | fixed_70_30 | 15.91% | -17.48% | 0.975 | 0.910 | 104.97% | 0.21x |
| full | core | 12.98% | -16.83% | 0.917 | 0.771 | 71.72% | 0.00x |

## 冻结门槛

- PASS：annual_return_at_least_core
- FAIL：sharpe_at_least_core
- PASS：drawdown_worse_than_core_within_1pct
- PASS：drawdown_within_20pct
- PASS：positive_excess
- PASS：all_folds_positive
- PASS：repair_2022_2023_to_positive
- FAIL：sharpe_at_least_fixed_70_30
- PASS：allocation_turnover_below_3x
- PASS：annualized_cost_drag_below_1pct
- PASS：active_day_share_between_10_and_30pct

## 重要限制

`RISK_POSITIVE` 来自同一段历史的先验归因，本实验不是独立样本外验证。
通过历史门槛只代表值得前向观察，不代表可生产晋级。

## 结论

历史门槛未通过，停止该条件式卫星方向。
