from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .gitops import (
    GitOperationError,
    ManagedTaskState,
    PatchRegistry,
    StateStore,
    _run_git,
    apply_patch,
    current_head,
    patch_state,
    safe_remove_worktree,
)
from .processes import HIDDEN_CONSOLE_FLAGS, process_is_running
from .scanner import TaskRecord, task_excerpt


class TaskRunner:
    def __init__(
        self,
        repo: Path,
        state_directory: Path,
        store: StateStore,
        patch_registry: PatchRegistry,
    ):
        self.repo = repo
        self.state_directory = state_directory
        self.store = store
        self.patch_registry = patch_registry
        self.worktree_root = state_directory / "worktrees"
        self.log_root = state_directory / "logs"
        self.result_root = state_directory / "results"
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.result_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active_task_id: str | None = None
        self._process: subprocess.Popen[str] | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._recover_interrupted_runs()

    @property
    def active_task_id(self) -> str | None:
        with self._lock:
            return self._active_task_id

    def start(self, task: TaskRecord) -> None:
        with self._lock:
            if self._active_task_id:
                raise GitOperationError("已有任务正在由 Codex 开发，请等待它结束。")
            actual_state, _ = self.patch_registry.actual_state(task.id, task.document_state, task.commit)
            managed = self.store.get(task.id)
            retryable_failure = bool(managed and managed.status == "failed" and not managed.patch_path)
            if actual_state != "pending" and not retryable_failure:
                if actual_state == "complete":
                    raise GitOperationError("此任务的代码已经存在。先 Revert 后才能重新开发。")
                raise GitOperationError("任务代码与记录不一致，请先人工检查，Task Dock 不会强制覆盖。")
            self._active_task_id = task.id
            self._idle.clear()
            self.store.update(
                task.id,
                status="running",
                started_at=_utc_now(),
                finished_at=None,
                last_error=None,
                last_message="正在创建隔离工作区",
                run_key=None,
                process_id=None,
                log_path=None,
                result_path=None,
                exit_code=None,
                result_summary=None,
            )
        thread = threading.Thread(target=self._execute, args=(task,), name=f"codex-{task.id}", daemon=True)
        thread.start()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def _execute(self, task: TaskRecord) -> None:
        head_commit = current_head(self.repo)
        run_key = f"{_safe_name(task.id)}-{int(time.time())}"
        worktree = self.worktree_root / run_key
        patch_path = self.patch_registry.patch_directory / f"{run_key}.patch"
        log_path = self.log_root / f"{run_key}.jsonl"
        result_path = self.result_root / f"{run_key}.json"
        try:
            self.store.update(
                task.id,
                run_key=run_key,
                patch_path=None,
                worktree_path=str(worktree),
                log_path=str(log_path),
                result_path=str(result_path),
            )
            self._write_receipt(task.id, "running")
            _run_git(self.repo, ["worktree", "add", "--detach", str(worktree), head_commit])
            base_commit = _snapshot_current_context(self.repo, worktree, head_commit)
            self.store.update(
                task.id,
                base_commit=base_commit,
                worktree_path=str(worktree),
                last_message="Codex 正在读取任务与项目约束",
            )
            prompt = _build_prompt(task)
            command = _codex_command(worktree)
            with log_path.open("w", encoding="utf-8") as log_file:
                self._process = _start_codex_process(command, worktree, prompt)
                self.store.update(task.id, process_id=self._process.pid)
                self._write_receipt(task.id, "running")
                assert self._process.stdout is not None
                for line in self._process.stdout:
                    log_file.write(line)
                    log_file.flush()
                    message = _event_message(line)
                    if message:
                        self.store.update(task.id, last_message=message[:180])
                return_code = self._process.wait()
            self._process = None
            self.store.update(task.id, process_id=None, exit_code=return_code)
            if return_code != 0:
                detail = _failure_detail(log_path)
                suffix = f"：{detail}" if detail else "。"
                raise GitOperationError(f"Codex 进程退出码为 {return_code}{suffix}")

            self.store.update(task.id, last_message="正在打包此任务的独立代码补丁")
            _run_git(worktree, ["add", "-N", "--", "."], check=False)
            diff = _run_git(worktree, ["diff", "--binary", base_commit, "--", "."], text=False)
            patch_path.write_bytes(diff.stdout)
            if not patch_path.stat().st_size:
                raise GitOperationError("Codex 没有生成代码改动。请查看执行日志或补充任务描述。")

            self.store.update(task.id, last_message="正在把任务补丁应用到当前项目")
            apply_patch(self.repo, patch_path)
            result_summary = _result_summary(log_path) or "Codex 已完成开发并返回代码补丁。"
            self.store.update(
                task.id,
                patch_path=str(patch_path),
                finished_at=_utc_now(),
                result_summary=result_summary,
                last_message="已收到 Codex 开发结果",
            )
            self._write_receipt(task.id, "complete")
            self.store.update(
                task.id,
                status="complete",
                patch_path=str(patch_path),
                finished_at=_utc_now(),
                last_error=None,
                last_message="已收到 Codex 开发结果，代码已应用到当前项目",
            )
            safe_remove_worktree(self.repo, worktree, self.worktree_root)
            self.store.update(task.id, worktree_path=None)
        except Exception as error:  # noqa: BLE001 - boundary reports all runner failures to the UI.
            failure = str(error)[:600]
            self.store.update(
                task.id,
                finished_at=_utc_now(),
                process_id=None,
                last_error=failure,
                last_message="任务未能安全应用",
                patch_path=str(patch_path) if patch_path.exists() and patch_path.stat().st_size else None,
                worktree_path=str(worktree) if worktree.exists() else None,
            )
            self._write_receipt(task.id, "failed")
            self.store.update(task.id, status="failed")
        finally:
            with self._lock:
                self._active_task_id = None
                self._process = None
                self._idle.set()

    def _recover_interrupted_runs(self) -> None:
        for state in self.store.all_states():
            if state.status != "running":
                continue
            if process_is_running(state.process_id) and self.active_task_id is None:
                with self._lock:
                    self._active_task_id = state.task_id
                    self._idle.clear()
                thread = threading.Thread(
                    target=self._wait_for_recovered_process,
                    args=(state.task_id, state.process_id),
                    name=f"codex-recover-{state.task_id}",
                    daemon=True,
                )
                thread.start()
                continue
            self._finalize_recovered_run(state.task_id)

    def _wait_for_recovered_process(self, task_id: str, process_id: int | None) -> None:
        while process_is_running(process_id):
            time.sleep(1.0)
        self._finalize_recovered_run(task_id)
        with self._lock:
            self._active_task_id = None
            self._idle.set()

    def _finalize_recovered_run(self, task_id: str) -> None:
        state = self.store.get(task_id)
        if not state or state.status != "running":
            return
        run_key = state.run_key or (Path(state.worktree_path).name if state.worktree_path else None)
        patch_path = Path(state.patch_path) if state.patch_path else (
            self.patch_registry.patch_directory / f"{run_key}.patch" if run_key else None
        )
        log_path = Path(state.log_path) if state.log_path else (self.log_root / f"{run_key}.jsonl" if run_key else None)
        result_path = Path(state.result_path) if state.result_path else (
            self.result_root / f"{run_key}.json" if run_key else None
        )
        self.store.update(
            task_id,
            run_key=run_key,
            patch_path=str(patch_path) if patch_path and patch_path.exists() and patch_path.stat().st_size else None,
            log_path=str(log_path) if log_path else None,
            result_path=str(result_path) if result_path else None,
            process_id=None,
        )
        receipt = _read_receipt(result_path)
        if receipt and receipt.get("status") == "failed":
            self.store.update(
                task_id,
                status="failed",
                finished_at=str(receipt.get("finished_at") or _utc_now()),
                last_error=str(receipt.get("error") or "Codex 返回了失败结果。")[:600],
                last_message="已恢复 Codex 失败结果，可重新尝试",
            )
            return
        try:
            if patch_path and patch_path.exists() and patch_path.stat().st_size:
                current_patch_state = patch_state(self.repo, patch_path)
                if current_patch_state == "absent":
                    apply_patch(self.repo, patch_path)
                elif current_patch_state != "present":
                    raise GitOperationError("Codex 已返回结果，但任务补丁与当前代码冲突。")
            else:
                if not log_path or not _log_completed(log_path):
                    raise GitOperationError("Dock 重启前没有收到 Codex 的完成结果，可重新尝试。")
                if not state.worktree_path or not state.base_commit:
                    raise GitOperationError("Codex 已结束，但缺少可恢复的隔离工作区，可重新尝试。")
                worktree = Path(state.worktree_path)
                if not worktree.exists() or not patch_path:
                    raise GitOperationError("Codex 已结束，但隔离工作区已不存在，可重新尝试。")
                _run_git(worktree, ["add", "-N", "--", "."], check=False)
                diff = _run_git(worktree, ["diff", "--binary", state.base_commit, "--", "."], text=False)
                patch_path.write_bytes(diff.stdout)
                if not patch_path.stat().st_size:
                    patch_path.unlink(missing_ok=True)
                    raise GitOperationError("Codex 已返回完成结果，但没有生成代码改动，可重新尝试。")
                apply_patch(self.repo, patch_path)

            summary = str(receipt.get("result_summary") or "") if receipt else ""
            summary = summary or (_result_summary(log_path) if log_path else None) or "Codex 已完成开发并返回代码补丁。"
            self.store.update(
                task_id,
                status="complete",
                patch_path=str(patch_path),
                finished_at=str(receipt.get("finished_at") or _utc_now()) if receipt else _utc_now(),
                last_error=None,
                last_message="已恢复 Codex 开发结果，代码已应用到当前项目",
                result_summary=summary[:2000],
            )
            self._write_receipt(task_id, "complete")
            if state.worktree_path and Path(state.worktree_path).exists():
                safe_remove_worktree(self.repo, Path(state.worktree_path), self.worktree_root)
                self.store.update(task_id, worktree_path=None)
        except Exception as error:  # noqa: BLE001 - recovery must always leave a terminal UI state.
            self.store.update(
                task_id,
                finished_at=_utc_now(),
                process_id=None,
                last_error=str(error)[:600],
                last_message="已检查 Codex 结果，任务可以重新尝试",
                patch_path=str(patch_path) if patch_path and patch_path.exists() and patch_path.stat().st_size else None,
            )
            self._write_receipt(task_id, "failed")
            self.store.update(task_id, status="failed")

    def _write_receipt(self, task_id: str, status: str) -> None:
        state = self.store.get(task_id)
        if not state or not state.result_path:
            return
        path = Path(state.result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "task_id": task_id,
            "run_key": state.run_key,
            "status": status,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "process_id": state.process_id,
            "exit_code": state.exit_code,
            "base_commit": state.base_commit,
            "worktree_path": state.worktree_path,
            "patch_path": state.patch_path,
            "log_path": state.log_path,
            "result_summary": state.result_summary,
            "error": state.last_error,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


def _codex_command(worktree: Path) -> list[str]:
    codex_cmd = shutil.which("codex.cmd") or shutil.which("codex.exe")
    if codex_cmd:
        return [
            codex_cmd,
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--json",
            "-C",
            str(worktree),
            "-s",
            "workspace-write",
            "-",
        ]
    codex_ps1 = shutil.which("codex.ps1")
    if codex_ps1:
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            codex_ps1,
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--json",
            "-C",
            str(worktree),
            "-s",
            "workspace-write",
            "-",
        ]
    raise GitOperationError("没有找到 Codex CLI。请先确认 codex 命令可用。")


