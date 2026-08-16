# 日内强度减隔夜情绪失败归因 V1

- 分类：ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT。
- 全期最大回撤：-97.38%。
- 全期成本影响：18.68%。
- 正收益年度：1。
- 收益分解恒等式最大误差：3.553e-15。
- 与20日动量秩相关中位：0.565。

| 样本 | 年化收益 |
|---|---:|
| train | -21.81% |
| validation | -22.97% |
| locked_test | -19.79% |
| full | -21.19% |

## 失败归因门槛

- PASS：data_identity_passed
- PASS：all_train_validation_locked_returns_negative
- PASS：positive_years_at_most_two
- PASS：full_execution_cost_impact_within_25pct
- PASS：full_drawdown_below_minus_80pct

源策略保持拒绝；禁止在看到结果后反转因子方向、改窗口、改TopN或改样本期。
