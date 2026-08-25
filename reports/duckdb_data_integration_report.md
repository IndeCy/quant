# DuckDB 数据接入与验收报告

## 1. 数据文件

- DuckDB 文件路径：`D:\project\database\daily_adj_19901219_20260615.duckdb`
- 接入入口：`data/duckdb_source.py`
- 业务访问路径：`DataManager -> DuckDBAshareDataSource -> data/schema.py`
- 禁止路径：策略、回测引擎、研究逻辑直接访问 DuckDB

## 2. 表结构摘要

| 表名 | 数据量 | 日期范围 | 字段 |
|---|---:|---|---|
| `adj_factor` | 18,692,731 | `trade_date`: 19901219 - 20260612 | `ts_code VARCHAR`, `trade_date VARCHAR`, `adj_factor DOUBLE` |
| `daily` | 17,875,849 | `trade_date`: 19901219 - 20260615 | `ts_code VARCHAR`, `trade_date VARCHAR`, `open DOUBLE`, `high DOUBLE`, `low DOUBLE`, `close DOUBLE`, `pre_close DOUBLE`, `change DOUBLE`, `pct_chg DOUBLE`, `vol DOUBLE`, `amount DOUBLE` |
| `daily_adj_cache` | 17,875,849 | `trade_date`: 19901219 - 20260615 | `ts_code VARCHAR`, `trade_date VARCHAR`, `adj_factor DOUBLE`, `first_adj DOUBLE`, `last_adj DOUBLE`, `open_qfq DOUBLE`, `high_qfq DOUBLE`, `low_qfq DOUBLE`, `close_qfq DOUBLE`, `pre_close_qfq DOUBLE`, `change_qfq DOUBLE`, `pct_chg_qfq DOUBLE`, `open_hfq DOUBLE`, `high_hfq DOUBLE`, `low_hfq DOUBLE`, `close_hfq DOUBLE`, `pre_close_hfq DOUBLE`, `change_hfq DOUBLE`, `pct_chg_hfq DOUBLE` |
| `stock_basic` | 5,936 | `list_date`: 19901201 - 20260615；`delist_date`: 19990712 - 20260610 | `ts_code VARCHAR`, `name VARCHAR`, `list_status VARCHAR`, `list_date VARCHAR`, `delist_date VARCHAR` |
| `stock_name_manual` | 8 | `start_date`: 19910129 - 20070514；`end_date`: 20000509 - 20260429 | `ts_code VARCHAR`, `name VARCHAR`, `start_date VARCHAR`, `end_date VARCHAR`, `name_type VARCHAR`, `source VARCHAR`, `notes VARCHAR` |
| `stock_namechange` | 3,838 | `start_date`: 20100629 - 20260623；`end_date`: 20100920 - 20260615；`ann_date`: 20100623 - 20260615 | `ts_code VARCHAR`, `name VARCHAR`, `start_date VARCHAR`, `end_date VARCHAR`, `ann_date VARCHAR`, `change_reason VARCHAR` |
| `stock_st` | 325,752 | `trade_date`: 20160809 - 20260612 | `ts_code VARCHAR`, `trade_date VARCHAR`, `name VARCHAR` |

## 3. 关键数据覆盖

| 数据项 | 是否包含 | 说明 |
|---|---|---|
| 日线行情 | 是 | `daily` 提供原始 OHLCV 与成交额 |
| 股票基础信息 | 是 | `stock_basic` 提供上市状态、上市日、退市日 |
| 交易日历 | 可派生 | 无独立日历表，已从 `daily.trade_date` 去重派生真实交易日历 |
| ST/退市状态 | 部分包含 | `stock_st` 提供日级 ST 名称，`stock_basic` 提供退市日期 |
| 财务数据 | 否 | 未发现利润表、资产负债表、现金流量表或指标表 |
| 财务公告日 / publish_date / ann_date | 否 | `stock_namechange.ann_date` 仅为名称变更公告日，不能作为财务公告日 |
| 分红数据 | 否 | 未发现分红/除权除息表 |
| 行业分类 | 否 | 未发现行业表 |
| 指数行情 / 沪深300 | 否 | `000300.SH`、`399300.SZ`、`000001.SH`、`399001.SZ` 在 `daily` 中记录数均为 0 |

## 4. 字段映射到系统 Schema

| 系统字段 | DuckDB 来源 | 状态 | 说明 |
|---|---|---|---|
| `trade_date` | `daily.trade_date` / `daily_adj_cache.trade_date` | 已映射 | `YYYYMMDD` 转为 `DatetimeIndex` |
| `code` | `ts_code` | 已映射 | 与 `symbol` 同值 |
| `symbol` | `ts_code` | 已映射 | 统一为项目标的代码 |
| `open` | `daily.open` / `daily_adj_cache.open_qfq/open_hfq` | 已映射 | 由 `adjust_policy` 决定读取口径 |
| `high` | `daily.high` / `daily_adj_cache.high_qfq/high_hfq` | 已映射 | 同上 |
| `low` | `daily.low` / `daily_adj_cache.low_qfq/low_hfq` | 已映射 | 同上 |
| `close` | `daily.close` / `daily_adj_cache.close_qfq/close_hfq` | 已映射 | 同上 |
| `volume` | `daily.vol` | 已映射 | 字段重命名 |
| `amount` | `daily.amount` | 已映射 | 原样保留 |
| `adj_factor` | `adj_factor.adj_factor` / `daily_adj_cache.adj_factor` | 已映射 | 原始价左连接复权因子；复权价使用缓存因子 |
| `is_suspended` | `daily.vol <= 0` 或缺 bar | 可推导 | 无原生停牌表；缺 bar 在成交时按 `missing_bar` 拦截 |
| `limit_up` | `pre_close` + ST 状态 + 代码板块规则推导 | 可推导，有风险 | 无原生涨停字段；IPO、新股、特殊制度日可能需要更精确规则 |
| `limit_down` | `pre_close` + ST 状态 + 代码板块规则推导 | 可推导，有风险 | 同上 |

