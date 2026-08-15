from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .processes import HIDDEN_CONSOLE_FLAGS


class GitOperationError(RuntimeError):
    pass


def _run_git(
    repo: Path,
    arguments: list[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
        creationflags=HIDDEN_CONSOLE_FLAGS,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode("utf-8", errors="replace").strip()
        raise GitOperationError(stderr or f"git {' '.join(arguments)} 执行失败")
    return result


def repository_root(path: Path) -> Path:
    result = _run_git(path, ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def current_head(repo: Path) -> str:
    return _run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()


def current_branch(repo: Path) -> str:
    result = _run_git(repo, ["branch", "--show-current"], check=False)
    return result.stdout.strip() or "detached"


def dirty_paths(repo: Path) -> list[str]:
    output = _run_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"]).stdout
    return [line[3:] for line in output.splitlines() if len(line) >= 4]


def commit_exists(repo: Path, commit: str) -> bool:
    return _run_git(repo, ["cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode == 0


def write_commit_patch(repo: Path, commit: str, destination: Path) -> bool:
    if not commit_exists(repo, commit):
        return False
    result = _run_git(repo, ["show", "--format=", "--binary", "--find-renames", commit], text=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result.stdout)
    return bool(result.stdout.strip())


def patch_state(repo: Path, patch_path: Path) -> str:
    if not patch_path.exists() or patch_path.stat().st_size == 0:
        return "unknown"
    reverse = _run_git(repo, ["apply", "--reverse", "--check", str(patch_path)], check=False)
    if reverse.returncode == 0:
        return "present"
    forward = _run_git(repo, ["apply", "--check", str(patch_path)], check=False)
    if forward.returncode == 0:
        return "absent"
    return "drift"


def apply_patch(repo: Path, patch_path: Path) -> None:
    check = _run_git(repo, ["apply", "--check", str(patch_path)], check=False)
    if check.returncode != 0:
        raise GitOperationError(check.stderr.strip() or "任务补丁与当前代码冲突。")
    _run_git(repo, ["apply", "--whitespace=nowarn", str(patch_path)])


def revert_patch(repo: Path, patch_path: Path) -> None:
    check = _run_git(repo, ["apply", "--reverse", "--check", str(patch_path)], check=False)
    if check.returncode != 0:
        raise GitOperationError(check.stderr.strip() or "当前代码已变化，无法安全回退此任务。")
    _run_git(repo, ["apply", "--reverse", "--whitespace=nowarn", str(patch_path)])


@dataclass(slots=True)
class ManagedTaskState:
    task_id: str
    status: str = "pending"
    patch_path: str | None = None
    base_commit: str | None = None
    worktree_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None
    last_message: str | None = None
    run_key: str | None = None
    process_id: int | None = None
    log_path: str | None = None
    result_path: str | None = None
    exit_code: int | None = None
    result_summary: str | None = None


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._states: dict[str, ManagedTaskState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._states = {key: ManagedTaskState(**value) for key, value in payload.get("tasks", {}).items()}
        except (OSError, ValueError, TypeError):
            self._states = {}

    def _save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        payload = {"version": 1, "tasks": {key: asdict(value) for key, value in self._states.items()}}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def get(self, task_id: str) -> ManagedTaskState | None:
        with self._lock:
            state = self._states.get(task_id)
            return ManagedTaskState(**asdict(state)) if state else None

    def all_states(self) -> list[ManagedTaskState]:
        with self._lock:
            return [ManagedTaskState(**asdict(state)) for state in self._states.values()]

    def update(self, task_id: str, **changes: object) -> ManagedTaskState:
        with self._lock:
            state = self._states.setdefault(task_id, ManagedTaskState(task_id=task_id))
            for key, value in changes.items():
                if not hasattr(state, key):
                    raise AttributeError(key)
                setattr(state, key, value)
            self._save()
            return ManagedTaskState(**asdict(state))

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._states.pop(task_id, None)
            self._save()


class PatchRegistry:
    def __init__(self, repo: Path, state_directory: Path, store: StateStore):
        self.repo = repo
        self.state_directory = state_directory
        self.store = store
        self.patch_directory = state_directory / "patches"
        self.patch_directory.mkdir(parents=True, exist_ok=True)

    def managed_patch(self, task_id: str) -> Path | None:
        state = self.store.get(task_id)
        if not state or not state.patch_path:
            return None
        return Path(state.patch_path)

    def patch_for_commit(self, task_id: str, commit: str) -> Path | None:
        safe_commit = commit.lower()
        path = self.patch_directory / f"commit-{safe_commit}.patch"
        if path.exists() and path.stat().st_size:
            return path
        return path if write_commit_patch(self.repo, commit, path) else None

    def actual_state(self, task_id: str, document_state: str, commit: str | None) -> tuple[str, str]:
        state = self.store.get(task_id)
        if state and state.status == "running":
            return "running", state.last_message or "Codex 正在开发"
        if state and state.status == "failed":
            return "drift", state.last_error or "Codex 执行失败"

        patch_path = self.managed_patch(task_id)
        if patch_path:
            current = patch_state(self.repo, patch_path)
            if current == "present":
                return "complete", "代码补丁已存在于当前工作区"
            if current == "absent":
                return "pending", "此任务的代码已回退"
            return "drift", "任务代码与当前工作区存在交叉修改"

        if commit:
            patch_path = self.patch_for_commit(task_id, commit)
            if not patch_path:
                return "drift", f"找不到提交 {commit[:7]}"
            current = patch_state(self.repo, patch_path)
            if current == "present":
                return "complete", f"代码提交 {commit[:7]} 已生效"
            if current == "absent":
                return "pending", f"提交 {commit[:7]} 的代码当前不存在"
            return "drift", f"提交 {commit[:7]} 与当前代码已发生漂移"

        if document_state == "complete":
            return "drift", "文档标记完成，但没有可验证的提交或补丁"
        if document_state == "blocked":
            return "drift", "任务文档标记为阻塞或失败"
        if document_state == "running":
            return "drift", "文档写着开发中，但当前没有 Codex 进程"
        return "pending", "等待开发"

    def revert_task(self, task_id: str, commit: str | None) -> None:
        patch_path = self.managed_patch(task_id)
        if not patch_path and commit:
            patch_path = self.patch_for_commit(task_id, commit)
        if not patch_path:
            raise GitOperationError("此任务没有可验证的独立代码补丁。")
        revert_patch(self.repo, patch_path)
        self.store.update(task_id, status="reverted", finished_at=_utc_now(), last_error=None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_remove_worktree(repo: Path, worktree: Path, allowed_root: Path) -> None:
    resolved = worktree.resolve()
    root = allowed_root.resolve()
    if root not in resolved.parents:
        raise GitOperationError("拒绝移除状态目录之外的 worktree。")
    _run_git(repo, ["worktree", "remove", "--force", str(resolved)], check=False)
    if resolved.exists():
        shutil.rmtree(resolved)


def temporary_patch_file(prefix: str = "task-dock-") -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".patch")
    os.close(descriptor)
    return Path(name)
