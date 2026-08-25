# 全球防守90%×红利低波10%容量可行性 V1

- 固定资金：1,000,000元；最大参与率：
  1.0%。
- 权重先验固定为标普/黄金/国债各30%，红利低波10%。
- 本阶段不计算组合收益。

| 代码 | 资产 | 权重 | 初始订单 | 日成交额中位 | 参与率中位 | 参与率P90 |
|---|---|---:|---:|---:|---:|---:|
| 513500.SH | 标普500ETF | 30% | 300,000 | 184,513,785 | 0.163% | 0.717% |
| 518880.SH | 黄金ETF | 30% | 300,000 | 1,287,676,774 | 0.023% | 0.055% |
| 511010.SH | 5年国债ETF | 30% | 300,000 | 259,664,706 | 0.116% | 0.491% |
| 512890.SH | 红利低波ETF | 10% | 100,000 | 31,222,453 | 0.320% | 11.268% |

## 冻结门槛

- PASS：all_four_assets_present
- PASS：common_days_at_least_1800
- PASS：monthly_signals_at_least_75
- PASS：fresh_within_five_days
- PASS：all_median_participation_within_1pct
- FAIL：all_p90_participation_within_2pct
- FAIL：no_missing_capacity_days

结论：`REJECTED_BEFORE_BACKTEST`。
