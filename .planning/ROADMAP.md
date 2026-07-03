# Roadmap

## Milestone E0：治理基座

目标：建立可断点继续、可回溯、可验收的项目管理方式。

### Phase E0.1：规划与任务治理

- 优先级：P0
- 状态：done
- 产物：`.planning/PROJECT.md`、`.planning/REQUIREMENTS.md`、`.planning/ROADMAP.md`、`.planning/STATE.md`、`.planning/TASKS.md`
- 验收：任务清单能指向下一步执行入口。

### Phase E0.2：开发流程门禁

- 优先级：P0
- 状态：done
- 目标：形成 TDD、测试、提交、产物登记规范。
- 验收：新增 `docs/development_workflow.md` 或等价文档。

## Milestone E1：可信研究平台

### Phase E1.1：Experiment Runner

- 优先级：P1
- 状态：done
- 目标：把研究/回测从脚本升级为可登记实验。
- 验收：一次实验生成配置、结果、报告索引。

### Phase E1.2：Walk-Forward Validation

- 优先级：P1
- 状态：done
- 目标：训练期按固定规则选参数，验证期禁止反向调参。
- 验收：Quality 风险层可跑 walk-forward 报告。

## Milestone E2：数据治理

### Phase E2.1：Data Catalog

- 优先级：P1
- 状态：done
- 目标：统一记录 DuckDB/SQLite 数据源、最新日期、字段口径、质量状态。

### Phase E2.2：Data Quality Gate

- 优先级：P1
- 状态：done
- 目标：复权、基准、交易日、缺失值异常统一阻断。

## Milestone E3：因子平台

### Phase E3.1：Factor Registry V2

- 优先级：P2
- 状态：done
- 目标：因子定义、依赖、as-of、方向、频率统一登记。

### Phase E3.2：Factor Computation Runner

- 优先级：P2
- 状态：done
- 目标：因子计算任务可调度、可缓存、可诊断。

## Milestone E4：策略/组合/风控平台

### Phase E4.1：Strategy Lifecycle

- 优先级：P2
- 状态：done
- 目标：draft/research/paper/live/retired 状态机。

### Phase E4.2：Portfolio & Account Model

- 优先级：P2
- 状态：done
- 目标：统一理论持仓、实盘持仓、现金、漂移。

## Milestone E5：前端平台化

### Phase E5.1：Operations Console

- 优先级：P3
- 状态：done
- 目标：统一展示策略、因子、实验、风险、调度、投研。

## Milestone E6：实盘执行准备

### Phase E6.1：Manual Order Workflow

- 优先级：P4
- 状态：done
- 目标：生成、确认、回填和审计本地手工调仓单，不接券商自动下单。

## Milestone E7：实盘前审计

### Phase E7.1：Live Readiness Audit

- 优先级：P4
- 状态：done
- 目标：审计数据、策略、调仓单、通知、备份和权限边界，确认是否具备小资金实盘前置条件。

## Milestone E8：发布与备份基线

### Phase E8.1：Release Baseline and Runtime Backup

- 优先级：P4
- 状态：done
- 目标：整理代码提交边界、运行数据备份包和恢复说明，形成可迁移到 Mac mini 的发布基线。

## Milestone E9：代码基线整理

### Phase E9.1：Git Baseline Hygiene

- 优先级：P4
- 状态：done
- 目标：将源码、治理文档、运行数据和本地生成产物分组，形成安全提交/发布清单。

## Milestone E10：安全提交与发布确认

### Phase E10.1：Safe Commit Review

- 优先级：P4
- 状态：done
- 目标：基于 Git 基线报告确认提交边界，安全提交源码和治理文档，隔离运行数据与本地生成产物。

## Milestone E11：选择性提交与发布基线

### Phase E11.1：Selective Commit and Release Baseline

- 优先级：P4
- 状态：done
- 目标：基于安全提交审查清单执行选择性暂存、提交和发布基线确认，不让运行数据进入代码提交。

## Milestone E12：长期运行观察

### Phase E12.1：Post-Baseline Operations

- 优先级：P4
- 状态：done
- 目标：基线提交后持续观察 Shadow Live / Paper 运行稳定性，围绕调度、通知、日报、投研和策略资产化做后续迭代。

## Milestone E13：后续策略与运维迭代

### Phase E13.1：Next Operations Iteration

- 优先级：P4
- 状态：done
- 目标：基于基线后运行审计结果，继续完善调度稳定性、通知闭环、日报可视化、投研资产化和策略资产化。

## Milestone E14：日报与运行告警收敛

### Phase E14.1：Daily Report Warning Closure

- 优先级：P4
- 状态：pending
- 目标：根据运行观察摘要中的 WARN，区分盘前检查产物与完整盘后日报产物，减少误报并提升日常巡检可读性。
