# Operations Console Design

## 背景

系统已经从脚本驱动逐步升级为本地运行系统：

- E1：Experiment Runner 与 Walk-Forward Validation。
- E2：Data Catalog 与 Data Quality Gate。
- E3：Factor Registry V2 与 Factor Computation Runner。
- E4：Strategy Lifecycle 与 Portfolio / Account Model。

前端已经具备 Vite + React 的本地控制台，包含 sidebar、总览、策略、因子、运行、调度、报告、研究、数据、风险和设置页面。但新完成的系统能力还没有被完整纳入页面：

- 数据页只有数据健康摘要，没有 Data Catalog 和 Quality Gate 操作入口。
- 因子页只展示旧因子定义，没有展示 Factor Contract。
- 策略页可以保存策略实例，但没有生命周期流转入口和运行准入原因。
- 账户/组合视图还没有展示目标持仓、实际持仓、现金和漂移。

E5.1 的目标是把现有前端升级为“Operations Console”：能维护和观察系统运行，而不是散落报告的浏览器外壳。

## 核心目标

第一版只做本地访问，不做公网部署，不做自动下单。

目标闭环：

```text
系统运行状态
→ 数据可信度
→ 因子契约
→ 策略生命周期
→ 账户漂移
→ 运行记录和报告
```

用户每天打开本地前端后，应能回答：

1. 数据有没有更新、有没有通过质量门禁。
2. 哪些因子具备 as-of 和数据依赖契约。
3. 哪些策略处于 paper / shadow_live / live，哪些不能运行。
4. 当前策略账户目标持仓和实际持仓差多少。
5. 今天是否需要人工处理。

## 非目标

- 不做自动下单。
- 不做券商接口。
- 不新增 Alpha 因子。
- 不修改策略收益逻辑。
- 不重写前端路由和布局。
- 不做复杂权限、多用户、云部署。
- 不把 reports 目录继续作为前端唯一事实来源。

## 信息架构

保留当前一级导航：

- `/` 总览
- `/strategies` 策略
- `/factors` 因子
- `/runs` 运行
- `/scheduler` 调度
- `/logs` 日志
- `/reports` 报告
- `/research` 研究
- `/data` 数据
- `/risk` 风险
- `/settings` 设置

E5.1 不新增一级菜单。新增能力落入现有页面：

| 页面 | 新增能力 | 目的 |
|---|---|---|
| 数据 | Data Catalog、Quality Gate | 判断数据是否可信 |
| 因子 | Factor Contract | 判断因子是否时点安全、可组合 |
| 策略 | Lifecycle Transition、Run Eligibility | 判断策略是否可运行 |
| 策略详情 | Account Snapshot | 展示现金、目标/实际持仓、漂移 |
| 总览 | 关键状态汇总 | 一屏判断是否需要处理 |

## 前端模块边界

继续沿用现有结构：

```text
frontend/src/
  app/
    loadDashboardData.ts
    types.ts
    navigation.ts
  entities/
    dataHealth/
    factor/
    strategy/
    run/
    scheduler/
    report/
  pages/
    dashboard/
    data/
    factors/
    strategies/
```

E5.1 新增或扩展实体：

```text
entities/dataCatalog/
  api.ts
  model.ts
  status.ts

entities/factorContract/
  api.ts
  model.ts

entities/account/
  api.ts
  model.ts
  drift.ts
```

不把所有 API 类型塞进 `app/types.ts`。`DashboardData` 只聚合首屏和跨页面共享数据；页面特有数据可以在页面内按需加载。

## API 依赖

E5.1 使用已有后端 API：

```text
GET  /api/data/health
POST /api/data/catalog/refresh
GET  /api/data/sources
GET  /api/data/sources/{dataset_id}
POST /api/data/quality-gate

GET  /api/factors
GET  /api/factors/{factor_id}
GET  /api/factor-contracts
GET  /api/factor-contracts/{factor_id}

GET  /api/strategy-instances
POST /api/strategy-instances
POST /api/strategy-instances/{strategy_id}/transition
GET  /api/strategy-instances/{strategy_id}/state
GET  /api/accounts/{strategy_id}
```

