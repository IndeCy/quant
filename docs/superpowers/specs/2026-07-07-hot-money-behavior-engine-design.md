# 游资行为驱动多策略交易引擎 V0 设计

## 背景

当前系统已经具备可信回测、每日调度、策略注册、前端看板、Paper/Shadow 运行、Bark 通知和 Tushare 增量数据能力。Tushare token 已验证可以调用 `limit_list_d`，能够获取每日涨停、跌停、炸板/开板相关数据。

本设计目标是构建一个“游资行为驱动”的研究和交易引擎，使系统可以识别 A 股短线情绪周期、主线板块、唯一龙头，并在历史数据和 Shadow Live 中解释收益来源。

第一版不直接追求收益最大化，而是先让系统回答：

- 当前市场处于什么情绪状态。
- 当前主线板块是什么。
- 当前唯一龙头和次级龙头是谁。
- 哪类策略在什么状态下有效。
- 收益和亏损分别来自哪个状态、哪个策略。

## 核心原则

- 不预测市场，只识别状态。
- 不分散持仓，只做主线和龙头。
- 不平均交易，只做高赔率阶段。
- 所有收益必须归因到市场状态。
- 所有交易必须可解释：状态 → 主线 → 龙头 → 策略 → 仓位 → 风控。

## 非目标

- 不自动下单。
- 不绕过现有 M0 ExecutionModel。
- 不新增机器学习模型。
- 不把龙虎榜作为第一版必需数据。
- 不直接把游资策略加入真实组合。
- 不替代 Quality Alpha V1 和现有主线链动策略。

## 总体结构

```text
Tushare Limit Data
  ↓
Emotion Data Builder
  ↓
Market State Engine
  ↓
Sector Momentum Engine
  ↓
Leader Stock Engine
  ↓
Strategy Router
  ↓
Execution Strategy Library
  ↓
Position Sizing Engine
  ↓
Risk Engine
  ↓
Backtest / Paper / Attribution Report
```

## 数据层

第一版使用当前系统已有数据和 Tushare 可用接口：

| 数据 | 来源 | 用途 |
|---|---|---|
| 涨跌停列表 | `limit_list_d` | 情绪周期、连板、炸板率 |
| 日线 OHLCV | 已有行情缓存 / Tushare | 回测和趋势判断 |
| 成交额 | 日线 / `daily_basic` | 市场活跃度、板块占比 |
| 板块分类 | 当前行业/概念数据 | 主线板块识别 |
| ST/停牌/涨跌停 | 当前数据清洗层 | 可交易性过滤 |

V0 需要新增一个标准情绪表：

```text
market_emotion_daily
```

建议字段：

| 字段 | 说明 |
|---|---|
| trade_date | 交易日 |
| limit_up_count | 涨停家数 |
| limit_down_count | 跌停家数 |
| zha_ban_count | 炸板/开板数量 |
| open_board_rate | 炸板率 |
| max_chain_height | 最高连板高度 |
| high_level_loss_count | 高位亏钱效应股票数 |
| market_amount | 全市场成交额 |
| market_amount_chg | 成交额变化 |
| top_sector | 当日最强板块 |
| sector_concentration | 板块涨停集中度 |

## Market State Engine

市场状态枚举：

```text
ICE_COLD
REBOUND
EXPANSION
BUBBLE
DISTRIBUTION
```

输入：

- 涨停家数。
- 跌停家数。
- 最高连板高度。
- 成交额变化。
- 板块涨停集中度。
- 高位股亏钱效应。
- 炸板率。

输出：

```text
market_state_daily
```

建议字段：

| 字段 | 说明 |
|---|---|
| trade_date | 交易日 |
| raw_state | 单日初判状态 |
| smoothed_state | 平滑后状态 |
| emotion_score | 情绪分 |
| risk_score | 风险分 |
| transition_reason | 状态变化原因 |

状态规则：

- 使用最近 3 个交易日的情绪分平滑。
- 普通状态切换需要连续 2 日满足条件。
- 极端风险可以直接进入 `DISTRIBUTION`。
- 不允许 `ICE_COLD → BUBBLE` 这种单日跨级跳变。

## Sector Momentum Engine

输入：

- 板块涨停数量。
- 板块成交额占比。
- 龙头涨幅和连板高度。
- 板块内唯一性。

输出：

```text
sector_momentum_daily
```

规则：

- 每天只允许识别 1 到 3 个主线。
- 第一名分数显著领先时，只保留唯一主线。
- 分数低于阈值的板块不进入主线。
- 多板块同时强时，最多保留前三。

板块强度分：

```text
0.35 * 板块涨停数量分位
+ 0.25 * 板块成交额占比分位
+ 0.25 * 板块龙头强度
+ 0.15 * 板块一致性
```

## Leader Stock Engine

输入：

- 个股涨停次数。
- 连板高度。
- 成交额占板块比例。
- 换手率。
- 是否卡位竞争成功。
- 是否属于主线板块。

输出：

```text
leader_stock_daily
```

规则：

- 每个主线板块最多 1 个唯一龙头。
- 可以有次级龙头。
- 杂毛股不得进入交易候选。
- 龙头必须动态更新。

