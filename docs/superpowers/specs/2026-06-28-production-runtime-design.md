# Production Runtime Design

## 背景

当前系统已经能够由脚本生成每日 Quality Alpha V1 观测结果，但运行方式仍然偏 agent 驱动，产物分散在项目目录下的 `data/`、`runs/`、`reports/`。第一阶段目标是把它升级为本地单机运行系统，后续迁移到常驻 Mac mini 时尽量只拷贝一个运行目录。

## 目标

- 引入统一运行目录 `QUANT_HOME`，集中保存可变数据和运行产物。
- 未设置 `QUANT_HOME` 时保持现有项目目录行为，避免破坏当前脚本。
- 策略运行不依赖 agent，agent 仅保留为研究分析入口。
- 前端、调度器、报告中心后续都读取统一运行目录与系统状态库。

## 运行目录约定

```text
$QUANT_HOME/
  data/
    live_market_increment.duckdb
    benchmark_increment.duckdb
    quality_overlay_paper.sqlite3
    monitoring.sqlite3
  state/
    quant_system.sqlite
    scheduler.sqlite
  runs/
    YYYYMMDD/
  reports/
    quality_overlay_paper_latest.md
    dashboard_data.json
    dashboard.html
  logs/
  config/
```

## 持久化分工

- DuckDB：保存行情、复权因子、基准等分析型数据。
- SQLite：保存系统状态、监控指标、paper 账户、调度任务状态。
- 文件系统：保存日报、月报、CSV、JSON 和研究 Markdown。
- SQLite 索引：后续前端不直接扫描目录，而是查询报告索引表。

## 第一阶段范围

- 新增 runtime 路径模块。
- 每日 Quality Paper 流水线改为通过 runtime 路径取增量库和产物目录。
- 保留旧默认路径，保证现有命令继续可运行。
- 不新增前端、不新增调度器、不修改策略逻辑。

## 后续方向

- FastAPI 提供策略、运行记录、报告索引、指标曲线 API。
- React/Vite + ECharts 构建本地前端。
- APScheduler 使用 SQLite job store 保存定时任务。
- Mac mini 迁移时只需要拉代码、拷贝 `QUANT_HOME`、设置环境变量并启动服务。

## 因子与策略模块化方向

系统后续需要把“因子”“策略”“组合构建”“风险层”拆开：

- 因子模块：只负责按 as-of 口径计算横截面因子值，例如 ROE、ROA、OCF_TO_OR。
- 策略模块：只负责声明使用哪些因子、过滤规则、打分方式、选股数量和调仓频率。
- 组合构建模块：把策略输出的候选池或 score 转成目标权重。
- 风险层模块：在目标权重外层调整总仓位，不修改 Alpha 因子。

第一阶段先在系统状态库登记因子和策略元数据，让前端可以维护组合关系；后续再把研究脚本里的因子计算沉淀成正式 `factors/` 与 `strategies/` 模块。
