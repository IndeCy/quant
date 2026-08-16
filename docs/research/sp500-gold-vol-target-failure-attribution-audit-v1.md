# 标普黄金波动目标失败归因 V1

- 来源结论：`REJECTED`；失败门槛：
  annual_turnover_below_15x, oos_drawdown_within_20pct, worst_fold_drawdown_within_20pct。
- 经济失败簇：2020_drawdown, annual_turnover。
- OOS年化/Sharpe/回撤：
  15.28% /
  1.261 /
  -20.31%。
- 回撤门槛短缺：0.31%；最差年份：
  2020。
- 年换手：1.62x；超限：
  0.12x。
- 相对同机制标普收益/Sharpe提升：
  3.06% /
  0.326。
- 相对直接标普回撤改善：
  9.36%。
- 分类：`CONCENTRATED_BORDERLINE_REJECTION`。

## 归因检查

- PASS：only_expected_checks_failed
- PASS：drawdown_shortfall_within_half_percent
- PASS：oos_and_worst_fold_share_same_drawdown
- PASS：worst_drawdown_year_is_2020
- PASS：turnover_excess_within_point_two
- PASS：same_mechanism_return_lift_positive
- PASS：same_mechanism_sharpe_lift_positive
- PASS：direct_sp500_drawdown_improvement_positive

边界失败仍是失败。本审计不调整门槛、参数或生产注册，也不授权晋级。
