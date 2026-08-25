# 企业级量化系统开发流程门禁

## 目标

本项目从个人量化系统升级为企业级量化平台。所有后续开发必须支持断点继续、可回溯、TDD、分里程碑推进。

## 工作流

```text
需求确认
→ Phase 计划
→ TDD 实现
→ 验证
→ 更新规划状态
→ 提交或等待用户确认
```

## 文件职责

```text
.planning/PROJECT.md       项目定位和边界
.planning/REQUIREMENTS.md  企业级系统需求
.planning/ROADMAP.md       里程碑和阶段
.planning/TASKS.md         任务看板
.planning/STATE.md         当前断点状态
.planning/adr/             架构决策记录
docs/development_workflow.md 当前开发门禁
docs/phase_template.md     Phase 执行模板
docs/verification_checklist.md 完成验收清单
```

## Phase 进入条件

开始任意 Phase 前必须满足：

1. `.planning/STATE.md` 指向当前 Phase。
2. `.planning/TASKS.md` 有对应任务。
3. Phase 目标、非目标和验收标准明确。
4. 如果涉及代码变更，先写失败测试。

## TDD 规则

所有功能性代码变更必须遵循：

```text
RED：先写失败测试
GREEN：写最小实现
REFACTOR：在测试通过后整理代码
```

允许不写自动化测试的情况：

- 纯规划文档。
- 纯运行产物补跑。
- 无稳定断言的探索性研究草稿。

即使不写自动化测试，也必须写明人工验收标准。

## 验证规则

Python 代码变更默认执行：

```bash
"$HOME/recommend_analysis/.venv/bin/python3" -m pytest -q
```

前端代码变更默认执行：

```bash
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm --prefix frontend test -- --run
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm --prefix frontend run build:pre
```

如果执行 `build:pre`，必须重启服务：

```bash
./scripts/restart_services.sh
```

调度或运行系统变更后必须检查：

```bash
curl -s http://127.0.0.1:8765/api/scheduler/status
```

## 运行产物规则

生产/观察类任务必须输出到：

```text
runs/YYYYMMDD/
```

长期系统状态必须写入：

```text
state/quant_system.sqlite
data/monitoring.sqlite3
```

临时研究报告可以写入：

```text
reports/
```

但可复现研究必须在后续 Experiment Runner 中登记。

## 通知规则

Bark 通知分为：

1. 数据更新摘要。
2. 策略运行摘要。
3. 投研监控摘要。
4. 风险处置摘要。
5. 调度异常通知。

正常 watchdog 不通知，只记录状态。异常必须通知。

## 风控规则

实盘前置阶段不自动下单。任何风险动作必须是：

```text
触发风险
→ 写 risk_actions.csv
→ Bark 通知
→ 次日 pre_market_check
→ 人工确认
```

## 断点恢复

每次中断前或完成 Phase 后必须更新：

```text
.planning/STATE.md
.planning/TASKS.md
```

恢复时先读取：

```bash
cat .planning/STATE.md
cat .planning/TASKS.md
```

## 禁止事项

- 不绕过统一 pipeline 新增临时生产入口。
- 不把自动下单提前到 P0-P3。
- 不在没有测试或验收标准时修改核心回测/风控。
- 不把调参结果直接当作有效 alpha。
- 不提交大体积本地数据和运行缓存，除非用户明确要求。
