# Phase 完成验收清单

## 代码验收

- [ ] 是否只修改本 Phase 相关文件。
- [ ] 是否没有改动 alpha 策略参数，除非 Phase 明确要求。
- [ ] 是否没有绕过统一 pipeline。
- [ ] 是否没有提交运行缓存、大体积数据库或临时文件。

## 测试验收

- [ ] 新功能是否先有失败测试。
- [ ] Python 是否通过：

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

- [ ] 前端变更是否通过：

```bash
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm --prefix frontend test -- --run
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm --prefix frontend run build:pre
```

## 运行验收

- [ ] 如果改调度，是否检查 `/api/scheduler/status`。
- [ ] 如果改通知，是否验证 Bark 成功或异常记录。
- [ ] 如果改日报/产物，是否检查 `runs/YYYYMMDD/`。
- [ ] 如果改风险模块，是否区分调仓操作和风险操作。

## 文档验收

- [ ] `.planning/TASKS.md` 状态已更新。
- [ ] `.planning/STATE.md` 断点已更新。
- [ ] 如有架构决策，是否新增 `.planning/adr/`。
- [ ] 如有用户可见流程变化，是否更新相关说明。

## 完成声明

完成 Phase 时必须说明：

```text
完成了什么
验证了什么
剩余风险
下一步是什么
```
