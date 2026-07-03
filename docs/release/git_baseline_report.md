# Git Baseline Report

- repo_root: `/Users/admin/PycharmProjects/quant`
- generated_at: `2026-07-03T09:43:27`

## Summary

| 分类 | 数量 | 提交建议 |
|---|---:|---|
| `source_code` | 129 | 可作为代码提交候选，仍需人工 review |
| `governance_docs` | 31 | 可作为治理文档提交候选 |
| `deleted_legacy` | 5 | 删除类变更，提交前必须确认无运行依赖 |
| `tracked_runtime_artifact` | 3 | 已跟踪运行产物，提交前必须逐项确认 |
| `runtime_data` | 9 | 运行数据，不建议提交 |
| `ignored_generated` | 85 | 已忽略生成物，不应提交 |
| `manual_review` | 0 | 未知类型，必须人工确认 |

## Groups

### source_code

- `M` `api/local_server.py`
- `M` `api/service.py`
- `A` `data/tushare_concept_incremental.py`
- `M` `frontend/src/App.tsx`
- `M` `frontend/src/app/loadDashboardData.ts`
- `M` `frontend/src/app/state.test.ts`
- `M` `frontend/src/app/types.ts`
- `A` `frontend/src/entities/account/api.ts`
- `A` `frontend/src/entities/account/drift.test.ts`
- `A` `frontend/src/entities/account/drift.ts`
- `A` `frontend/src/entities/account/model.ts`
- `A` `frontend/src/entities/dataCatalog/api.ts`
- `A` `frontend/src/entities/dataCatalog/model.ts`
- `A` `frontend/src/entities/dataCatalog/status.test.ts`
- `A` `frontend/src/entities/dataCatalog/status.ts`
- `A` `frontend/src/entities/factorContract/api.ts`
- `A` `frontend/src/entities/factorContract/display.test.ts`
- `A` `frontend/src/entities/factorContract/display.ts`
- `A` `frontend/src/entities/factorContract/model.ts`
- `A` `frontend/src/entities/manualOrder/api.ts`
- `A` `frontend/src/entities/manualOrder/model.ts`
- `A` `frontend/src/entities/manualOrder/status.test.ts`
- `A` `frontend/src/entities/manualOrder/status.ts`
- `M` `frontend/src/entities/readiness/status.test.ts`
- `M` `frontend/src/entities/readiness/status.ts`
- `M` `frontend/src/entities/research/api.ts`
- `M` `frontend/src/entities/research/model.ts`
- `M` `frontend/src/entities/strategy/api.ts`
- `A` `frontend/src/entities/strategy/lifecycle.test.ts`
- `A` `frontend/src/entities/strategy/lifecycle.ts`
- `M` `frontend/src/entities/strategy/model.ts`
- `M` `frontend/src/pages/dashboard/components/ReadinessPanel.tsx`
- `M` `frontend/src/pages/data/DataHealthPage.tsx`
- `M` `frontend/src/pages/factors/FactorsPage.tsx`
- `M` `frontend/src/pages/research/ResearchPage.tsx`
- `A` `frontend/src/pages/strategies/ManualOrderPanel.tsx`
- `M` `frontend/src/pages/strategies/StrategiesPage.tsx`
- `A` `frontend/src/pages/strategies/StrategyAccountSnapshotPanel.tsx`
- `A` `frontend/src/pages/strategies/StrategyOperationsPanel.tsx`
- `M` `frontend/src/shared/styles/features.css`
- `A` `frontend/src/shared/styles/operations.css`
- `M` `monitoring/repository.py`
- `A` `runtime/daily_pipeline.py`
- `A` `runtime/data_catalog.py`
- `A` `runtime/data_catalog_repository.py`
- `A` `runtime/data_catalog_runner.py`
- `A` `runtime/data_quality_gate.py`
- `A` `runtime/experiment_repository.py`
- `A` `runtime/experiment_runner.py`
- `A` `runtime/factor_computation_runner.py`
- `A` `runtime/factor_registry_repository.py`
- `A` `runtime/git_baseline.py`
- `A` `runtime/live_risk_guard.py`
- `M` `runtime/mainline_cache_sync.py`
- `A` `runtime/mainline_tushare_backfill.py`
- `A` `runtime/manual_order.py`
- `A` `runtime/manual_order_repository.py`
- `M` `runtime/notification_config.py`
- `A` `runtime/opportunity_catalog.py`
- `A` `runtime/opportunity_verifier.py`
- `A` `runtime/portfolio_account.py`
- `A` `runtime/portfolio_account_repository.py`
- `A` `runtime/pre_market_check.py`
- `M` `runtime/readiness.py`
- `A` `runtime/release_baseline.py`
- `M` `runtime/repository.py`
- `M` `runtime/repository_schema.py`
- `A` `runtime/research_monitor.py`
- `A` `runtime/research_monitor_scoring.py`
- `M` `runtime/research_repository.py`
- `AM` `runtime/safe_commit_review.py`
- `M` `runtime/scheduler.py`
- `A` `runtime/scheduler_watchdog.py`
- `M` `runtime/strategy_batch_runner.py`
- `M` `runtime/strategy_catalog.py`
- `M` `runtime/strategy_instance_catalog.py`
- `M` `runtime/strategy_instance_repository.py`
- `A` `runtime/strategy_lifecycle.py`
- `M` `runtime/strategy_templates.py`
- `A` `runtime/walk_forward.py`
- `A` `scripts/backfill_mainline_tushare_cache.py`
- `A` `scripts/create_release_baseline.py`
- `A` `scripts/generate_git_baseline_report.py`
- `A` `scripts/generate_safe_commit_review.py`
- `A` `scripts/refresh_data_catalog.py`
- `M` `scripts/run_daily_data_update.py`
- `A` `scripts/run_daily_pipeline.py`
- `A` `scripts/run_data_quality_gate.py`
- `A` `scripts/run_experiment.py`
- `A` `scripts/run_factor_computation.py`
- `A` `scripts/run_live_risk_guard.py`
- `M` `scripts/run_local_scheduler.py`
- `A` `scripts/run_pre_market_check.py`
- `A` `scripts/run_research_monitor.py`
- `A` `scripts/run_scheduler_watchdog.py`
- `M` `scripts/run_strategy_batch.py`
- `A` `scripts/run_walk_forward_experiment.py`
- `A` `strategies/mainline_chain_factor_runner.py`
- `A` `tests/test_daily_pipeline.py`
- `A` `tests/test_data_catalog.py`
- `A` `tests/test_data_quality_gate.py`
- `A` `tests/test_experiment_runner.py`
- `A` `tests/test_factor_computation_runner.py`
- `A` `tests/test_factor_registry_v2.py`
- `M` `tests/test_factor_strategy_workbench_e2e.py`
- `A` `tests/test_git_baseline.py`
- `A` `tests/test_live_risk_guard.py`
- `M` `tests/test_local_api_service.py`
- `M` `tests/test_mainline_cache_sync.py`
- `A` `tests/test_mainline_chain_factor_runner.py`
- `A` `tests/test_mainline_tushare_backfill.py`
- `A` `tests/test_manual_order_workflow.py`
- `A` `tests/test_operations_api_service.py`
- `A` `tests/test_opportunity_verifier.py`
- `A` `tests/test_portfolio_account_model.py`
- `A` `tests/test_pre_market_check.py`
- `A` `tests/test_release_baseline.py`
- `A` `tests/test_research_monitor.py`
- `M` `tests/test_runtime_readiness.py`
- `M` `tests/test_runtime_repository.py`
- `M` `tests/test_runtime_scheduler.py`
- `AM` `tests/test_safe_commit_review.py`
- `A` `tests/test_scheduler_watchdog.py`
- `M` `tests/test_strategy_batch_runner.py`
- `M` `tests/test_strategy_catalog.py`
- `M` `tests/test_strategy_instances.py`
- `A` `tests/test_strategy_lifecycle.py`
- `A` `tests/test_tushare_concept_incremental.py`
- `A` `tests/test_walk_forward.py`

