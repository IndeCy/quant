# 纳指黄金60/40相对标普统计支配审计 V1

- 共同日收益：1834；20日配对区块Bootstrap
  10000次。
- 滚动窗口：756交易日，步长21日，共52窗。
- 原历史研究门槛不因本审计而覆盖。

## 原样本

- 年化收益：候选 20.74% /
  标普 16.97% /
  提升 3.78%
- Sharpe：候选 1.205 /
  标普 0.934 /
  提升 0.271
- 最大回撤：候选 -21.71% /
  标普 -29.67% /
  改善 7.96%

## Bootstrap

- P(年化收益提升≥0.5%)：
  80.4%
- P(Sharpe提升≥0.05)：
  87.5%
- P(回撤改善>0)：
  92.2%
- 收益提升 P05/中位/P95：
  -2.99% /
  4.30% /
  11.56%

## 滚动三年

- 收益提升为正占比：76.9%
- Sharpe提升为正占比：86.5%
- 回撤改善为正占比：100.0%
- 收益提升 P10/中位/P90：
  -2.50% /
  2.21% /
  9.11%

## 冻结门槛

- PASS：return_lift_probability_at_least_80pct
- PASS：sharpe_lift_probability_at_least_80pct
- PASS：drawdown_improvement_probability_at_least_80pct
- FAIL：bootstrap_return_lift_p05_above_minus_1pct
- PASS：rolling_positive_return_lift_share_at_least_70pct
- PASS：rolling_positive_sharpe_lift_share_at_least_70pct

结论：`INCONCLUSIVE`。源策略结论保持不变，但统计证据按本审计单独解释。