## 5. 缺失字段清单

- 原生 `is_suspended`：缺失，但可通过成交量为 0 或缺 bar 保守拦截。
- 原生 `limit_up` / `limit_down`：缺失，当前只能推导，会影响涨跌停精确成交判断。
- 财务表：缺失，无法支持质量因子或财务 as-of 查询。
- 财务 `publish_date` / `ann_date`：缺失，财务接口必须报错，不能假装可用。
- 分红表：缺失，无法满足红利策略数据要求。
- 行业分类：缺失，无法做行业约束、行业轮动或行业暴露分析。
- 指数行情 / 沪深300：缺失，无法从该库直接读取沪深300基准。

## 6. 风险字段清单

- `limit_up` / `limit_down`：推导字段，不是交易所原始涨跌停价。M0 可拦截常规涨跌停，但精确历史制度需要后续补充原生涨跌停价或更完整规则。
- `is_suspended`：无独立停复牌表。若供应商停牌日不落行，系统会按 `missing_bar` 拦截，不会成交，但失败原因不是 `suspended`。
- `amount` 单位：库内沿用供应商字段，当前只做透传，未转换单位。
- ST 覆盖起点：`stock_st.trade_date` 从 20160809 开始，更早 ST 状态依赖名称变更/手工补丁，覆盖不完整。

## 7. 复权口径

- `adjust_policy="none"`：读取 `daily` 原始不复权价格。
- `adjust_policy="qfq"`：读取 `daily_adj_cache` 的 `*_qfq` 前复权价格。
- `adjust_policy="hfq"`：读取 `daily_adj_cache` 的 `*_hfq` 后复权价格。
- 同一次回测仍由 `DataManager.validate_single_adjustment_policy()` 校验，禁止混用不同复权口径。
- 如果请求的复权缓存字段不存在，适配层直接报错。
- 策略信号价、成交价、估值价在引擎中均来自同一份已加载 schema 数据，因此同一回测保持同一口径。

## 8. 交易日历接入

- 默认优先使用 `DuckDBAshareDataSource.get_trading_calendar()`。
- 该日历从 `daily.trade_date` 去重生成。
- `BacktestEngine` 在 DataManager 提供外部日历时自动使用该日历；没有外部数据源时保留原 `TradingCalendar` fallback。
- 已验证春节区间 `2024-02-07` 到 `2024-02-20` 只包含：`2024-02-07`, `2024-02-08`, `2024-02-19`, `2024-02-20`。

## 9. M0 验收结论

当前接入满足 M0 可信回测标准。

已验证：

- 回测按 DuckDB 派生交易日历推进。
- T 日信号，T+1 交易日成交。
- 周五信号，下一交易日成交。
- 停牌或缺 bar 不成交。
- 买入涨停不成交。
- 卖出跌停不成交。
- 成交价缺失/为 0 不成交。
- 买入费用 = 佣金 + 滑点。
- 卖出费用 = 佣金 + 印花税 + 滑点。
- 所有 DuckDB 价格读取经过统一 schema。
- as-of 财务接口在缺少财务公告日时明确报错，不能看到未来数据。
- `backtest` 业务模块不直接 `import duckdb`。

## 10. Milestone 1 红利 + 质量策略数据要求

当前 DuckDB 不满足 Milestone 1 红利 + 质量策略的数据要求。

原因：

- 缺少财务数据和财务公告日，无法构造无未来函数的质量因子。
- 缺少分红数据，无法构造红利因子。
- 缺少行业分类，无法做行业约束或行业中性分析。
- 缺少沪深300/指数行情，无法从该库直接构造沪深300基准。

## 11. 运行测试命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_duckdb_source.py tests\test_m0_audit.py tests\test_phase1_acceptance.py tests\test_phase1_trustworthy_backtest.py tests\test_phase15_data_contracts.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

测试结果：

- M0/Phase1 相关测试：32 passed
- 全量测试：145 passed

## 12. 最小读取示例

```python
from backtest.data import DataManager
from data.adjustment import AdjustType
from data.duckdb_source import DuckDBAshareDataSource

source = DuckDBAshareDataSource(r"D:\project\database\daily_adj_19901219_20260615.duckdb")
manager = DataManager(source, default_adjust=AdjustType.QFQ)

manager.load_symbol("000001.SZ", "2024-01-02", "2024-01-05", adjust=AdjustType.QFQ)
bars = manager.get_data("000001.SZ")
calendar = manager.get_trading_calendar("2024-02-07", "2024-02-20")

print(bars[["open", "high", "low", "close", "volume", "amount", "adj_factor"]].head())
print(calendar.trading_days("2024-02-07", "2024-02-20"))
```
