# Selective Commit and Release Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit the enterprise quant platform source/governance baseline without committing runtime data, local databases, backups, or generated observation reports.

**Architecture:** Use `docs/release/safe_commit_review.json` as the machine-readable staging source. Regenerate the Git baseline and safe commit review immediately before staging, run verification gates, then stage only `stage_candidates` and confirm excluded runtime paths remain unstaged.

**Tech Stack:** Git CLI, Python standard library, pytest, npm/Vitest, Vite build.

## Global Constraints

- 不使用 `git add -A`。
- 不提交 `runs/`、DuckDB、SQLite、日志、runtime backup。
- 不自动回滚用户或运行产物变更。
- `reports/` 下已跟踪运行产物保持 hold，不进入本次提交。
- 前端变更必须执行 `npm test` 和 `npm run build:pre`。
- `build:pre` 后必须重启本地服务。

---

### Task 1: Refresh Commit Review Inputs

**Files:**
- Modify: `docs/release/git_baseline_report.md`
- Modify: `docs/release/git_baseline_report.json`
- Modify: `docs/release/safe_commit_review.md`
- Modify: `docs/release/safe_commit_review.json`

**Interfaces:**
- Consumes: `scripts/generate_git_baseline_report.py`
- Consumes: `scripts/generate_safe_commit_review.py`
- Produces: refreshed safe commit command in `docs/release/safe_commit_review.md`

- [ ] **Step 1: Regenerate reports**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_git_baseline_report.py --output-dir docs/release
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/generate_safe_commit_review.py --output-dir docs/release
```

Expected: `Ready: True`.

- [ ] **Step 2: Confirm runtime exclusions**

Run a Python check that asserts the safe git add command does not contain `reports/`, `runs/`, `runtime_backups/`, or `.duckdb`.

Expected: all checks are false.

### Task 2: Verification Gates

**Files:**
- No code changes expected.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_safe_commit_review.py tests/test_git_baseline.py tests/test_release_baseline.py -q
```

Expected: PASS.

- [ ] **Step 2: Run backend full suite**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
```

Expected: PASS.

### Task 3: Selective Stage and Commit

**Files:**
- Stage only paths listed in `stage_candidates`.
- Hold: `reports/dashboard.html`, `reports/dashboard_data.json`, `reports/quality_overlay_paper_latest.md`.
- Exclude: `runs/`, `runtime_backups/`, local databases, logs, caches.

- [ ] **Step 1: Stage from safe review JSON**

Run a Python helper that reads `stage_candidates` from `docs/release/safe_commit_review.json` and executes `git add -- <paths>`.

Expected: staged files include source/governance changes only.

- [ ] **Step 2: Verify staged boundary**

Run:

```bash
git diff --cached --name-only
git diff --cached --name-only | grep -E '^(runs/|runtime_backups/|reports/|.*\\.duckdb$)' && exit 1 || true
```

Expected: no runtime paths are staged.

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "chore: establish enterprise quant platform baseline"
```

Expected: commit succeeds and working tree still keeps runtime/report artifacts unstaged.

### Task 4: Post-Commit Service Recovery

**Files:**
- No code changes expected.

- [ ] **Step 1: Restart services after frontend build**

Run:

```bash
./scripts/restart_services.sh
```

Expected: local API and frontend are available.

- [ ] **Step 2: Record status**

Confirm current branch, latest commit, and remaining unstaged runtime/report files.

## Self-Review

- Spec coverage: covers selective staging, runtime exclusion, verification gates, and service restart after frontend build.
- Placeholder scan: no TBD or vague commands remain.
- Type consistency: this phase only consumes previously implemented review outputs.
