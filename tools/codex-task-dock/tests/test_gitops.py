from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.gitops import PatchRegistry, StateStore, _run_git, apply_patch, patch_state, safe_remove_worktree
from taskdock.processes import HIDDEN_CONSOLE_FLAGS
from taskdock.runner import _snapshot_current_context


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class GitPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.name", "Task Dock Test")
        git(self.repo, "config", "user.email", "task-dock-test@example.invalid")
        (self.repo / "sample.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "sample.txt")
        git(self.repo, "commit", "-m", "base")
        self.state_dir = self.root / "state"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_patch_registry_tracks_actual_code_and_reverts(self) -> None:
        (self.repo / "sample.txt").write_text("base\ntask change\n", encoding="utf-8")
        patch = self.state_dir / "patches" / "task.patch"
        patch.parent.mkdir(parents=True)
        patch.write_bytes(subprocess.check_output(["git", "diff", "--binary"], cwd=self.repo))
        git(self.repo, "restore", "sample.txt")
        store = StateStore(self.state_dir / "state.json")
        store.update("DEV-TEST", patch_path=str(patch), status="complete")
        registry = PatchRegistry(self.repo, self.state_dir, store)

        self.assertEqual("absent", patch_state(self.repo, patch))
        apply_patch(self.repo, patch)
        self.assertEqual("complete", registry.actual_state("DEV-TEST", "pending", None)[0])
        registry.revert_task("DEV-TEST", None)
        self.assertEqual("pending", registry.actual_state("DEV-TEST", "pending", None)[0])
        self.assertEqual("base\n", (self.repo / "sample.txt").read_text(encoding="utf-8"))

    def test_context_snapshot_excludes_existing_dirty_files_from_task_diff(self) -> None:
        (self.repo / "sample.txt").write_text("base\nuser edit\n", encoding="utf-8")
        (self.repo / "notes.txt").write_text("untracked context\n", encoding="utf-8")
        head = git(self.repo, "rev-parse", "HEAD").strip()
        worktree_root = self.root / "worktrees"
        worktree = worktree_root / "task"
        worktree_root.mkdir()
        _run_git(self.repo, ["worktree", "add", "--detach", str(worktree), head])
        try:
            context_commit = _snapshot_current_context(self.repo, worktree, head)
            self.assertNotEqual(head, context_commit)
            self.assertEqual("base\nuser edit\n", (worktree / "sample.txt").read_text(encoding="utf-8"))
            self.assertEqual("untracked context\n", (worktree / "notes.txt").read_text(encoding="utf-8"))
            (worktree / "sample.txt").write_text("base\nuser edit\ntask edit\n", encoding="utf-8")
            task_diff = git(worktree, "diff", context_commit)
            self.assertIn("+task edit", task_diff)
            self.assertNotIn("+user edit", task_diff)
        finally:
            safe_remove_worktree(self.repo, worktree, worktree_root)

    def test_git_children_use_windows_no_console_flag(self) -> None:
        completed = subprocess.CompletedProcess(["git", "status"], 0, stdout="", stderr="")
        with mock.patch("taskdock.gitops.subprocess.run", return_value=completed) as run:
            _run_git(self.repo, ["status", "--short"])

        self.assertEqual(HIDDEN_CONSOLE_FLAGS, run.call_args.kwargs["creationflags"])
        if sys.platform == "win32":
            self.assertTrue(HIDDEN_CONSOLE_FLAGS & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
