"""调度、API、命令行和补跑共用的唯一 Pipeline 应用服务。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
from pathlib import Path
import subprocess
from typing import Callable, Iterator

from runtime.artifact_registry import ArtifactRegistry
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.pipeline_context import PipelineContext, TriggerType
from runtime.pipeline_run_repository import PipelineRunRepository


PipelineExecutor = Callable[..., dict[str, object]]


class PipelineAlreadyRunningError(RuntimeError):
    """同一 Pipeline 和交易日已经有进程持锁。"""


class PipelineLockManager:
    """用本地文件锁阻止调度和人工补跑并发写状态。"""

    def __init__(self, lock_dir: Path) -> None:
        self.lock_dir = lock_dir

    @contextmanager
    def acquire(self, pipeline_id: str, trade_date: str) -> Iterator[None]:
        """非阻塞获取运行锁，失败时明确报错。"""
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_dir / f"{pipeline_id}-{trade_date}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PipelineAlreadyRunningError(f"{pipeline_id} {trade_date} is already running") from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _default_executor(**kwargs: object) -> dict[str, object]:
    """延迟导入业务实现，确保其他入口只依赖本应用服务。"""
    from runtime.daily_pipeline import run_production_daily_pipeline

    return run_production_daily_pipeline(**kwargs)


def _code_version(root: Path) -> str:
    """记录 Git 提交及脏工作区标记。"""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        return f"{commit}+dirty" if dirty else commit
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _data_version(data_dir: Path) -> str:
    """用数据文件名、大小和修改时间生成轻量快照指纹。"""
    records: list[str] = []
    if data_dir.exists():
        for path in sorted(item for item in data_dir.iterdir() if item.is_file() and item.suffix != ".py"):
            stat = path.stat()
            records.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    payload = "\n".join(records) if records else "empty"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class PipelineService:
    """唯一 Pipeline 入口，统一幂等、锁、版本和运行记录。"""

    def __init__(
        self,
        paths: RuntimePaths | None = None,
        executor: PipelineExecutor | None = None,
    ) -> None:
        self.paths = paths or get_runtime_paths()
        self.paths.ensure_directories()
        self.executor = executor or _default_executor
        self.repository = PipelineRunRepository(self.paths.system_state_path)
        self.artifacts = ArtifactRegistry(self.paths.system_state_path)
        self.lock_manager = PipelineLockManager(self.paths.state_dir / "locks")

    def run(
        self,
        pipeline_id: str = "daily_trading_pipeline",
        trade_date: str | None = None,
        trigger_type: TriggerType = "MANUAL",
        *,
        push: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """执行标准日流水线；成功结果默认幂等，force 用于明确补跑。"""
        target_date = trade_date or datetime.now().strftime("%Y%m%d")
        if trigger_type not in {"SCHEDULED", "MANUAL", "API"}:
            raise ValueError(f"unsupported trigger_type: {trigger_type}")
        if pipeline_id != "daily_trading_pipeline":
            raise ValueError(f"unsupported pipeline_id: {pipeline_id}")
        with self.lock_manager.acquire(pipeline_id, target_date):
            previous = self.repository.latest_success(pipeline_id, target_date)
            if previous is not None and not force:
                return {
                    "run_id": previous["run_id"],
                    "pipeline_id": pipeline_id,
                    "trade_date": target_date,
                    "status": "SKIPPED",
                    "message": "该交易日已有成功运行，使用 force 才允许重跑",
                }
            context = PipelineContext.create(
                pipeline_id,
                target_date,
                trigger_type,
                _code_version(Path(__file__).resolve().parents[1]),
                _data_version(self.paths.data_dir),
            )
            self.repository.start(context)
            try:
                result = self.executor(
                    paths=self.paths,
                    push=push,
                    source={"SCHEDULED": "scheduler", "MANUAL": "manual", "API": "api"}[trigger_type],
                    trade_date=target_date,
                )
                status = str(result.get("status", "SUCCESS"))
                self.artifacts.register_directory(context.run_id, self.paths.runs_dir / target_date)
                self.repository.finish(context.run_id, status, str(result.get("message", "")))
                return {**result, **context.to_dict(), "status": status}
            except Exception as exc:
                self.artifacts.register_directory(context.run_id, self.paths.runs_dir / target_date)
                self.repository.finish(context.run_id, "FAILED", str(exc))
                raise
