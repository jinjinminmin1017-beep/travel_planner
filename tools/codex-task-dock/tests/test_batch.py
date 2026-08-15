from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.batch import TaskBatchController
from taskdock.scanner import TaskRecord


def task(task_id: str) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        display_id=task_id,
        title=task_id,
        description="test task",
        source_path=str(Path("docs/Dev/task_test.md").resolve()),
        source_name="task_test.md",
        start_line=1,
        end_line=2,
        source_kind="section",
        document_state="pending",
        commit=None,
        source_signature="signature",
        updated_at_ns=1,
    )


class FakeScanner:
    def __init__(self, tasks: list[TaskRecord]):
        self._tasks = tasks

    def tasks(self) -> list[TaskRecord]:
        return list(self._tasks)

    def task_by_id(self, task_id: str) -> TaskRecord | None:
        return next((item for item in self._tasks if item.id == task_id), None)

    def tick(self) -> list[TaskRecord]:
        return self.tasks()


class FakeRegistry:
    def __init__(self, states: dict[str, str]):
        self.states = states

    def actual_state(self, task_id: str, _document_state: str, _commit: str | None) -> tuple[str, str]:
        return self.states[task_id], self.states[task_id]


class ImmediateRunner:
    def __init__(self, registry: FakeRegistry):
        self.registry = registry
        self.active_task_id: str | None = None
        self.started: list[str] = []

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return True

    def start(self, item: TaskRecord) -> None:
        self.active_task_id = item.id
        self.started.append(item.id)
        self.registry.states[item.id] = "complete"
        self.active_task_id = None


class BlockingRunner(ImmediateRunner):
    def __init__(self, registry: FakeRegistry):
        super().__init__(registry)
        self.idle = threading.Event()
        self.idle.set()
        self.started_event = threading.Event()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self.idle.wait(timeout)

    def start(self, item: TaskRecord) -> None:
        self.active_task_id = item.id
        self.started.append(item.id)
        self.idle.clear()
        self.started_event.set()

    def finish(self) -> None:
        assert self.active_task_id
        self.registry.states[self.active_task_id] = "complete"
        self.active_task_id = None
        self.idle.set()


class TaskBatchControllerTests(unittest.TestCase):
    def test_runs_only_pending_tasks_in_scanner_order(self) -> None:
        tasks = [task("A"), task("B"), task("C")]
        registry = FakeRegistry({"A": "pending", "B": "drift", "C": "pending"})
        runner = ImmediateRunner(registry)
        controller = TaskBatchController(FakeScanner(tasks), registry, runner)

        self.assertEqual(2, controller.start_all())
        self._wait_for_finish(controller)

        self.assertEqual(["A", "C"], runner.started)
        self.assertEqual(2, controller.snapshot()["completed"])
        self.assertEqual(0, controller.snapshot()["failed"])

    def test_cancel_keeps_current_task_and_clears_remaining_queue(self) -> None:
        tasks = [task("A"), task("B"), task("C")]
        registry = FakeRegistry({item.id: "pending" for item in tasks})
        runner = BlockingRunner(registry)
        controller = TaskBatchController(FakeScanner(tasks), registry, runner)

        controller.start_all()
        self.assertTrue(runner.started_event.wait(1))
        self.assertEqual(2, controller.cancel())
        runner.finish()
        self._wait_for_finish(controller)

        self.assertEqual(["A"], runner.started)
        self.assertEqual(1, controller.snapshot()["completed"])
        self.assertFalse(controller.snapshot()["active"])

    def _wait_for_finish(self, controller: TaskBatchController) -> None:
        deadline = time.monotonic() + 2
        while controller.snapshot()["active"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(controller.snapshot()["active"])


if __name__ == "__main__":
    unittest.main()
