# Post-Baseline Operations Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable post-baseline operations audit that verifies the local quant system is ready for long-running Shadow Live / Paper observation after the release baseline commit.

**Architecture:** Add a pure Python audit module that reads local filesystem/git/runtime evidence and produces PASS/WARN/FAIL checks. A CLI writes compact JSON and Markdown reports under `docs/release/` so the operating baseline can be reviewed without committing daily runtime data.

**Tech Stack:** Python standard library, pytest, git CLI.

## Global Constraints

- 不修改策略、因子、执行模型或调仓逻辑。
- 审计只读取本地状态，不触发 Tushare 更新，不运行策略，不发送 Bark。
- 不提交 `runs/`、`reports/dashboard*`、DuckDB/SQLite、日志、runtime backup。
- 新增核心逻辑先写失败测试，再实现。
- Python 文件保持清晰类型提示，关键业务逻辑添加中文注释。
- 生成 JSON 使用紧凑格式，避免生成文件超过 500 行。

---

### Task 1: Operations Audit Model

**Files:**
- Create: `tests/test_post_baseline_audit.py`
- Create: `runtime/post_baseline_audit.py`

**Interfaces:**
- Produces: `AuditCheck`
- Produces: `build_post_baseline_audit(repo_root: Path, required_scripts: Iterable[str] | None = None) -> dict[str, object]`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from runtime.post_baseline_audit import build_post_baseline_audit


def test_post_baseline_audit_passes_with_required_scripts(tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "runs" / "20260703").mkdir(parents=True)
    (tmp_path / "scripts" / "run_daily_pipeline.py").write_text("", encoding="utf-8")

    report = build_post_baseline_audit(tmp_path, required_scripts=["scripts/run_daily_pipeline.py"])

    assert report["summary"]["fail"] == 0
    assert any(item["name"] == "required_scripts" for item in report["checks"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q`

Expected: FAIL because `runtime.post_baseline_audit` does not exist.

- [ ] **Step 3: Implement minimal audit model**

Implement checks for required scripts, run directories, held report artifacts, and git runtime boundary.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q`

Expected: PASS.

### Task 2: Report Writer and CLI

**Files:**
- Modify: `tests/test_post_baseline_audit.py`
- Modify: `runtime/post_baseline_audit.py`
- Create: `scripts/run_post_baseline_audit.py`

**Interfaces:**
- Produces: `write_post_baseline_audit(report: Mapping[str, object], output_dir: Path) -> dict[str, Path]`

- [ ] **Step 1: Write failing report writer tests**

Add tests that assert Markdown and compact JSON are created.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q`

Expected: FAIL because writer is missing.

- [ ] **Step 3: Implement writer and CLI**

The CLI writes `docs/release/post_baseline_operations_audit.md` and `docs/release/post_baseline_operations_audit.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q`

Expected: PASS.

### Task 3: Generate Current Audit and Update Governance

**Files:**
- Create: `docs/release/post_baseline_operations_audit.md`
- Create: `docs/release/post_baseline_operations_audit.json`
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Generate current report**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_post_baseline_audit.py --output-dir docs/release`

Expected: report lists PASS/WARN/FAIL checks for long-running local operations.

- [ ] **Step 2: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_post_baseline_audit.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit source/governance outputs only**

Use the existing safe commit review workflow or explicit `git add --` for the new source/governance files. Do not commit `runs/`, local databases, or dashboard runtime report mutations.

## Self-Review

- Spec coverage: covers post-baseline observation evidence, report generation, runtime exclusion, and no strategy execution.
- Placeholder scan: no TBD or vague implementation commands remain.
- Type consistency: function names and output paths are consistent across tasks.
