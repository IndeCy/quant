# 标准化意外盈利数据可行性 V1

- 数据截止：20260724。
- 月度信号数：138。
- 点时候选记录：245992。
- 候选数最少/中位/最新：
  2 /
  943 /
  1659。
- Top20可构造月份：92.03%。
- 公告日违规：0；
  重复键：0。
- 覆盖年份：12。

## 分阶段Top20可构造率

- 2015_2018：95.83%
- 2019_2021：94.44%
- 2022_latest：87.04%

## 固定门槛

- PASS：no_asof_violations
- PASS：no_event_age_violations
- PASS：no_history_observation_violations
- PASS：no_duplicate_signal_symbol
- FAIL：all_months_constructible
- PASS：median_candidates_at_least_100
- PASS：latest_candidates_at_least_100
- FAIL：each_fold_constructible_at_least_95pct
- PASS：at_least_10_years

结论：数据覆盖不足，停止于回测前。
