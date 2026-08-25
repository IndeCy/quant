# Production Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a minimal runtime home abstraction so production candidate outputs can move from repo-local scattered paths to one migratable `QUANT_HOME`.

**Architecture:** Add a small `runtime.paths` module that resolves default repo-local paths or environment-driven runtime paths. Wire the existing Quality Overlay Paper daily script to those paths without changing strategy logic.

**Tech Stack:** Python stdlib, pathlib, pytest.

## Global Constraints

- 不修改 Quality Alpha V1 策略逻辑。
- 不新增因子、不调参数、不改 M0 ExecutionModel。
- 未设置 `QUANT_HOME` 时保持现有路径兼容。
- 设置 `QUANT_HOME` 后，可变产物必须集中写入该目录。

---

### Task 1: Runtime Path Abstraction

**Files:**
- Create: `runtime/__init__.py`
- Create: `runtime/paths.py`
- Test: `tests/test_runtime_paths.py`

**Interfaces:**
- Produces: `RuntimePaths`, `get_runtime_paths()`

- [ ] Create a dataclass that resolves `data/`, `state/`, `runs/`, `reports/`, `logs/`, and `config/`.
- [ ] Add tests for default repo-local behavior and `QUANT_HOME` override behavior.
- [ ] Run `pytest tests/test_runtime_paths.py`.

### Task 2: Daily Pipeline Path Wiring

**Files:**
- Modify: `examples/run_quality_overlay_paper.py`
- Test: `tests/test_quality_overlay_paper.py`

**Interfaces:**
- Consumes: `get_runtime_paths()`

- [ ] Replace hardcoded mutable paths in the daily paper script with runtime paths.
- [ ] Keep immutable historical data paths untouched for this phase.
- [ ] Add a test that reloading the script under `QUANT_HOME` points mutable outputs to the runtime home.
- [ ] Run `pytest tests/test_runtime_paths.py tests/test_quality_overlay_paper.py tests/test_production_daily_pipeline.py`.

### Task 3: Verification

**Files:**
- Verify only.

- [ ] Run targeted tests.
- [ ] Inspect `git diff --stat`.
- [ ] Confirm no strategy, factor, or execution model logic changed.
