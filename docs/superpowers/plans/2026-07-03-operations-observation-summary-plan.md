# Operations Observation Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a daily operations observation summary that tells the operator what to inspect after the post-baseline system has run.

**Architecture:** Build a read-only Python module that scans `runs/`, `logs/`, `state/`, notification configuration, and known report artifacts. The CLI writes compact JSON and Markdown under `docs/release/`, keeping runtime output uncommitted while preserving a stable observation checklist.

**Tech Stack:** Python standard library, pytest.

## Global Constraints

- 不修改策略、因子、执行模型或调仓逻辑。
- 不运行 Tushare 更新，不运行策略，不发送 Bark。
- 不提交 `runs/`、`reports/dashboard*`、DuckDB/SQLite、日志、runtime backup。
- 新增核心逻辑先写失败测试，再实现。
- 生成 JSON 使用紧凑格式，避免生成文件超过 500 行。

---

### Task 1: Observation Summary Model

**Files:**
- Create: `tests/test_operations_observation.py`
- Create: `runtime/operations_observation.py`

**Interfaces:**
- Produces: `build_operations_observation(repo_root: Path) -> dict[str, object]`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from runtime.operations_observation import build_operations_observation


def test_operations_observation_reads_latest_run_and_notification(tmp_path: Path, monkeypatch):
    run_dir = tmp_path / "runs" / "20260703"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv"]:
        (run_dir / name).write_text("ok", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "scheduler.log").write_text("ok", encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "scheduler.heartbeat").write_text("ok", encoding="utf-8")
    monkeypatch.setenv("BARK_PUSH_URL", "https://example.test/token")

    report = build_operations_observation(tmp_path)

    assert report["latest_run_date"] == "20260703"
    assert report["notification"]["configured"] is True
    assert report["summary"]["fail"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: FAIL because `runtime.operations_observation` does not exist.

- [ ] **Step 3: Implement read-only summary model**

Inspect latest run directory, required artifacts, scheduler evidence, held reports, and Bark configuration.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: PASS.

### Task 2: Report Writer and CLI

**Files:**
- Modify: `tests/test_operations_observation.py`
- Modify: `runtime/operations_observation.py`
- Create: `scripts/run_operations_observation.py`

**Interfaces:**
- Produces: `write_operations_observation(report: Mapping[str, object], output_dir: Path) -> dict[str, Path]`

- [ ] **Step 1: Write failing writer tests**

Assert Markdown and compact JSON are created.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: FAIL because writer is missing.

- [ ] **Step 3: Implement writer and CLI**

The CLI writes `docs/release/operations_observation_summary.md` and `docs/release/operations_observation_summary.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: PASS.

### Task 3: Generate Current Summary and Update Governance

**Files:**
- Create: `docs/release/operations_observation_summary.md`
- Create: `docs/release/operations_observation_summary.json`
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Generate current summary**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_operations_observation.py --output-dir docs/release`

Expected: report lists latest run date, run artifacts, scheduler evidence, notification configuration, and held reports.

- [ ] **Step 2: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py tests/test_post_baseline_audit.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit source/governance outputs only**

Stage only E13 source, tests, scripts, governance docs, and release summary. Do not commit runtime `runs/` or dashboard report mutations.

## Self-Review

- Spec coverage: covers daily observation summary, notification configuration evidence, scheduler evidence, and runtime exclusion.
- Placeholder scan: no TBD or vague commands remain.
- Type consistency: function names and output paths are consistent across tasks.