龙头评分：

```text
0.30 * 连板高度
+ 0.25 * 涨停次数
+ 0.15 * 成交额占板块比例
+ 0.15 * 换手健康度
+ 0.15 * 卡位成功信号
```

## Strategy Router

策略路由由市场状态决定。

| 市场状态 | 策略动作 |
|---|---|
| ICE_COLD | 空仓或极小试错 |
| REBOUND | 首板打板 |
| EXPANSION | 连板接力 |
| BUBBLE | 龙头趋势持有 |
| DISTRIBUTION | 减仓和退出 |

第一版建议只实现路由输出，不直接交易：

```text
strategy_route_daily
```

字段：

| 字段 | 说明 |
|---|---|
| trade_date | 交易日 |
| market_state | 市场状态 |
| enabled_strategies | 允许策略 |
| disabled_reason | 禁用原因 |
| max_total_exposure | 最大总仓位 |

## Execution Strategy Library

策略库按行为风格拆分：

| 策略 | 适用状态 | V0 是否实现交易 |
|---|---|---|
| Breakout Strategy | REBOUND | 否，先输出候选 |
| Momentum Leader | EXPANSION | 否，先输出候选 |
| Trend Leader | BUBBLE | 否，先输出候选 |
| Institutional Trend | BUBBLE 后段 | 否，后续扩展 |

V0 只输出“可交易候选”和“理论动作”，不进入真实调仓。

## Position Sizing Engine

仓位由状态控制：

| 状态 | 总仓位 |
|---|---|
| ICE_COLD | 0-10% |
| REBOUND | 10-30% |
| EXPANSION | 30-60% |
| BUBBLE | 60-100% |
| DISTRIBUTION | 0% |

单标的约束：

- 唯一龙头最多 80%。
- 次级龙头最多 30%。
- 杂毛禁止。

V0 只输出建议仓位，不写入真实组合账户。

## Risk Engine

风控优先级高于收益。

必须检测：

- 连板断层风险。
- 高位亏钱效应。
- 板块退潮。
- 单日组合最大回撤。
- 强制止损。
- 炸板率过高。

风控输出：

```text
ALLOW
STOP_BUY
REDUCE
EXIT_POSITION
EXIT_ALL
```

V0 中风控只影响理论候选和报告，不影响现有正式策略。

## 回测输出

后续回测模块必须输出：

- 年化收益。
- 最大回撤。
- 夏普。
- Calmar。
- 胜率。
- 盈亏比。
- 交易次数。
- 交易成本。

归因维度：

- 按市场状态归因。
- 按策略归因。
- 按板块归因。
- 按龙头/次龙头归因。

必须回答：

- 收益是否来自少数情绪爆发阶段。
- 亏损是否来自退潮误判。
- 打板策略是否只在修复期有效。
- 龙头趋势策略是否只在主升期有效。
- 是否存在可解释的游资风格 alpha。

## 分阶段落地

### Phase Y1：情绪数据层

新增 Tushare 涨跌停数据采集和本地缓存：

- 拉取 `limit_list_d`。
- 生成每日涨停、跌停、炸板率、连板高度。
- 生成板块涨停分布。
- 接入数据质量检查。

### Phase Y2：市场状态机

新增 Market State Engine：

- 每日输出状态。
- 保持状态平滑。
- 支持历史区间回放。
- 前端展示状态时间序列。

### Phase Y3：主线和龙头识别

新增 Sector Momentum 和 Leader Stock：

- 每天输出主线 Top3。
- 每个主线输出唯一龙头。
- 输出次级龙头和杂毛过滤原因。

### Phase Y4：策略路由和理论候选

新增 Strategy Router：

- 按状态输出可用策略。
- 输出理论候选、目标仓位、禁用原因。
- 不进入真实调仓。

### Phase Y5：回测和归因

新增游资引擎回测：

- 使用 M0 ExecutionModel。
- 输出按状态和策略的收益归因。
- 判断收益是否集中于少数阶段。

### Phase Y6：Shadow Live 观察

接入每日调度：

- 每日生成市场状态、主线、龙头、理论动作。
- 前端新增“市场情绪/游资引擎”页面。
- Bark 只做风险/状态变化提示，不做买卖建议。

## V0 验收标准

- 能用 Tushare `limit_list_d` 生成情绪数据。
- 能输出每日市场状态。
- 状态切换有原因说明。
- 能识别 1 到 3 个主线板块。
- 每个主线最多 1 个唯一龙头。
- 能输出理论策略路由和建议仓位。
- 不影响现有 Quality Alpha 和主线链动策略。
- 不生成真实调仓单。
- 所有候选和状态都有可解释字段。

## 第一轮建议

第一轮只做 Phase Y1 和 Phase Y2。

原因：

- 情绪状态机是整个游资引擎的根。
- 如果状态机无法解释历史行情，后续策略回测没有意义。
- 先不做交易，可以避免把噪声误认为 alpha。

第一轮交付物：

- `market_emotion_daily` 数据。
- `market_state_daily` 数据。
- 状态机回放脚本。
- 状态分布报告。
- 前端或报告中展示最近一个月市场状态。
