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
| 模拟成交 | `runtime/local_paper_broker.py` | signal 直接等于 position |
| 策略定义 | `config/strategies/` | 多处硬编码同一策略参数 |
| 运行状态 | `state/quant_system.sqlite` | 以日报作为状态存储 |

## 受保护文件

M0 文件包括交易日历、Schema、清洗、复权、财务 as-of、ExecutionModel、Engine 和 Analysis。
修改这些文件必须触发专项测试，且不得与普通前端或报表变更混在同一提交中。

## 扩展方式

新增因子时先登记因子契约；新增策略时组合已有因子并创建带版本的策略声明；新增页面时读取
通用 API 模型。正常新增策略不应修改调度器、Paper Broker 或前端路由。
