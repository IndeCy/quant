# 全球防守核心 × A股主线卫星 80/20 V2

- 严格共同区间：20200615 至 20260728，
  1483 个交易日。
- Core 80%：全球防守三资产固定等权 V1。
- Satellite 20%：A股主线链动 V1；权重上限预先固定，不因回测结果调整。
- 两个袖套均读取 monitoring 净成本净值；不重跑或改变底层策略。
- 每月末形成调拨信号，下一交易日恢复 80/20，月内权重自然漂移。
- 基准调拨成本 10bps，累计成本 0.001315 净值单位，
  全期净值拖累 0.18%。

| 阶段 | 袖套 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额 | 调拨换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| 2020_2021 | combined | 8.81% | -6.54% | 1.125 | 1.346 | -14.77% | 0.11x |
| 2020_2021 | core | 8.78% | -7.17% | 1.158 | 1.224 | -14.82% | 0.00x |
| 2020_2021 | satellite | 4.62% | -26.62% | 0.304 | 0.174 | -21.26% | 0.00x |
| 2022_2023 | combined | 4.11% | -7.78% | 0.476 | 0.528 | 35.68% | 0.10x |
| 2022_2023 | core | 7.57% | -6.48% | 1.065 | 1.169 | 42.66% | 0.00x |
| 2022_2023 | satellite | -11.19% | -37.45% | -0.139 | -0.299 | 7.38% | 0.00x |
| 2024_latest | combined | 25.05% | -13.81% | 1.713 | 1.813 | 29.67% | 0.20x |
| 2024_latest | core | 16.86% | -12.97% | 1.495 | 1.300 | 3.07% | 0.00x |
| 2024_latest | satellite | 44.72% | -41.73% | 1.036 | 1.072 | 104.65% | 0.00x |
| full | combined | 13.77% | -13.81% | 1.226 | 0.997 | 82.56% | 0.15x |
| full | core | 11.70% | -12.97% | 1.285 | 0.902 | 60.67% | 0.00x |
| full | satellite | 14.00% | -43.77% | 0.533 | 0.320 | 85.03% | 0.00x |

## 年度表现

| 年份 | 组合 | Core | Satellite | 组合最大回撤 |
|---|---:|---:|---:|---:|
| 2020 | 4.28% | 5.32% | 0.00% | -5.76% |
| 2021 | 8.64% | 7.47% | 7.01% | -6.54% |
| 2022 | 0.50% | -0.62% | 0.97% | -7.78% |
| 2023 | 7.58% | 15.85% | -21.06% | -3.32% |
| 2024 | 32.23% | 22.48% | 67.15% | -6.64% |
| 2025 | 41.46% | 21.16% | 123.29% | -9.91% |
| 2026 | -8.10% | -2.89% | -31.32% | -13.81% |

## 独立性与尾部风险

- Core / Satellite 日收益相关性：0.118。
- 组合 / Quality 日收益相关性：0.298。
- 最差单日：-5.41%。
- 95% Expected Shortfall：-1.57%。
- 最长水下期：252 个共同交易日。
- 正收益年份：6 / 7。

## 成本压力

| 场景 | 年化收益 | 最大回撤 | Sharpe | Calmar | 全期成本拖累 |
|---|---:|---:|---:|---:|---:|
| 10bps 基准 | 13.77% | -13.81% | 1.226 | 0.997 | 0.18% |
| 50bps 压力 | 13.71% | -13.82% | 1.221 | 0.992 | 0.92% |

## 冻结门槛

- PASS：history_audit
- PASS：sleeve_correlation_at_most_035
- PASS：quality_correlation_at_most_045
- PASS：full_annual_return_at_least_10pct
- PASS：full_drawdown_within_18pct
- PASS：full_sharpe_at_least_100
- PASS：full_calmar_at_least_060
- PASS：full_positive_excess
- PASS：return_lift_vs_core_at_least_03pct
- PASS：sharpe_shortfall_vs_core_within_010
- PASS：drawdown_worse_than_core_within_3pct
- PASS：all_folds_positive
- PASS：worst_fold_drawdown_within_20pct
- PASS：median_fold_sharpe_at_least_075
- PASS：at_least_five_positive_years
- PASS：allocation_turnover_below_1x
- PASS：base_cost_drag_within_05pct
- PASS：stress_50bps_return_at_least_95pct
- PASS：stress_50bps_drawdown_within_19pct
- PASS：stress_50bps_sharpe_at_least_095
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_25pct
- PASS：max_underwater_within_504_days

## 结论

通过冻结研究门槛；只允许进入组合级前向 Paper 观察，不自动注册或接入调度。

本研究只验证两个既有净成本袖套的固定组合，不证明主线卫星自身已经解决
尾部不稳定问题。即使通过，也必须先做组合级前向 Paper，且不得自动启动
scheduler、生成实盘订单或替代底层策略。
