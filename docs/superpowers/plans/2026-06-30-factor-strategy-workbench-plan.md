# Factor Strategy Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a factor-driven strategy workbench where external factor or strategy ideas can become structured assets, strategy instances, scheduled runs, and dashboard-visible history.

**Architecture:** Keep the existing M0/M3/M4 execution and monitoring layers intact. Add lightweight registry and instance layers in the existing SQLite state database, then migrate the frontend and scheduler to consume strategy assets dynamically.

**Tech Stack:** Python, SQLite, DuckDB, Pandas, FastAPI local API, React, TypeScript, Vite, Vitest.

## Global Constraints

- Do not modify M0 `ExecutionModel`.
- Do not change existing strategy logic while introducing registries.
- Do not introduce machine learning.
- Do not introduce automatic broker ordering.
- Data update must remain separated from strategy execution.
- Frontend must not hard-code concrete strategy IDs except in tests and migration fixtures.
- Runtime artifacts under `reports/` and `runs/` are not committed unless explicitly requested.

---

## File Structure

- `runtime/repository.py`: extend the local SQLite repository with idea, template, and strategy instance persistence.
- `runtime/strategy_templates.py`: define template metadata and validation helpers.
- `runtime/strategy_instance_catalog.py`: migrate current fixed strategies into strategy instance records.
- `runtime/strategy_batch_runner.py`: run enabled strategy instances through adapters.
- `scripts/run_strategy_batch.py`: scheduler entrypoint for the dynamic runner.
- `api/service.py`: expose factor ideas, strategy ideas, templates, and strategy instances.
- `api/local_server.py`: add local API routes for the new assets.
- `frontend/src/entities/strategyInstance/*`: frontend model and API client for strategy instances.
- `frontend/src/entities/researchIdea/*`: frontend model and API client for factor and strategy ideas.
- `frontend/src/pages/strategies/*`: evolve strategy page into strategy factory entry.
- `frontend/src/pages/dashboard/*`: consume strategy instances dynamically.

---

### Task 1: Persist Factor And Strategy Ideas

**Files:**
- Modify: `runtime/repository.py`
- Modify: `api/service.py`
- Modify: `api/local_server.py`
- Create: `tests/test_research_idea_repository.py`
- Modify: `tests/test_local_api_service.py`

