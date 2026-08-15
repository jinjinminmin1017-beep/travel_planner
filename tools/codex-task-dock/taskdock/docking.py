from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path

from .processes import HIDDEN_CONSOLE_FLAGS


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class DockController:
    def __init__(self, panel_title_fragment: str = "Task Dock", poll_seconds: float = 0.3):
        self.panel_title_fragment = panel_title_fragment
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._panel_handle: int | None = None

    def start(self) -> None:
        if os.name != "nt" or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, name="codex-window-dock", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self._dock_once()
            except OSError:
                continue

    def _dock_once(self) -> None:
        windows = _visible_windows()
        panel = next((window for window in windows if self.panel_title_fragment.lower() in window.title.lower()), None)
        if panel:
            self._panel_handle = panel.handle
        elif self._panel_handle and user32.IsWindow(self._panel_handle):
            panel = _window_from_handle(self._panel_handle)
        codex = next(
            (window for window in windows if window.executable.lower() in {"codex.exe", "chatgpt.exe"}),
            None,
        )
        if not panel:
            return
        if not codex or codex.minimized:
            user32.ShowWindow(panel.handle, 0)  # SW_HIDE when Codex is unavailable.
            return
        foreground = user32.GetForegroundWindow()
        if _panel_owns_foreground(panel, foreground):
            # Native Edge controls such as <select> open a separate foreground
            # popup. Reordering the app window while that popup is active closes
            # it immediately, so leave the z-order untouched during interaction.
            return
        user32.ShowWindow(panel.handle, 4)  # SW_SHOWNOACTIVATE
        codex_width = codex.rect.right - codex.rect.left
        codex_height = codex.rect.bottom - codex.rect.top
        desired_width = max(320, min(420, round(codex_width * 0.28)))
        work = _monitor_work_area(codex.handle)
        available_left = max(0, codex.rect.left - work.left)
        if available_left >= 280:
            panel_width = min(desired_width, available_left)
            panel_left = codex.rect.left - panel_width
        else:
            # Maximized Codex has no outer gutter. Use a restrained in-window overlay
            # instead of resizing the user's application window.
            panel_width = min(desired_width, max(280, round(codex_width * 0.3)))
            panel_left = codex.rect.left
        flags = 0x0010 | 0x0040  # SWP_NOACTIVATE | SWP_SHOWWINDOW
        insert_after = -1 if foreground in {codex.handle, panel.handle} else -2
        user32.SetWindowPos(
            panel.handle,
            insert_after,  # Topmost only while the user is working in Codex or Task Dock.
            panel_left,
            codex.rect.top,
            panel_width,
            codex_height,
            flags,
        )


def _panel_owns_foreground(panel: "_Window", foreground_handle: int) -> bool:
    if not foreground_handle:
        return False
    if foreground_handle == panel.handle:
        return True
    foreground_executable = _process_executable(foreground_handle)
    return bool(
        panel.executable
        and foreground_executable
        and foreground_executable.casefold() == panel.executable.casefold()
    )


class BrowserLauncher:
    def __init__(self, url: str, profile_directory: Path):
        self.url = url
        self.profile_directory = profile_directory
        self.process: subprocess.Popen[bytes] | None = None

    def launch(self) -> None:
        _close_existing_task_dock_windows()
        time.sleep(1.0)
        edge = _edge_path()
        self.profile_directory.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            [
                str(edge),
                f"--app={self.url}",
                f"--user-data-dir={self.profile_directory}",
                "--no-first-run",
                "--disable-features=msEdgeSidebarV2",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=HIDDEN_CONSOLE_FLAGS,
        )

    def close(self) -> None:
        _close_existing_task_dock_windows()


class _Window:
    def __init__(self, handle: int, title: str, executable: str, rect: "RECT", minimized: bool):
        self.handle = handle
        self.title = title
        self.executable = executable
        self.rect = rect
        self.minimized = minimized


def _visible_windows(include_hidden: bool = False) -> list[_Window]:
    windows: list[_Window] = []

    @EnumWindowsProc
    def callback(handle: int, _lparam: int) -> bool:
        if not include_hidden and not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        rect = RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return True
        windows.append(_Window(handle, buffer.value, _process_executable(handle), rect, bool(user32.IsIconic(handle))))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def _process_executable(handle: int) -> str:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
    process = kernel32.OpenProcess(0x1000, False, process_id.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(process)


def _window_from_handle(handle: int) -> _Window | None:
    if not user32.IsWindow(handle):
        return None
    length = user32.GetWindowTextLengthW(handle)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, buffer, length + 1)
    rect = RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        return None
    return _Window(handle, buffer.value, _process_executable(handle), rect, bool(user32.IsIconic(handle)))


def _monitor_work_area(handle: int) -> "RECT":
    monitor = user32.MonitorFromWindow(handle, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        rect = RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        return rect
    return info.rcWork


def _edge_path() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("没有找到 Microsoft Edge，无法打开桌面侧栏。")


def _close_existing_task_dock_windows() -> None:
    if os.name != "nt":
        return
    for window in _visible_windows(include_hidden=True):
        if window.executable.lower() == "msedge.exe" and window.title.strip().lower() == "task dock":
            user32.PostMessageW(window.handle, 0x0010, 0, 0)  # WM_CLOSE
