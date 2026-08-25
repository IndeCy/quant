"""Quality Value LowVol 固定分级恢复风险层研究。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from runtime.risk_rules import classify_strategy_risk
from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_value_lowvol_runner import compute_quality_value_lowvol_instance


REPORT_PATH = Path("docs/research/quality-value-lowvol-risk-recovery-study.md")
TRIGGER_VOLATILITY = 0.45
REDUCED_EXPOSURE = 0.30
RECOVERY_STEPS = (0.50, 0.70, 1.00)
STABLE_DAYS_REQUIRED = 3
RECOVERY_DAILY_RETURN_FLOOR = -0.05
MIN_DRAWDOWN_RECOVERY = 0.02
RESEARCH_SPEC = ResearchSpec(
    experiment_id="quality_value_lowvol_risk_recovery_v0",
    name="Quality Value LowVol Risk Recovery V0",
    category="risk_overlay",
    hypothesis="分级恢复能否在保留防御组合收益的同时把最大回撤控制在25%以内",
    definition={
        "base_strategy": "quality_value_lowvol_v0@0.1.0",
        "risk_trigger": {
            "volatility_window": 20,
            "threshold": TRIGGER_VOLATILITY,
            "reduced_exposure": REDUCED_EXPOSURE,
        },
        "recovery": {
            "steps": RECOVERY_STEPS,
            "stable_days": STABLE_DAYS_REQUIRED,
            "daily_return_floor": RECOVERY_DAILY_RETURN_FLOOR,
            "minimum_drawdown_recovery": MIN_DRAWDOWN_RECOVERY,
        },
        "alpha_change": "none",
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq"},
        "methodology_version": "v0",
    },
)


@dataclass
class StatefulRecoveryController:
    """复现现有实盘风险恢复思想的历史状态机。"""

    exposure: float = 1.0
    stable_days: int = 0
    low_drawdown: float = 0.0
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def update(
        self,
        date: pd.Timestamp,
        *,
        volatility: float,
        drawdown: float,
        daily_return: float,
    ) -> float:
        """高波立即降仓，解除时按 30→50→70→100 分级恢复。"""
        if volatility > TRIGGER_VOLATILITY:
            self._transition(date, REDUCED_EXPOSURE, "volatility_trigger", volatility, drawdown)
            self.stable_days = 0
            self.low_drawdown = drawdown
            return self.exposure
        if self.exposure >= 1.0:
            return self.exposure

        self.low_drawdown = min(self.low_drawdown, drawdown)
        stable = daily_return > RECOVERY_DAILY_RETURN_FLOOR and volatility < TRIGGER_VOLATILITY
        self.stable_days = self.stable_days + 1 if stable else 0
        recovery = drawdown - self.low_drawdown
        severity, _ = classify_strategy_risk(
            {
                "daily_return": daily_return,
                "drawdown": drawdown,
                "volatility_20": volatility,
            }
        )
        if not self._eligible(recovery, severity):
            return self.exposure
        self._transition(
            date,
            _next_exposure(self.exposure),
            f"recovery_{severity.lower()}",
            volatility,
            drawdown,
        )
        self.stable_days = 0
        self.low_drawdown = drawdown
        return self.exposure

    def _eligible(self, recovery: float, severity: str) -> bool:
        if self.stable_days < STABLE_DAYS_REQUIRED or recovery + 1e-12 < MIN_DRAWDOWN_RECOVERY:
            return False
        if self.exposure < 0.70:
            return severity != "CRITICAL"
        return severity == "NORMAL"

    def _transition(
        self,
        date: pd.Timestamp,
        target: float,
        reason: str,
        volatility: float,
        drawdown: float,
    ) -> None:
        if target == self.exposure:
            return
        self.transitions.append(
            {
                "date": pd.Timestamp(date).strftime("%Y%m%d"),
                "from_exposure": self.exposure,
                "to_exposure": target,
                "reason": reason,
                "volatility": volatility,
                "drawdown": drawdown,
            }
        )
        self.exposure = target


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """运行固定恢复实验；相同数据和口径默认读取历史结果。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _run_study_calculation(paths, as_of_date)
        summary_path = attempt.output_dir / "summary.md"
        summary_path.write_text(
            Path(result["report_path"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        registration = complete_research_attempt(
            attempt,
            metrics=result,
            outcome="PASSED" if result["gate"]["passed"] else "REJECTED",
            decision_reason=(
                "通过固定风险层门槛"
                if result["gate"]["passed"]
                else "分级恢复降低了收益且未满足回撤和Calmar门槛，终止晋级"
            ),
            artifacts=[ExperimentArtifact("summary", summary_path, "研究报告")],
        )
        return {**result, **registration}
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _run_study_calculation(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """执行基线与固定恢复状态机的实际计算。"""
    instance = load_strategy_definition("quality_value_lowvol_v0").to_instance_payload()
    baseline = compute_quality_value_lowvol_instance(instance, paths, as_of_date)
    controller = StatefulRecoveryController()
    recovery = compute_quality_value_lowvol_instance(
        instance,
        paths,
        as_of_date,
        exposure_controller=controller,
    )
    baseline_metrics = _metric_summary(baseline)
    recovery_metrics = _metric_summary(recovery)
    gate = evaluate_gate(baseline_metrics, recovery_metrics)
    report = render_report(baseline_metrics, recovery_metrics, gate, controller.transitions)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    return {
        "baseline": baseline_metrics,
        "recovery": recovery_metrics,
        "gate": gate,
        "transitions": controller.transitions,
        "report_path": str(output),
    }


def evaluate_gate(baseline: dict[str, float], recovery: dict[str, float]) -> dict[str, Any]:
    """使用研究前固定门槛，禁止根据结果反向修改。"""
    checks = {
        "annualized_return_at_least_10pct": recovery["annualized_return"] >= 0.10,
        "max_drawdown_within_25pct": recovery["max_drawdown"] >= -0.25,
        "calmar_at_least_045": recovery["calmar"] >= 0.45,
        "execution_cost_not_worse_10pct": recovery["execution_cost"] <= baseline["execution_cost"] * 1.10,
    }
    return {"passed": all(checks.values()), "checks": checks}


def render_report(
    baseline: dict[str, float],
    recovery: dict[str, float],
    gate: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> str:
    """生成可回溯研究结论。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality Value LowVol Risk Recovery Study

## 固定规则

- 20日组合年化波动率大于45%：下一交易日仓位降至30%。
- 连续稳定3日、相对受限后低点回撤修复至少2%后，按30%→50%→70%→100%恢复。
- 仍为CRITICAL时不得从30%/50%上调；恢复满仓前必须为NORMAL。
- Alpha、股票池、Top20、月频、M0和交易成本保持不变。

## 结果

| 方案 | 年化收益 | 最大回撤 | Sharpe | Calmar | 总收益 | 执行成本 |
|---|---:|---:|---:|---:|---:|---:|
| 原波动率开关 | {baseline['annualized_return']:.2%} | {baseline['max_drawdown']:.2%} | {baseline['sharpe']:.3f} | {baseline['calmar']:.3f} | {baseline['total_return']:.2%} | {baseline['execution_cost']:.2f} |
| 分级恢复状态机 | {recovery['annualized_return']:.2%} | {recovery['max_drawdown']:.2%} | {recovery['sharpe']:.3f} | {recovery['calmar']:.3f} | {recovery['total_return']:.2%} | {recovery['execution_cost']:.2f} |

## 晋级门槛

{checks}

最终结论：{'允许继续生产前验收' if gate['passed'] else '终止该策略，转向下一策略'}。

风险状态迁移次数：{len(transitions)}。
"""


def _metric_summary(computation: Any) -> dict[str, float]:
    metrics = computation.metrics
    annualized = float(metrics["annualized_return"])
    drawdown = float(metrics["max_drawdown"])
    return {
        "annualized_return": annualized,
        "max_drawdown": drawdown,
        "sharpe": float(metrics["sharpe"]),
        "calmar": annualized / abs(drawdown) if drawdown < 0 else 0.0,
        "total_return": float(metrics["cumulative_return"]),
        "execution_cost": float(metrics["total_execution_cost"]),
    }


def _next_exposure(current: float) -> float:
    return next((step for step in RECOVERY_STEPS if step > current), 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true", help="显式允许相同数据口径重新计算")
    args = parser.parse_args()
    result = run_study(get_runtime_paths(), args.as_of_date, force=args.force)
    print(result["report_path"])
    print(result["gate"])


if __name__ == "__main__":
    main()
