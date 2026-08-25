# 变更检查表

开发开始前回答：

- 改动属于 data、factor、strategy、portfolio、risk、execution、runtime、API 还是 frontend？
- 是否触碰 M0、复权、as-of、交易日历或费用口径？
- 是否改变已有策略定义、风险层或历史结果？
- 是否修改数据库 Schema，是否提供 migration？
- 是否新增执行入口、持久化副本或策略特殊分支？

开发完成后确认：

- 新代码走标准 Pipeline、策略声明和数据接口。
- 核心逻辑有正常、失败和边界测试。
- 自动生成产物、密钥和数据库没有进入 Git。
- `./scripts/verify.sh` 完整通过。
- 已报告兼容性、结果差异和剩余风险。
