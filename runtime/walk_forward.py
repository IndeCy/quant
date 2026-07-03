"""Walk-Forward 验证基础设施。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


METRIC_COLUMNS = [
    "annual_return",
    "max_drawdown",
    "sharpe",
    "calmar",
    "average_exposure",
]


@dataclass(frozen=True)
class WalkForwardWindow:
    """一次 Walk-Forward 的训练和验证窗口定义。"""

    window_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str


def select_best_parameter(train_frame: pd.DataFrame) -> pd.Series:
    """按固定四级排序规则选择训练集最优参数。"""
    _require_columns(
        train_frame,
        ["parameter_id", "sharpe", "calmar", "max_drawdown", "average_exposure"],
    )
    if train_frame.empty:
        raise ValueError("train_frame is empty")
    ranked = train_frame.copy()
    # 最大回撤通常为负数，越接近 0 风险越小，因此按降序排列。
    ranked = ranked.sort_values(
        ["sharpe", "calmar", "max_drawdown", "average_exposure"],
        ascending=[False, False, False, False],
        kind="stable",
    ).reset_index(drop=True)
    return ranked.iloc[0]


def run_walk_forward_validation(
    metric_frame: pd.DataFrame,
    windows: list[WalkForwardWindow],
) -> dict[str, pd.DataFrame]:
    """基于预先计算的参数指标执行 Walk-Forward 验证。"""
    _require_columns(metric_frame, ["window", "sample", "parameter_id", *METRIC_COLUMNS])
    selected_rows: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    for window in windows:
        train = metric_frame[
            metric_frame["window"].eq(window.window_id) & metric_frame["sample"].eq("train")
        ].copy()
        best = select_best_parameter(train)
        parameter_id = str(best["parameter_id"])
        selected_rows.append({"window": window.window_id, "parameter_id": parameter_id})
        output_rows.append(_build_output_row(window, "train", best))

        validation = metric_frame[
            metric_frame["window"].eq(window.window_id)
            & metric_frame["sample"].eq("validation")
            & metric_frame["parameter_id"].eq(parameter_id)
        ]
        if validation.empty:
            raise ValueError(f"validation row missing: window={window.window_id}, parameter={parameter_id}")
        output_rows.append(_build_output_row(window, "validation", validation.iloc[0]))

    walk_forward = pd.DataFrame(output_rows)
    selected_parameters = pd.DataFrame(selected_rows)
    return {"selected_parameters": selected_parameters, "walk_forward": walk_forward}


def run_walk_forward_experiment(
    metric_frame: pd.DataFrame,
    windows: list[WalkForwardWindow],
    paths: RuntimePaths | None = None,
    experiment_id: str = "quality_walk_forward_research",
    name: str = "Quality Walk Forward Research",
    run_date: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    """运行 Walk-Forward 验证并登记为实验产物。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = run_date or datetime.now().strftime("%Y%m%d")
    timestamp = datetime.now().strftime("%H%M%S")
    output_dir = runtime_paths.runs_dir / "experiments" / experiment_id / f"{target_date}-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_walk_forward_validation(metric_frame, windows)
    selected = result["selected_parameters"]
    walk_forward = result["walk_forward"]
    metrics = _summarize_validation(walk_forward)
    config = {"windows": [asdict(window) for window in windows], "selection_rule": _selection_rule()}

    selected_path = output_dir / "selected_parameters.csv"
    walk_forward_path = output_dir / "walk_forward.csv"
    metrics_path = output_dir / "metrics.json"
    summary_path = output_dir / "summary.md"
    selected.to_csv(selected_path, index=False, encoding="utf-8-sig")
    walk_forward.to_csv(walk_forward_path, index=False, encoding="utf-8-sig")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(
        _render_summary(name, experiment_id, target_date, config, metrics, walk_forward, message),
        encoding="utf-8",
    )

    repository = SystemRepository(runtime_paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": experiment_id,
            "name": name,
            "category": "walk_forward",
            "status": "active",
            "owner": "Codex",
            "description": message,
            "config": config,
        }
    )
    run_id = f"{experiment_id}:{target_date}:{timestamp}"
    run = repository.record_experiment_run(
        experiment_id=experiment_id,
        run_id=run_id,
        run_date=target_date,
        status="SUCCESS",
        output_dir=output_dir,
        config=config,
        metrics=metrics,
        message=message,
    )
    repository.record_experiment_artifact(run_id, "summary", summary_path, "Walk-Forward 摘要")
    repository.record_experiment_artifact(run_id, "selected_parameters", selected_path, "训练集选参")
    repository.record_experiment_artifact(run_id, "walk_forward", walk_forward_path, "训练验证结果")
    repository.record_experiment_artifact(run_id, "metrics", metrics_path, "聚合指标")
    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "run_date": target_date,
        "status": run["status"],
        "output_dir": str(output_dir),
        "summary_path": str(summary_path),
    }


def _build_output_row(window: WalkForwardWindow, sample: str, source: pd.Series) -> dict[str, Any]:
    """把指标行补齐窗口日期信息。"""
    start = window.train_start if sample == "train" else window.validation_start
    end = window.train_end if sample == "train" else window.validation_end
    row: dict[str, Any] = {
        "window": window.window_id,
        "sample": sample,
        "start_date": start,
        "end_date": end,
        "parameter_id": str(source["parameter_id"]),
    }
    for column in METRIC_COLUMNS:
        row[column] = float(source[column])
    return row


def _summarize_validation(walk_forward: pd.DataFrame) -> dict[str, Any]:
    """汇总验证集表现，作为实验列表可直接展示的核心指标。"""
    validation = walk_forward[walk_forward["sample"].eq("validation")]
    return {
        "validation_windows": int(len(validation)),
        "avg_validation_sharpe": float(validation["sharpe"].mean()) if not validation.empty else 0.0,
        "avg_validation_calmar": float(validation["calmar"].mean()) if not validation.empty else 0.0,
        "avg_validation_return": float(validation["annual_return"].mean()) if not validation.empty else 0.0,
        "worst_validation_drawdown": float(validation["max_drawdown"].min()) if not validation.empty else 0.0,
    }


def _render_summary(
    name: str,
    experiment_id: str,
    run_date: str,
    config: dict[str, Any],
    metrics: dict[str, Any],
    walk_forward: pd.DataFrame,
    message: str,
) -> str:
    """生成便于前端和人工审阅的 Markdown 摘要。"""
    display = walk_forward.copy()
    return "\n".join(
        [
            f"# {name}",
            "",
            f"- 实验ID：{experiment_id}",
            f"- 运行日期：{run_date}",
            f"- 说明：{message or '无'}",
            "",
            "## 固定选参规则",
            "",
            _selection_rule(),
            "",
            "## 验证集聚合指标",
            "",
            "```json",
            json.dumps(metrics, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Walk-Forward 明细",
            "",
            _markdown_table(display),
            "",
            "## 窗口配置",
            "",
            "```json",
            json.dumps(config["windows"], ensure_ascii=False, indent=2),
            "```",
        ]
    )


def _selection_rule() -> str:
    return "第一排序 Sharpe 最高，第二排序 Calmar 最高，第三排序最大回撤更小，第四排序平均仓位更高。"


def _markdown_table(frame: pd.DataFrame) -> str:
    """渲染轻量 Markdown 表格，避免依赖可选的 tabulate 包。"""
    if frame.empty:
        return "无数据"
    text_frame = frame.astype(str)
    headers = list(text_frame.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in text_frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    """检查输入表结构，避免隐式列名漂移。"""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
