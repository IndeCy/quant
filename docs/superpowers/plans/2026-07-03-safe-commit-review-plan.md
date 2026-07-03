# Safe Commit Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a safe commit review package from the Git baseline report so source/governance changes can be staged without runtime data or generated artifacts.

**Architecture:** Reuse `docs/release/git_baseline_report.json` as the source of truth. Add a small Python module that turns classified paths into stage candidates, excluded runtime paths, and hold-for-review artifacts, then writes Markdown/JSON review outputs with exact safe `git add -- ...` commands.

**Tech Stack:** Python standard library, pytest, git CLI.

## Global Constraints

- 使用中文回答和项目文档说明。
- 不修改策略、因子、执行模型、调度业务逻辑。
- 不提交运行数据、DuckDB、SQLite、日志、runtime backup。
- 不自动回滚用户或运行时产物变更。
- 新增核心逻辑先写失败测试，再实现。
- 文件尽量小于 500 行，生成 JSON 使用紧凑格式避免超限。

---

### Task 1: Safe Commit Review Model

**Files:**
- Create: `tests/test_safe_commit_review.py`
- Create: `runtime/safe_commit_review.py`

**Interfaces:**
- Produces: `build_safe_commit_review(baseline: Mapping[str, object]) -> dict[str, object]`
- Produces: `render_safe_commit_markdown(review: Mapping[str, object]) -> str`

- [ ] **Step 1: Write the failing tests**

```python
from runtime.safe_commit_review import build_safe_commit_review


def test_safe_commit_review_separates_stage_exclude_and_hold_groups():
    baseline = {
        "summary": {},
        "groups": {
            "source_code": [{"status": "M", "path": "runtime/scheduler.py"}],
            "governance_docs": [{"status": "??", "path": "docs/dev.md"}],
            "deleted_legacy": [{"status": "D", "path": "scripts/old.py"}],
            "tracked_runtime_artifact": [{"status": "M", "path": "reports/dashboard.html"}],
            "runtime_data": [{"status": "??", "path": "runs/20260703/"}],
            "ignored_generated": [{"status": "!!", "path": "runtime_backups/"}],
            "manual_review": [],
        },
    }

    review = build_safe_commit_review(baseline)

    assert review["ready_for_selective_commit"] is True
    assert review["stage_candidates"] == [
        "runtime/scheduler.py",
        "docs/dev.md",
        "scripts/old.py",
    ]
    assert review["hold_for_review"] == ["reports/dashboard.html"]
    assert review["excluded_runtime"] == ["runs/20260703/", "runtime_backups/"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py -q`

Expected: FAIL because `runtime.safe_commit_review` does not exist.

- [ ] **Step 3: Implement minimal review builder**

Read groups by classification and produce deterministic sorted path lists.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py -q`

Expected: PASS.

### Task 2: CLI and Release Review Outputs

**Files:**
- Modify: `tests/test_safe_commit_review.py`
- Modify: `runtime/safe_commit_review.py`
- Create: `scripts/generate_safe_commit_review.py`
- Modify: `runtime/git_baseline.py`

**Interfaces:**
- Produces: `write_safe_commit_review(review: Mapping[str, object], output_dir: Path) -> dict[str, Path]`
- Updates: `write_git_baseline_report(...)` writes compact JSON.

- [ ] **Step 1: Write failing tests**

Add tests that verify Markdown/JSON are written, JSON is compact, and the safe `git add -- ...` command excludes `reports/`, `runs/`, `data/*.duckdb`, and `runtime_backups/`.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py tests/test_git_baseline.py -q`

Expected: FAIL because writer and CLI are missing or JSON is multi-line.

- [ ] **Step 3: Implement writer, CLI, and compact JSON**

The CLI reads `docs/release/git_baseline_report.json` and writes `docs/release/safe_commit_review.md` plus `docs/release/safe_commit_review.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py tests/test_git_baseline.py -q`

Expected: PASS.

### Task 3: Generate Current Review and Update Governance State

**Files:**
- Create: `docs/release/safe_commit_review.md`
- Create: `docs/release/safe_commit_review.json`
- Modify: `docs/release/git_baseline_report.json`
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Regenerate baseline and review**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_git_baseline_report.py --output-dir docs/release
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_safe_commit_review.py --output-dir docs/release
```

Expected: review reports safe stage candidates and explicit excluded runtime paths.

- [ ] **Step 2: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py tests/test_git_baseline.py tests/test_release_baseline.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Update planning files**

Mark E10.1 done and set the next action to selective staging/commit after user confirmation or a future explicit commit phase.

## Self-Review

- Spec coverage: covers safe commit candidates, runtime exclusion, tracked runtime artifact hold list, and generated file size control.
- Placeholder scan: no TBD or open implementation placeholders remain.
- Type consistency: interface names match task references.
