# R3 Strategy Commit Journal & Recovery

## 目标

为 R2 的串行提交阶段增加可恢复的提交日志。策略计算仍可重新执行，但跨系统状态库、监控库、
Paper 库、文件产物和通知的提交过程必须可定位、可幂等重放，并能在进程中断后从最后成功检查点继续。

## 工作项

1. 策略提交日志
   - 新增 migration `003_strategy_commit_journal.sql`。
   - 每个 `strategy_id + trade_date` 只有一个逻辑提交记录。
   - 记录 Pipeline run_id、代码版本、数据版本、状态、最后检查点、尝试次数和错误。
2. 幂等提交协议
   - 检查点固定为 `BEGIN -> ADAPTER_PERSISTED -> PAPER_SYNCED -> RUN_RECORDED -> NOTIFICATION_DISPATCHING -> COMPLETED`。
   - 已完成的逻辑提交默认跳过；`force` 明确重置并重新提交。
   - adapter 落盘、Paper 同步和运行记录均要求幂等；通知采用 at-most-once 恢复语义。
3. 中断恢复
   - `FAILED/COMMITTING` 记录在下一次标准 Pipeline 中保留最后成功检查点并增加 attempt。
   - 新 Pipeline run_id 可以接管同一策略交易日的未完成提交。
   - 代码或数据版本变化时从 `BEGIN` 重放，避免跨版本续接半成品。
4. 运行身份贯穿
   - PipelineService 将 run_id、code_version、data_version 和 force 传到 Daily Pipeline 与策略提交上下文。
   - 批次摘要输出恢复数、幂等跳过数和 commit_id。

## 不在本轮范围

- 不修改 M0、策略 Alpha、组合构建、风险层或 Paper Broker 撮合规则。
- 不做分布式事务，不引入消息队列或外部数据库。
- 不追求 Bark exactly-once；中断窗口采用不重复推送优先的 at-most-once 语义。
- 不新增前端页面或调度任务。

## 验收

1. migration 可重复执行，并在升级旧库前生成备份。
2. adapter 完成后 Paper 同步失败，下一次运行不重复 adapter，仅从 Paper 检查点恢复。
3. 已完成提交默认幂等跳过，force 明确重放。
4. 不完整提交可由新的 Pipeline run_id 接管。
5. 单策略恢复不阻止其他策略提交。
6. `./scripts/verify.sh` 完整通过。

