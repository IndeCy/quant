# Multi Strategy Workbench Design

## 背景

当前前端已经有策略、因子、运行、报告、设置等模块，但全局数据入口仍以 `quality_overlay`
作为固定中心。结果是 Quality Alpha V1 可以完整展示，主线链动策略虽然已经登记到策略目录、
监控指标和调度任务中，却不能在首页获得同等级总览。

本设计目标是把前端从“单策略日报看板”升级为“多策略观测工作台”。第一阶段只服务本地
Shadow Live / Paper 观察，不做自动下单，不做收益优化，不重构后端大目录。

## 目标

1. 支持多个生产观察策略在同一前端中切换和对比。
2. Dashboard 不再硬编码 Quality Alpha V1。
3. 主线链动策略进入首页总览、净值曲线、风险指标、运行记录。
4. Quality Alpha V1 与主线链动策略可以共享页面结构，但保留各自业务语义。
5. 数据更新、策略运行、报告与监控指标在页面上可追踪。
6. 后续可扩展到更多策略、策略组合、账户视角和 Agent 研究入口。

## 非目标

1. 不修改策略逻辑。
2. 不新增因子。
3. 不修改 M0 ExecutionModel。
4. 不做自动下单。
5. 不引入复杂前端框架或远程服务。
6. 不把运行产物强行提交到 Git。

## 信息架构

### 顶层导航

保留现有侧边栏：

- Dashboard
- Strategies
- Factors
- Runs
- Reports
- Risk
- Data
- Research
- Logs
- Settings

新增全局策略上下文：

- `ALL`：全部策略总览
- `quality_overlay`：Quality Alpha V1
- `mainline_chain_b`：主线链动策略

策略选择器建议放在顶部状态栏，作为全局控制项。页面本身也可以在局部提供筛选，但全局选择器是主入口。

## 页面设计

### Dashboard

Dashboard 支持两种模式。

#### 全部策略模式

用于开机后第一眼巡检。

模块：

- 策略总览卡片：每个策略一张卡，展示最新日期、累计收益、当日收益、当前回撤、20日波动率、仓位、最近运行状态。
- 多策略净值对比：Quality 与主线链动在同一折线图中展示 `nav`。
- 多策略风险对比：展示 `drawdown`、`volatility_20`、`exposure`。
- 今日运行状态：展示数据更新任务和各策略任务最近一次运行结果。
- 操作关注区：展示调仓信号、失败订单数、风险层状态或主线链动信号。

#### 单策略模式

用于深入查看某个策略。

模块：

- 当前策略指标卡。
- 策略收益与基准折线。
- 风险状态折线。
- 策略定义。
- 因子组合或信号组件。
- 最近运行记录。
- 最近报告。

Quality Alpha V1 展示为“因子组合”；主线链动展示为“信号组件”。两者使用同一组件模型，不在页面硬编码业务文案。

### Strategies

策略页定位为策略管理与详情页。

模块：

- 策略列表：展示所有策略的最新指标，不再只给选中策略显示指标。
- 策略详情：展示配置、因子或信号组件、最新运行、最新指标。
- 策略历史曲线：选中策略后加载对应 `strategySeries`。
- 策略草案：第一阶段保留现有能力，只对因子类策略开放编辑提示，不把主线链动误导成可随意编辑因子权重。

### Runs

运行页需要支持：

- 默认展示所有任务。
- 按策略筛选。
- `system_data_update` 单独作为系统任务展示。
- 策略任务包括 `quality_overlay` 和 `mainline_chain_b`。

### Reports

报告页需要支持：

- 默认展示所有报告。
- 按策略筛选。
- Quality 日报继续展示。
- 主线链动第一阶段先展示运行记录和监控指标；后续再补独立观察报告。

### Risk

第一阶段不新增复杂风险模型，只让 Risk 页面支持当前全局策略上下文：

- 全部策略模式：展示各策略当前回撤、20日波动率、仓位。
- 单策略模式：沿用该策略历史风险曲线。

## 前端数据模型

新增或调整本地前端状态：

```ts
type SelectedStrategyId = "ALL" | string;

interface StrategyWorkspaceState {
  selectedStrategyId: SelectedStrategyId;
  strategyDetails: Record<string, StrategyDefinition>;
  strategySeriesMap: Record<string, StrategyMetric[]>;
}
```

