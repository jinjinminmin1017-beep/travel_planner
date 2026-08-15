from __future__ import annotations

import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.processes import HIDDEN_CONSOLE_FLAGS
from taskdock.gitops import PatchRegistry, StateStore, _run_git, safe_remove_worktree
from taskdock.runner import TaskRunner, _codex_command, _failure_detail, _start_codex_process


class CodexCommandTests(unittest.TestCase):
    @mock.patch("taskdock.runner.shutil.which")
    def test_approval_policy_precedes_exec_subcommand_for_cmd_launcher(self, which: mock.Mock) -> None:
        which.side_effect = lambda name: r"C:\tools\codex.cmd" if name == "codex.cmd" else None

        command = _codex_command(Path(r"C:\repo\worktree"))

        self.assertEqual([r"C:\tools\codex.cmd", "-a", "never", "exec"], command[:4])
        self.assertEqual("--ignore-user-config", command[4])
        self.assertNotIn("-a", command[command.index("exec") + 1 :])
        self.assertEqual("-", command[-1])

    @mock.patch("taskdock.runner.shutil.which")
    def test_approval_policy_precedes_exec_subcommand_for_powershell_launcher(self, which: mock.Mock) -> None:
        which.side_effect = lambda name: r"C:\tools\codex.ps1" if name == "codex.ps1" else None

        command = _codex_command(Path(r"C:\repo\worktree"))

        script_index = command.index(r"C:\tools\codex.ps1")
        self.assertEqual(["-a", "never", "exec"], command[script_index + 1 : script_index + 4])
        self.assertEqual("--ignore-user-config", command[script_index + 4])

    def test_failure_detail_surfaces_cli_argument_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "run.jsonl"
            log_path.write_text(
                "error: unexpected argument '-a' found\n\nUsage: codex exec [OPTIONS] [PROMPT]\n",
                encoding="utf-8",
            )

            self.assertEqual("error: unexpected argument '-a' found", _failure_detail(log_path))

    def test_failure_detail_surfaces_invalid_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "run.jsonl"
            log_path.write_text(
                "Error loading config.toml: unknown variant `default`, expected `fast` or `flex`\n",
                encoding="utf-8",
            )

            self.assertIn("unknown variant", _failure_detail(log_path) or "")

    @mock.patch("taskdock.runner.subprocess.Popen")
    def test_background_codex_process_receives_prompt_through_stdin(self, popen: mock.Mock) -> None:
        worktree = Path(r"C:\repo\worktree")
        process = popen.return_value

        _start_codex_process(["codex.cmd", "exec", "-"], worktree, "完整任务正文")

        self.assertEqual(subprocess.PIPE, popen.call_args.kwargs["stdin"])
        self.assertEqual(subprocess.PIPE, popen.call_args.kwargs["stdout"])
        self.assertEqual(HIDDEN_CONSOLE_FLAGS, popen.call_args.kwargs["creationflags"])
        process.stdin.write.assert_called_once_with("完整任务正文")
        process.stdin.close.assert_called_once_with()


class InterruptedRunRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.name", "Task Dock Test")
        self._git("config", "user.email", "task-dock-test@example.invalid")
        (self.repo / "sample.txt").write_text("base\n", encoding="utf-8")
        self._git("add", "sample.txt")
        self._git("commit", "-m", "base")
        self.state_dir = self.root / "state"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

    def _interrupted_state(self, *, with_change: bool) -> tuple[StateStore, PatchRegistry, Path]:
        run_key = "DEV-RECOVER-1"
        worktree_root = self.state_dir / "worktrees"
        worktree = worktree_root / run_key
        worktree_root.mkdir(parents=True)
        base_commit = self._git("rev-parse", "HEAD").strip()
        _run_git(self.repo, ["worktree", "add", "--detach", str(worktree), base_commit])
        if with_change:
            (worktree / "sample.txt").write_text("base\nrecovered task\n", encoding="utf-8")
        log_path = self.state_dir / "logs" / f"{run_key}.jsonl"
        log_path.parent.mkdir(parents=True)
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "任务已经完成。"}},
            {"type": "turn.completed"},
        ]
        log_path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8")
        result_path = self.state_dir / "results" / f"{run_key}.json"
        store = StateStore(self.state_dir / "state.json")
        store.update(
            "DEV-RECOVER",
            status="running",
            run_key=run_key,
            base_commit=base_commit,
            worktree_path=str(worktree),
            log_path=str(log_path),
            result_path=str(result_path),
        )
        return store, PatchRegistry(self.repo, self.state_dir, store), worktree

    def test_completed_child_result_is_recovered_and_applied(self) -> None:
        store, registry, worktree = self._interrupted_state(with_change=True)

        TaskRunner(self.repo, self.state_dir, store, registry)

        state = store.get("DEV-RECOVER")
        self.assertIsNotNone(state)
        self.assertEqual("complete", state.status)
        self.assertEqual("任务已经完成。", state.result_summary)
        self.assertFalse(worktree.exists())
        self.assertEqual("base\nrecovered task\n", (self.repo / "sample.txt").read_text(encoding="utf-8"))
        receipt = json.loads(Path(state.result_path).read_text(encoding="utf-8"))
        self.assertEqual("complete", receipt["status"])

    def test_completed_child_without_code_becomes_retryable_failure(self) -> None:
        store, registry, worktree = self._interrupted_state(with_change=False)
        try:
            TaskRunner(self.repo, self.state_dir, store, registry)

            state = store.get("DEV-RECOVER")
            self.assertIsNotNone(state)
            self.assertEqual("failed", state.status)
            self.assertIsNone(state.patch_path)
            self.assertIn("没有生成代码改动", state.last_error or "")
            self.assertEqual("drift", registry.actual_state("DEV-RECOVER", "pending", None)[0])
        finally:
            if worktree.exists():
                safe_remove_worktree(self.repo, worktree, self.state_dir / "worktrees")


if __name__ == "__main__":
    unittest.main()
