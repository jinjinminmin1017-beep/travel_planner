from __future__ import annotations

import argparse
import ctypes
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

from taskdock.docking import BrowserLauncher, DockController
from taskdock.gitops import PatchRegistry, StateStore, repository_root
from taskdock.runner import TaskRunner
from taskdock.scanner import IncrementalTaskScanner
from taskdock.server import TaskDockApplication, create_server, serve_in_thread


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex Task Dock desktop companion")
    parser.add_argument("--repo", type=Path, help="Git repository root")
    parser.add_argument("--port", type=int, default=0, help="Local HTTP port, 0 chooses a free port")
    parser.add_argument("--no-browser", action="store_true", help="Do not launch the desktop panel")
    parser.add_argument("--no-dock", action="store_true", help="Do not attach the panel to Codex")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    inferred_repo = Path(__file__).resolve().parents[2]
    repo = repository_root((arguments.repo or inferred_repo).resolve())
    dev_directory = repo / "docs" / "Dev"
    if not dev_directory.is_dir():
        raise FileNotFoundError(f"开发任务目录不存在：{dev_directory}")

    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    repo_key = hashlib.sha1(str(repo).casefold().encode("utf-8")).hexdigest()[:12]
    acquired, instance_handle = _acquire_single_instance(repo_key)
    if not acquired:
        print("Task Dock 已经在此项目中运行。")
        return 0
    state_directory = local_app_data / "CodexTaskDock" / repo_key
    state_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=state_directory / "task-dock.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )

    scanner = IncrementalTaskScanner(dev_directory, poll_seconds=3.0, directory_backstop_ticks=20)
    store = StateStore(state_directory / "state.json")
    registry = PatchRegistry(repo, state_directory, store)
    runner = TaskRunner(repo, state_directory, store, registry)
    application = TaskDockApplication(
        repo,
        Path(__file__).resolve().parent / "web",
        scanner,
        store,
        registry,
        runner,
    )
    server = create_server(application, arguments.port)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={application.session_token}"
    docking = DockController()
    browser: BrowserLauncher | None = None

    scanner.start()
    serve_in_thread(server)
    if not arguments.no_browser:
        browser = BrowserLauncher(url, state_directory / "edge-profile")
        browser.launch()
    if not arguments.no_dock:
        docking.start()

    print(f"Task Dock 正在运行：{url}")
    logging.info("Task Dock started for %s on port %s", repo, port)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        docking.stop()
        if browser:
            browser.close()
        scanner.stop()
        server.shutdown()
        server.server_close()
        if instance_handle:
            ctypes.windll.kernel32.CloseHandle(instance_handle)


def _acquire_single_instance(repo_key: str) -> tuple[bool, int | None]:
    if os.name != "nt":
        return True, None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, f"Local\\CodexTaskDock-{repo_key}")
    if not handle:
        raise OSError(ctypes.get_last_error(), "无法创建 Task Dock 单实例锁")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False, None
    return True, int(handle)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - desktop entrypoint must persist diagnostics.
        logging.exception("Task Dock failed to start")
        raise
