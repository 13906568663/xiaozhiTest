"""进程内后台任务表。

ask_assistant 超时降级与 submit_task 显式异步都会把一个正在运行的
asyncio.Task 登记进 TaskBoard，语音端稍后通过 query_task 用编号（或
"最近一个"）取回结果。

设计取舍：
  - 任务只存进程内存不落库：语音场景任务生命周期是分钟级，服务重启
    丢任务可接受，换来零表结构成本；
  - 编号用进程内自增整数（1、2、3……），语音播报和用户复述都比 UUID 友好；
  - 有界缓存：已完成记录超上限后按完成时间先进先出淘汰，运行中的永不淘汰。
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger("app.xiaozhi_mcp.tasks")

TaskStatus = Literal["running", "done", "failed"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TaskRecord:
    """一条后台任务的可播报状态。"""

    task_id: int
    kind: str
    description: str
    status: TaskStatus = "running"
    result: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None


class TaskBoard:
    """后台任务登记与查询（进程内单例，由 connector 持有）。"""

    def __init__(self, max_finished: int = 50) -> None:
        self._max_finished = max_finished
        self._counter = itertools.count(1)
        self._records: dict[int, TaskRecord] = {}
        self._tasks: dict[int, asyncio.Task[str]] = {}

    # ------------------------------------------------------------------
    # 登记
    # ------------------------------------------------------------------

    def submit(
        self,
        coro: Coroutine[Any, Any, str],
        *,
        description: str,
        kind: str = "任务",
    ) -> TaskRecord:
        """启动一个新协程并登记为后台任务。"""
        return self.adopt(asyncio.create_task(coro), description=description, kind=kind)

    def adopt(
        self,
        task: asyncio.Task[str],
        *,
        description: str,
        kind: str = "任务",
    ) -> TaskRecord:
        """收编一个已在运行的 Task（ask_assistant 超时降级路径）。"""
        record = TaskRecord(
            task_id=next(self._counter),
            kind=kind,
            description=description,
        )
        self._records[record.task_id] = record
        self._tasks[record.task_id] = task
        task.add_done_callback(
            lambda t, task_id=record.task_id: self._on_done(task_id, t)
        )
        return record

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, task_id: int) -> TaskRecord | None:
        return self._records.get(task_id)

    def latest(self) -> TaskRecord | None:
        """最近创建的一条任务（query_task 不带编号时的默认目标）。"""
        if not self._records:
            return None
        return self._records[max(self._records)]

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """取消所有运行中的任务（进程优雅退出时由 connector 调用）。"""
        pending = list(self._tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_done(self, task_id: int, task: asyncio.Task[str]) -> None:
        record = self._records.get(task_id)
        self._tasks.pop(task_id, None)
        if record is None:
            return
        record.finished_at = _utcnow()
        if task.cancelled():
            record.status = "failed"
            record.error = "任务被取消"
        elif (exc := task.exception()) is not None:
            record.status = "failed"
            record.error = str(exc) or type(exc).__name__
            logger.warning("小智后台任务 %s 失败：%s", task_id, record.error)
        else:
            record.status = "done"
            record.result = task.result()
        self._trim()

    def _trim(self) -> None:
        finished = [r for r in self._records.values() if r.status != "running"]
        overflow = len(finished) - self._max_finished
        if overflow <= 0:
            return
        finished.sort(key=lambda r: r.finished_at or r.created_at)
        for stale in finished[:overflow]:
            self._records.pop(stale.task_id, None)
