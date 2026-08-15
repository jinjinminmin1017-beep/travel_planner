from __future__ import annotations

import threading
from collections import deque
from typing import Any

from .gitops import GitOperationError, PatchRegistry
from .runner import TaskRunner
from .scanner import IncrementalTaskScanner


class TaskBatchController:
    """Runs every pending task sequentially while keeping task patches isolated."""

    def __init__(
        self,
        scanner: IncrementalTaskScanner,
        registry: PatchRegistry,
        runner: TaskRunner,
    ):
        self.scanner = scanner
        self.registry = registry
        self.runner = runner
        self._lock = threading.RLock()
        self._queued_ids: deque[str] = deque()
        self._active = False
        self._cancelling = False
        self._total = 0
        self._completed = 0
        self._failed = 0
        self._skipped = 0
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start_all(self) -> int:
        with self._lock:
            if self._active:
                raise GitOperationError("全部任务开发队列已经在运行。")

        pending_ids: list[str] = []
        active_task_id = self.runner.active_task_id
        for task in self.scanner.tasks():
            actual_state, _ = self.registry.actual_state(task.id, task.document_state, task.commit)
            if actual_state == "pending" and task.id != active_task_id:
                pending_ids.append(task.id)
        if not pending_ids:
            raise GitOperationError("当前没有可开发的待办任务。")

        with self._lock:
            # Recheck under the lock so simultaneous API requests cannot create
            # two queue workers from the same pending snapshot.
            if self._active:
                raise GitOperationError("全部任务开发队列已经在运行。")
            self._queued_ids = deque(pending_ids)
            self._active = True
            self._cancelling = False
            self._total = len(pending_ids)
            self._completed = 0
            self._failed = 0
            self._skipped = 0
            self._thread = threading.Thread(target=self._run, name="task-batch-queue", daemon=True)
            self._thread.start()
        return len(pending_ids)

    def cancel(self) -> int:
        with self._lock:
            if not self._active:
                raise GitOperationError("当前没有正在运行的全部任务队列。")
            cancelled = len(self._queued_ids)
            self._queued_ids.clear()
            self._cancelling = True
            return cancelled

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "cancelling": self._cancelling,
                "queued": len(self._queued_ids),
                "queued_task_ids": list(self._queued_ids),
                "total": self._total,
                "completed": self._completed,
                "failed": self._failed,
                "skipped": self._skipped,
            }

    def _run(self) -> None:
        try:
            while True:
                with self._lock:
                    if self._cancelling or not self._queued_ids:
                        return
                if not self.runner.wait_until_idle(timeout=0.5):
                    continue

                with self._lock:
                    if self._cancelling or not self._queued_ids:
                        return
                    task_id = self._queued_ids.popleft()

                try:
                    self.scanner.tick()
                    task = self.scanner.task_by_id(task_id)
                    if not task:
                        self._increment("_skipped")
                        continue
                    actual_state, _ = self.registry.actual_state(task.id, task.document_state, task.commit)
                    if actual_state != "pending":
                        self._increment("_skipped")
                        continue
                    self.runner.start(task)
                    self.runner.wait_until_idle()
                    finished_state, _ = self.registry.actual_state(task.id, task.document_state, task.commit)
                    self._increment("_completed" if finished_state == "complete" else "_failed")
                except (GitOperationError, OSError, ValueError):
                    self._increment("_failed")
        finally:
            with self._lock:
                self._queued_ids.clear()
                self._active = False
                self._cancelling = False

    def _increment(self, field: str) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)
