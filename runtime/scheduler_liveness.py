"""本地调度器存活与休眠恢复辅助逻辑。"""

from __future__ import annotations

from typing import Protocol

from runtime.paths import RuntimePaths
from runtime.scheduler import write_scheduler_heartbeat


class SchedulerWakeup(Protocol):
    """调度器唤醒能力，隔离具体 APScheduler 实现。"""

    def wakeup(self) -> None:
        """通知调度线程立即重新检查到期任务。"""


def wake_scheduler_after_system_resume(
    scheduler: SchedulerWakeup,
    paths: RuntimePaths | None = None,
) -> None:
    """唤醒调度线程并更新心跳，避免 macOS 休眠后任务计时器停滞。"""
    scheduler.wakeup()
    write_scheduler_heartbeat(paths)
