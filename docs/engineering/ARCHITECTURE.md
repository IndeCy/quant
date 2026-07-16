# 系统架构与依赖方向

## 标准链路

```text
DataSource -> DataQuality -> Factor -> Strategy Signal
           -> Portfolio -> Risk Overlay -> Target Portfolio
           -> Order Plan -> Paper Broker -> Monitoring -> API -> Frontend
```

## 依赖规则

```text
frontend -> api -> runtime/application -> domain
                                  |-> infrastructure

data, factors, strategies, portfolio, risk, backtest
不得反向依赖 api、frontend 或 scheduler。
```

允许 `runtime` 编排领域模块，禁止领域模块回调 `runtime` 执行入口。现有策略 Runner 为兼容层，
可以使用运行仓库写入标准产物，但不得调用 Scheduler、PipelineService 或 Paper Broker。

## 核心所有者

| 能力 | 唯一所有者 | 禁止重复实现 |
|---|---|---|
| 交易日推进 | `data/calendar.py` | 自然日循环 |
| 行情字段 | `data/schema.py` | 策略私有字段映射 |
| 复权口径 | `data/adjustment.py` | 策略内自行复权 |
| 财务可见性 | `data/financial.py` | 直接按报告期取财务数据 |
| 回测成交 | `backtest/execution_model.py` | Engine 或策略散落费用计算 |
| 日常编排 | `runtime/pipeline_service.py` | API、脚本或调度器旁路运行 |
| 编排依赖 | `runtime/pipeline_dag.py` | 用时钟偏移模拟依赖 |
| 策略执行扩展 | `runtime/strategy_executor_registry.py` | 批处理器按策略 ID 增加分支 |
| 目标组合契约 | `domain/strategy_execution.py` | CSV/Markdown 作为执行输入 |
| 模拟成交 | `runtime/local_paper_broker.py` | signal 直接等于 position |
| 账户查询投影 | `runtime/account_projection_service.py` | 页面自行拼持仓和净值 |
| 生产行情快照 | `data/market_snapshot.py` | 策略直接拼基线库与增量库 |
| 策略定义 | `config/strategies/` | 多处硬编码同一策略参数 |
| 运行状态 | `state/quant_system.sqlite` | 以日报作为状态存储 |

## 受保护文件

M0 文件包括交易日历、Schema、清洗、复权、财务 as-of、ExecutionModel、Engine 和 Analysis。
修改这些文件必须触发专项测试，且不得与普通前端或报表变更混在同一提交中。

## 扩展方式

新增因子时先登记因子契约；新增策略时组合已有因子并创建带版本的策略声明；新增页面时读取
通用 API 模型。正常新增策略不应修改调度器、Paper Broker 或前端路由。

每日生产依赖固定为：`data_update -> data_quality_gate -> strategy_batch + market_beta_observer`。
策略和 Beta 位于同一受控波次，但共享 `monitoring.sqlite3` 时由资源锁串行写入；任何策略运行都不得早于数据质量门禁。
