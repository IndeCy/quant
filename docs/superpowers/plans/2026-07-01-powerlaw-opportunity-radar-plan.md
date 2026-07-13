# Long Horizon Power Law Opportunity Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将投研观察池升级为“长期右偏产业机会雷达”，用于沉淀 5-10 年产业假设、候选公司角色、起势证据和升级路径。

**Architecture:** 继续复用现有 `opportunity_themes`、`opportunity_stocks`、`research_monitor_runs` 三层结构，只增加轻量字段和 JSON 证据，不进入策略库、不产生交易信号。每日研究监控从本地行情缓存和财务库读取数据，更新观察等级、起势证据、反证状态和升级建议。

**Tech Stack:** Python、SQLite、DuckDB、Pandas、FastAPI、本地 React/Vite 前端。

## Global Constraints

- 不修改已验证策略逻辑。
- 不新增交易因子，不进入策略库，不生成调仓建议。
- 不新增外部数据源，只使用当前本地缓存、DuckDB 财务数据和已有 510300 基准缓存。
- 所有新增逻辑必须可测试，可通过 `pytest` 和 `npm run build:pre` 验证。
- Python 关键业务逻辑保留中文注释和类型提示。

---

### Task 1: Extend Opportunity Data Model

**Files:**
- Modify: `runtime/repository_schema.py`
- Modify: `runtime/research_repository.py`
- Modify: `runtime/repository.py`
- Test: `tests/test_runtime_repository.py`

**Interfaces:**
- Consumes: existing `SystemRepository.upsert_opportunity_theme(payload)` and `upsert_opportunity_stock(payload)`.
- Produces: theme fields `horizon_years`, `thesis_type`, `upgrade_rule`, `disconfirm_rule`; stock fields `chain_role`, `conviction`, `first_observed_date`, `evidence`.

- [ ] Add columns using migration-safe `ALTER TABLE` helper.
- [ ] Persist new fields in upsert/load methods.
- [ ] Parse `evidence_json` into `evidence`.
- [ ] Add repository test for long-horizon metadata.

### Task 2: Add Power Law Evidence Scoring

**Files:**
- Modify: `runtime/research_monitor.py`
- Test: `tests/test_research_monitor.py`

**Interfaces:**
- Consumes: local qfq bars from `MarketDataCache`, optional financial rows from `fina_indicator.duckdb`.
- Produces: metrics keys `ret_1y`, `ret_2y`, `relative_strength_250d`, `distance_to_high_250d`, `finance_growth_confirmed`, `trend_confirmed`, `disconfirm_triggered`, `powerlaw_score`.

- [ ] Compute long-horizon price evidence.
- [ ] Compute 510300-relative strength when benchmark data exists.
- [ ] Keep missing benchmark non-fatal and mark `benchmark_status`.
- [ ] Classify S/A/B/淘汰 using evidence score, while staying research-only.
- [ ] Extend tests with high-growth and disconfirm cases.

### Task 3: Register AI Optical Module as Power Law Theme

**Files:**
- Modify: `runtime/opportunity_catalog.py`
- Test: `tests/test_runtime_repository.py`

**Interfaces:**
- Consumes: `SystemRepository`.
- Produces: built-in theme metadata and stock chain roles.

- [ ] Mark theme as `thesis_type=power_law_industry`.
- [ ] Set `horizon_years=10`.
- [ ] Add explicit upgrade and disconfirm rules.
- [ ] Add stock chain roles and conviction levels.

### Task 4: Expose Radar Fields in Frontend

**Files:**
- Modify: `frontend/src/entities/research/model.ts`
- Modify: `frontend/src/pages/research/ResearchPage.tsx`
- Modify: `frontend/src/shared/styles/features.css`

**Interfaces:**
- Consumes: `/api/research/opportunities`.
- Produces: visual display for horizon, chain role, conviction, power law score, evidence and disconfirm status.

- [ ] Add TypeScript fields.
- [ ] Show theme horizon and upgrade path.
- [ ] Show stock chain role, conviction, score, relative strength and disconfirm status.
- [ ] Keep the page readable on narrow screens.

### Task 5: Verify Runtime and Build

**Files:**
- Modify only test expectations as needed.

**Interfaces:**
- Consumes: project commands.
- Produces: passing test/build and restarted local services.

- [ ] Run targeted pytest for repository and monitor.
- [ ] Run full pytest.
- [ ] Run frontend tests.
- [ ] Run `npm run build:pre`.
- [ ] Restart services and verify `/api/research/opportunities`.
