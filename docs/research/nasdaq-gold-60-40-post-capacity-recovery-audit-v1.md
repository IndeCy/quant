# 纳指黄金60/40容量恢复后表现审计 V1

- 容量恢复起点：20230228；收益样本从下一交易日
  20230301 开始，到 20260728。
- 共同收益日：827。
- 分类：POST_CAPACITY_EVIDENCE_PASSED。

## 相对场内标普500

- 候选年化：29.19%；
  标普年化：21.78%；
  差值：7.41%。
- Sharpe 差：0.416；最大回撤改善：
  7.77%。
- Bootstrap达到收益差0.5%的概率：
  81.63%。
- Bootstrap达到Sharpe差0.05的概率：
  82.56%。
- Bootstrap回撤改善为正的概率：
  83.57%。

| 完整年度 | 交易日 | 候选 | 场内标普 |
|---:|---:|---:|---:|
| 2024 | 242 | 32.32% | 34.87% |
| 2025 | 243 | 30.97% | 12.49% |

## 冻结门槛

- PASS：annualized_return_lift_vs_sp500_at_least_1pct
- PASS：sharpe_lift_vs_sp500_at_least_010
- PASS：drawdown_worse_vs_sp500_within_2pct
- PASS：return_lift_probability_at_least_70pct
- PASS：sharpe_lift_probability_at_least_70pct
- PASS：drawdown_improvement_probability_at_least_70pct
- PASS：all_full_calendar_years_positive

样本起点完全由成交容量恢复确定，不读取收益择时。本审计不覆盖源容量风险，
也不把2019至2022的历史回测追认为可成交。
