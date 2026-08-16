# 纳指黄金60/40资金容量与整手审计 V1

- 截止日：20260728；共同最新交易日：
  20260728。
- 成交额使用未复权日线 amount，源单位千元，换算为人民币元。
- 参与率按一次性建立完整目标仓位计算，比月度再平衡差额更保守。
- 结论：CAPACITY_RISK_FLAGGED。

| 标的 | 权重 | 有效日 | 日成交额中位 | 100万P90 | 100万最新 | 500万P90 |
|---|---:|---:|---:|---:|---:|---:|
| 159941.SZ | 60% | 1835 | 333,880,972 | 64.339% | 0.058% | 321.697% |
| 518880.SH | 40% | 1835 | 1,228,019,964 | 0.072% | 0.022% | 0.362% |

| 本金 | 纳指份额 | 黄金份额 | 余留现金 | 组合总变差 |
|---:|---:|---:|---:|---:|
| 100,000 | 39,100 | 4,700 | 0.541% | 0.541% |
| 500,000 | 195,500 | 23,800 | 0.037% | 0.037% |
| 1,000,000 | 391,100 | 47,600 | 0.021% | 0.021% |
| 5,000,000 | 1,955,600 | 238,000 | 0.018% | 0.018% |

## 冻结门槛

- PASS：fresh_within_five_days
- PASS：each_asset_has_at_least_1800_valid_days
- FAIL：one_million_p90_participation_within_1pct
- PASS：one_million_latest_participation_within_1pct
- PASS：five_million_median_participation_within_1pct
- FAIL：five_million_p90_participation_within_2pct
- FAIL：one_hundred_thousand_tracking_tv_within_05pct
- PASS：all_capital_cases_hold_both_assets

本审计不改源策略权重或历史研究结论，也不代表已具备实时申购赎回、
IOPV或盘中折溢价控制。
