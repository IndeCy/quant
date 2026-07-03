# Current State

## Active Milestone

Enterprise Quant Platform / Milestone E17：异常确认与处置回溯

## Active Phase

Phase E17.1：Operations Acknowledgement Log

## Current Status

pending

## Last Completed

- Phase E0.1：规划与任务治理。
- Phase E0.2：开发流程门禁。
- 新增 `docs/development_workflow.md`、`docs/phase_template.md`、`docs/verification_checklist.md`。
- Phase E1.1：Experiment Runner。
- 新增实验定义、运行、产物索引和最小 CLI。
- Phase E1.2：Walk-Forward Validation。
- 新增 `runtime/walk_forward.py`、`scripts/run_walk_forward_experiment.py` 和 `tests/test_walk_forward.py`。
- 最小 smoke 已登记到 `runs/experiments/enterprise_e1_2_walk_forward_smoke/`。
- Phase E2.1：Data Catalog。
- 新增本地 DuckDB/SQLite 数据资产扫描、持久化和 API 读取能力。
- 已刷新真实目录：20 个数据源，0 个错误。
- Phase E2.2：Data Quality Gate。
- 新增生产数据质量门禁，接入每日流水线，检查 A 股日线/复权因子和基准日线/复权/指数数据。
- 真实本地数据门禁通过：5 个关键检查，0 个失败。
- Phase E3.1：Factor Registry V2。
- 新增因子契约表、as-of 校验、数据依赖声明、策略因子契约覆盖检查和本地 API。
- 内置 Quality 与主线链动因子已登记 V2 契约。
- Phase E3.2：Factor Computation Runner。
- 新增基于 Factor Contract 的因子计算 Runner，幂等写入标准 `factor_scores` 和可选 `daily_prices`。
- 新增 CSV 标准入库脚本，供外部研究结果进入统一因子分数库。
- Phase E4.1：Strategy Lifecycle。
- 新增策略生命周期状态机、运行态准入校验和策略实例状态流转 API。
- 每日批处理只运行 `paper/shadow_live/live` 且通过因子契约校验的策略实例。
- Phase E4.2：Portfolio & Account Model。
- 新增统一账户快照、目标/实际持仓、现金、漂移和调仓差异模型。
- 新增账户快照 API，供前端展示策略账户视图。
- Phase E5.1：Operations Console。
- 新增数据目录/质量门禁、因子契约、策略生命周期、账户快照和漂移的前端运营控制台。
- 前端 `npm test`、`npm run build:pre` 和后端 `pytest` 均已通过，本地服务已重启。
- Phase E6.1：Manual Order Workflow。
- 新增本地手工调仓单生成、确认、成交/未成交回填和审计日志。
- 新增 `/api/manual-orders/*` API，并在策略页展示手工调仓批次。
- 后端 `421 passed`、前端 `24 passed / 47 tests`、`build:pre` 均已通过，本地服务已重启。
- Phase E7.1：Live Readiness Audit。
- 扩展生产就绪度审计，覆盖备份清单、Bark 通知、手工调仓闭环和券商权限边界。
- 当前 `/api/readiness` 返回 READY，新增审计项全部 PASS。
- 后端 `424 passed`、前端 `24 passed / 48 tests`、`build:pre` 均已通过，本地服务已重启。
- Phase E8.1：Release Baseline and Runtime Backup。
- 新增 `runtime/release_baseline.py` 和 `scripts/create_release_baseline.py`，可生成 runtime tar.gz、release manifest 和恢复说明。
- 已生成真实本地备份：`runtime_backups/quant_runtime_e8_1_smoke_20260703_091102.tar.gz`，manifest 记录当前分支和 dirty 状态。
- 后端 `426 passed`、前端 `24 passed / 48 tests`、`build:pre` 均已通过，本地服务已重启。
- Phase E9.1：Git Baseline Hygiene。
- 新增 `runtime/git_baseline.py` 和 `scripts/generate_git_baseline_report.py`，可生成提交前 Git 基线分类报告。
- 当前报告位于 `docs/release/git_baseline_report.md` 和 `docs/release/git_baseline_report.json`，分类结果：source_code 113、governance_docs 13、deleted_legacy 5、tracked_runtime_artifact 3、runtime_data 9、ignored_generated 85、manual_review 0。
- `runtime_backups/` 已确认归类为 ignored_generated，不进入提交候选。
- 后端全量测试通过：`430 passed`。
- Phase E10.1：Safe Commit Review。
- 新增 `runtime/safe_commit_review.py` 和 `scripts/generate_safe_commit_review.py`，基于 Git 基线报告生成安全提交候选、运行数据排除清单和已跟踪运行产物 hold 清单。
- 当前审查清单位于 `docs/release/safe_commit_review.md` 和 `docs/release/safe_commit_review.json`。
- 当前结果：ready_for_selective_commit=True，stage_candidates 135，hold_for_review 3，excluded_runtime 94。
- `docs/release/git_baseline_report.json` 和 `docs/release/safe_commit_review.json` 已改为紧凑 JSON，避免生成文件超过 500 行。
- 后端全量测试通过：`433 passed`。
- Phase E11.1：Selective Commit and Release Baseline。
- 新增 `docs/superpowers/plans/2026-07-03-selective-commit-release-baseline-plan.md`，明确选择性暂存、验证门禁和运行产物排除规则。
- 本阶段使用 `docs/release/safe_commit_review.json` 的 `stage_candidates` 执行选择性暂存，不使用 `git add -A`。
- `reports/dashboard.html`、`reports/dashboard_data.json`、`reports/quality_overlay_paper_latest.md` 保持 hold，不进入本次提交。
- Phase E12.1：Post-Baseline Operations。
- 新增 `runtime/post_baseline_audit.py` 和 `scripts/run_post_baseline_audit.py`，生成基线后本地运行观察审计。
- 当前审计报告位于 `docs/release/post_baseline_operations_audit.md` 和 `docs/release/post_baseline_operations_audit.json`。
- 当前审计结果：5 PASS、0 WARN、0 FAIL，`ready_for_observation=True`。
- 后端全量测试通过：`437 passed`。
- Phase E13.1：Operations Observation Summary。
- 新增 `runtime/operations_observation.py` 和 `scripts/run_operations_observation.py`，生成长期运行观察摘要。
- 当前摘要位于 `docs/release/operations_observation_summary.md` 和 `docs/release/operations_observation_summary.json`。
- 当前摘要结果：PASS 8、WARN 5、FAIL 0，最新运行日 `20260703`，WARN 集中在最新运行日缺少完整盘后日报/指标/持仓/调仓/run_log 产物。
- 后端全量测试通过：`440 passed`。
- Phase E14.1：Daily Report Warning Closure。
- 更新 `runtime/operations_observation.py`，区分 `latest_activity_date` 与 `latest_run_date`。
- 当前真实摘要：`latest_activity_date=20260703`、`latest_activity_type=pre_market_only`、`latest_run_date=20260702`，PASS 13、WARN 0、FAIL 0。
- 后端全量测试通过：`441 passed`。
- Phase E15.1：Operations UX and Alert Loop。
- 新增 `/api/operations/observation`，将长期运行观察摘要接入本地 API。
- 调度页新增“运行观察”面板，展示最新完整日报、最新活动、Bark 状态、PASS/WARN/FAIL 和日报/调度/报告产物状态。
- 后端全量测试通过：`442 passed`；前端全量测试通过：`25 files / 49 tests`；`npm run build:pre` 通过，本地服务已重启。
- Phase E16.1：Operations Alert Decision Surface。
- 新增 `runtime/operations_decision.py`，聚合运行观察和就绪度审计，输出 `NO_ACTION/ACTION_REQUIRED`、严重级别、下一步建议和人工处理 action。
- 新增 `/api/operations/decision`，调度页新增“今日操作判断”面板，第一屏展示是否需要人工介入。
- 当前真实接口返回：`decision=NO_ACTION`、`severity=NORMAL`、`manual_intervention_required=false`、`latest_run_date=20260702`。
- 后端全量测试通过：`445 passed`；前端全量测试通过：`26 files / 50 tests`；`npm run build:pre` 通过，本地服务已重启。

## Next Action

进入 Phase E17.1：Operations Acknowledgement Log。继续把人工确认、异常处理记录和处置结果做成可回溯闭环。

## Resume Prompt

```text
继续企业级量化系统项目，从 .planning/STATE.md 恢复，执行 Phase E17.1：Operations Acknowledgement Log。
```

## Verification Commands

```bash
test -f .planning/PROJECT.md
test -f .planning/REQUIREMENTS.md
test -f .planning/ROADMAP.md
test -f .planning/TASKS.md
test -f docs/development_workflow.md
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_experiment_runner.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_walk_forward.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_data_catalog.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_data_quality_gate.py tests/test_daily_pipeline.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_factor_registry_v2.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_factor_computation_runner.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_strategy_lifecycle.py tests/test_strategy_batch_runner.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_portfolio_account_model.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_manual_order_workflow.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_runtime_readiness.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_release_baseline.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision.py tests/test_operations_decision_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_git_baseline_report.py --output-dir docs/release
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_safe_commit_review.py --output-dir docs/release
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_post_baseline_audit.py --output-dir docs/release
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_operations_observation.py --output-dir docs/release
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
```
