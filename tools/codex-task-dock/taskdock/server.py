from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .batch import TaskBatchController
from .gitops import GitOperationError, PatchRegistry, StateStore, current_branch, dirty_paths
from .processes import HIDDEN_CONSOLE_FLAGS
from .runner import TaskRunner
from .scanner import IncrementalTaskScanner, TaskRecord


SourceLauncher = Callable[[Path, int], None]


def open_source_in_editor(source_path: Path, line_number: int) -> None:
    """Open a task source at its heading without creating a visible console."""
    location = f"{source_path}:{line_number}"
    code_command = shutil.which("code")
    if code_command:
        command: str | list[str] = [code_command, "--reuse-window", "--goto", location]
        use_shell = os.name == "nt" and Path(code_command).suffix.casefold() in {".cmd", ".bat"}
        if use_shell:
            # A .cmd path containing spaces must be passed as one fully quoted
            # command line. Quote the scanned source too so shell metacharacters
            # in an otherwise valid filename cannot be interpreted by cmd.exe.
            command = f'"{code_command}" --reuse-window --goto "{location}"'
        result = subprocess.run(
            command,
            cwd=source_path.parent,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            shell=use_shell,
            creationflags=HIDDEN_CONSOLE_FLAGS,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            suffix = f"：{detail[:240]}" if detail else "。"
            raise RuntimeError(f"VS Code 未能跳转到任务原文{suffix}")
        return

    if os.name == "nt":
        startfile = getattr(os, "startfile", None)
        if startfile:
            encoded_path = urllib.parse.quote(source_path.as_posix(), safe="/:")
            startfile(f"vscode://file/{encoded_path}:{line_number}")
            return
    raise RuntimeError("未找到 VS Code，无法定位任务原文。")


class TaskDockApplication:
    def __init__(
        self,
        repo: Path,
        web_root: Path,
        scanner: IncrementalTaskScanner,
        store: StateStore,
        registry: PatchRegistry,
        runner: TaskRunner,
        source_launcher: SourceLauncher | None = None,
    ):
        self.repo = repo
        self.web_root = web_root
        self.scanner = scanner
        self.store = store
        self.registry = registry
        self.runner = runner
        self.batch = TaskBatchController(scanner, registry, runner)
        self.source_launcher = source_launcher or open_source_in_editor
        self.session_token = secrets.token_urlsafe(24)

    def state_payload(self) -> dict[str, Any]:
        tasks = [self._task_payload(task) for task in self.scanner.tasks()]
        counts = {"pending": 0, "running": 0, "complete": 0, "drift": 0}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        return {
            "project": self.repo.name,
            "branch": current_branch(self.repo),
            "tasks": tasks,
            "counts": counts,
            "active_task_id": self.runner.active_task_id,
            "batch": self.batch.snapshot(),
            "working_tree_changes": len(dirty_paths(self.repo)),
            "scanner": self.scanner.scanner_metrics(),
        }

    def _task_payload(self, task: TaskRecord) -> dict[str, Any]:
        actual_state, detail = self.registry.actual_state(task.id, task.document_state, task.commit)
        managed = self.store.get(task.id)
        return {
            **task.to_dict(),
            "status": actual_state,
            "status_detail": detail,
            "managed": {
                "last_error": managed.last_error if managed else None,
                "last_message": managed.last_message if managed else None,
                "started_at": managed.started_at if managed else None,
                "finished_at": managed.finished_at if managed else None,
                "has_patch": bool(managed and managed.patch_path),
                "result_summary": managed.result_summary if managed else None,
            },
        }

    def task(self, task_id: str) -> TaskRecord:
        task = self.scanner.task_by_id(task_id)
        if not task:
            raise KeyError("任务已不存在，请等待下一次同步。")
        return task

    def run_task(self, task_id: str) -> None:
        if self.batch.active:
            raise GitOperationError("全部任务开发队列正在运行，请先停止后续任务。")
        self.runner.start(self.task(task_id))

    def run_all_pending(self) -> int:
        return self.batch.start_all()

    def cancel_batch(self) -> int:
        return self.batch.cancel()

    def revert_task(self, task_id: str) -> None:
        if self.batch.active:
            raise GitOperationError("全部任务开发队列正在运行，请先停止后续任务。")
        task = self.task(task_id)
        self.registry.revert_task(task.id, task.commit)

    def delete_task(self, task_id: str) -> None:
        if self.batch.active:
            raise GitOperationError("全部任务开发队列正在运行，请先停止后续任务。")
        task = self.task(task_id)
        state, _ = self.registry.actual_state(task.id, task.document_state, task.commit)
        if state == "running":
            raise GitOperationError("Codex 正在处理此任务，暂时不能删除。")
        self.scanner.delete_task_source(task)
        self.store.remove(task.id)

    def task_diff(self, task_id: str) -> str:
        task = self.task(task_id)
        patch = self.registry.managed_patch(task.id)
        if not patch and task.commit:
            patch = self.registry.patch_for_commit(task.id, task.commit)
        if not patch or not patch.exists():
            raise GitOperationError("此任务没有可查看的独立补丁。")
        text = patch.read_text(encoding="utf-8", errors="replace")
        return text[:200_000]

    def open_task_source(self, task_id: str) -> None:
        task = self.task(task_id)
        source_path = Path(task.source_path).resolve()
        try:
            source_path.relative_to(self.scanner.dev_directory)
        except ValueError as error:
            raise ValueError("任务出处不在开发任务目录中，已拒绝打开。") from error
        if not source_path.is_file():
            raise FileNotFoundError("任务原文已不存在，请先同步任务列表。")
        self.source_launcher(source_path, max(1, task.start_line))


def create_server(application: TaskDockApplication, port: int = 0) -> ThreadingHTTPServer:
    handler = _handler_factory(application)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def _handler_factory(application: TaskDockApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TaskDock/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/state":
                if not self._authorized():
                    return
                self._json(application.state_payload())
                return
            if path.startswith("/api/tasks/") and path.endswith("/diff"):
                if not self._authorized():
                    return
                task_id = urllib.parse.unquote(path[len("/api/tasks/") : -len("/diff")]).rstrip("/")
                try:
                    self._json({"diff": application.task_diff(task_id)})
                except (KeyError, GitOperationError) as error:
                    self._error(HTTPStatus.CONFLICT, str(error))
                return
            if path == "/health":
                self._json({"ok": True})
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            path = urllib.parse.urlparse(self.path).path
            if path in {"/api/batch/run-all", "/api/batch/cancel"}:
                try:
                    if path.endswith("run-all"):
                        queued = application.run_all_pending()
                        self._json({"ok": True, "queued": queued}, HTTPStatus.ACCEPTED)
                    else:
                        cancelled = application.cancel_batch()
                        self._json({"ok": True, "cancelled": cancelled}, HTTPStatus.ACCEPTED)
                except GitOperationError as error:
                    self._error(HTTPStatus.CONFLICT, str(error))
                return
            if not path.startswith("/api/tasks/"):
                self._error(HTTPStatus.NOT_FOUND, "接口不存在。")
                return
            tail = path[len("/api/tasks/") :]
            task_id, _, action = tail.rpartition("/")
            try:
                if action == "run":
                    application.run_task(urllib.parse.unquote(task_id))
                elif action == "revert":
                    application.revert_task(urllib.parse.unquote(task_id))
                elif action == "open-source":
                    application.open_task_source(urllib.parse.unquote(task_id))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "接口不存在。")
                    return
                self._json({"ok": True}, HTTPStatus.ACCEPTED)
            except (KeyError, GitOperationError, OSError, RuntimeError, ValueError) as error:
                self._error(HTTPStatus.CONFLICT, str(error))

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            path = urllib.parse.urlparse(self.path).path
            if not path.startswith("/api/tasks/"):
                self._error(HTTPStatus.NOT_FOUND, "接口不存在。")
                return
            task_id = urllib.parse.unquote(path[len("/api/tasks/") :])
            try:
                application.delete_task(task_id)
                self._json({"ok": True})
            except (KeyError, GitOperationError, ValueError) as error:
                self._error(HTTPStatus.CONFLICT, str(error))

        def _authorized(self) -> bool:
            token = self.headers.get("X-Task-Dock-Token", "")
            if secrets.compare_digest(token, application.session_token):
                return True
            self._error(HTTPStatus.FORBIDDEN, "本地会话已失效，请重新启动 Task Dock。")
            return False

        def _static(self, request_path: str) -> None:
            relative = request_path.lstrip("/") or "index.html"
            target = (application.web_root / relative).resolve()
            if application.web_root.resolve() not in target.parents and target != application.web_root.resolve():
                self._error(HTTPStatus.FORBIDDEN, "无效路径。")
                return
            if not target.is_file():
                target = application.web_root / "index.html"
            mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            content = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") else mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._json({"ok": False, "error": message}, status)

    return Handler


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="task-dock-http", daemon=True)
    thread.start()
    return thread
