# Hot Money Emotion State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase Y1/Y2 of the hot-money behavior engine: Tushare 涨跌停情绪数据层 and a smoothed A 股市场情绪状态机.

**Architecture:** Add a standalone Tushare `limit_list_d` cache, derive daily emotion metrics, then classify smoothed market states. This phase is research-only and must not generate orders, mutate current strategies, or enter the production portfolio.

**Tech Stack:** Python 3, Tushare Pro API, DuckDB, Pandas, pytest, existing `.env.properties` runtime config.

## Global Constraints

- 不自动下单。
- 不绕过现有 M0 ExecutionModel。
- 不新增机器学习模型。
- 不把龙虎榜作为第一版必需数据。
- 不直接把游资策略加入真实组合。
- 不替代 Quality Alpha V1 和现有主线链动策略。
- 本轮只做 Phase Y1/Y2：情绪数据层和市场状态机。
- `TUSHARE_TOKEN` 只能通过 `runtime.config.get_config_value` 读取。
- 不提交 `runs/`、`reports/`、DuckDB、SQLite、日志或本地私密配置。

---

## File Structure

- `data/tushare_limit_incremental.py`：Tushare `limit_list_d` 客户端、本地 DuckDB 存储、增量更新入口。
- `runtime/hot_money_emotion.py`：从涨跌停缓存聚合每日市场情绪指标。
- `runtime/hot_money_state.py`：状态枚举、单日状态初判、时间序列平滑和状态转移原因。
- `scripts/run_hot_money_state.py`：生成区间市场状态报告，不接入生产调度。
- `tests/test_tushare_limit_incremental.py`：涨跌停缓存和字段标准化测试。
- `tests/test_hot_money_emotion.py`：情绪指标聚合测试。
- `tests/test_hot_money_state.py`：状态机和平滑规则测试。
- `tests/test_hot_money_state_cli.py`：CLI 报告 smoke 测试。