def _start_codex_process(command: list[str], worktree: Path, prompt: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        cwd=worktree,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=HIDDEN_CONSOLE_FLAGS,
    )
    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()
    return process


def _snapshot_current_context(repo: Path, worktree: Path, head_commit: str) -> str:
    """Copy the current dirty tree into the isolated worktree and commit it as context.

    The temporary commit is the task diff base. This lets Codex see the user's real
    working files while keeping every pre-existing edit out of the task patch.
    """
    tracked = _run_git(repo, ["diff", "--name-only", "-z", "HEAD", "--"], text=False)
    untracked = _run_git(repo, ["ls-files", "-o", "--exclude-standard", "-z"], text=False)
    relative_paths = {
        Path(os.fsdecode(raw))
        for raw in tracked.stdout.split(b"\0") + untracked.stdout.split(b"\0")
        if raw
    }
    for relative in sorted(relative_paths, key=lambda path: path.as_posix()):
        source = (repo / relative).resolve()
        target = (worktree / relative).resolve()
        if worktree.resolve() not in target.parents:
            raise GitOperationError(f"检测到工作区外路径，已停止：{relative}")
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    _run_git(worktree, ["add", "-A", "--", "."])
    status = _run_git(worktree, ["status", "--porcelain"])
    if not status.stdout.strip():
        return head_commit
    _run_git(
        worktree,
        [
            "-c",
            "user.name=Task Dock",
            "-c",
            "user.email=task-dock@local",
            "commit",
            "--no-gpg-sign",
            "-m",
            "Task Dock context snapshot",
        ],
    )
    return current_head(worktree)


