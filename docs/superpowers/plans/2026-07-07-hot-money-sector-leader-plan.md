# Hot Money Sector Leader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Y3 research-only Sector Momentum and Leader Stock engines so the hot-money system can identify mainline sectors, unique leaders, secondary leaders, and filtered weak stocks.

**Architecture:** Keep this phase as a pure observation layer. `runtime/hot_money_sector.py` scores sectors from cached limit rows plus a caller-provided sector map. `runtime/hot_money_leader.py` consumes sector rankings and limit rows to classify leaders without touching strategy, execution, scheduler, or portfolio code.

**Tech Stack:** Python 3, pandas, pytest, existing DuckDB limit cache, existing Markdown report pattern.

## Global Constraints

- Do not modify M0 `ExecutionModel`.
- Do not modify Quality Alpha, mainline chain, factor, portfolio, scheduler, or order logic.
- Do not add machine learning.
- Do not add a new external data source.
- Do not rely on live Tushare calls in unit tests.
- Do not edit `data/tushare_concept_incremental.py` in this phase because it currently has unrelated local changes.
- All outputs are research/observation artifacts only and must not trigger orders.
- Keep every new/modified source file under 500 lines.

---

## File Structure

- Create `runtime/hot_money_sector.py`: sector scoring and 1-3 mainline selection.
- Create `runtime/hot_money_leader.py`: leader scoring, limit streak calculation, and role assignment.
- Create `scripts/run_hot_money_leaders.py`: CLI report generator from local cache and optional sector CSV.
- Create `tests/test_hot_money_sector.py`: sector ranking, top-three cap, and uniqueness tests.
- Create `tests/test_hot_money_leader.py`: unique leader, secondary leader, streak, and filtering tests.
- Create `tests/test_hot_money_leaders_cli.py`: report smoke test with local mock DuckDB.
- Modify `.planning/STATE.md` and `.planning/TASKS.md` after implementation.

---

### Task 1: Sector Momentum Engine

**Files:**
- Create: `runtime/hot_money_sector.py`
- Test: `tests/test_hot_money_sector.py`

**Interfaces:**
- `build_sector_momentum_daily(limit_rows: pd.DataFrame, sector_map: pd.DataFrame | None = None, max_mainlines: int = 3) -> pd.DataFrame`
- Output columns: `trade_date, sector_name, limit_up_count, limit_amount, leader_ts_code, leader_name, leader_score, consistency_score, uniqueness_score, sector_score, rank, is_mainline, reason`

- [ ] **Step 1: Write failing tests**

Create `tests/test_hot_money_sector.py` with:

```python
"""游资主线板块强度测试。"""

import pandas as pd

from runtime.hot_money_sector import build_sector_momentum_daily


def test_sector_momentum_selects_top_three_mainlines() -> None:
    """板块强度最多只应识别前三条主线。"""
    limit_rows = pd.DataFrame([
        {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 100.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 80.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000003.SZ", "name": "B1", "limit_type": "U", "amount": 70.0, "pct_chg": 10.0, "open_times": 1},
        {"trade_date": "20260706", "ts_code": "000004.SZ", "name": "C1", "limit_type": "U", "amount": 60.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000005.SZ", "name": "D1", "limit_type": "U", "amount": 50.0, "pct_chg": 10.0, "open_times": 0},
    ])
    sector_map = pd.DataFrame([
        {"ts_code": "000001.SZ", "sector_name": "算力"},
        {"ts_code": "000002.SZ", "sector_name": "算力"},
        {"ts_code": "000003.SZ", "sector_name": "机器人"},
        {"ts_code": "000004.SZ", "sector_name": "半导体"},
        {"ts_code": "000005.SZ", "sector_name": "低空经济"},
    ])

    result = build_sector_momentum_daily(limit_rows, sector_map, max_mainlines=3)

    assert result[result["is_mainline"]].sort_values("rank")["sector_name"].tolist() == ["算力", "机器人", "半导体"]
    assert result["sector_score"].between(0, 100).all()


def test_sector_momentum_keeps_unique_mainline_when_first_sector_dominates() -> None:
    """第一名显著领先时，应只保留唯一主线。"""
    limit_rows = pd.DataFrame([
        {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 300.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 260.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000003.SZ", "name": "A3", "limit_type": "U", "amount": 220.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000004.SZ", "name": "B1", "limit_type": "U", "amount": 20.0, "pct_chg": 10.0, "open_times": 2},
    ])
    sector_map = pd.DataFrame([
        {"ts_code": "000001.SZ", "sector_name": "算力"},
        {"ts_code": "000002.SZ", "sector_name": "算力"},
        {"ts_code": "000003.SZ", "sector_name": "算力"},
        {"ts_code": "000004.SZ", "sector_name": "机器人"},
    ])

    result = build_sector_momentum_daily(limit_rows, sector_map, max_mainlines=3)

    assert result[result["is_mainline"]]["sector_name"].tolist() == ["算力"]
```

