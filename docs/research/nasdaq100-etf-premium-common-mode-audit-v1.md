# 境内纳指100 ETF溢价共同模式审计 V1

- 候选：12只。
- 溢价超过5%的占比：100.0%。
- 溢价中位：9.43%。
- 最低：159632.SZ
  8.89%；最高：
  513100.SH 11.56%。
- 横截面范围：2.67%。
- 流动性和容量通过、仅溢价失败：
  11只。
- 分类：`SYSTEM_WIDE_NASDAQ100_QDII_PREMIUM_REGIME`。

## 共同模式门槛

- PASS：at_least_ten_candidates
- PASS：at_least_90pct_above_5pct_premium
- PASS：median_premium_at_least_8pct
- PASS：premium_cross_section_range_within_4pct
- PASS：at_least_eight_liquid_capacity_pass_but_premium_fail

横截面共同状态支持“换另一只纳指100 ETF不能解决当前溢价门槛”，但没有
申购额度等一级数据，因此不把具体因果武断归为QDII额度限制，也不授权替换。
