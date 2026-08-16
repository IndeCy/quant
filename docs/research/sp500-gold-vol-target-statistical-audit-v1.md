# 标普黄金波动目标统计优势 V1

- 共同日收益：1834；配对20日区块Bootstrap：
  10000次。
- 对照为相同12%波动目标机制的纯标普，不是直接满仓标普。
- 原样本年化收益提升：3.07%；
  Sharpe提升：0.327；
  回撤改善：3.06%。
- P(收益提升≥1%)：78.5%；
  P(Sharpe提升≥0.10)：
  90.0%；
  P(回撤改善>0)：
  86.2%。
- 收益提升Bootstrap P05/中位/P95：
  -1.26% /
  3.09% /
  7.44%。
- 滚动三年收益/Sharpe提升为正占比：
  69.2% /
  86.5%。
- 分类：`INCONCLUSIVE`。

## 冻结门槛

- FAIL：return_lift_probability_at_least_80pct
- PASS：sharpe_lift_probability_at_least_80pct
- PASS：drawdown_improvement_probability_at_least_80pct
- FAIL：bootstrap_return_lift_p05_above_minus_1pct
- FAIL：rolling_positive_return_lift_share_at_least_70pct
- PASS：rolling_positive_sharpe_lift_share_at_least_70pct

统计通过也不覆盖来源策略的冻结拒绝，不修改参数，不构成生产晋级。
