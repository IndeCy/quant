# 涨停首板封单强度次日轮换 V1

- 研究区间：20230101 至 20260615。
- 每日收盘从非ST、非退市、open_times=0的涨停事件中，按封单额/成交额选前10名。
- T+1开盘经M0换入，持有一个交易日，于下一批目标执行时换出；无事件则现金。
- 基准执行：10bps滑点；压力执行：30bps；佣金、最低佣金、卖出印花税均启用。
- 对照：同日首板按成交额前10名，以及沪深300ETF买入持有。
- 与Quality日收益相关性：0.029。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2023 | -98.71% | -98.47% | -14.296 | -1.002 | 312.1x |
| 2024 | -41.93% | -40.93% | -5.268 | -1.024 | 19.8x |
| 2025_latest | -0.13% | -0.18% | -1.173 | -0.722 | 0.0x |
| locked_test | -0.13% | -0.18% | -1.173 | -0.722 | 0.0x |
| full | -75.85% | -99.09% | -6.762 | -0.766 | 304.2x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| limit_up_first_board_seal_strength_v1 | -75.85% | -99.09% | -6.762 | -0.766 |
| limit_up_first_board_amount_control | -78.32% | -99.36% | -7.641 | -0.788 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2023 | -98.71% | -98.47% | -14.296 |
| 2024 | -41.93% | -40.93% | -5.268 |
| 2025 | -0.19% | -0.18% | -1.407 |
| 2026 | 0.00% | 0.00% | 0.000 |

## 执行与样本诊断

- 信号日：832，有候选日占比：100.12%
- 唯一入选股票：2416
- 实际成交：3262，失败委托：3919
- 失败委托率：54.57%
- 年化波动：20.66%
- 最差单日：-7.61%
- 95% Expected Shortfall：-4.43%
- 最长水下期：832个交易日

## 冻结门槛

- FAIL：full_return_at_least_10pct
- FAIL：full_drawdown_within_30pct
- FAIL：full_sharpe_at_least_075
- FAIL：full_calmar_at_least_035
- FAIL：positive_excess_vs_hs300
- PASS：return_lift_vs_amount_control_at_least_2pct
- PASS：sharpe_lift_vs_amount_control_at_least_010
- FAIL：at_least_two_positive_folds
- FAIL：worst_fold_drawdown_within_35pct
- FAIL：median_fold_sharpe_at_least_055
- FAIL：locked_return_at_least_8pct
- PASS：locked_drawdown_within_30pct
- FAIL：locked_sharpe_at_least_065
- FAIL：at_least_three_positive_years
- FAIL：annual_turnover_below_250x
- FAIL：stress_return_at_least_5pct
- FAIL：stress_sharpe_at_least_055
- FAIL：failed_order_rate_at_most_20pct
- PASS：active_signal_share_at_least_90pct
- PASS：worst_day_within_10pct
- PASS：expected_shortfall_95_within_5pct
- PASS：quality_correlation_at_most_050

结论：未通过冻结门槛，归档且不注册。