def _build_prompt(task: TaskRecord) -> str:
    excerpt = task_excerpt(task)
    return f"""你正在由 Task Dock 执行一个独立开发任务。

任务 ID：{task.id}
任务标题：{task.title}
来源文件：{task.source_path}
来源行：{task.start_line}-{task.end_line}

任务原文：
---
{excerpt}
---

执行要求：
1. 先读取仓库根目录 AGENTS.md，并严格读取它指定的专家文档与开发上下文。
2. 只实现本任务，不修改无关业务。
3. 完成必要测试，不能用跳过或弱化测试隐藏问题。
4. 将来源任务在原文位置更新为已完成，并把验证结果写入 docs/Dev/code_change_log.md。
5. 不执行 git push，不清理用户数据。允许在当前隔离 worktree 内提交，但 Task Dock 会根据完整 diff 打包结果。
6. 如果任务因外部许可、密钥、真实服务或缺失决策而无法完成，保留任务为未完成并在最终说明中写清阻塞原因。
"""


def _event_message(line: str) -> str | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    event_type = str(event.get("type", ""))
    if event_type in {"thread.started", "turn.started"}:
        return "Codex 已开始处理"
    if event_type in {"turn.completed", "item.completed"}:
        item = event.get("item") or {}
        text = item.get("text") if isinstance(item, dict) else None
        return str(text) if text else "Codex 完成一个执行步骤"
    if event_type == "error":
        return str(event.get("message") or "Codex 报告错误")
    return None


def _failure_detail(log_path: Path) -> str | None:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace")[-12_000:].splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except ValueError:
            if stripped.lower().startswith("error"):
                return stripped[:360]
            continue
        if event.get("type") == "error":
            message = str(event.get("message") or "").strip()
            if message:
                return message[:360]
    return None


def _log_completed(log_path: Path) -> bool:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            if json.loads(line).get("type") == "turn.completed":
                return True
        except ValueError:
            continue
    return False


def _result_summary(log_path: Path) -> str | None:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace")[-200_000:].splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") in {"agent_message", "message"} and item.get("text"):
                return str(item["text"])[:2000]
    return None


def _read_receipt(path: Path | None) -> dict[str, object] | None:
    if not path or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "-" for character in value)[:80]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
