"""研究尝试的统一身份、去重门禁和结果登记。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


class ResearchAlreadyRunningError(RuntimeError):
    """相同数据和口径的研究正在运行。"""


@dataclass(frozen=True)
class ResearchSpec:
    """描述一个可复现研究，不把展示名称计入计算指纹。"""

    experiment_id: str
    name: str
    category: str
    hypothesis: str
    definition: dict[str, Any]
    lifecycle_status: str = "active"
    owner: str = "Codex"


@dataclass(frozen=True)
class ResearchAttempt:
    """一次研究运行许可，或一次命中历史结果的复用决定。"""

    paths: RuntimePaths
    spec: ResearchSpec
    run_id: str
    run_date: str
    data_as_of: str
    data_version: str
    definition_fingerprint: str
    run_fingerprint: str
    output_dir: Path
    should_run: bool
    reused_run: dict[str, Any] | None = None

    def cached_result(self) -> dict[str, Any]:
        """返回历史结构化结果，并明确标记本次没有重新计算。"""
        if self.reused_run is None:
            raise ValueError("research attempt does not contain a reusable result")
        return {
            **dict(self.reused_run.get("metrics") or {}),
            "reused": True,
            "reused_from_run_id": str(self.reused_run["run_id"]),
            "run_fingerprint": self.run_fingerprint,
        }


def research_fingerprint(payload: Mapping[str, Any]) -> str:
    """对研究定义生成与字典顺序无关的稳定 SHA-256 指纹。"""
    canonical = json.dumps(
        _normalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_run_fingerprint(
    definition_fingerprint: str,
    data_as_of: str,
    data_version: str = "",
) -> str:
    """运行指纹额外绑定数据截止日和可选数据版本。"""
    return research_fingerprint(
        {
            "definition_fingerprint": definition_fingerprint,
            "data_as_of": _normalize_date(data_as_of),
            "data_version": data_version.strip(),
        }
    )


def begin_research_attempt(
    spec: ResearchSpec,
    *,
    paths: RuntimePaths | None = None,
    data_as_of: str,
    data_version: str = "",
    force: bool = False,
) -> ResearchAttempt:
    """在重计算前申请运行许可；完全相同的成功结果默认直接复用。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    normalized_as_of = _normalize_date(data_as_of)
    definition_fingerprint = research_fingerprint(spec.definition)
    run_fingerprint = build_run_fingerprint(
        definition_fingerprint,
        normalized_as_of,
        data_version,
    )
    repository = SystemRepository(runtime_paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": spec.experiment_id,
            "name": spec.name,
            "category": spec.category,
            "status": spec.lifecycle_status,
            "owner": spec.owner,
            "description": spec.hypothesis,
            "hypothesis": spec.hypothesis,
            "definition_fingerprint": definition_fingerprint,
            "config": {"definition": spec.definition},
        }
    )
    running = repository.find_running_experiment(run_fingerprint)
    if running is not None:
        raise ResearchAlreadyRunningError(
            f"相同研究正在运行: {running['run_id']}"
        )
    reusable = None if force else repository.find_reusable_experiment_run(run_fingerprint)
    if reusable is not None:
        reused = repository.mark_experiment_run_reused(
            str(reusable["run_id"]),
            requested_experiment_id=spec.experiment_id,
        )
        _record_cross_experiment_reuse(repository, spec, reused)
        return _build_attempt(
            runtime_paths,
            spec,
            normalized_as_of,
            data_version,
            definition_fingerprint,
            run_fingerprint,
            should_run=False,
            reused_run=reused,
        )

    attempt = _build_attempt(
        runtime_paths,
        spec,
        normalized_as_of,
        data_version,
        definition_fingerprint,
        run_fingerprint,
        should_run=True,
    )
    try:
        repository.record_experiment_run(
            experiment_id=spec.experiment_id,
            run_id=attempt.run_id,
            run_date=attempt.run_date,
            status="RUNNING",
            output_dir=attempt.output_dir,
            config=_attempt_config(attempt),
            definition_fingerprint=definition_fingerprint,
            run_fingerprint=run_fingerprint,
            data_as_of=normalized_as_of,
            data_version=data_version,
        )
    except sqlite3.IntegrityError as error:
        running = repository.find_running_experiment(run_fingerprint)
        running_id = str(running["run_id"]) if running else "unknown"
        raise ResearchAlreadyRunningError(f"相同研究正在运行: {running_id}") from error
    attempt.output_dir.mkdir(parents=True, exist_ok=True)
    return attempt