如果某策略没有账户快照，前端展示“暂无账户快照”，不报错阻断页面。

## 页面设计

### 数据页

数据页分三块：

1. 数据健康摘要：保留现有行情、基准、监控和系统状态。
2. Data Catalog：展示数据源、类型、状态、最新日期、文件大小、表数量。
3. Data Quality Gate：按钮触发质量门禁，展示 PASS/FAIL、检查项、失败原因。

交互：

- “刷新目录”按钮调用 `POST /api/data/catalog/refresh`。
- “运行质量门禁”按钮调用 `POST /api/data/quality-gate`。
- 点击数据源行读取详情，展示表、行数、日期字段、最新日期。

### 因子页

因子页保留因子列表和使用关系，新增 Factor Contract 面板：

- as_of_policy
- as_of_field
- frequency
- value_type
- input_datasets
- input_fields
- output_fields
- validation

因子详情应明确显示：

- `有契约`：可以进入可运行策略组合。
- `无契约`：只能作为草案或研究素材。

E5.1 不提供复杂的因子契约编辑表单。正式契约新增仍通过后端或后续 E5.x 实现。

### 策略页

策略页分成三块：

1. 策略定义：现有策略库、因子组合、指标。
2. 策略实例：可运行策略资产，展示 template、status、enabled、benchmark、risk_overlay。
3. 生命周期操作：对选中的策略实例执行状态流转。

状态流转按钮：

- draft -> research
- research -> paper
- paper -> shadow_live
- shadow_live -> live
- 任意非 retired -> paused
- paused -> paper
- 任意 -> retired

前端不硬编码复杂准入逻辑，只展示后端返回错误。例如缺 Factor Contract 时，后端返回 400，前端显示错误信息。

### 账户/组合视图

账户视图挂在策略页选中实例右侧，不新增一级菜单。

展示：

- total_value
- cash
- cash_weight
- position_value
- max_abs_drift
- 持仓表：symbol、target_weight、actual_weight、drift_weight、target_amount、actual_amount、trade_amount、action

排序：

1. `action` 为 BUY/SELL 的排前面。
2. `abs(drift_weight)` 大的排前面。
3. symbol 升序。

### 总览页

总览页第一版只做轻量增强：

- Readiness 保留。
- 策略总览保留。
- 新增“需要关注”摘要：
  - 数据质量最近状态。
  - 有多少策略处于可运行态。
  - 有多少策略有账户漂移超过阈值。

如果账户快照数据缺失，不把总览标红，只提示“账户快照未生成”。

## 错误处理

- API 失败时页面局部展示错误，不让整个应用白屏。
- Data Quality Gate FAIL 用 warning/error 样式展示，但不自动触发任何策略运行。
- 状态流转失败时显示后端错误文本。
- 账户快照 404 显示空状态。

## 测试策略

### 单元测试

- `dataCatalog/status.test.ts`
  - Data Catalog 状态聚合。
  - 文件大小格式化。
  - PASS/FAIL tone。

- `factorContract/display.test.ts`
  - contract 有无判定。
  - as-of 文案。

- `account/drift.test.ts`
  - 持仓按 action 和漂移排序。
  - 最大漂移摘要。

- `strategy/lifecycle.test.ts`
  - 状态流转按钮候选项。
  - 后端错误展示文案。

### 构建验证

必须执行：

```bash
cd frontend
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
```

构建后必须重启本地服务，避免缓存导致 BFF 或前端状态异常。

## 成功标准

E5.1 完成后：

1. 数据页可以查看 Data Catalog 并手动运行 Quality Gate。
2. 因子页可以查看 Factor Contract。
3. 策略页可以执行生命周期流转。
4. 策略页可以查看账户快照和漂移。
5. 当前所有前端测试通过。
6. `npm run build:pre` 通过。
7. 不引入新的策略逻辑、因子逻辑或交易执行逻辑。

## 后续阶段

E5.2 可以继续做：

- 账户页一级导航。
- 策略实例创建向导。
- 因子契约编辑器。
- 实验结果可视化。
- 运行失败诊断页。
- 操作待办中心。
