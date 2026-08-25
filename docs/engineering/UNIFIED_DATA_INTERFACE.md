# 统一量化数据接口与增量管理

## 目标

策略、因子和研究只依赖 `QuantDataSnapshot`，不直接连接 Tushare、DuckDB 文件或运行状态库。
统一快照绑定 `as_of_date`、前复权行情口径和数据文件版本，确保同一次运行的数据输入可追溯。

## 读取入口

运行层使用 `runtime.data_access.create_quant_data_snapshot()` 构造快照，再把快照注入策略或研究：

```python
snapshot = create_quant_data_snapshot("20260824")

bars = snapshot.stock_bars("600519.SH", start_date="20250101")
valuation = snapshot.load_dataset(
    "market.daily_basic",
    latest_only=True,
    symbols=["600519.SH"],
)
financial = snapshot.financial_snapshot("600519.SH", fields=["roe", "grossprofit_margin"])
```

- 股票和基金日线继续复用 `data.market_snapshot`，默认 qfq。
- 财务数据继续复用 `FinancialDataPortal`，只能按公告日 as-of 读取。
- 资金流、两融、龙虎榜、股东事件等扩展表通过稳定 `dataset_id` 访问。
- 带日期的大表必须指定 `start_date` 或 `latest_only=True`，避免误加载全部历史。
- 查询只以只读方式连接 DuckDB，并在 SQL 层限制 `date_field <= as_of_date`。

## 当前登记的数据集

- `market.daily_basic`、`market.index_dailybasic`
- `fund.share`
- `flow.hsgt`、`flow.order`、`flow.top_inst`
- `margin.market`、`margin.detail`
- `market.limit_list`
- `event.block_trade`、`event.shareholder_count`、`event.holder_trade`、`event.dividend`
- `fund.ownership`
- `reference.stock_industry`、`reference.concept_member`

登记只建立逻辑名称到现有数据资产的映射，不复制数据，也不会改变现有生产口径。

## 增量同步协议

`IncrementalDatasetUpdater` 以完整日期分区为最小单位：

1. 检查 `data_sync_partitions` 中的成功检查点及本地实际行数。
2. 只拉取缺失、失败或行数不一致的分区。
3. 校验字段、日期分区、主键非空和主键唯一。
4. 在单个 DuckDB 事务中替换完整分区，允许源端订正或删除记录。
5. 记录行数、内容哈希、成功或失败状态，支持断点续跑。

增量写入器不会创建数据库或表。新数据集必须先提供版本化 migration；缺少数据库、表或字段时立即失败。

`DataSyncService` 只能由现有 `PipelineService` 的 `data_update` 节点调用，不是新的日常 Pipeline、
命令行旁路或撮合入口。现有唯一日常 Pipeline 已接入以下研究扩展域：

- 个股订单资金流、龙虎榜机构席位、融资融券明细按交易日补缺；每次最多补 5 日，并始终优先包含最新缺口日。
- 大宗交易、股东户数、重要股东增减持按公告/交易日滚动复查最近 62 个自然日。
- ETF 份额覆盖 `510300.SH` 和当前组合配置内的 `513500.SH`、`518880.SH`、`511010.SH`，每次回看 14 天。
- 每个扩展域均写入 `data_sync_runs` 审计；原有数据域自己的逐日或游标状态继续负责断点续跑。

这些扩展域当前只供研究和观测使用，异常记录为非阻断告警；一旦有生产策略声明依赖，必须把对应
完整性检查提升为 `data_quality_gate` 的阻断条件后才能消费。

## 下一阶段

按优先级为新数据域提供 DuckDB migration 和契约：

1. 2026 中报财务 VIP 增量库。
2. 专业技术因子、Tushare 因子值和筹码胜率。
3. 资金流、两融、龙虎榜和股东事件由日更预算逐步补齐 2026-07 以来的缺口。
4. 宏观、可转债、期货、期权、黄金、外汇和港股。
5. 分钟数据按月分区，独立容量预算，不进入日常策略主库。
