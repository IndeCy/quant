# Git Baseline Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable pre-commit baseline report that separates source code, governance documents, runtime data, generated reports, ignored artifacts, and manual-review changes.

**Architecture:** Add a small Python classifier under `runtime/` with pure functions for tests and a CLI script under `scripts/` for real repository reports. The tool reads `git status`, classifies paths by project policy, and writes Markdown/JSON governance artifacts without staging or committing anything.

**Tech Stack:** Python standard library, pytest, git CLI.

## Global Constraints

- 使用中文回答和项目文档说明。
- 不修改策略、因子、执行模型、调度业务逻辑。
- 不提交运行数据、DuckDB、SQLite、日志、runtime backup。
- 新增核心逻辑先写测试，再实现。
- Python 代码保持清晰类型提示，关键业务逻辑添加中文注释。

---

### Task 1: Git Baseline Classifier

**Files:**
- Create: `tests/test_git_baseline.py`
- Create: `runtime/git_baseline.py`

**Interfaces:**
- Produces: `classify_git_path(path: str, status: str = "") -> str`
- Produces: `parse_status_lines(lines: Iterable[str]) -> list[GitStatusEntry]`
- Produces: `summarize_entries(entries: Iterable[GitStatusEntry]) -> dict[str, list[GitStatusEntry]]`

- [ ] **Step 1: Write the failing tests**

```python
from runtime.git_baseline import classify_git_path, parse_status_lines, summarize_entries


def test_classify_git_paths_separates_commit_safe_and_runtime_files():
    assert classify_git_path("runtime/scheduler.py", " M") == "source_code"
    assert classify_git_path(".planning/STATE.md", "??") == "governance_docs"
    assert classify_git_path("runtime_backups/quant.tar.gz", "!!") == "ignored_generated"
    assert classify_git_path("data/local.duckdb", "??") == "runtime_data"
    assert classify_git_path("reports/dashboard_data.json", " M") == "tracked_runtime_artifact"


def test_parse_status_lines_preserves_status_and_path():
    entries = parse_status_lines([" M runtime/scheduler.py", "?? .planning/STATE.md"])
    assert entries[0].status == "M"
    assert entries[0].path == "runtime/scheduler.py"
    assert entries[1].status == "??"
    assert entries[1].path == ".planning/STATE.md"


def test_summarize_entries_groups_by_classification():
    entries = parse_status_lines([" M runtime/scheduler.py", "?? data/cache.duckdb"])
    grouped = summarize_entries(entries)
    assert [item.path for item in grouped["source_code"]] == ["runtime/scheduler.py"]
    assert [item.path for item in grouped["runtime_data"]] == ["data/cache.duckdb"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py -q`

Expected: FAIL because `runtime.git_baseline` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement a small dataclass-based classifier with deterministic path rules.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py -q`

Expected: PASS.

### Task 2: Report Writer and CLI

**Files:**
- Modify: `tests/test_git_baseline.py`
- Modify: `runtime/git_baseline.py`
- Create: `scripts/generate_git_baseline_report.py`

**Interfaces:**
- Produces: `build_git_baseline_report(repo_root: Path, include_ignored: bool = True) -> dict[str, object]`
- Produces: `write_git_baseline_report(report: Mapping[str, object], output_dir: Path) -> dict[str, Path]`

- [ ] **Step 1: Write failing tests**

Add a tmpdir test that writes a small report and asserts both Markdown and JSON exist.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py -q`

Expected: FAIL because report writer is missing.

- [ ] **Step 3: Implement report writer and CLI**

The CLI writes to `docs/release/git_baseline_report.md` and `docs/release/git_baseline_report.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py -q`

Expected: PASS.

### Task 3: Generate Current Baseline and Update Governance State

**Files:**
- Create: `docs/release/git_baseline_report.md`
- Create: `docs/release/git_baseline_report.json`
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Generate current report**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_git_baseline_report.py --output-dir docs/release`

Expected: report contains grouped working-tree changes and confirms ignored runtime backups are not commit candidates.

- [ ] **Step 2: Run focused tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_git_baseline.py tests/test_release_baseline.py -q`

Expected: PASS.

- [ ] **Step 3: Run project verification**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Update planning files**

Mark E9.1 done and record next action as user confirmation of safe commit groups.

## Self-Review

- Spec coverage: covers safe grouping, report generation, runtime backup exclusion, and no commit side effects.
- Placeholder scan: no deferred implementation placeholders remain; tasks name exact files and commands.
- Type consistency: all task interfaces are defined before use.