### governance_docs

- `M` `.gitignore`
- `A` `.planning/PROJECT.md`
- `A` `.planning/REQUIREMENTS.md`
- `A` `.planning/ROADMAP.md`
- `A` `.planning/STATE.md`
- `A` `.planning/TASKS.md`
- `A` `.planning/adr/0001-enterprise-priority-order.md`
- `A` `.planning/milestones/enterprise-quant-platform/E1.1-experiment-runner-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E1.2-walk-forward-validation-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E2.1-data-catalog-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E2.2-data-quality-gate-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E3.1-factor-registry-v2-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E3.2-factor-computation-runner-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E4.1-strategy-lifecycle-plan.md`
- `A` `.planning/milestones/enterprise-quant-platform/E4.2-portfolio-account-model-plan.md`
- `A` `docs/development_workflow.md`
- `A` `docs/phase_template.md`
- `A` `docs/release/git_baseline_report.json`
- `A` `docs/release/git_baseline_report.md`
- `A` `docs/release/safe_commit_review.json`
- `A` `docs/release/safe_commit_review.md`
- `A` `docs/superpowers/plans/2026-07-01-powerlaw-opportunity-radar-plan.md`
- `A` `docs/superpowers/plans/2026-07-02-live-readiness-audit-plan.md`
- `A` `docs/superpowers/plans/2026-07-02-live-risk-guard-plan.md`
- `A` `docs/superpowers/plans/2026-07-02-manual-order-workflow-plan.md`
- `A` `docs/superpowers/plans/2026-07-02-unified-daily-pipeline-plan.md`
- `A` `docs/superpowers/plans/2026-07-03-git-baseline-hygiene-plan.md`
- `A` `docs/superpowers/plans/2026-07-03-release-baseline-runtime-backup-plan.md`
- `A` `docs/superpowers/plans/2026-07-03-safe-commit-review-plan.md`
- `A` `docs/superpowers/plans/2026-07-03-selective-commit-release-baseline-plan.md`
- `A` `docs/verification_checklist.md`

