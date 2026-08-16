# Quality Value LowVol Risk Recovery Study

## 固定规则

- 20日组合年化波动率大于45%：下一交易日仓位降至30%。
- 连续稳定3日、相对受限后低点回撤修复至少2%后，按30%→50%→70%→100%恢复。
- 仍为CRITICAL时不得从30%/50%上调；恢复满仓前必须为NORMAL。
- Alpha、股票池、Top20、月频、M0和交易成本保持不变。

## 结果

| 方案 | 年化收益 | 最大回撤 | Sharpe | Calmar | 总收益 | 执行成本 |
|---|---:|---:|---:|---:|---:|---:|
| 原波动率开关 | 11.48% | -31.26% | 0.635 | 0.367 | 235.40% | 239115.12 |
| 分级恢复状态机 | 9.53% | -35.71% | 0.585 | 0.267 | 175.42% | 177700.32 |

## 晋级门槛

- FAIL：annualized_return_at_least_10pct
- FAIL：max_drawdown_within_25pct
- FAIL：calmar_at_least_045
- PASS：execution_cost_not_worse_10pct

最终结论：终止该策略，转向下一策略。

风险状态迁移次数：16。
