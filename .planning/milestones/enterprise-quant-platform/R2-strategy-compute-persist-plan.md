# R2 Strategy Compute/Persist Separation

## 目标

在不修改 M0、Alpha、组合构建、风险参数和 Paper Broker 语义的前提下，把每日策略批次拆成两个明确阶段：

1. Compute：并行读取同一份已通过质量门禁的数据，只生成内存计算结果。
2. Persist：按稳定顺序串行写入运行状态、监控指标、报告产物、目标组合和通知。

这一步用于消除多个策略直接竞争 `quant_system.sqlite`、`monitoring.sqlite3` 和
`paper_trading.sqlite3` 的风险，并为后续增加策略实例提供固定扩展协议。

## 工作项

1. 扩展策略执行器注册表
   - 执行器返回 `StrategyComputation`，其中包含标准 `StrategyExecutionResult` 和私有计算载荷。
   - 每个 adapter 可登记独立 persister，批处理器不按 `strategy_id` 分支。
   - 保留 `execute()` 兼容入口，但生产批处理显式调用 `compute()` / `persist()`。
2. 策略 Runner 纯计算化
   - 因子 TopN、主线链动、机会观察和 Quality 兼容适配器增加 compute/persist 边界。
   - Compute 阶段允许只读 DuckDB/SQLite，不写共享数据库、运行目录和通知通道。
   - 原有 `run_*` 入口继续执行 compute + persist，避免破坏研究脚本。
3. 策略级受控并行
   - 所有 runnable 策略先进入受限线程池并行计算。
   - 计算完成后按策略实例列表顺序串行提交。
   - 单策略失败独立登记，不允许阻止其他已成功计算策略完成提交。
4. 可观测性
   - 批次摘要记录 compute/persist 阶段、状态和错误。
   - 策略通知只在串行提交阶段发送。

## 不在本轮范围

- 不修改 M0 ExecutionModel、回测引擎、交易日历、复权或财务 as-of。
- 不改变 Quality、主线链动和机会观察策略的因子、参数、股票池、调仓或风险层。
- 不改变 Paper Broker 的 T+1、撮合、滑点和成交限制。
- 不新增 Pipeline、调度任务、数据库 Schema 或前端页面。

## 验收

1. 两个策略的 compute 可真实并行。
2. 所有 persist 调用始终串行且顺序稳定。
3. compute 完成前无策略提交、Paper 同步或通知。
4. 单策略 compute/persist 失败不会污染其他策略。
5. 现有策略 runner 的兼容入口和产物保持可用。
6. `./scripts/verify.sh` 完整通过。

