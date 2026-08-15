from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.gitops import PatchRegistry, StateStore
from taskdock.runner import TaskRunner
from taskdock.scanner import IncrementalTaskScanner
from taskdock.processes import HIDDEN_CONSOLE_FLAGS
from taskdock.server import TaskDockApplication, create_server, open_source_in_editor, serve_in_thread


class LocalServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.dev = self.repo / "docs" / "Dev"
        self.web = self.root / "web"
        self.dev.mkdir(parents=True)
        self.web.mkdir()
        (self.web / "index.html").write_text("<!doctype html><title>Task Dock</title>", encoding="utf-8")
        (self.dev / "task_api.md").write_text("## DEV-20260814-5 API 任务\n\n状态：待开发\n", encoding="utf-8")
        self._git("init")
        self._git("config", "user.name", "Task Dock Test")
        self._git("config", "user.email", "task-dock-test@example.invalid")
        self._git("add", ".")
        self._git("commit", "-m", "base")
        state_dir = self.root / "state"
        scanner = IncrementalTaskScanner(self.dev)
        scanner.tick(force=True)
        store = StateStore(state_dir / "state.json")
        registry = PatchRegistry(self.repo, state_dir, store)
        runner = TaskRunner(self.repo, state_dir, store, registry)
        self.opened_sources: list[tuple[Path, int]] = []
        app = TaskDockApplication(
            self.repo,
            self.web,
            scanner,
            store,
            registry,
            runner,
            source_launcher=lambda path, line: self.opened_sources.append((path, line)),
        )
        self.app = app
        self.task = scanner.tasks()[0]
        self.token = app.session_token
        self.server = create_server(app)
        serve_in_thread(self.server)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> None:
        import subprocess

        result = subprocess.run(["git", *arguments], cwd=self.repo, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_health_and_static_are_public_but_api_requires_session_token(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/health") as response:
            self.assertEqual({"ok": True}, json.load(response))
        with urllib.request.urlopen(f"{self.base_url}/") as response:
            self.assertIn(b"Task Dock", response.read())
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f"{self.base_url}/api/state")
        self.assertEqual(403, denied.exception.code)

        request = urllib.request.Request(
            f"{self.base_url}/api/state",
            headers={"X-Task-Dock-Token": self.token},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        self.assertEqual("repo", payload["project"])
        self.assertEqual(1, len(payload["tasks"]))
        self.assertEqual("pending", payload["tasks"][0]["status"])

    def test_open_source_uses_scanned_path_and_heading_line(self) -> None:
        task_id = urllib.parse.quote(self.task.id, safe="")
        request = urllib.request.Request(
            f"{self.base_url}/api/tasks/{task_id}/open-source",
            method="POST",
            headers={"X-Task-Dock-Token": self.token},
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(202, response.status)
            self.assertEqual({"ok": True}, json.load(response))

        self.assertEqual([(Path(self.task.source_path).resolve(), self.task.start_line)], self.opened_sources)

    def test_batch_endpoints_report_queued_and_cancelled_counts(self) -> None:
        with mock.patch.object(self.app.batch, "start_all", return_value=4):
            request = urllib.request.Request(
                f"{self.base_url}/api/batch/run-all",
                method="POST",
                headers={"X-Task-Dock-Token": self.token},
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual({"ok": True, "queued": 4}, json.load(response))

        with mock.patch.object(self.app.batch, "cancel", return_value=3):
            request = urllib.request.Request(
                f"{self.base_url}/api/batch/cancel",
                method="POST",
                headers={"X-Task-Dock-Token": self.token},
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual({"ok": True, "cancelled": 3}, json.load(response))


class WebAssetContractTests(unittest.TestCase):
    def test_task_status_filter_exposes_all_supported_states(self) -> None:
        web_root = Path(__file__).resolve().parents[1] / "web"
        html = (web_root / "index.html").read_text(encoding="utf-8")
        javascript = (web_root / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="status-filter"', html)
        for status in ("all", "pending", "running", "complete", "drift"):
            self.assertIn(f'value="{status}"', html)
        self.assertIn('ui.statusFilter.addEventListener("change"', javascript)
        self.assertIn('task.status === statusFilter', javascript)
        self.assertIn('task.display_id || task.id', javascript)
        self.assertIn('id="task-list-heading">全部任务</h2>', html)
        self.assertIn('? tasks\n    : tasks.filter', javascript)
        self.assertNotIn('tasks.filter((task) => task.id !== selected?.id)', javascript)
        self.assertIn('selectButton.setAttribute("aria-pressed", String(isSelected))', javascript)

    def test_task_detail_can_open_its_source(self) -> None:
        web_root = Path(__file__).resolve().parents[1] / "web"
        html = (web_root / "index.html").read_text(encoding="utf-8")
        javascript = (web_root / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="source-action"', html)
        self.assertIn("跳转到任务原文", html)
        self.assertIn('/open-source`, { method: "POST" }', javascript)
        self.assertIn('ui.sourceAction.addEventListener("click"', javascript)

    def test_batch_action_exposes_start_and_safe_cancel_states(self) -> None:
        web_root = Path(__file__).resolve().parents[1] / "web"
        html = (web_root / "index.html").read_text(encoding="utf-8")
        javascript = (web_root / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="batch-action"', html)
        self.assertIn("一键开发全部", html)
        self.assertIn('mutate("/api/batch/run-all"', javascript)
        self.assertIn('mutate("/api/batch/cancel"', javascript)
        self.assertIn("当前正在开发的任务不会被强制终止", javascript)


class SourceLauncherTests(unittest.TestCase):
    @mock.patch("taskdock.server.subprocess.run")
    @mock.patch("taskdock.server.shutil.which", return_value=r"E:\vscode\bin\code.cmd")
    def test_vscode_launcher_targets_exact_line_without_console(self, _which: mock.Mock, run: mock.Mock) -> None:
        source_path = Path(r"C:\repo\docs\Dev\task_user.md")
        run.return_value = subprocess.CompletedProcess([], 0, "", "")

        open_source_in_editor(source_path, 27)

        command = run.call_args.args[0]
        self.assertIn("--reuse-window", command)
        self.assertIn(f"{source_path}:27", command)
        self.assertTrue(run.call_args.kwargs["shell"])
        self.assertEqual(HIDDEN_CONSOLE_FLAGS, run.call_args.kwargs["creationflags"])
        self.assertEqual(source_path.parent, run.call_args.kwargs["cwd"])

    @mock.patch("taskdock.server.subprocess.run")
    @mock.patch("taskdock.server.shutil.which", return_value=r"E:\vscode\bin\code.cmd")
    def test_vscode_launcher_reports_rejected_jump(self, _which: mock.Mock, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, "", "invalid target")

        with self.assertRaisesRegex(RuntimeError, "invalid target"):
            open_source_in_editor(Path(r"C:\repo\docs\Dev\task_user.md"), 27)


if __name__ == "__main__":
    unittest.main()
