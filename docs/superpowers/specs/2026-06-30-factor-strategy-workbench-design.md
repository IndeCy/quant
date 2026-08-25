# Factor Strategy Workbench Design

## 背景

系统当前已经具备可信回测、Paper/Shadow Live、每日调度、策略监控和本地前端。但策略仍主要来自代码入口：

- Quality Alpha V1 是固定脚本。
- 主线链动是固定观察脚本。
- 前端策略草案只能保存组合想法，不能成为可运行策略资产。

目标升级为：用户可以从外部获得一个因子或策略想法，用自然语言沉淀到系统，再转成结构化配置、可执行因子或策略实例，最后进入每日自动观测和看板。

## 核心目标

建立完整闭环：

```text
外部想法
→ 自然语言沉淀
→ 结构化因子/策略草案
→ 可执行因子或策略模板
→ 策略实例
→ 自动调度运行
→ 监控指标、历史曲线、持仓、调仓建议、报告
```

这不是单纯前端改造，而是“研究资产管理 + 策略实例运行系统”。

## 设计原则

1. 因子是可复用资产，不直接决定仓位。
2. 策略模板是可复用运行逻辑，不绑定具体因子。
3. 策略实例是可运行资产，由模板、因子组合、股票池、过滤器、组合构建、风险层组成。
4. 调度器不认识具体策略，只运行所有启用的策略实例。
5. 前端不认识具体策略，只展示策略资产和运行结果。
6. 自然语言想法必须先进入草案状态，经过结构化和验证后才可运行。
7. 不修改 M0 ExecutionModel，不做自动下单，不用机器学习自动生成未审计策略。

## 核心对象

### Factor Idea

因子想法来自外部论文、经验、对话或用户输入。

字段：

- `idea_id`
- `title`
- `raw_description`
- `source`
- `hypothesis`
- `required_data`
- `as_of_requirement`
- `direction`
- `status`: `draft | structured | implemented | validated | archived`
- `created_at`
- `updated_at`

例子：

```json
{
  "title": "盈利稳定性",
  "raw_description": "过去三年ROE波动率越低越好",
  "hypothesis": "盈利稳定公司更可能获得稳定估值溢价",
  "required_data": ["roe", "f_ann_date"],
  "as_of_requirement": "必须使用财报披露日",
  "direction": "lower_is_better",
  "status": "draft"
}
```

### Factor Definition

可执行因子定义。它必须明确计算逻辑、输入字段、as-of 规则和验证状态。

字段：

- `factor_id`
- `name`
- `category`
- `direction`
- `source`
- `input_fields`
- `compute_spec`
- `as_of_policy`
- `transform_default`
- `validation_status`
- `description`

因子可以来自：

1. 现有字段直接映射，例如 ROA。
2. 现有字段派生，例如三年 ROE 稳定性。
3. 后续新增数据源，但新增数据源必须先进入数据层规划。

### Strategy Idea

策略想法来自外部策略描述或用户语言输入。

字段：

- `idea_id`
- `title`
- `raw_description`
- `source`
- `hypothesis`
- `candidate_template`
- `required_factors`
- `status`: `draft | structured | instantiable | blocked | archived`

例子：

```json
{
  "title": "高ROA高现金流低波组合",
  "raw_description": "选高ROA、高经营现金流、低波动股票，月频调仓，Top30，行业上限20%",
  "candidate_template": "factor_topn_monthly",
  "required_factors": ["roa", "ocf_to_or", "low_volatility"],
  "status": "structured"
}
```

### Strategy Template

策略模板定义可复用运行逻辑。模板不是策略实例。

第一阶段支持：

- `factor_topn_monthly`

模板配置能力：

- 股票池
- 过滤器
- 因子列表和权重
- transform
- TopN
- 权重方式
- 调仓频率
- 风险层
- 基准

后续模板：

- `industry_chain_momentum`
- `low_volatility_topn`
- `dividend_quality`
- `event_driven_asof`

### Strategy Instance

策略实例是系统真正运行和展示的对象。

字段：

- `strategy_id`
- `name`
- `template_id`
- `status`: `draft | research | paper | shadow_live | paused | archived`
- `enabled`
- `universe`
- `filters`
- `factors`
- `construction`
- `risk_overlay`
- `benchmark`
- `schedule_policy`
- `created_at`
- `updated_at`

例子：

```json
{
  "strategy_id": "quality_roa_ocf_v2",
  "name": "Quality ROA OCF V2",
  "template_id": "factor_topn_monthly",
  "status": "paper",
  "enabled": true,
  "universe": "all_a",
  "filters": ["listed_3y", "exclude_st", "liquidity_top80"],
  "factors": [
    {"factor_id": "roa", "weight": 0.6, "transform": "winsorize_zscore"},
    {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "winsorize_zscore"}
  ],
  "construction": {"top_n": 20, "weighting": "equal_weight"},
  "risk_overlay": "vol_20_45_to_30",
  "benchmark": "510300"
}
```

