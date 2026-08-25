# 半导体黄金国债失败统计审计 V1

- 候选与同区间全球防守日收益配对，20日区块Bootstrap
  10000次。
- 原研究的失败门槛不覆盖，不生成权重变体。

## 原样本相对全球防守

- 年化收益差：2.03%
- Sharpe差：-0.263
- 最大回撤改善：-5.45%

## Bootstrap

- P(Sharpe差≥-0.10)：
  37.8%
- P(年化收益差≥-2%)：
  79.4%
- P(回撤改善>0)：
  3.8%
- Sharpe差 P05/中位/P95：
  -0.890 /
  -0.220 /
  0.434

## 冻结判定

- FAIL：sharpe_tolerance_probability_at_least_80pct
- FAIL：return_tolerance_probability_at_least_80pct
- FAIL：drawdown_improvement_probability_at_least_50pct

结论：`INCONCLUSIVE`。原候选继续保持拒绝状态。
