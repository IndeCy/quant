# 交易活跃度稳定性失败归因 V1

- 来源决策：`REJECTED`；分类：
  `BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE`。
- 全期年化/Sharpe/回撤：
  12.34% /
  0.617 /
  -38.92%。
- 回撤门槛短缺：8.92%。
- 年换手：18.24x，为门槛
  1.82倍；全期成本影响：
  67.40%。
- 2024至今/最新年年化：
  6.32% /
  -18.97%。
- 与质量策略收益相关：
  0.7546。

## 冻结归因检查

- PASS：full_drawdown_misses_by_at_least_5pct
- PASS：turnover_is_at_least_1_5x_limit
- PASS：execution_cost_impact_at_least_50pct
- PASS：recent_fold_return_below_8pct
- PASS：latest_year_return_negative
- PASS：quality_correlation_exceeds_gate
- PASS：source_has_multiple_economic_gate_failures

该失败不是成本单因子解释。按预注册规则，不运行方向、窗口、TopN、
调仓频率、风险层或样本变体。
