# 数据所有权与迁移规范

## 唯一事实来源

| 数据类型 | 存储 | 用途 |
|---|---|---|
| 日线、复权、财务、市场扩展数据 | DuckDB | 研究和生产计算输入 |
| 生产行情快照 | base DuckDB + increment DuckDB + as-of + adjust_policy | 单次运行可复现输入 |
| 策略、因子、运行、订单、持仓索引 | SQLite | 运行系统事实状态 |
| 策略提交检查点 | `state/quant_system.sqlite` | 跨状态库提交恢复与幂等审计 |
| 大型中间研究结果 | DuckDB/Parquet | 可重复计算的数据资产 |
| ML 数据集、模型和评估产物 | `runs/experiments/<experiment_id>/<run_id>/` | 可复现研究资产，不是生产事实状态 |
| 研究定义、运行指纹、结论、复用审计 | `state/quant_system.sqlite` | 防止同口径重复研究 |
| `runs/YYYYMMDD/` | 文件 | 面向人的每日导出产物 |
| `reports/` | 文件 | 研究结论和可再生展示 |

JSON、CSV、Markdown 和 HTML 不得作为下一次交易计算的输入。前端通过 API 读取 SQLite 或
DuckDB 的标准查询结果，不直接扫描文件目录。

ML 训练集必须由统一行情、财务 as-of 和复权口径派生，数据清单记录内容哈希、日期范围、特征列和
异常计数。模型文件仅属于对应实验运行；未通过晋级门槛时不得复制到生产目录或登记为可运行策略。
实验元数据继续写入系统 SQLite，页面只通过通用实验 API 查询，禁止扫描 `runs/` 猜测运行状态。
定义指纹不包含实验展示名称，运行指纹绑定定义、数据截止日和数据版本；源数据订正但截止日不变时，
必须更新 `data_version` 或显式 `force`，并保留新旧运行，不允许覆盖原结论。

## 迁移边界

迁移到 Mac mini 时只迁移以下内容：

1. Git 仓库和未提交的本地配置模板。
2. `.env.properties`，通过安全方式单独传输。
3. `data/` 下业务数据库和 `state/` 下系统状态数据库。
4. 需要保留的历史 `runs/`、研究报告和备份。

可删除并重建：前端依赖、Python 缓存、测试缓存、日志、心跳和 HTML 看板。

历史基线大库可通过 `QUANT_BASE_MARKET_DB` 单独挂载；增量库仍位于 `QUANT_HOME/data`。
`.env.properties` 不进入 Git，也不进入普通运行目录压缩包，备份清单必须把它列为外部敏感文件。

## Schema 规则

- 新 Schema 使用递增 migration，不允许只修改初始化 SQL。
- migration 必须幂等记录版本，并在修改前备份数据库。
- 迁移脚本只做结构变化，不包含策略参数调优或历史收益改写。
- 每次运行记录 code_version 和 data_version，报告通过 run_id 关联。

## 备份规则

状态库和不可重新获取的数据必须进入备份清单；外部可重拉缓存可以只备份元数据。恢复验收必须
验证 Schema 版本、最新交易日、策略版本、持仓、未完成订单和最近一次 Pipeline 状态。
