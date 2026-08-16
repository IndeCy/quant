# 全球防守核心 × 主线卫星 80/20 稳健性 V1

| 场景 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| satellite_10pct_10bps | 12.84% | -13.39% | 1.349 |
| baseline_20pct_10bps | 13.77% | -13.81% | 1.226 |
| satellite_30pct_10bps | 14.50% | -15.46% | 1.062 |
| baseline_20pct_100bps | 13.63% | -13.83% | 1.215 |

## 滚动与重抽样

- 252日滚动窗口：1231；正收益占比：
  99.11%；跑赢核心占比：
  64.26%；最差252日：
  -1.26%。
- 20日区块 bootstrap：5000次；相对核心年化收益提升
  P05/中位/P95 = -3.30% /
  2.44% / 9.13%；
  提升为正概率 75.06%。

## 冻结门槛

- PASS `all_neighborhood_returns_at_least_10pct`
- PASS `all_neighborhood_drawdowns_within_20pct`
- PASS `all_neighborhood_sharpes_at_least_095`
- PASS `all_neighborhood_folds_positive`
- PASS `stress_100bps_return_at_least_95pct`
- PASS `stress_100bps_drawdown_within_19pct`
- PASS `stress_100bps_sharpe_at_least_090`
- PASS `rolling_252d_positive_share_at_least_70pct`
- PASS `bootstrap_lift_positive_probability_at_least_75pct`
- FAIL `bootstrap_lift_p05_above_minus_3pct`

结论：`ROBUSTNESS_FAILED_NO_PROMOTION`。不修改底层策略、观察名单或生产调度。