`DashboardData` 不再只包含单个 `strategy` 与 `strategySeries`。第一阶段可保留旧字段兼容，但新增 map：

```ts
interface DashboardData {
  strategies: StrategyDefinition[];
  strategy: StrategyDefinition;
  strategySeries: StrategyMetric[];
  strategyDetails: Record<string, StrategyDefinition>;
  strategySeriesMap: Record<string, StrategyMetric[]>;
}
```

## 数据流

第一阶段不新增后端聚合接口，前端并发调用已有接口：

1. `GET /api/strategies`
2. 对每个策略调用 `GET /api/strategies/{strategy_id}`
3. 对每个策略调用 `GET /api/series/strategy/{strategy_id}`
4. 根据当前选中策略调用 `GET /api/runs?strategy_id=...`
5. 根据当前选中策略调用 `GET /api/reports?strategy_id=...`

后续策略数量超过 5 个时，再新增后端聚合接口：

- `GET /api/strategies/overview`
- `GET /api/series/strategies?ids=...`

## 阶段计划

### Phase 1：多策略数据上下文

目标：去掉前端对 `quality_overlay` 的硬编码中心。

改动：

- `frontend/src/app/loadDashboardData.ts`
- `frontend/src/app/types.ts`
- `frontend/src/app/state.ts`
- `frontend/src/entities/strategy/api.ts`

结果：

- 前端启动时加载所有策略详情和历史曲线。
- Quality 仍可作为默认单策略视角。
- 主线链动数据进入前端上下文。

验证：

- `npm test`
- `npm run build:pre`

### Phase 2：全局策略切换器

目标：顶部状态栏支持 `全部策略 / 单策略` 切换。

改动：

- `frontend/src/app/layout/TopStatusBar.tsx`
- `frontend/src/app/state.ts`
- `frontend/src/app/navigation.ts`

结果：

- 用户可以切换当前观察策略。
- Dashboard、Runs、Reports 读取同一全局策略上下文。

### Phase 3：Dashboard 多策略总览

目标：首页能同时看到 Quality 和主线链动。

改动：

- `frontend/src/pages/dashboard/DashboardPage.tsx`
- 新增 `frontend/src/pages/dashboard/components/StrategyOverviewGrid.tsx`
- 新增 `frontend/src/pages/dashboard/components/MultiStrategyChart.tsx`

结果：

- `ALL` 模式下展示多策略卡片和净值对比。
- 单策略模式下展示当前策略详情。

### Phase 4：Strategies 页补齐历史资产

目标：策略页成为单策略深挖入口。

改动：

- `frontend/src/pages/strategies/StrategiesPage.tsx`
- `frontend/src/entities/strategy/display.ts`

结果：

- 策略列表每行都有真实最新指标。
- 选中主线链动时能看到它的曲线、信号组件和运行记录。

### Phase 5：Runs / Reports 多策略过滤

目标：运行和报告不再默认只看 Quality。

改动：

- `frontend/src/pages/runs/RunsPage.tsx`
- `frontend/src/pages/reports/ReportsPage.tsx`
- `frontend/src/entities/run/api.ts`
- `frontend/src/entities/report/api.ts`

结果：

- `ALL` 模式展示所有运行和报告。
- 单策略模式展示该策略运行和报告。
- `system_data_update` 在运行页单独可见。

### Phase 6：长期演进

后续可做：

- 后端多策略 overview 聚合接口。
- 主线链动独立日报。
- 策略组合/账户视角。
- Agent 研究入口与人工复盘入口。
- 多策略资金分配与组合风险预算。

## 测试策略

每个 Phase 必须有前端单测覆盖：

- 数据加载是否包含多个策略。
- 全局策略选择是否影响页面数据。
- `ALL` 模式是否展示多策略总览。
- 单策略模式是否展示对应策略指标。
- Runs / Reports 筛选是否正确。

每次前端改动后必须运行：

```bash
cd frontend && npm test && npm run build:pre
```

如涉及 Python API 或数据契约，额外运行：

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

## 验收标准

1. Dashboard 能看到 Quality Alpha V1 和主线链动策略。
2. Dashboard 可以在全部策略和单策略之间切换。
3. 主线链动有总览指标、净值曲线、风险指标、运行记录。
4. Quality 不再是页面唯一中心。
5. 页面没有把主线链动误展示成基本面因子策略。
6. `npm test` 和 `npm run build:pre` 通过。

