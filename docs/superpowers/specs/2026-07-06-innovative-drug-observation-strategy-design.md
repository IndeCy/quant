# 创新药出海观察策略 V0 设计

## 背景

Quality Alpha V1 已进入 Production Candidate，投研模块也已经具备产业机会观察池、主题强度排行、候选股优先级和升级候选提示。2026-07-06 的投研监控中，`innovative_drug_globalization`（创新药出海）成为当天唯一升级候选，原因是主题内出现 1 个 S 级样本和 2 个 A 级样本。

本设计的目标不是新增可交易 Alpha，也不是优化收益，而是把“创新药出海”从一次性投研结论沉淀为可每日运行、可回看、可展示的观察策略。

## 目标

新增 `innovative_drug_globalization_observer_v0`，定位为研究观察策略：

- 每天自动运行。
- 生成目标观察组合和历史净值曲线。
- 在策略页面可切换查看。
- 在投研页面保留升级路径和证据说明。
- 不生成正式调仓建议，不进入真实组合，不触发买卖提醒。

## 非目标

- 不接券商。
- 不新增交易策略。
- 不新增 Alpha 因子。
- 不修改 M0 ExecutionModel。
- 不改变 Quality Alpha V1 或主线链动策略。
- 不把观察组合写入正式 `rebalance_plan.csv`。
- 不把观察策略升级为 Paper Trading。

## 策略身份

| 字段 | 值 |
|---|---|
| strategy_id | `innovative_drug_globalization_observer_v0` |
| name | 创新药出海观察策略 V0 |
| template_id | `opportunity_observer` |
| status | `research_observation` |
| universe | `opportunity_theme:innovative_drug_globalization` |
| benchmark | `510300` |
| adjust_policy | `qfq` |
| execution | 仅模拟观察，不进入 M0 交易执行 |

## 输入数据

第一版只复用当前系统已有数据：

- `opportunity_themes`
- `opportunity_stocks`
- `opportunity_direction_rankings`
- `research_monitor_runs`
- 已缓存前复权日线行情
- 已有财务指标摘要

创新药深层数据暂不接入，包括海外收入占比、BD 授权金额、管线阶段、临床进展和现金 runway。这些作为后续升级条件，不作为 V0 实现范围。

## 组合规则

观察组合每天按以下规则生成：

1. 读取 `innovative_drug_globalization` 主题下已验证入池股票。
2. 排除 `淘汰`。
3. 默认排除 `成熟`，但在页面保留成熟样本说明。
4. 按观察优先级分排序。
5. 取 Top5。
6. 等权生成观察目标组合。
7. 如果可入选股票不足，按实际数量等权；如果没有可入选股票，则空仓观察。

该组合只用于观察收益和路径，不代表交易建议。

## 运行产物

每日运行后写入统一可读产物：

- 策略每日净值。
- 当前观察组合。
- 股票排序和入选原因。
- 排除股票和排除原因。
- 主题强度分。
- 升级候选状态。
- 观察策略状态说明。

文件产物建议落在 `runs/YYYYMMDD/`：

- `innovative_drug_globalization_observer_v0_snapshot.csv`
- `innovative_drug_globalization_observer_v0_metrics.json`
- `innovative_drug_globalization_observer_v0_report.md`

同时写入系统 SQLite 监控表，以便前端统一读取策略曲线和快照。

## 每日流水线

观察策略应接在投研监控之后：

1. 增量更新 Tushare 数据。
2. 数据质量校验。
3. 运行正式策略。
4. 运行投研监控。
5. 运行创新药出海观察策略。
6. 更新策略监控数据。
7. 更新前端看板数据。
8. Bark 仅提示观察状态变化，不提示买卖。

如果投研监控失败，观察策略不运行。原因是观察策略依赖投研监控产生的主题强度、观察级别和优先级。

## 前端展示

策略页面需要支持展示 `research_observation` 状态的策略实例：

- 可在策略切换器中选择。
- 显示净值曲线。
- 显示当前观察组合。
- 显示“观察中，不可交易”状态。
- 显示入选原因、排除原因和数据缺口。
- 显示升级路径：观察策略 → Paper Candidate → Paper Trading → Shadow Live。

投研页面继续显示主题排行和研究报告，策略页面负责展示观察策略的类策略表现。

## 通知规则

Bark 通知只在以下情况触发：

- 主题首次成为升级候选。
- S/A 样本数量变化。
- 观察组合发生变化。
- 主题从升级候选退回继续观察。

通知文案必须包含“观察策略，不构成调仓建议”。

## 风险控制

为避免误操作，系统必须具备以下保护：

- `status=research_observation` 的策略不能进入正式调仓计划。
- 观察组合不能写入真实组合账户。
- 观察组合不能触发“今日需要操作”。
- 前端必须明确展示不可交易状态。
- 报告中必须说明数据缺口：海外收入、BD 金额、管线阶段暂未结构化接入。

## 测试验收

至少覆盖：

- 策略实例能被注册为 `research_observation`。
- 观察策略只读取创新药出海主题。
- 成熟样本默认不进入目标组合。
- Top5 等权组合生成正确。
- 没有候选股票时生成空仓观察。
- 观察策略不会生成正式调仓建议。
- 每日流水线在投研监控后运行观察策略。
- 前端策略切换器能显示观察策略。

## 实施边界

第一轮实现只做 V0：

- 注册策略实例。
- 增加观察策略 runner。
- 写入监控数据和 runs 产物。
- 接入每日流水线。
- 让前端策略页可见、可切换、可看曲线和当前组合。

不做医药专业数据库、不做 BD 事件结构化、不做策略回测优化、不做实盘提醒。