- [ ] **Step 2: Confirm tests fail**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_sector.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement `runtime/hot_money_sector.py`**

Implementation rules:

- Filter to `limit_type == "U"` only.
- Left join `sector_map[ts_code, sector_name]`; missing sectors become `UNKNOWN`.
- Group by `trade_date, sector_name`.
- Score formula: `0.35 * limit_up_count_rank + 0.25 * limit_amount_rank + 0.25 * leader_score + 0.15 * consistency_score`.
- `leader_score`: amount percentile 60% + average涨幅 percentile 40%.
- `consistency_score`: penalize high `open_times`.
- Mainline count: if first-vs-second `sector_score` gap >= 25, keep 1; otherwise keep at most `max_mainlines`; require score >= 45 except the top sector.
- Return exactly the interface columns above.

- [ ] **Step 4: Run sector tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_sector.py -q
```

Expected: pass.

---

### Task 2: Leader Stock Engine

**Files:**
- Create: `runtime/hot_money_leader.py`
- Test: `tests/test_hot_money_leader.py`

**Interfaces:**
- `build_leader_stock_daily(limit_rows: pd.DataFrame, sector_momentum: pd.DataFrame, sector_map: pd.DataFrame | None = None) -> pd.DataFrame`
- Output columns: `trade_date, sector_name, ts_code, name, role, leader_score, limit_streak, amount_share, open_times, reason`
- Roles: `LEADER`, `SECONDARY_LEADER`, `FILTERED`

- [ ] **Step 1: Write failing tests**

Create `tests/test_hot_money_leader.py` with:

```python
"""游资龙头识别测试。"""

import pandas as pd

from runtime.hot_money_leader import build_leader_stock_daily


def test_leader_engine_selects_one_unique_leader_per_mainline() -> None:
    """每条主线只能有一个唯一龙头。"""
    limit_rows = pd.DataFrame([
        {"trade_date": "20260703", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 80.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 120.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 60.0, "pct_chg": 10.0, "open_times": 1},
    ])
    sector_map = pd.DataFrame([
        {"ts_code": "000001.SZ", "sector_name": "算力"},
        {"ts_code": "000002.SZ", "sector_name": "算力"},
    ])
    sector_momentum = pd.DataFrame([{"trade_date": "20260706", "sector_name": "算力", "is_mainline": True}])

    result = build_leader_stock_daily(limit_rows, sector_momentum, sector_map)
    daily = result[result["trade_date"] == "20260706"]

    assert daily[daily["role"] == "LEADER"]["ts_code"].tolist() == ["000001.SZ"]
    assert daily[daily["role"] == "SECONDARY_LEADER"]["ts_code"].tolist() == ["000002.SZ"]
    assert int(daily[daily["ts_code"] == "000001.SZ"]["limit_streak"].iloc[0]) == 2


def test_leader_engine_filters_non_mainline_stocks() -> None:
    """非主线涨停股只能被标记为过滤对象。"""
    limit_rows = pd.DataFrame([
        {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 100.0, "pct_chg": 10.0, "open_times": 0},
        {"trade_date": "20260706", "ts_code": "000009.SZ", "name": "Z1", "limit_type": "U", "amount": 90.0, "pct_chg": 10.0, "open_times": 0},
    ])
    sector_map = pd.DataFrame([
        {"ts_code": "000001.SZ", "sector_name": "算力"},
        {"ts_code": "000009.SZ", "sector_name": "其他"},
    ])
    sector_momentum = pd.DataFrame([{"trade_date": "20260706", "sector_name": "算力", "is_mainline": True}])

    result = build_leader_stock_daily(limit_rows, sector_momentum, sector_map)

    assert result[result["ts_code"] == "000009.SZ"]["role"].tolist() == ["FILTERED"]
```

- [ ] **Step 2: Confirm tests fail**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_leader.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement `runtime/hot_money_leader.py`**

Implementation rules:

- Left join sector map; missing sectors become `UNKNOWN`.
- Compute `limit_streak` by sorting `ts_code, trade_date` and counting consecutive `limit_type == "U"`.
- Keep daily rows where `limit_type == "U"`.
- Mainline key is `(trade_date, sector_name)` where `sector_momentum.is_mainline == True`.
- `amount_share = stock amount / sector amount`.
- `leader_score = 35% streak + 30% amount_share + 20% open_times health + 15% pct_chg`.
- For each mainline sector/day, top score is `LEADER`, next two with score >= 45 are `SECONDARY_LEADER`, others are `FILTERED`.
- For non-mainline sector/day, all rows are `FILTERED`.
- Return exactly the interface columns above.

- [ ] **Step 4: Run leader tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_leader.py -q
```