**Interfaces:**
- Produces: `SystemRepository.upsert_factor_idea(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `SystemRepository.list_factor_ideas() -> list[dict[str, Any]]`
- Produces: `SystemRepository.upsert_strategy_idea(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `SystemRepository.list_strategy_ideas() -> list[dict[str, Any]]`
- Produces API routes: `GET/POST /api/research/factor-ideas`, `GET/POST /api/research/strategy-ideas`

- [ ] **Step 1: Write failing repository tests**

```python
def test_factor_idea_can_be_saved_and_listed(tmp_path):
    repo = SystemRepository(tmp_path / "state.sqlite")
    saved = repo.upsert_factor_idea({
        "idea_id": "profit_stability",
        "title": "盈利稳定性",
        "raw_description": "过去三年ROE波动率越低越好",
        "source": "external_note",
        "hypothesis": "盈利稳定公司更可能获得稳定估值溢价",
        "required_data": ["roe", "f_ann_date"],
        "as_of_requirement": "必须使用财报披露日",
        "direction": "lower_is_better",
        "status": "draft",
    })
    assert saved["idea_id"] == "profit_stability"
    assert repo.list_factor_ideas()[0]["title"] == "盈利稳定性"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_research_idea_repository.py -q
```

Expected: failure because repository methods do not exist.

- [ ] **Step 3: Implement SQLite persistence**

Add tables created lazily in `runtime/repository.py`:

```sql
CREATE TABLE factor_ideas (
  idea_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  raw_description TEXT NOT NULL,
  source TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  required_data TEXT NOT NULL,
  as_of_requirement TEXT NOT NULL,
  direction TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  modified_at TEXT NOT NULL
)
```

Use JSON strings for list fields. Apply the same pattern for `strategy_ideas`.

- [ ] **Step 4: Add service and routes**

Add methods:

```python
def factor_ideas(self) -> list[dict[str, Any]]:
    return self.system_repository.list_factor_ideas()

def save_factor_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
    return self.system_repository.upsert_factor_idea(payload)
```

Add FastAPI routes in `api/local_server.py`.

- [ ] **Step 5: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_research_idea_repository.py tests/test_local_api_service.py -q
```

- [ ] **Step 6: Commit**

```bash
git add runtime/repository.py api/service.py api/local_server.py tests/test_research_idea_repository.py tests/test_local_api_service.py
git commit -m "feat(research): persist factor and strategy ideas"
```

---

### Task 2: Add Strategy Templates And Instances

**Files:**
- Create: `runtime/strategy_templates.py`
- Create: `runtime/strategy_instance_catalog.py`
- Modify: `runtime/repository.py`
- Create: `tests/test_strategy_instances.py`

**Interfaces:**
- Produces: `list_strategy_templates() -> list[dict[str, Any]]`
- Produces: `SystemRepository.upsert_strategy_instance(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `SystemRepository.list_strategy_instances(enabled_only: bool = False) -> list[dict[str, Any]]`
- Produces: `register_builtin_strategy_instances(repository: SystemRepository) -> None`

- [ ] **Step 1: Write failing tests**

```python
def test_strategy_instance_can_reference_factor_template(tmp_path):
    repo = SystemRepository(tmp_path / "state.sqlite")
    instance = repo.upsert_strategy_instance({
        "strategy_id": "quality_roa_ocf_v2",
        "name": "Quality ROA OCF V2",
        "template_id": "factor_topn_monthly",
        "status": "paper",
        "enabled": True,
        "universe": "all_a",
        "filters": ["listed_3y", "exclude_st"],
        "factors": [
            {"factor_id": "roa", "weight": 0.6, "transform": "winsorize_zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "winsorize_zscore"},
        ],
        "construction": {"top_n": 20, "weighting": "equal_weight"},
        "risk_overlay": "vol_20_45_to_30",
        "benchmark": "510300",
    })
    assert instance["enabled"] is True
    assert repo.list_strategy_instances(enabled_only=True)[0]["strategy_id"] == "quality_roa_ocf_v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_strategy_instances.py -q
```

- [ ] **Step 3: Implement templates**

Create `runtime/strategy_templates.py` with:

```python
def list_strategy_templates() -> list[dict[str, object]]:
    return [
        {
            "template_id": "factor_topn_monthly",
            "name": "多因子TopN月频策略",
            "required_sections": ["universe", "filters", "factors", "construction", "benchmark"],
            "supported_status": ["draft", "research", "paper", "shadow_live", "paused", "archived"],
        },
        {
            "template_id": "industry_chain_momentum",
            "name": "产业链动量策略",
            "required_sections": ["universe", "construction", "benchmark"],
            "supported_status": ["paper", "shadow_live", "paused", "archived"],
        },
    ]
```

- [ ] **Step 4: Implement strategy instance persistence**

Use one `strategy_instances` table with JSON columns for `filters`, `factors`, `construction`, and `risk_overlay`.

- [ ] **Step 5: Register built-in instances**

`runtime/strategy_instance_catalog.py` should register:

- `quality_overlay`
- `mainline_chain_b`

Both are compatibility instances that call existing adapters.

- [ ] **Step 6: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_strategy_instances.py -q
```

- [ ] **Step 7: Commit**

```bash
git add runtime/strategy_templates.py runtime/strategy_instance_catalog.py runtime/repository.py tests/test_strategy_instances.py
git commit -m "feat(strategy): add templates and strategy instances"
```

---

### Task 3: Expose Strategy Factory APIs

**Files:**
- Modify: `api/service.py`
- Modify: `api/local_server.py`
- Modify: `tests/test_local_api_service.py`

**Interfaces:**
- Produces API route: `GET /api/strategy-templates`
- Produces API route: `GET /api/strategy-instances`
- Produces API route: `POST /api/strategy-instances`

- [ ] **Step 1: Write failing service tests**

```python
def test_local_api_service_exposes_strategy_templates_and_instances(tmp_path):
    service = LocalApiService(_seed_runtime(tmp_path))
    assert service.strategy_templates()[0]["template_id"] == "factor_topn_monthly"
    saved = service.save_strategy_instance({
        "strategy_id": "quality_roa_ocf_v2",
        "name": "Quality ROA OCF V2",
        "template_id": "factor_topn_monthly",
        "status": "paper",
        "enabled": True,
        "universe": "all_a",
        "filters": ["listed_3y"],
        "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
        "construction": {"top_n": 20, "weighting": "equal_weight"},
        "risk_overlay": "",
        "benchmark": "510300",
    })
    assert saved["strategy_id"] == "quality_roa_ocf_v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py -q
```

- [ ] **Step 3: Implement service methods and FastAPI routes**

Add thin route handlers only. Do not implement strategy execution in this task.

- [ ] **Step 4: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py -q
```

- [ ] **Step 5: Commit**

```bash
git add api/service.py api/local_server.py tests/test_local_api_service.py
git commit -m "feat(api): expose strategy factory assets"
```

---

### Task 4: Make Frontend Data Catalog-Driven

**Files:**
- Modify: `frontend/src/app/types.ts`
- Modify: `frontend/src/app/loadDashboardData.ts`
- Modify: `frontend/src/app/state.ts`
- Modify: `frontend/src/entities/strategy/api.ts`
- Modify: `frontend/src/app/state.test.ts`
- Modify: `frontend/src/entities/strategy/display.test.ts`

**Interfaces:**
- Produces: `strategyDetails: Record<string, StrategyDefinition>`
- Produces: `strategySeriesMap: Record<string, StrategyMetric[]>`
- Produces: default selected strategy derived from catalog, not hard-coded ID.

- [ ] **Step 1: Write failing frontend tests**

```ts
it("chooses default strategy from catalog without hard-coded id", () => {
  const selected = chooseDefaultStrategyId([
    { strategy_id: "new_strategy", status: "active", latest_metrics: null } as StrategyDefinition
  ]);
  expect(selected).toBe("new_strategy");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && npm test -- state
```

- [ ] **Step 3: Implement catalog-driven loading**

Change `loadDashboardData.ts` to:

1. Load `listStrategies()`.
2. Fetch every strategy detail.
3. Fetch every strategy series.
4. Build maps keyed by `strategy_id`.
5. Keep `strategy` and `strategySeries` as compatibility fields for the default selected strategy.

- [ ] **Step 4: Run verification**

Run:

```bash
cd frontend && npm test && npm run build:pre
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/types.ts frontend/src/app/loadDashboardData.ts frontend/src/app/state.ts frontend/src/entities/strategy/api.ts frontend/src/app/state.test.ts frontend/src/entities/strategy/display.test.ts
git commit -m "feat(frontend): load strategies from catalog"
```

---

### Task 5: Build Dynamic Dashboard And Strategy Switcher

**Files:**
- Modify: `frontend/src/app/layout/TopStatusBar.tsx`
- Modify: `frontend/src/pages/dashboard/DashboardPage.tsx`
- Create: `frontend/src/pages/dashboard/components/StrategyOverviewGrid.tsx`
- Create: `frontend/src/pages/dashboard/components/MultiStrategyChart.tsx`
- Modify: `frontend/src/app/navigation.test.ts`

**Interfaces:**
- Consumes: `DashboardData.strategyDetails`
- Consumes: `DashboardData.strategySeriesMap`
- Produces UI mode: `ALL` or selected strategy ID.

- [ ] **Step 1: Write failing tests**

Add tests that verify the selector options come from strategy names in data and not from fixed IDs.

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd frontend && npm test -- navigation
```

- [ ] **Step 3: Implement selector and dashboard modes**

Top bar:

- Always include `ALL`.
- Append all strategies from `data.strategies`.

Dashboard:

- In `ALL`, render overview grid and multi-strategy chart.
- In single strategy, reuse existing metric grid and detail panels.

- [ ] **Step 4: Run verification**

Run:

```bash
cd frontend && npm test && npm run build:pre
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/layout/TopStatusBar.tsx frontend/src/pages/dashboard/DashboardPage.tsx frontend/src/pages/dashboard/components/StrategyOverviewGrid.tsx frontend/src/pages/dashboard/components/MultiStrategyChart.tsx frontend/src/app/navigation.test.ts
git commit -m "feat(frontend): add catalog-driven strategy dashboard"
```

---

## Runner Plan

Dynamic scheduling and executable factor strategy work continue in
`docs/superpowers/plans/2026-06-30-factor-strategy-runner-plan.md`.

## Final Verification For This Plan

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && npm test && npm run build:pre
```

Manual checks:

```bash
curl -s http://127.0.0.1:8765/api/strategy-instances | python -m json.tool
curl -s http://127.0.0.1:8765/api/scheduler/status | python -m json.tool
```

Expected:

- Existing Quality and mainline strategies appear as strategy instances.
- New factor strategy instances can be saved.
- Dashboard shows all monitored strategy instances without hard-coded strategy IDs.
