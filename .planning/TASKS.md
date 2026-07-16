# Task Board

| ID | Phase | Priority | Status | Owner | Task | Verification |
|---|---|---:|---|---|---|---|
| E0-001 | E0.1 | P0 | done | Codex | 创建项目治理文件 | `test -f .planning/STATE.md` |
| E0-002 | E0.1 | P0 | done | Codex | 输出企业级项目计划 | 用户确认 |
| E0-003 | E0.2 | P0 | done | Codex | 编写开发流程门禁 | 文档存在且包含 TDD/测试/提交 |
| E1-000 | E1.1 | P1 | done | Codex | 规划 Experiment Runner | 输出 Phase E1.1 计划 |
| E1-001 | E1.1 | P1 | done | Codex | 设计 Experiment Runner 数据模型 | 单测覆盖实验登记 |
| E1-002 | E1.2 | P1 | done | Codex | 实现 Walk-Forward Runner | `pytest tests/test_walk_forward.py -q` |
| E2-001 | E2.1 | P1 | done | Codex | 建立 Data Catalog | `pytest tests/test_data_catalog.py -q` |
| E2-002 | E2.2 | P1 | done | Codex | 统一 Data Quality Gate | `pytest tests/test_data_quality_gate.py tests/test_daily_pipeline.py -q` |
| E3-001 | E3.1 | P2 | done | Codex | Factor Registry V2 | `pytest tests/test_factor_registry_v2.py -q` |
| E3-002 | E3.2 | P2 | done | Codex | Factor Computation Runner | `pytest tests/test_factor_computation_runner.py -q` |
| E4-001 | E4.1 | P2 | done | Codex | 策略生命周期状态机 | `pytest tests/test_strategy_lifecycle.py tests/test_strategy_batch_runner.py -q` |
| E4-002 | E4.2 | P2 | done | Codex | 账户/持仓模型 | `pytest tests/test_portfolio_account_model.py -q` |
| E5-001 | E5.1 | P3 | done | Codex | 前端运营控制台信息架构 | `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre` |
| E6-001 | E6.1 | P4 | done | Codex | 人工订单工作流 | `pytest tests/test_manual_order_workflow.py -q` |
| E7-001 | E7.1 | P4 | done | Codex | 实盘前就绪审计 | `/api/readiness` 包含备份、通知、调仓、券商权限边界 |
| E8-001 | E8.1 | P4 | done | Codex | 发布基线和运行数据备份 | `scripts/create_release_baseline.py --output-dir runtime_backups --label e8_1_smoke` |
| E9-001 | E9.1 | P4 | done | Codex | Git 基线整理 | `pytest tests/test_git_baseline.py tests/test_release_baseline.py -q` |
| E10-001 | E10.1 | P4 | done | Codex | 安全提交分组确认 | `pytest tests/test_safe_commit_review.py tests/test_git_baseline.py tests/test_release_baseline.py -q` |
| E11-001 | E11.1 | P4 | done | Codex | 选择性暂存和提交 | `git diff --cached --name-only` 不包含 runtime/report 数据 |
| E12-001 | E12.1 | P4 | done | Codex | 基线后运行观察 | `pytest tests/test_post_baseline_audit.py -q` |
| E13-001 | E13.1 | P4 | done | Codex | 下一轮运维迭代 | `pytest tests/test_operations_observation.py -q` |
| E14-001 | E14.1 | P4 | done | Codex | 日报 WARN 收敛 | `pytest tests/test_operations_observation.py -q` |
| E15-001 | E15.1 | P4 | done | Codex | 运行体验与告警闭环 | `/api/operations/observation` 与调度页运行观察面板 |
| E16-001 | E16.1 | P4 | done | Codex | 通知决策面与异常闭环 | `/api/operations/decision` 与调度页今日操作判断 |
| E17-001 | E17.1 | P4 | done | Codex | 异常确认与处置回溯 | `/api/operations/acknowledgements` 与调度页人工确认记录 |
| E18-001 | E18.1 | P4 | done | Codex | 运维闭环复盘指标 | `/api/operations/review` 与调度页闭环复盘面板 |
| E19-001 | E19.1 | P4 | done | Codex | 运维质量趋势报告 | `operations_quality_review` 登记到报告索引 |
| E20-001 | E20.1 | P4 | done | Codex | 运行环境一致性审计 | `/api/environment/audit` 暴露 API 进程缺少 `TUSHARE_TOKEN` |
| E21-001 | E21.1 | P4 | done | Codex | 本地私密配置统一 | `.env.properties` 已创建且 `/api/environment/audit` 为 PASS |
| E22-001 | E22.1 | P4 | done | Codex | 运行配置迁移与备份校验 | `.env.properties` 纳入迁移检查但不提交 Git |
| R1-001 | R1.1 | P0 | done | Codex | 统一策略目标组合契约与执行器注册 | `pytest tests/test_strategy_execution_contract.py -q` |
| R1-002 | R1.2 | P0 | done | Codex | 统一 Paper 账本到账户快照投影 | `pytest tests/test_market_open_paper_execution.py -q` |
| R1-003 | R1.3 | P0 | done | Codex | Quality/Mainline 原生协议接入 | `pytest tests/test_strategy_batch_runner.py -q` |
| R1-004 | R1.4 | P0 | done | Codex | 显式 Pipeline DAG 与受控并行 | `pytest tests/test_pipeline_dag.py tests/test_daily_pipeline.py -q` |
| R1-005 | R1.5 | P0 | done | Codex | base+increment 统一行情快照 | `pytest tests/test_market_snapshot.py -q` |
| R1-006 | R1.6 | P1 | done | Codex | 静态前端、配置化服务和恢复验收 | `pytest tests/test_static_frontend_server.py tests/test_restore_audit.py -q` |
| R2-001 | R2.1 | P0 | done | Codex | 建立策略 Compute/Persist 协议并迁移现有执行器 | `pytest tests/test_strategy_compute_persist.py -q` |
| R2-002 | R2.2 | P1 | done | Codex | 开放策略级受控并行和失败隔离 | `pytest tests/test_strategy_batch_runner.py tests/test_strategy_compute_persist.py -q` |
| Y1Y2-001 | Y1/Y2.1 | P2 | done | Codex | 游资情绪数据层与市场状态机 | `pytest tests/test_tushare_limit_incremental.py tests/test_hot_money_emotion.py tests/test_hot_money_state.py tests/test_hot_money_state_cli.py -q` |
| Y3-001 | Y3.1 | P2 | done | Codex | 主线板块与龙头识别 | 生成 sector momentum、leader stock 和报告 CLI |

## 状态规则

- pending：未开始。
- in_progress：当前正在做。
- blocked：明确阻塞，必须写阻塞原因。
- done：代码、测试、文档或验收已完成。

## 执行规则

- 每次只允许一个 Phase 处于 in_progress。
- 每个 Phase 开始前必须写计划。
- 每个实现任务必须先写失败测试。
- 每个 Phase 完成后更新本文件和 `.planning/STATE.md`。
