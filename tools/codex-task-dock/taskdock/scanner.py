from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


TASK_FILE_PATTERN = re.compile(r"^task.*\.md$", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
TASK_ID_PATTERN = re.compile(
    r"\b((?:ARC|DEV|UI|BUG)(?:-DEV)?-\d{8}(?:-\d+)?|"
    r"(?:ARC|DEV|UI|BUG)-\d{8}-\d+|P[0-3]-\d+)\b",
    re.IGNORECASE,
)
GENERIC_TASK_HEADING_PATTERN = re.compile(r"^(?:开发任务|用户任务)[：:]\s*(.+)$")
COMMIT_PATTERN = re.compile(r"(?:代码提交|提交(?:记录)?)[^\n`]*`?([0-9a-f]{7,40})`?", re.IGNORECASE)
STATUS_PATTERN = re.compile(r"(?:完成状态|开发状态|前端实施状态|状态)[：:]\s*([^\n]+)")


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    modified_ns: int
    size: int


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str
    display_id: str
    title: str
    description: str
    source_path: str
    source_name: str
    start_line: int
    end_line: int
    source_kind: str
    document_state: str
    commit: str | None
    source_signature: str
    updated_at_ns: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _stable_task_id(relative_path: str, _line_number: int, title: str, explicit_id: str | None) -> str:
    if explicit_id:
        # IDs such as P0-1 are document-local and commonly repeat in different
        # architecture task files. Keep the visible ID, but namespace the
        # internal identity by source so selection and task actions stay exact.
        source_digest = hashlib.sha1(relative_path.casefold().encode("utf-8")).hexdigest()[:10]
        return f"{explicit_id.upper()}@{source_digest.upper()}"
    # Keep generated IDs stable when unrelated content is inserted above a task.
    # The deduplication pass adds a line suffix only for genuinely repeated titles.
    digest = hashlib.sha1(f"{relative_path}:{title}".encode("utf-8")).hexdigest()[:10]
    return f"DOC-{digest.upper()}"


def _clean_markdown(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", value)
    value = re.sub(r"[*_>#]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _document_state(text: str, checkbox_checked: bool | None = None) -> str:
    if checkbox_checked is True:
        return "complete"
    if checkbox_checked is False:
        return "pending"
    match = STATUS_PATTERN.search(text)
    value = match.group(1).lower() if match else ""
    if any(token in value for token in ("已完成", "completed", "complete", "done")):
        return "complete"
    if any(token in value for token in ("开发中", "进行中", "running", "in progress")):
        return "running"
    if any(token in value for token in ("阻塞", "blocked", "失败", "failed")):
        return "blocked"
    if any(token in value for token in ("待开发", "未完成", "pending", "todo")):
        return "pending"
    return "pending"


def _first_description(lines: list[str], start: int, end: int, title: str) -> str:
    for raw in lines[start:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or STATUS_PATTERN.search(stripped):
            continue
        if CHECKBOX_PATTERN.match(stripped):
            continue
        cleaned = _clean_markdown(stripped.lstrip("-* "))
        if cleaned and cleaned != title:
            return cleaned[:180]
    return "来自开发任务文档"


def _section_end(lines: list[str], start_index: int, level: int) -> int:
    for index in range(start_index + 1, len(lines)):
        match = HEADING_PATTERN.match(lines[index])
        if match and len(match.group(1)) <= level:
            return index
    return len(lines)


def parse_task_document(path: Path, dev_directory: Path, fingerprint: FileFingerprint) -> list[TaskRecord]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    relative_path = path.relative_to(dev_directory.parent.parent).as_posix()
    tasks: list[TaskRecord] = []
    section_ranges: list[tuple[int, int]] = []

    for index, line in enumerate(lines):
        heading_match = HEADING_PATTERN.match(line)
        if not heading_match:
            continue
        heading_level = len(heading_match.group(1))
        heading_text = _clean_markdown(heading_match.group(2))
        id_match = TASK_ID_PATTERN.search(heading_text)
        generic_match = GENERIC_TASK_HEADING_PATTERN.match(heading_text)
        if not id_match and not generic_match:
            continue
        end_index = _section_end(lines, index, heading_level)
        block = "\n".join(lines[index:end_index])
        explicit_id = id_match.group(1) if id_match else None
        title = heading_text
        if explicit_id:
            title = heading_text.replace(explicit_id, "", 1).strip(" ：:-") or explicit_id
        elif generic_match:
            title = generic_match.group(1).strip()
        commit_match = COMMIT_PATTERN.search(block)
        task_id = _stable_task_id(relative_path, index + 1, title, explicit_id)
        signature = hashlib.sha1(line.encode("utf-8")).hexdigest()
        tasks.append(
            TaskRecord(
                id=task_id,
                display_id=explicit_id.upper() if explicit_id else task_id,
                title=title[:140],
                description=_first_description(lines, index + 1, min(end_index, index + 18), title),
                source_path=str(path),
                source_name=path.name,
                start_line=index + 1,
                end_line=end_index,
                source_kind="section",
                document_state=_document_state(block),
                commit=commit_match.group(1) if commit_match else None,
                source_signature=signature,
                updated_at_ns=fingerprint.modified_ns,
            )
        )
        section_ranges.append((index, end_index))

    for index, line in enumerate(lines):
        checkbox_match = CHECKBOX_PATTERN.match(line)
        if not checkbox_match:
            continue
        checked = checkbox_match.group(1).lower() == "x"
        title = _clean_markdown(checkbox_match.group(2))
        commit_match = COMMIT_PATTERN.search(line)
        # Completed checklist details without their own code evidence create hundreds
        # of duplicate rows. Their parent task remains visible and verifiable.
        if checked and not commit_match:
            continue
        parent_id = None
        for task in reversed(tasks):
            if task.start_line <= index + 1 <= task.end_line:
                parent_id = task.id
                break
        explicit_match = TASK_ID_PATTERN.search(title)
        explicit_id = explicit_match.group(1) if explicit_match else None
        base_id = _stable_task_id(relative_path, index + 1, title, explicit_id)
        task_id = f"{parent_id}/{base_id}" if parent_id and not explicit_id else base_id
        signature = hashlib.sha1(line.encode("utf-8")).hexdigest()
        tasks.append(
            TaskRecord(
                id=task_id,
                display_id=explicit_id.upper() if explicit_id else base_id,
                title=title[:140],
                description=f"{path.stem} 第 {index + 1} 行",
                source_path=str(path),
                source_name=path.name,
                start_line=index + 1,
                end_line=index + 1,
                source_kind="checkbox",
                document_state=_document_state(line, checked),
                commit=commit_match.group(1) if commit_match else None,
                source_signature=signature,
                updated_at_ns=fingerprint.modified_ns,
            )
        )

    deduplicated: dict[str, TaskRecord] = {}
    for task in tasks:
        candidate_id = task.id
        if candidate_id in deduplicated:
            candidate_id = f"{candidate_id}-{task.start_line}"
            task = TaskRecord(**{**task.to_dict(), "id": candidate_id})
        deduplicated[candidate_id] = task
    return list(deduplicated.values())


class IncrementalTaskScanner:
    """Polls cheap metadata every three seconds and reads only changed files."""

    def __init__(self, dev_directory: Path, poll_seconds: float = 3.0, directory_backstop_ticks: int = 20):
        self.dev_directory = dev_directory.resolve()
        self.poll_seconds = poll_seconds
        self.directory_backstop_ticks = max(1, directory_backstop_ticks)
        self._fingerprints: dict[Path, FileFingerprint] = {}
        self._parsed_tasks: dict[Path, list[TaskRecord]] = {}
        self._known_files: set[Path] = set()
        self._directory_mtime_ns: int | None = None
        self._ticks_since_directory_scan = directory_backstop_ticks
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.metrics = {
            "directory_scans": 0,
            "content_reads": 0,
            "files_read_last_tick": 0,
            "last_scan_at": None,
        }

    @staticmethod
    def _is_task_file(path: Path) -> bool:
        return path.is_file() and bool(TASK_FILE_PATTERN.match(path.name)) and not path.stem.lower().endswith("done")

    def _scan_directory(self) -> None:
        files: set[Path] = set()
        with os.scandir(self.dev_directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_file() and TASK_FILE_PATTERN.match(entry.name) and not path.stem.lower().endswith("done"):
                    files.add(path.resolve())
        removed = self._known_files - files
        for path in removed:
            self._fingerprints.pop(path, None)
            self._parsed_tasks.pop(path, None)
        self._known_files = files
        self.metrics["directory_scans"] += 1
        self._ticks_since_directory_scan = 0

    @staticmethod
    def _fingerprint(path: Path) -> FileFingerprint:
        stat = path.stat()
        return FileFingerprint(modified_ns=stat.st_mtime_ns, size=stat.st_size)

    def tick(self, force: bool = False) -> list[TaskRecord]:
        with self._lock:
            self.metrics["files_read_last_tick"] = 0
            directory_stat = self.dev_directory.stat()
            directory_changed = self._directory_mtime_ns != directory_stat.st_mtime_ns
            if force or directory_changed or self._ticks_since_directory_scan >= self.directory_backstop_ticks:
                self._scan_directory()
                self._directory_mtime_ns = directory_stat.st_mtime_ns
            else:
                self._ticks_since_directory_scan += 1

            for path in sorted(self._known_files):
                try:
                    fingerprint = self._fingerprint(path)
                except FileNotFoundError:
                    self._ticks_since_directory_scan = self.directory_backstop_ticks
                    continue
                if force or self._fingerprints.get(path) != fingerprint:
                    self._parsed_tasks[path] = parse_task_document(path, self.dev_directory, fingerprint)
                    self._fingerprints[path] = fingerprint
                    self.metrics["content_reads"] += 1
                    self.metrics["files_read_last_tick"] += 1

            self.metrics["last_scan_at"] = time.time()
            return self.tasks()

    def tasks(self) -> list[TaskRecord]:
        with self._lock:
            all_tasks = [task for tasks in self._parsed_tasks.values() for task in tasks]
        state_order = {"running": 0, "pending": 1, "blocked": 2, "complete": 3}
        return sorted(all_tasks, key=lambda task: (state_order.get(task.document_state, 9), -task.updated_at_ns, task.id))

    def task_by_id(self, task_id: str) -> TaskRecord | None:
        return next((task for task in self.tasks() if task.id == task_id), None)

    def scanner_metrics(self) -> dict[str, object]:
        with self._lock:
            return {
                **self.metrics,
                "files_known": len(self._known_files),
                "poll_seconds": self.poll_seconds,
                "strategy": "目录 mtime + 已知文件 stat；仅变更文件读取；60 秒兜底重枚举",
            }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.tick(force=True)
        self._thread = threading.Thread(target=self._run, name="task-source-scanner", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self.tick()
            except OSError:
                # The API exposes stale data and scanner health instead of crashing the dock.
                self.metrics["last_scan_at"] = time.time()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.poll_seconds + 1)

    def delete_task_source(self, task: TaskRecord) -> None:
        path = Path(task.source_path)
        fingerprint = self._fingerprint(path)
        lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        if task.start_line < 1 or task.end_line > len(lines):
            raise ValueError("任务文档已经变化，请等待下一次增量同步。")
        current_signature = hashlib.sha1(lines[task.start_line - 1].rstrip("\r\n").encode("utf-8")).hexdigest()
        if current_signature != task.source_signature:
            raise ValueError("任务起始位置已经变化，请等待下一次增量同步。")
        del lines[task.start_line - 1 : task.end_line]
        temporary = path.with_suffix(path.suffix + ".task-dock.tmp")
        temporary.write_text("".join(lines), encoding="utf-8")
        os.replace(temporary, path)
        self._fingerprints.pop(path.resolve(), None)
        self.tick()


def task_excerpt(task: TaskRecord, max_lines: int = 120) -> str:
    lines = Path(task.source_path).read_text(encoding="utf-8-sig").splitlines()
    start = max(0, task.start_line - 1)
    end = min(len(lines), task.end_line, start + max_lines)
    return "\n".join(lines[start:end])


def task_sources(dev_directory: Path) -> Iterable[Path]:
    with os.scandir(dev_directory) as entries:
        for entry in entries:
            path = Path(entry.path)
            if entry.is_file() and TASK_FILE_PATTERN.match(entry.name) and not path.stem.lower().endswith("done"):
                yield path