### Task 1: Tushare Limit Data Cache

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/data/tushare_limit_incremental.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_tushare_limit_incremental.py`

**Interfaces:**
- Produces: `LIMIT_LIST_COLUMNS: list[str]`
- Produces: `class TushareLimitClient`
- Produces: `class LimitListDuckDBStore`
- Produces: `update_limit_list_range(store, client, trade_dates) -> dict[str, object]`

- [x] **Step 1: Write failing tests**

Create tests that:
- use a fake client returning one涨停 and one跌停 row;
- verify `update_limit_list_range` writes standardized columns;
- verify a repeated update for the same date stays idempotent.

Required assertions:

```python
assert result["rows_written"] == 2
assert rows["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
assert rows["limit_type"].tolist() == ["U", "D"]
assert len(rows_after_second_update) == 2
```

- [x] **Step 2: Run red test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_limit_incremental.py -q
```

Expected: import failure because `data.tushare_limit_incremental` does not exist.

- [x] **Step 3: Implement cache module**

Implementation requirements:
- `TushareLimitClient` reads token with `get_config_value("TUSHARE_TOKEN")`;
- fetches `limit_list_d(trade_date=..., fields="trade_date,ts_code,name,close,pct_chg,limit,amount,fd_amount,first_time,last_time,open_times")`;
- `LimitListDuckDBStore.ensure_schema()` creates `limit_list_daily`;
- normalized storage renames Tushare `limit` to `limit_type`;
- `PRIMARY KEY (trade_date, ts_code)` supports idempotent `INSERT OR REPLACE`;
- `load(start_date, end_date)` returns rows ordered by `trade_date, ts_code`.

- [x] **Step 4: Run green test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_limit_incremental.py -q
```

Expected: `2 passed`.

### Task 2: Market Emotion Aggregation

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/hot_money_emotion.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_hot_money_emotion.py`

**Interfaces:**
- Consumes standardized limit rows with `trade_date`, `ts_code`, `limit_type`, `open_times`, `amount`.
- Produces: `build_market_emotion_daily(limit_rows: pd.DataFrame, market_amount: pd.DataFrame | None = None) -> pd.DataFrame`

- [x] **Step 1: Write failing tests**

Create tests that verify:
- `U` rows count as `limit_up_count`;
- `D` rows count as `limit_down_count`;
- `Z` rows count as `zha_ban_count`;
- open-board rate equals opened涨停 rows divided by涨停 rows;
- optional market amount produces `market_amount_chg`.

Required assertions:

```python
assert row["limit_up_count"] == 2
assert row["limit_down_count"] == 1
assert row["zha_ban_count"] == 1
assert row["open_board_rate"] == 0.5
assert round(float(second_day["market_amount_chg"]), 4) == 0.2
```

- [x] **Step 2: Run red test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_emotion.py -q
```

Expected: import failure because `runtime.hot_money_emotion` does not exist.

- [x] **Step 3: Implement emotion aggregation**

Implementation requirements:
- returns columns `trade_date`, `limit_up_count`, `limit_down_count`, `zha_ban_count`, `open_board_rate`, `limit_amount`, `market_amount`, `market_amount_chg`;
- empty input returns an empty DataFrame with the same columns;
- all numeric fields are coerced safely;
- result is sorted by `trade_date`.

- [x] **Step 4: Run green test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_emotion.py -q
```

Expected: `2 passed`.

### Task 3: Market State Engine

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/hot_money_state.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_hot_money_state.py`

**Interfaces:**
- Consumes emotion rows from Task 2.
- Produces: `MarketState` enum.
- Produces: `MarketStateEngine.classify_series(emotion: pd.DataFrame) -> pd.DataFrame`

- [x] **Step 1: Write failing tests**

Create tests that verify:
- extreme跌停/炸板 risk directly enters `DISTRIBUTION`;
- a single day cannot jump from `ICE_COLD` straight to `BUBBLE`;
- output includes `raw_state`, `smoothed_state`, `emotion_score`, `risk_score`, `transition_reason`.

Required assertions:

```python
assert result.iloc[-1]["raw_state"] == MarketState.DISTRIBUTION.value
assert result.iloc[-1]["smoothed_state"] == MarketState.DISTRIBUTION.value
assert "极端风险" in result.iloc[-1]["transition_reason"]
assert result.iloc[1]["raw_state"] == MarketState.BUBBLE.value
assert result.iloc[1]["smoothed_state"] in {MarketState.REBOUND.value, MarketState.EXPANSION.value}
```

- [x] **Step 2: Run red test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_state.py -q
```

Expected: import failure because `runtime.hot_money_state` does not exist.

- [x] **Step 3: Implement state engine**

Implementation requirements:
- define states `ICE_COLD`, `REBOUND`, `EXPANSION`, `BUBBLE`, `DISTRIBUTION`;
- compute an `emotion_score` from涨停数量、跌停惩罚、炸板惩罚、成交额变化;
- compute a `risk_score` from跌停数量、炸板率、炸板数量;
- raw state thresholds are deterministic and documented in code comments;
- normal transitions move at most one state step per day;
- extreme risk can immediately force `DISTRIBUTION`.

- [x] **Step 4: Run green test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_state.py -q
```

Expected: `2 passed`.

### Task 4: CLI Report Runner

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/scripts/run_hot_money_state.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_hot_money_state_cli.py`

**Interfaces:**
- Consumes: `LimitListDuckDBStore.load`, `build_market_emotion_daily`, `MarketStateEngine.classify_series`.
- Produces: `market_state_report.md`.

- [x] **Step 1: Write failing CLI test**

Create a test that:
- seeds a temporary `LimitListDuckDBStore`;
- runs `scripts/run_hot_money_state.py --cache-path ... --start-date ... --end-date ... --output-dir ...`;
- asserts `market_state_report.md` exists and contains `市场状态`.

- [x] **Step 2: Run red test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_state_cli.py -q
```

Expected: script missing failure.

- [x] **Step 3: Implement CLI**

Implementation requirements:
- arguments: `--cache-path`, `--start-date`, `--end-date`, `--output-dir`;
- reads cached limit rows only;
- writes markdown report with latest date, latest state, emotion score, risk score, and daily table;
- prints report path to stdout;
- does not call Tushare and does not write trading artifacts.

- [x] **Step 4: Run green test**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_hot_money_state_cli.py -q
```

Expected: `1 passed`.

### Task 5: Verification and Commit

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`

- [x] **Step 1: Run focused verification**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_limit_incremental.py tests/test_hot_money_emotion.py tests/test_hot_money_state.py tests/test_hot_money_state_cli.py -q
```

- [x] **Step 2: Run full backend verification**

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

- [x] **Step 3: Optional smoke report**

Only if `data/limit_list_increment.duckdb` exists locally, run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_hot_money_state.py \
  --cache-path data/limit_list_increment.duckdb \
  --start-date 20260701 \
  --end-date 20260707 \
  --output-dir runs/experiments/hot_money_state_smoke
```

Do not commit the generated `runs/` output.

- [x] **Step 4: Update planning state**

Update `.planning/ROADMAP.md`, `.planning/STATE.md`, and `.planning/TASKS.md` with:

```text
Milestone Y1/Y2：游资情绪数据层与市场状态机
Status：done after verification
Next Action：Phase Y3 主线板块与龙头识别
```

- [x] **Step 5: Stage safely**

```bash
git add data/tushare_limit_incremental.py runtime/hot_money_emotion.py runtime/hot_money_state.py scripts/run_hot_money_state.py tests/test_tushare_limit_incremental.py tests/test_hot_money_emotion.py tests/test_hot_money_state.py tests/test_hot_money_state_cli.py .planning/ROADMAP.md .planning/STATE.md .planning/TASKS.md docs/superpowers/plans/2026-07-07-hot-money-emotion-state-plan.md
bad=$(git diff --cached --name-only | grep -E '^(runs/|runtime_backups/|reports/|.*\.env\.properties$|.*\.duckdb$|.*\.sqlite3$|logs/|state/)' || true)
if [ -n "$bad" ]; then echo "$bad"; exit 1; fi
git diff --cached --check
```

- [x] **Step 6: Commit**

```bash
git commit -m "feat: add hot money emotion state engine"
```

## Self-Review

- Spec coverage: covers Y1 Tushare limit cache and Y2 market state engine only; Y3-Y6 remain explicitly out of scope.
- Placeholder scan: no unresolved markers or incomplete sections.
- Type consistency: `limit_type`, `build_market_emotion_daily`, and `MarketStateEngine.classify_series` are used consistently across tasks.
