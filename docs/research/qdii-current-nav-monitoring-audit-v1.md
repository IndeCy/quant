# QDII最新净值与折溢价监控可用性 V1

- 截止：20260728；分类：CURRENT_PREMIUM_RISK_FLAGGED。
- 本次仅调用Tushare只读接口，未写生产数据库。
- 日频单位净值不能替代盘中IOPV。

| 代码 | 名称 | 净值日 | 滞后日 | 单位净值 | 同日收盘 | 折溢价 |
|---|---|---|---:|---:|---:|---:|
| 159941.SZ | 纳斯达克100ETF | 20260727 | 1 | 1.4224 | 1.5790 | 11.01% |
| 513500.SH | 标普500ETF | 20260727 | 1 | 2.3792 | 2.5200 | 5.92% |

## 冻结门槛

- PASS：all_symbols_returned
- PASS：all_nav_staleness_within_seven_days
- PASS：all_same_date_raw_close_present
- FAIL：all_absolute_latest_premium_within_10pct

源历史折溢价审计结论保持不变；实盘下单前仍必须检查盘中IOPV、申赎状态、
涨跌停和实时买卖价差。
