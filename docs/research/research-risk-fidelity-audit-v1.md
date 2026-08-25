# 研究风险层实现一致性审计 V1

- 审计日期：20260726。
- 受影响历史研究：38项。
- 已按新指纹重跑：38项。
- 待复验：0项。
- 静态围栏：PASS。

## 已复验

| 实验 | 最新结论 | 最新运行 |
|---|---|---|
| low_return_skewness_60d_v1 | REJECTED | `low_return_skewness_60d_v1:20260726:064726792159` |
| factor_multifold_revalidation_v1 | REJECTED | `factor_multifold_revalidation_v1:20260726:070241122944` |
| gross_margin_expansion_fresh_rank_v2 | REJECTED | `gross_margin_expansion_fresh_rank_v2:20260726:070428403985` |
| price_high_breakout_252d_v2 | REJECTED | `price_high_breakout_252d_v2:20260726:070526605337` |
| abnormal_inventory_accumulation_v1 | REJECTED | `abnormal_inventory_accumulation_v1:20260726:075356818304` |
| low_accrual_quality_v1 | REJECTED | `low_accrual_quality_v1:20260726:073931089892` |
| amihud_illiquidity_60d_v1 | REJECTED | `amihud_illiquidity_60d_v1:20260726:074851291430` |
| asset_turnover_change_v1 | REJECTED | `asset_turnover_change_v1:20260726:075356820233` |
| block_trade_premium_v1 | REJECTED | `block_trade_premium_v1:20260726:080142104739` |
| capitulation_volume_reversal_v1 | REJECTED | `capitulation_volume_reversal_v1:20260726:080242825584` |
| cash_conversion_cycle_change_v1 | REJECTED | `cash_conversion_cycle_change_v1:20260726:075544685649` |
| dividend_growth_persistence_v1 | REJECTED | `dividend_growth_persistence_v1:20260726:081007119075` |
| dividend_growth_persistence_v2 | REJECTED | `dividend_growth_persistence_v2:20260726:081045817488` |
| dividend_growth_persistence_v3 | REJECTED | `dividend_growth_persistence_v3:20260726:081130985405` |
| downside_beta_252d_v1 | REJECTED | `downside_beta_252d_v1:20260726:074701436394` |
| earnings_express_acceleration_v1 | REJECTED | `earnings_express_acceleration_v1:20260726:081219866685` |
| earnings_express_acceleration_v2 | REJECTED | `earnings_express_acceleration_v2:20260726:071704760016` |
| earnings_forecast_momentum_v1 | REJECTED | `earnings_forecast_momentum_v1:20260726:071359089725` |
| earnings_stability_5y_v1 | REJECTED | `earnings_stability_5y_v1:20260726:073501307949` |
| earnings_surprise_event_v1 | REJECTED | `earnings_surprise_event_v1:20260726:072846873832` |
| fund_ownership_breadth_v1 | REJECTED | `fund_ownership_breadth_v1:20260726:072935381267` |
| gross_margin_expansion_v1 | REJECTED | `gross_margin_expansion_v1:20260726:075544687248` |
| gross_profitability_v1 | REJECTED | `gross_profitability_v1:20260726:073311089876` |
| insider_net_buying_v1 | REJECTED | `insider_net_buying_v1:20260726:071607087564` |
| intraday_strength_vs_overnight_20d_v1 | REJECTED | `intraday_strength_vs_overnight_20d_v1:20260726:080426199828` |
| low_asset_growth_v1 | REJECTED | `low_asset_growth_v1:20260726:074030680679` |
| low_max_lottery_avoidance_v1 | REJECTED | `low_max_lottery_avoidance_v1:20260726:074701414102` |
| margin_financing_flow_v1 | REJECTED | `margin_financing_flow_v1:20260726:080613459281` |
| monthly_seasonality_v1 | REJECTED | `monthly_seasonality_v1:20260726:081309308006` |
| net_debt_financing_strict_st_v2 | REJECTED | `net_debt_financing_strict_st_v2:20260726:074139867054` |
| operating_profitability_v1 | REJECTED | `operating_profitability_v1:20260726:073356330473` |
| piotroski_value_v1 | REJECTED | `piotroski_value_v1:20260726:074236960183` |
| price_high_proximity_252d_v1 | REJECTED | `price_high_proximity_252d_v1:20260726:074851247641` |
| profitability_floor_5y_v1 | REJECTED | `profitability_floor_5y_v1:20260726:073553179807` |
| low_residual_volatility_120d_v1 | REJECTED | `low_residual_volatility_120d_v1:20260726:072603952430` |
| shareholder_concentration_v1 | REJECTED | `shareholder_concentration_v1:20260726:071757313376` |
| signed_amount_pressure_v1 | REJECTED | `signed_amount_pressure_v1:20260726:081455647807` |
| smooth_skip_month_momentum_120d_v1 | REJECTED | `smooth_skip_month_momentum_120d_v1:20260726:072705422709` |

## 待复验

| 实验 | 治理状态 | 旧结论 |
|---|---|---|


## 口径说明

- `GRID`：20日组合波动率超过45%时，下一交易日目标仓位降至30%。
- `FIXED`：不应用该波动率覆盖层；传入阈值参数也不会生效。
- 待复验实验的旧结果仍保留用于审计，但不能作为风险层有效性证据。
- 明确声明无覆盖层或使用独立状态控制器的研究不属于缺陷。

结论：源码错配已经修复并由总验收阻断复发；历史研究仍在分批复验，
完成前不得用待复验结果晋级生产策略。
