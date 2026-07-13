# Market Beta Observatory V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一大盘 beta 观测模块，输出可解释的 `BETA_ON / NEUTRAL / BETA_OFF / CRASH_RISK` 状态，先服务策略风控判断与前端观察。

**Architecture:** V1 采用 provider + metrics + scoring + repository + API + frontend 的轻量结构。先使用当前可稳定获取和可推导的数据，新增 Tushare P0 beta 数据缓存，但不改变任何策略逻辑和下单逻辑。

**Tech Stack:** Python, DuckDB, SQLite, Pandas, FastAPI, React/Vite, ECharts, pytest.

## Global Constraints

- 不修改 M0 ExecutionModel。
- 不修改现有策略 alpha 因子和参数。
- 不做自动调仓，只输出 beta 状态与解释。
- 所有外部数据必须先落本地 DuckDB，再进入观测计算。
- Tushare token 从 `.env.properties` 读取，不提交该文件。
- 新增 Python 核心逻辑必须有单测。

---

## Files

- Create: `data/tushare_beta_incremental.py`，P0 beta 数据增量缓存。
- Create: `runtime/market_beta_observer.py`，统一 beta 指标计算与状态评分。
- Create: `tests/test_tushare_beta_incremental.py`。
- Create: `tests/test_market_beta_observer.py`。
- Modify: `scripts/run_daily_data_update.py`，接入 beta P0 数据更新。
- Modify: `monitoring/repository.py`，新增 beta 观测表。
- Modify: `api/service.py` and `api/local_server.py`，新增 beta API。
- Modify: `frontend/src/entities/market/model.ts` and `frontend/src/entities/market/api.ts`。
- Modify: `frontend/src/pages/dashboard/DashboardPage.tsx`，大盘模块展示 beta 状态。

## Task 1: P0 Beta 数据缓存

**Deliverable:** `data/beta_increment.duckdb` 可缓存估值、资金、杠杆、ETF份额。

- [ ] 写 `tests/test_tushare_beta_incremental.py`，用 fake client 覆盖 `daily_basic`、`index_dailybasic`、`fund_share`、`moneyflow_hsgt`、`margin`、`margin_detail` 幂等写入。
- [ ] 新增 `data/tushare_beta_incremental.py`：
  - `TushareBetaClient` 协议。
  - `TushareBetaProClient` 真实实现。
  - `BetaIncrementalStore` 管理 DuckDB 表。
  - `TushareBetaUpdater.update(trade_date)`。
- [ ] 表设计：
  - `daily_basic(trade_date, ts_code, pe_ttm, pb, dv_ttm, total_mv, circ_mv, turnover_rate)`
  - `index_dailybasic(trade_date, ts_code, pe_ttm, pb, turnover_rate, total_mv)`
  - `fund_share(trade_date, ts_code, fd_share)`
  - `moneyflow_hsgt(trade_date, north_money, south_money, hgt, sgt)`
  - `margin(trade_date, exchange_id, rzye, rzmre, rqye, rzrqye)`
  - `margin_detail(trade_date, ts_code, rzye, rqye, rzmre, rqmcl, rzrqye)`
- [ ] 运行：`/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_beta_incremental.py -q`。

## Task 2: Beta 指标计算

**Deliverable:** 给定行情、涨跌停、行业和 P0 beta 数据，输出单日 `MarketBetaSnapshot`。

- [ ] 写 `tests/test_market_beta_observer.py`，覆盖：
  - 趋势向上且宽度扩散时输出 `BETA_ON`。
  - 指数跌破均线、宽度差、跌停增加时输出 `BETA_OFF`。
  - 20日跌幅极端且跌停/宽度恶化时输出 `CRASH_RISK`。
  - 缺少 P0 扩展数据时仍可用价格和宽度降级计算。
- [ ] 新增 `runtime/market_beta_observer.py`：
  - `MarketBetaSnapshot` dataclass。
  - `compute_trend_metrics()`。
  - `compute_breadth_metrics()`。
  - `compute_sentiment_metrics()`。
  - `compute_liquidity_metrics()`。
  - `compute_funding_metrics()`。
  - `classify_beta_state()`。
- [ ] V1 分数结构：
  - Trend 30 分。
  - Breadth 25 分。
  - Sentiment 20 分。
  - Liquidity 15 分。
  - Funding/Valuation 10 分。
- [ ] 状态阈值：
  - `score >= 70`: `BETA_ON`
  - `45 <= score < 70`: `NEUTRAL`
  - `25 <= score < 45`: `BETA_OFF`
  - `score < 25` 或 crash trigger: `CRASH_RISK`
- [ ] 运行：`/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_market_beta_observer.py -q`。

## Task 3: 监控持久化与每日流水线

**Deliverable:** 每个交易日生成并保存 beta 快照。

- [ ] 扩展 `monitoring/repository.py`，新增表 `market_beta_daily`。
- [ ] 字段包含：`trade_date, beta_state, beta_score, trend_score, breadth_score, sentiment_score, liquidity_score, funding_score, valuation_score, risk_level, reasons_json`。
- [ ] 修改 `scripts/run_daily_data_update.py`，数据更新后调用 `TushareBetaUpdater`。
- [ ] 在策略批处理前或后调用 beta observer，写入 `market_beta_daily`。
- [ ] 测试：新增或扩展 `tests/test_monitoring_repository.py`，验证 upsert/load beta 快照。

## Task 4: API 与前端展示

**Deliverable:** 前端大盘模块能看到当前 beta 状态、分数、拆解和原因。

- [ ] API：
  - `GET /api/market/beta/latest`
  - `GET /api/market/beta/series?limit=120`
- [ ] 前端：
  - 新增 `MarketBetaPanel`。
  - 在 Dashboard 大盘模块展示状态灯、总分、五个维度分数、原因列表。
  - 保留原 `510300 / MA60 / MA120` 曲线。
- [ ] 测试：
  - `tests/test_local_api_service.py` 覆盖 beta API。
  - `npm run build:pre` 必须通过。

## Task 5: 验收

**Deliverable:** V1 能解释当前市场 beta，不影响策略运行。

- [ ] 跑后端测试：`/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_tushare_beta_incremental.py tests/test_market_beta_observer.py tests/test_monitoring_repository.py tests/test_local_api_service.py -q`。
- [ ] 跑前端构建：`cd frontend && npm run build:pre`。
- [ ] 手动跑一次每日流水线：`/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_daily_pipeline.py --trade-date 20260710`。
- [ ] 验证 API：`curl http://127.0.0.1:8765/api/market/beta/latest`。
- [ ] 验证前端：打开 `http://127.0.0.1:5173/`，大盘模块展示 beta 状态。

## Out of Scope

- 不接券商。
- 不把 beta 状态自动转成真实交易。
- 不引入机器学习。
- 不做 P1/P2 宏观全量接入。
- 不重构现有策略系统。
