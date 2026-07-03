# Safe Commit Review

- repo_root: `/Users/admin/PycharmProjects/quant`
- baseline_generated_at: `2026-07-03T09:50:06`
- ready_for_selective_commit: `True`

## Safe Git Add

git add -- '.planning/ROADMAP.md' '.planning/STATE.md' '.planning/TASKS.md' 'docs/release/post_baseline_operations_audit.json' 'docs/release/post_baseline_operations_audit.md' 'docs/superpowers/plans/2026-07-03-post-baseline-operations-audit-plan.md' 'runtime/post_baseline_audit.py' 'scripts/run_post_baseline_audit.py' 'tests/test_post_baseline_audit.py'

## Safe Git Update

# no deleted candidates

## Stage Candidates

- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/TASKS.md`
- `docs/release/post_baseline_operations_audit.json`
- `docs/release/post_baseline_operations_audit.md`
- `docs/superpowers/plans/2026-07-03-post-baseline-operations-audit-plan.md`
- `runtime/post_baseline_audit.py`
- `scripts/run_post_baseline_audit.py`
- `tests/test_post_baseline_audit.py`

## Hold For Review

- `reports/dashboard.html`
- `reports/dashboard_data.json`
- `reports/quality_overlay_paper_latest.md`

## Excluded Runtime

- `.DS_Store`
- `.gitignore.bak`
- `.idea/copilot.data.migration.ask2agent.xml`
- `.idea/dbnavigator.xml`
- `.idea/inspectionProfiles/Project_Default.xml`
- `.idea/misc.xml`
- `.idea/vcs.xml`
- `.idea/workspace.xml`
- `.pytest_cache/`
- `api/__pycache__/`
- `backtest/__pycache__/`
- `balancesheet.duckdb`
- `cashflow.duckdb`
- `daily_adj_19901219_20260615.duckdb`
- `data/__pycache__/`
- `data/benchmark_increment.duckdb`
- `data/dividend_increment.duckdb`
- `data/industry_increment.duckdb`
- `data/live_market_increment.duckdb`
- `data/market_breadth.sqlite3`
- `data/market_cache.sqlite3`
- `data/monitoring.sqlite3`
- `data/opportunity_concept_increment.duckdb`
- `data/paper_trading.sqlite3`
- `data/quality_overlay_paper.sqlite3`
- `data/strategy_history.sqlite3`
- `etf_lof_reits_basic_export_20041220_20260617.duckdb`
- `etf_lof_reits_daily_adj_20041220_20260617.duckdb`
- `examples/__pycache__/`
- `express.duckdb`
- `fina_indicator.duckdb`
- `forecast.duckdb`
- `frontend/dist/`
- `frontend/node_modules/`
- `frontend/src/shared/lib/`
- `frontend/tsconfig.tsbuildinfo`
- `income.duckdb`
- `logs/`
- `monitoring/__pycache__/`
- `pipeline/__pycache__/`
- `quant_backtest.egg-info/`
- `reports/cash_cow_v15_holdings.csv`
- `reports/cash_cow_v1_holdings.csv`
- `reports/industry_rotation_vs_benchmark_curve.csv`
- `reports/quality_attribution_holdings.csv`
- `reports/quality_cleanup_holdings.csv`
- `reports/quality_current_holdings_for_comparison.csv`
- `reports/quality_overlay_annual.csv`
- `reports/quality_overlay_robustness_grid.csv`
- `reports/quality_overlay_trigger_events.csv`
- `reports/quality_overlay_walk_forward.csv`
- `reports/quality_strategy_v1_holdings.csv`
- `reports/quality_strategy_v1_worst_contributors.csv`
- `reports/quality_volatility_grid_search.csv`
- `reports/style_rotation_diagnostic_curves.csv`
- `reports/style_rotation_diagnostic_metrics.csv`
- `reports/style_rotation_diagnostic_signals.csv`
- `runs/.DS_Store`
- `runs/202606/`
- `runs/20260626/daily_report.md`
- `runs/20260626/portfolio_snapshot.csv`
- `runs/20260626/rebalance_plan.csv`
- `runs/20260626/strategy_metrics.json`
- `runs/20260629/`
- `runs/20260629/portfolio_snapshot.csv`
- `runs/20260629/rebalance_plan.csv`
- `runs/20260630/`
- `runs/20260630/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `runs/20260630/mainline_chain_factor_v1_rebalance_plan.csv`
- `runs/20260630/portfolio_snapshot.csv`
- `runs/20260630/rebalance_plan.csv`
- `runs/20260701/`
- `runs/20260701/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `runs/20260701/mainline_chain_factor_v1_rebalance_plan.csv`
- `runs/20260701/portfolio_snapshot.csv`
- `runs/20260701/rebalance_plan.csv`
- `runs/20260702/`
- `runs/20260702/mainline_chain_factor_v1_portfolio_snapshot.csv`
- `runs/20260702/mainline_chain_factor_v1_rebalance_plan.csv`
- `runs/20260702/portfolio_snapshot.csv`
- `runs/20260702/rebalance_plan.csv`
- `runs/20260702/risk_actions.csv`
- `runs/20260703/`
- `runs/20260703/execution_checklist.csv`
- `runs/experiments/`
- `runs/experiments/enterprise_e1_2_walk_forward_smoke/20260702-205831/selected_parameters.csv`
- `runs/experiments/enterprise_e1_2_walk_forward_smoke/20260702-205831/walk_forward.csv`
- `runtime/__pycache__/`
- `runtime/system_state.sqlite3`
- `runtime_backups/`
- `scripts/__pycache__/`
- `state/`
- `strategies/__pycache__/`
- `tests/__pycache__/`

## Manual Review

- 无

## Notes

- 选择性提交前先阅读本报告和 Git diff。
- 运行数据、备份包、日报输出不进入代码发布基线。
- 已跟踪报告产物不自动处理，避免误删用户需要保留的本地观察结果。
