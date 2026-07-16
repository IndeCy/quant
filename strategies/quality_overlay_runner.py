"""冻结 Quality Alpha V1 的原生策略执行适配器。"""

from __future__ import annotations

from typing import Any

from backtest.quality_overlay_paper import QualityPaperStore
from runtime.paths import RuntimePaths


def run_quality_overlay_instance(
    instance: dict[str, Any],
    paths: RuntimePaths,
    trade_date: str,
) -> dict[str, Any]:
    """复用冻结 Quality 计算逻辑，返回标准目标组合而不启动子进程。"""
    from examples import run_quality_overlay_paper as quality

    if paths.root != quality.RUNTIME_PATHS.root:
        raise RuntimeError("quality runner paths must match configured QUANT_HOME")
    quality.validate_incremental_quality()
    snapshot, holdings, run, benchmark_curve, shanghai_curve = quality.build_snapshot([], as_of_date=trade_date)
    if snapshot.trade_date > trade_date:
        raise RuntimeError(
            f"quality data date {snapshot.trade_date} exceeds requested trade date {trade_date}"
        )
    quality.update_monitoring_dashboard(run, benchmark_curve, shanghai_curve)
    run_dir = quality.write_production_artifacts(snapshot, holdings, run, benchmark_curve, [])
    QualityPaperStore(paths.quality_overlay_paper_path).save(snapshot)
    report = quality.render_report(snapshot, holdings, [])
    paths.latest_report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_report_path.write_text(report, encoding="utf-8")
    return {
        "strategy_id": str(instance["strategy_id"]),
        "trade_date": snapshot.trade_date,
        "selected_count": len(snapshot.target_weights),
        "target_weights": snapshot.target_weights,
        "nav": float(run.result.daily_values.iloc[-1]),
        "run_dir": str(run_dir),
    }
