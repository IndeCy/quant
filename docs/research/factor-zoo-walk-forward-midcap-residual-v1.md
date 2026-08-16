# 因子动物园走步中盘残差审计 V1

- 数据截止：20260728。
- 验证期Beta训练：2015–2018；验证：2019–2021。
- 锁定期Beta训练：2015–2021；锁定：2022–2026。
- 残差只扣除训练期估计的中证500相对沪深300斜率，保留截距作为候选Alpha。
- 本审计已经使用既有历史结果做元诊断，不具备生产晋级效力。

## 总体结果

- 完整候选：30 个。
- 验证期平均残差为正：
  5 个。
- 锁定期平均残差为正：
  5 个。
- 两段平均残差同时为正：
  1 个。
- 五项门槛全部通过：
  0 个。
- 候选中位验证/锁定残差：
  -9.28% /
  -6.92%。

## 最接近门槛的候选

| 实验 | 通过项 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正收益年 | 锁定IR | 最差锁定年 | 失败项 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| earnings_surprise_event_v1 | 4/5 | 1.46 | 1.44 | -5.10% | 3.21% | 80% | 0.260 | -15.57% | validation_mean_residual_positive |
| earnings_surprise_event_rank_v2 | 4/5 | 0.85 | 0.91 | 0.39% | 1.08% | 60% | 0.111 | -13.07% | locked_residual_information_ratio_at_least_025 |
| insider_net_buying_v1 | 3/5 | 2.14 | 2.17 | -2.99% | 2.08% | 60% | 0.236 | -7.81% | validation_mean_residual_positive, locked_residual_information_ratio_at_least_025 |
| fund_ownership_breadth_v1 | 3/5 | 0.43 | 0.19 | 7.74% | -1.28% | 60% | -0.124 | -17.31% | locked_mean_residual_positive, locked_residual_information_ratio_at_least_025 |
| low_residual_volatility_120d_v1 | 2/5 | 1.19 | 1.26 | -15.70% | 4.24% | 60% | 0.202 | -29.18% | validation_mean_residual_positive, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |
| earnings_forecast_momentum_v1 | 2/5 | 1.91 | 1.79 | -5.50% | 2.46% | 40% | 0.172 | -9.25% | validation_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025 |
| block_trade_premium_v1 | 2/5 | 1.42 | 1.44 | 3.54% | -4.64% | 40% | -0.562 | -13.82% | locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025 |
| low_accrual_quality_v1 | 1/5 | 1.60 | 1.40 | -7.04% | -2.44% | 60% | -0.190 | -20.28% | validation_mean_residual_positive, locked_mean_residual_positive, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |
| low_return_skewness_60d_v1 | 1/5 | 2.14 | 2.12 | -1.85% | -2.66% | 40% | -0.202 | -19.73% | validation_mean_residual_positive, locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025 |
| monthly_seasonality_v1 | 1/5 | 1.50 | 1.38 | -6.32% | -2.74% | 40% | -0.431 | -9.60% | validation_mean_residual_positive, locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025 |
| shareholder_concentration_v1 | 1/5 | 1.16 | 1.17 | 13.16% | -8.40% | 40% | -0.467 | -37.05% | locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |
| profitability_floor_5y_v1 | 1/5 | 0.63 | 0.45 | 3.67% | -6.96% | 20% | -0.684 | -22.74% | locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |
| operating_profitability_v1 | 1/5 | 1.49 | 1.27 | -12.46% | -6.99% | 0% | -0.893 | -17.10% | validation_mean_residual_positive, locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025 |
| low_max_lottery_avoidance_v1 | 0/5 | 1.39 | 1.41 | -14.05% | -4.58% | 40% | -0.256 | -33.42% | validation_mean_residual_positive, locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |
| abnormal_inventory_accumulation_v1 | 0/5 | 3.19 | 2.84 | -14.49% | -6.72% | 40% | -0.346 | -34.10% | validation_mean_residual_positive, locked_mean_residual_positive, locked_positive_year_share_at_least_60pct, locked_residual_information_ratio_at_least_025, locked_worst_residual_within_20pct |

## 判定

- 结论：`NO_EXISTING_FACTOR_PASSES_STYLE_RESIDUAL_GATE`。
- 旧因子的正收益大多无法在剔除中盘风格后跨验证与锁定窗口稳定保留。
- `earnings_surprise_event_v1` 的锁定残差较强，但验证期残差为负。
- `earnings_surprise_event_rank_v2` 两段残差均为正，但锁定期残差信息比率不足。
- 后续不能从这30个失败定义里继续挑历史最好者；有效证据只能来自全新定义的多折研究，
  或冻结后的前瞻Paper。
