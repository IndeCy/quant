# A股因子低换手优势统计审计 V1

- 低/高换手家族：12 /
  10。
- 原始锁定收益中位差：9.15%。
- Bootstrap差值为正概率：
  83.44%。
- Bootstrap差值至少3个百分点概率：
  71.91%。
- 差值P05/中位/P95：-2.83% /
  8.69% / 18.33%。
- 单侧置换p值：0.0103。
- 分类：LOWER_TURNOVER_ADVANTAGE_STATISTICALLY_SUPPORTED。

## 冻结门槛

- PASS：probability_positive_difference_at_least_80pct
- PASS：probability_difference_at_least_3pct_at_least_70pct
- PASS：one_sided_permutation_pvalue_within_10pct
- PASS：bootstrap_difference_p05_above_minus_3pct

这只是31个研究家族之间的描述性推断。即使低换手分布更好，也不代表低频
策略产生Alpha；所有换手层的锁定核心通过数仍为0。
