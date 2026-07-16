# R1 Architecture Convergence

## 目标

在不修改 M0、Alpha 因子和策略参数的前提下，收敛策略运行、Paper 账本、每日编排、数据快照和 Mac mini 部署边界。

## 工作项

1. 统一策略运行契约
   - `TargetPortfolio` 作为策略到组合/执行层的唯一目标组合模型。
   - `StrategyExecutorRegistry` 按模板或显式 adapter 扩展，禁止批处理器继续增加策略 ID 分支。
2. 统一 Paper 账户投影
   - `paper_trading.sqlite3` 为成交事实账本。
   - `account_projection_service` 从成交、持仓和目标组合生成前端账户快照。
3. 原生策略接入
   - Quality 与主线链动返回标准目标权重。
   - 每日生产路径不再通过子进程和 CSV 回读目标组合。
4. 显式 Pipeline DAG
   - 数据更新 -> 质量门禁 -> 策略批次/Beta 观察。
   - 同一波次受控并行，共享 SQLite 的节点由资源锁串行写入，失败依赖明确标记 SKIPPED。
5. 统一行情快照
   - 基线库 + 增量库 + as-of + adjust_policy 形成可追溯 snapshot_id。
   - 增量覆盖基线，快照层阻止读取 as-of 之后的数据和复权因子。
6. Mac mini 部署收口
   - 前端构建后由 Python 静态服务托管，Node 不再作为常驻依赖。
   - `.env.properties` 管理运行路径和可执行文件路径。
   - 备份清单显式列出本地私密配置和历史大库，恢复脚本验证数据库可读性。

## 不在本轮范围

- 不修改 M0 ExecutionModel、回测引擎、交易日历或财务 as-of 规则。
- 不新增或调整因子、选股、风险层和策略参数。
- 不接真实券商，不改变 Paper Broker 成交逻辑。
- 不做数据库 Schema 变化。

## 验收

```bash
./scripts/verify.sh
cd frontend && npm run build:pre
python scripts/verify_runtime_restore.py --runtime-root "$QUANT_HOME"
```

恢复验收命令在真实迁移完成后执行；开发环境测试使用 `tests/test_restore_audit.py` 覆盖完整和缺失场景。
