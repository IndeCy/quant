# Quality Overlay Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Quality Alpha 与风险层定义的前提下，验证参数平台、样本外表现、年度稳定性和风险层贡献。

**Architecture:** 复用现有 Quality Cleanup 目标持仓与 `run_risk_layer_backtest`，新增纯分析函数处理参数排序、区间指标、事件合并与损失规避估算。研究入口只负责加载现有 DuckDB 数据、执行固定参数网格并输出 Markdown、CSV 和 PNG 热力图。

**Tech Stack:** Python、Pandas、Matplotlib、DuckDB、pytest。

## Global Constraints

- 不新增或修改 Alpha 因子、股票池、月频调仓和 Top20 等权逻辑。
- 风险层固定为历史组合波动率阈值控制，信号收盘生成并在下一交易日执行。
- Walk Forward 排序固定为 Sharpe 降序、Calmar 降序、最大回撤绝对值升序、平均仓位降序。
- 验证集不参与参数选择，也不允许根据验证结果反向调整参数。
- 全参数网格为 6 个窗口、5 个阈值、4 个降仓比例，共 120 组。

---

### Task 1: 纯分析函数

**Files:**
- Create: `backtest/quality_robustness.py`
- Test: `tests/test_quality_robustness.py`

**Interfaces:**
- Consumes: `pd.Series` 净值、基准净值、风险仓位和风险状态事件。
- Produces: `rank_parameters`、`slice_performance`、`build_trigger_episodes`、`calculate_avoided_loss`。

- [ ] 先编写参数排序、区间指标、连续触发合并和规避损失测试。
- [ ] 运行测试并确认因接口缺失而失败。
- [ ] 实现最小纯函数，所有区间指标从区间首个净值重新归一化。
- [ ] 运行单测并确认通过。

### Task 2: 稳健性研究入口与热力图

**Files:**
- Create: `examples/quality_overlay_robustness_study.py`
- Test: `tests/test_quality_overlay_robustness_study.py`

**Interfaces:**
- Consumes: 现有 Quality Cleanup 目标持仓、行情、510300 基准和 `run_risk_layer_backtest`。
- Produces: 120 组结果、Sharpe/Calmar 热力图、两阶段 Walk Forward、年度表、触发明细和贡献结论。

- [ ] 先编写网格规模、固定排序规则和热力图矩阵测试。
- [ ] 运行测试并确认失败。
- [ ] 实现研究入口，热力图按降仓比例分别绘制，避免把第三维错误压平。
- [ ] 输出 `reports/quality_overlay_robustness_study.md`、明细 CSV 和 PNG。
- [ ] 运行定向测试并确认通过。

### Task 3: 实际研究与验收

**Files:**
- Verify: `reports/quality_overlay_robustness_study.md`
- Verify: `reports/quality_overlay_robustness_grid.csv`

- [ ] 执行 120 组全样本研究和两个 Walk Forward 阶段。
- [ ] 检查训练胜出参数与验证参数完全一致。
- [ ] 检查年度收益、回撤、超额收益覆盖 2015 至 2026。
- [ ] 检查每次触发日期、原因、持续天数和规避损失。
- [ ] 运行全量 `pytest`，再根据实证结果回答四个最终问题。