Expected: pass.

---

### Task 3: CLI Report

**Files:**
- Create: `scripts/run_hot_money_leaders.py`
- Test: `tests/test_hot_money_leaders_cli.py`

**Interfaces:**
- CLI arguments: `--db-path`, optional `--sector-map-csv`, `--output`
- Consumes local DuckDB table `limit_list_daily`.
- Produces Markdown report.

- [ ] **Step 1: Write CLI smoke test**

Create `tests/test_hot_money_leaders_cli.py` with:

```python
"""游资主线龙头报告 CLI 测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from scripts.run_hot_money_leaders import main


def test_run_hot_money_leaders_writes_report(tmp_path: Path) -> None:
    """CLI 应读取本地缓存并输出主线龙头报告。"""
    db_path = tmp_path / "limit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE limit_list_daily AS
            SELECT * FROM (
                VALUES
                ('20260706','000001.SZ','A1',10.0,10.0,'U',100.0,0.0,'09:30','09:30',0),
                ('20260706','000002.SZ','A2',10.0,10.0,'U',80.0,0.0,'09:31','09:31',1)
            ) AS t(trade_date, ts_code, name, close, pct_chg, limit_type, amount, fd_amount, first_time, last_time, open_times)
            """
        )
    sector_csv = tmp_path / "sector.csv"
    pd.DataFrame([
        {"ts_code": "000001.SZ", "sector_name": "算力"},
        {"ts_code": "000002.SZ", "sector_name": "算力"},
    ]).to_csv(sector_csv, index=False)
    output = tmp_path / "report.md"

    code = main(["--db-path", str(db_path), "--sector-map-csv", str(sector_csv), "--output", str(output)])

    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "游资主线与龙头识别报告" in text
    assert "算力" in text
    assert "A1" in text
```

- [ ] **Step 2: Confirm test fails**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_leaders_cli.py -q
```

Expected: import failure because the script does not exist.

- [ ] **Step 3: Implement CLI**

Implementation rules:

- Read `limit_list_daily` from `--db-path` with DuckDB.
- Read sector map CSV when provided; it must contain `ts_code,sector_name`.
- Call `build_sector_momentum_daily`, then `build_leader_stock_daily`.
- Write a Markdown report with latest trade date, mainline sector table, and leader candidate table.
- Return process code `0` on success.

- [ ] **Step 4: Run CLI test**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_leaders_cli.py -q
```

Expected: pass.

---

### Task 4: Planning State, Verification, and Commit

**Files:**
- Modify: `.planning/STATE.md`
- Modify: `.planning/TASKS.md`

**Interfaces:**
- Consumes completed Y3.1 tests and implementation.
- Produces updated project state and one focused Git commit.

- [ ] **Step 1: Update `.planning/STATE.md`**

Set current status to `completed`. Append a Y3.1 completion summary under `Last Completed`. Set next action to `Phase Y4.1：Strategy Router and Risk-Aware Hot Money Research Backtest`.

- [ ] **Step 2: Update `.planning/TASKS.md`**

Mark `Y3-001` as completed with summary: `生成 sector momentum、leader stock 和报告 CLI`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_sector.py tests/test_hot_money_leader.py tests/test_hot_money_leaders_cli.py -q
```

Expected: all pass.

- [ ] **Step 4: Run existing hot-money tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_limit_incremental.py tests/test_hot_money_emotion.py tests/test_hot_money_state.py tests/test_hot_money_state_cli.py tests/test_hot_money_sector.py tests/test_hot_money_leader.py tests/test_hot_money_leaders_cli.py -q
```

Expected: all pass.

- [ ] **Step 5: Run full backend tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit only Y3.1 files**

Run:

```bash
git add runtime/hot_money_sector.py runtime/hot_money_leader.py scripts/run_hot_money_leaders.py tests/test_hot_money_sector.py tests/test_hot_money_leader.py tests/test_hot_money_leaders_cli.py .planning/STATE.md .planning/TASKS.md
git commit -m "feat: add hot money sector leader engine"
```

Do not stage `reports/`, `runs/`, DuckDB files, `.env.properties`, or unrelated dirty files.

---

## Self-Review

- Spec coverage: Covers sector momentum ranking, 1-3 mainlines, unique leader, secondary leader, weak-stock filtering, and research report output.
- Scope control: No strategy router, execution, scheduler, frontend page, or new data source.
- Type consistency: Both engines accept pandas `DataFrame` inputs and return pandas `DataFrame` outputs with fixed columns.
- Testability: All tests use mock data and avoid live Tushare calls.