def complete_research_attempt(
    attempt: ResearchAttempt,
    *,
    metrics: dict[str, Any],
    outcome: str,
    decision_reason: str,
    artifacts: list[ExperimentArtifact] | None = None,
) -> dict[str, Any]:
    """完成研究，统一落盘配置、指标、结论和外部报告索引。"""
    if not attempt.should_run:
        raise ValueError("reused research attempt cannot be completed again")
    normalized_metrics = _normalize(metrics)
    config_path = attempt.output_dir / "research_identity.json"
    metrics_path = attempt.output_dir / "research_result.json"
    config_path.write_text(
        json.dumps(_attempt_config(attempt), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps(normalized_metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    all_artifacts = [
        ExperimentArtifact("research_identity", config_path, "研究身份"),
        ExperimentArtifact("research_result", metrics_path, "研究结论"),
        *(artifacts or []),
    ]
    missing = [str(item.path) for item in all_artifacts if not item.path.exists()]
    if missing:
        raise FileNotFoundError(f"research artifacts missing: {missing}")

    repository = SystemRepository(attempt.paths.system_state_path)
    run = repository.record_experiment_run(
        experiment_id=attempt.spec.experiment_id,
        run_id=attempt.run_id,
        run_date=attempt.run_date,
        status="SUCCESS",
        output_dir=attempt.output_dir,
        config=_attempt_config(attempt),
        metrics=normalized_metrics,
        message=decision_reason,
        definition_fingerprint=attempt.definition_fingerprint,
        run_fingerprint=attempt.run_fingerprint,
        data_as_of=attempt.data_as_of,
        data_version=attempt.data_version,
        outcome=outcome.upper(),
        decision_reason=decision_reason,
    )
    for artifact in all_artifacts:
        repository.record_experiment_artifact(
            attempt.run_id,
            artifact.artifact_type,
            artifact.path,
            artifact.title,
        )
    return {
        "experiment_id": attempt.spec.experiment_id,
        "run_id": attempt.run_id,
        "run_date": attempt.run_date,
        "status": run["status"],
        "outcome": run["outcome"],
        "output_dir": str(attempt.output_dir),
        "run_fingerprint": attempt.run_fingerprint,
        "reused": False,
    }


def fail_research_attempt(attempt: ResearchAttempt, error: BaseException) -> None:
    """记录失败以便排障；失败运行不会阻止下一次重试。"""
    if not attempt.should_run:
        return
    repository = SystemRepository(attempt.paths.system_state_path)
    repository.record_experiment_run(
        experiment_id=attempt.spec.experiment_id,
        run_id=attempt.run_id,
        run_date=attempt.run_date,
        status="FAILED",
        output_dir=attempt.output_dir,
        config=_attempt_config(attempt),
        message=f"{type(error).__name__}: {error}",
        definition_fingerprint=attempt.definition_fingerprint,
        run_fingerprint=attempt.run_fingerprint,
        data_as_of=attempt.data_as_of,
        data_version=attempt.data_version,
        outcome="FAILED",
        decision_reason=str(error),
    )


def _build_attempt(
    paths: RuntimePaths,
    spec: ResearchSpec,
    data_as_of: str,
    data_version: str,
    definition_fingerprint: str,
    run_fingerprint: str,
    *,
    should_run: bool,
    reused_run: dict[str, Any] | None = None,
) -> ResearchAttempt:
    now = datetime.now()
    run_date = now.strftime("%Y%m%d")
    suffix = now.strftime("%H%M%S%f")
    run_id = f"{spec.experiment_id}:{run_date}:{suffix}"
    output_dir = paths.runs_dir / "experiments" / spec.experiment_id / f"{run_date}-{suffix}"
    return ResearchAttempt(
        paths=paths,
        spec=spec,
        run_id=run_id,
        run_date=run_date,
        data_as_of=data_as_of,
        data_version=data_version,
        definition_fingerprint=definition_fingerprint,
        run_fingerprint=run_fingerprint,
        output_dir=output_dir,
        should_run=should_run,
        reused_run=reused_run,
    )


def _record_cross_experiment_reuse(
    repository: SystemRepository,
    spec: ResearchSpec,
    source: dict[str, Any],
) -> None:
    """新实验名称命中旧计算时留下别名运行，避免研究页出现空记录。"""
    if str(source["experiment_id"]) == spec.experiment_id:
        return
    alias_id = f"{spec.experiment_id}:reused:{source['run_id']}"
    repository.record_experiment_run(
        experiment_id=spec.experiment_id,
        run_id=alias_id,
        run_date=datetime.now().strftime("%Y%m%d"),
        status="REUSED",
        output_dir=str(source["output_dir"]),
        config=dict(source.get("config") or {}),
        metrics=dict(source.get("metrics") or {}),
        message=f"复用 {source['experiment_id']} 的相同计算结果",
        definition_fingerprint=str(source.get("definition_fingerprint") or ""),
        run_fingerprint=str(source.get("run_fingerprint") or ""),
        data_as_of=str(source.get("data_as_of") or ""),
        data_version=str(source.get("data_version") or ""),
        outcome=str(source.get("outcome") or ""),
        decision_reason=str(source.get("decision_reason") or ""),
        reused_from_run_id=str(source["run_id"]),
    )


def _attempt_config(attempt: ResearchAttempt) -> dict[str, Any]:
    return {
        "hypothesis": attempt.spec.hypothesis,
        "definition": _normalize(attempt.spec.definition),
        "data_as_of": attempt.data_as_of,
        "data_version": attempt.data_version,
        "definition_fingerprint": attempt.definition_fingerprint,
        "run_fingerprint": attempt.run_fingerprint,
    }


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("data_as_of must be YYYYMMDD or YYYY-MM-DD")
    return normalized


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("research payload cannot contain NaN or Infinity")
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted((_normalize(item) for item in value), key=str)
    item_method = getattr(value, "item", None)
    if callable(item_method):
        return _normalize(item_method())
    raise TypeError(f"unsupported research payload type: {type(value).__name__}")