### deleted_legacy

- `D` `monitoring/mainline_adapter.py`
- `D` `monitoring/mainline_backtest.py`
- `D` `scripts/run_mainline_chain_daily.py`
- `D` `tests/test_mainline_backtest.py`
- `D` `tests/test_mainline_monitoring_adapter.py`

### tracked_runtime_artifact

- `M` `reports/dashboard.html`
- `M` `reports/dashboard_data.json`
- `M` `reports/quality_overlay_paper_latest.md`

### runtime_data

- `??` `runs/202606/`
- `??` `runs/20260626/daily_report.md`
- `??` `runs/20260626/strategy_metrics.json`
- `??` `runs/20260629/`
- `??` `runs/20260630/`
- `??` `runs/20260701/`
- `??` `runs/20260702/`
- `??` `runs/20260703/`
- `??` `runs/experiments/`

### ignored_generated

- `!!` `.DS_Store`
- `!!` `.gitignore.bak`
- `!!` `.idea/copilot.data.migration.ask2agent.xml`
- `!!` `.idea/dbnavigator.xml`
- `!!` `.idea/inspectionProfiles/Project_Default.xml`
- `!!` `.idea/misc.xml`
- `!!` `.idea/vcs.xml`
- `!!` `.idea/workspace.xml`
- `!!` `.pytest_cache/`
- `!!` `api/__pycache__/`
- `!!` `backtest/__pycache__/`
- `!!` `balancesheet.duckdb`
- `!!` `cashflow.duckdb`
- `!!` `daily_adj_19901219_20260615.duckdb`
- `!!` `data/__pycache__/`
- `!!` `data/benchmark_increment.duckdb`
- `!!` `data/dividend_increment.duckdb`
- `!!` `data/industry_increment.duckdb`
- `!!` `data/live_market_increment.duckdb`
- `!!` `data/market_breadth.sqlite3`
- `!!` `data/market_cache.sqlite3`
- `!!` `data/monitoring.sqlite3`
- `!!` `data/opportunity_concept_increment.duckdb`
- `!!` `data/paper_trading.sqlite3`
- `!!` `data/quality_overlay_paper.sqlite3`
- `!!` `data/strategy_history.sqlite3`
- `!!` `etf_lof_reits_basic_export_20041220_20260617.duckdb`
- `!!` `etf_lof_reits_daily_adj_20041220_20260617.duckdb`
- `!!` `examples/__pycache__/`
- `!!` `express.duckdb`
- `!!` `fina_indicator.duckdb`
- `!!` `forecast.duckdb`
- `!!` `frontend/dist/`
- `!!` `frontend/node_modules/`
- `!!` `frontend/src/shared/lib/`
- `!!` `frontend/tsconfig.tsbuildinfo`
- `!!` `income.duckdb`
- `!!` `logs/`
- `!!` `monitoring/__pycache__/`
- `!!` `pipeline/__pycache__/`
- `!!` `quant_backtest.egg-info/`
- `!!` `reports/cash_cow_v15_holdings.csv`
- `!!` `reports/cash_cow_v1_holdings.csv`
- `!!` `reports/industry_rotation_vs_benchmark_curve.csv`
- `!!` `reports/quality_attribution_holdings.csv`
- `!!` `reports/quality_cleanup_holdings.csv`
- `!!` `reports/quality_current_holdings_for_comparison.csv`
- `!!` `reports/quality_overlay_annual.csv`
- `!!` `reports/quality_overlay_robustness_grid.csv`
- `!!` `reports/quality_overlay_trigger_events.csv`
- `!!` `reports/quality_overlay_walk_forward.csv`
- `!!` `reports/quality_strategy_v1_holdings.csv`
- `!!` `reports/quality_strategy_v1_worst_contributors.csv`
- `!!` `reports/quality_volatility_grid_search.csv`
- `!!` `reports/style_rotation_diagnostic_curves.csv`
- `!!` `reports/style_rotation_diagnostic_metrics.csv`
- `!!` `reports/style_rotation_diagnostic_signals.csv`
- `!!` `runs/.DS_Store`
- `!!` `runs/20260626/portfolio_snapshot.csv`
- `!!` `runs/20260626/rebalance_plan.csv`
- `!!` `runs/20260629/portfolio_snapshot.csv`
- `!!` `runs/20260629/rebalance_plan.csv`
- `!!` `runs/20260630/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `!!` `runs/20260630/mainline_chain_factor_v1_rebalance_plan.csv`
- `!!` `runs/20260630/portfolio_snapshot.csv`
- `!!` `runs/20260630/rebalance_plan.csv`
- `!!` `runs/20260701/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `!!` `runs/20260701/mainline_chain_factor_v1_rebalance_plan.csv`
- `!!` `runs/20260701/portfolio_snapshot.csv`
- `!!` `runs/20260701/rebalance_plan.csv`
- `!!` `runs/20260702/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `!!` `runs/20260702/mainline_chain_factor_v1_rebalance_plan.csv`
- `!!` `runs/20260702/portfolio_snapshot.csv`
- `!!` `runs/20260702/rebalance_plan.csv`
- `!!` `runs/20260702/risk_actions.csv`
- `!!` `runs/20260703/execution_checklist.csv`
- `!!` `runs/experiments/enterprise_e1_2_walk_forward_smoke/20260702-205831/selected_parameters.csv`
- `!!` `runs/experiments/enterprise_e1_2_walk_forward_smoke/20260702-205831/walk_forward.csv`
- `!!` `runtime/__pycache__/`
- `!!` `runtime/system_state.sqlite3`
- `!!` `runtime_backups/`
- `!!` `scripts/__pycache__/`
- `!!` `state/`
- `!!` `strategies/__pycache__/`
- `!!` `tests/__pycache__/`

### manual_review

- 无
