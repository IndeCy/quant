# Factor Strategy Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed per-strategy scheduler jobs with a dynamic runner that executes enabled strategy instances and supports configurable factor TopN strategies.

**Architecture:** Keep one data update job, then run one strategy batch job. The batch job reads enabled strategy instances from SQLite, dispatches existing compatibility strategies through adapters, and executes configurable factor strategies through a template runner.

**Tech Stack:** Python, SQLite, DuckDB, Pandas, APScheduler, existing monitoring repositories.

## Global Constraints

- Data update remains separated from strategy execution.
- Do not modify M0 `ExecutionModel`.
- Do not change existing Quality or mainline strategy logic.
- New runner writes strategy metrics, holdings, rebalance plans, and run records through existing repository boundaries.
- Scheduler must not hard-code concrete strategy IDs except compatibility adapter registration.

---

### Task 1: Replace Fixed Strategy Jobs With Batch Runner

**Files:**
- Create: `runtime/strategy_batch_runner.py`
- Create: `scripts/run_strategy_batch.py`
- Modify: `runtime/scheduler.py`
- Create: `tests/test_strategy_batch_runner.py`
- Modify: `tests/test_runtime_scheduler.py`

**Interfaces:**
- Produces: `run_enabled_strategy_instances(paths: RuntimePaths | None = None) -> dict[str, object]`
- Scheduler jobs become `daily_data_update_pipeline` and `strategy_batch_pipeline`.

- [ ] **Step 1: Write failing runner test**

```python
def test_batch_runner_loads_enabled_instances(tmp_path):
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repo = SystemRepository(paths.system_state_path)
    repo.upsert_strategy_instance({
        "strategy_id": "paper_test",
        "name": "Paper Test",
        "template_id": "factor_topn_monthly",
        "status": "paper",
        "enabled": True,
        "universe": "all_a",
        "filters": [],
        "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
        "construction": {"top_n": 20, "weighting": "equal_weight"},
        "risk_overlay": "",
        "benchmark": "510300",
    })
    summary = run_enabled_strategy_instances(paths)
    assert summary["enabled_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_strategy_batch_runner.py -q
```

- [ ] **Step 3: Implement compatibility runner**

First implementation routes existing instances through adapters:

- `quality_overlay` uses `examples/run_quality_overlay_paper.py --skip-update`.
- `mainline_chain_b` uses `scripts/run_mainline_chain_daily.py`.
- Unsupported templates record a failed run with reason `unsupported_template`.

- [ ] **Step 4: Update scheduler**

Keep `daily_data_update_pipeline`. Replace per-strategy jobs with `strategy_batch_pipeline`.

- [ ] **Step 5: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_strategy_batch_runner.py tests/test_runtime_scheduler.py -q
```

- [ ] **Step 6: Commit**

```bash
git add runtime/strategy_batch_runner.py scripts/run_strategy_batch.py runtime/scheduler.py tests/test_strategy_batch_runner.py tests/test_runtime_scheduler.py
git commit -m "feat(scheduler): run enabled strategy instances dynamically"
```

---

### Task 2: Execute Factor TopN Monthly Strategy Instances

**Files:**
- Create: `strategies/factor_topn_runner.py`
- Create: `tests/test_factor_topn_runner.py`
- Modify: `runtime/strategy_batch_runner.py`

**Interfaces:**
- Produces: `run_factor_topn_monthly_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]`
- Writes monitoring metrics, holdings, and rebalance plan for the instance.

- [ ] **Step 1: Write failing runner test with mock data**

```python
def test_factor_topn_runner_selects_weighted_top_names(tmp_path):
    instance = {
        "strategy_id": "quality_roa_ocf_v2",
        "factors": [
            {"factor_id": "roa", "weight": 0.6, "transform": "zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "zscore"},
        ],
        "construction": {"top_n": 2, "weighting": "equal_weight"},
        "benchmark": "510300",
    }
    result = run_factor_topn_monthly_instance(instance, RuntimePaths(tmp_path / "runtime"))
    assert result["selected_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_factor_topn_runner.py -q
```

- [ ] **Step 3: Implement minimal factor strategy execution**

Support only existing registered factors and transforms:

- `winsorize_zscore`
- `zscore`
- equal weighted score
- TopN
- equal weight

- [ ] **Step 4: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_factor_topn_runner.py tests/test_strategy_batch_runner.py -q
```

- [ ] **Step 5: Commit**

```bash
git add strategies/factor_topn_runner.py runtime/strategy_batch_runner.py tests/test_factor_topn_runner.py
git commit -m "feat(strategy): execute factor topn strategy instances"
```

---

## Final Verification

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

- Scheduler has one data update job and one strategy batch job.
- Existing Quality and mainline instances still run.
- Enabled factor TopN instances are picked up by the batch runner.
- Dashboard shows monitored instances without strategy ID hard-coding.