## 系统运行流

### 数据更新

每天只运行一个数据更新任务：

```text
daily_data_update_pipeline
```

它负责：

- Tushare 增量日线。
- ETF/指数基准。
- 复权因子校验。
- 数据质量校验。

策略运行阶段只读数据，不写行情库。

### 策略批量运行

调度器不为每个策略写固定 job，而是运行：

```text
strategy_batch_runner
```

批量 runner 读取所有：

```text
strategy_instances.enabled = true
status in (paper, shadow_live)
```

然后执行：

```text
for instance in enabled_instances:
    load template
    validate config
    run strategy
    write metrics
    write holdings
    write rebalance plan
    write run record
    write report if supported
```

第一阶段可以顺序执行，第二阶段再并行。并行前必须保证每个策略写入自己的结果命名空间。

## 前端工作台

### Factor Library

能力：

- 查看因子库。
- 新增自然语言因子想法。
- 将因子想法结构化。
- 查看因子状态：草案、已实现、已验证、归档。
- 查看因子覆盖率、分布、as-of 说明。

### Strategy Factory

能力：

- 从策略模板创建策略实例。
- 选择因子并配置权重。
- 配置股票池、过滤器、TopN、权重方式、调仓频率、风险层、基准。
- 保存为草案。
- 启用为 Paper / Shadow Live。
- 暂停或归档策略实例。

### Dashboard

能力：

- 展示所有启用策略实例。
- 展示历史净值、基准、超额、回撤、波动率、仓位。
- 支持 `ALL` 和任意策略实例切换。
- 新增策略实例后自动进入看板。

### Runs

能力：

- 展示数据更新任务。
- 展示批量 runner。
- 展示每个策略实例子任务。
- 失败时能看到失败阶段和原因。

## 数据模型改造

建议轻量使用当前 SQLite 状态库，新增表：

- `factor_ideas`
- `strategy_ideas`
- `strategy_templates`
- `strategy_instances`
- `strategy_instance_factors`
- `strategy_instance_runs`
- `strategy_instance_holdings`
- `strategy_instance_rebalance_plans`

已有表继续保留：

- `factor_registry`
- `strategy_registry`
- `strategy_runs`
- `strategy_run_steps`
- `report_index`
- `strategy_nav_daily`

兼容策略：

- Quality Alpha V1 迁移为一个 `strategy_instance`。
- 主线链动迁移为一个 `strategy_instance`，模板为 `industry_chain_momentum`。
- 迁移期间保留旧脚本入口，runner 可以先调用旧脚本适配器。

## 分阶段实施

### Phase 1：策略目录驱动展示

先完成多策略看板，不改变策略生成方式。

交付：

- 前端从策略目录动态加载策略。
- Dashboard 支持所有策略总览。
- 主线链动和 Quality 都能展示。

### Phase 2：研究资产库

新增因子想法和策略想法的持久化。

交付：

- 可以把自然语言因子想法保存为 `factor_idea`。
- 可以把自然语言策略想法保存为 `strategy_idea`。
- 前端提供列表、详情、状态管理。

### Phase 3：策略模板与实例

新增模板和实例模型。

交付：

- `factor_topn_monthly` 模板。
- 因子组合可保存为 `strategy_instance`。
- 实例有 `draft/research/paper/shadow_live/paused/archived` 状态。

### Phase 4：可执行因子策略 runner

让因子组合策略实例真正跑起来。

交付：

- runner 读取 `strategy_instance`。
- 生成 signal、target、metrics、holdings、rebalance plan。
- 写入监控库和运行记录。

### Phase 5：动态批量调度

替换固定策略 job。

交付：

- 保留一个数据更新 job。
- 新增一个 strategy batch runner job。
- runner 自动运行所有 enabled 策略实例。
- 新增策略无需改调度器。

### Phase 6：策略工厂前端

前端支持完整创建和启用策略实例。

交付：

- 因子自由组合。
- 配置过滤器、TopN、权重、基准、风险层。
- 保存草案。
- 启用 Paper / Shadow Live。
- 自动进入看板。

## 验收标准

1. 用户能用自然语言保存一个外部因子想法。
2. 用户能把因子想法结构化为可执行因子定义，或标记为缺数据/不可执行。
3. 用户能用因子库里的因子组合出一个策略实例。
4. 策略实例启用后，不改调度器即可自动每日运行。
5. 策略实例有历史收益曲线、风险指标、持仓、调仓建议、运行记录。
6. 前端新增策略实例不需要改代码。
7. Quality Alpha V1 和主线链动都能作为策略实例兼容迁移。

