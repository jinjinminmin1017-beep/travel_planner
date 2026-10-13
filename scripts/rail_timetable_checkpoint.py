"""Small import manifest and independently durable service-date checkpoints.

Legacy checkpoints are input only: migration writes a sidecar and leaves the
original file intact. SQLite, rather than a list in this file, owns committed
service progress.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class RailCheckpointError(RuntimeError):
    pass


class RailCheckpointBusyError(RailCheckpointError):
    pass


def manifest_path(path: Path) -> Path:
    return path if path.name.endswith(".v2.json") else path.with_name(f"{path.stem}.v2.json")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                return len(content.encode("utf-8"))
            except PermissionError:
                if attempt == 5:
                    raise
                # Antivirus scanners on Windows can briefly hold a file without
                # sharing delete access; never abandon the atomic boundary.
                time.sleep(min(0.8, 0.05 * (2**attempt)))
    finally:
        if temporary.exists():
            temporary.unlink()
    raise RailCheckpointError("checkpoint replacement did not complete")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RailCheckpointError("rail timetable checkpoint is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RailCheckpointError("rail timetable checkpoint is not an object")
    return payload


class CheckpointDocument(dict[str, Any]):
    """Dict compatibility for import helpers, with lazy per-date storage."""

    def __init__(self, path: Path, *, resume: bool) -> None:
        self.path = manifest_path(path)
        self.directory = self.path.with_suffix(".d")
        self.resume = resume
        self.loaded_dates: set[str] = set()
        self.legacy_dates: dict[str, Any] = {}
        self.bytes_written = 0
        self.write_count = 0
        self.write_seconds = 0.0
        payload: dict[str, Any] = {"version": 2, "dates": {}, "scheduler": {}}
        if resume and self.path.exists():
            payload = _read_json(self.path)
            if payload.get("version") != 2 or not isinstance(payload.get("dates"), dict):
                raise RailCheckpointError("rail timetable v2 manifest has an unsupported shape")
        elif resume and path.exists():
            legacy = _read_json(path)
            if legacy.get("version") != 1 or not isinstance(legacy.get("dates"), dict):
                raise RailCheckpointError("rail timetable legacy checkpoint has an unsupported shape")
            self.legacy_dates = legacy["dates"]
            if any(not isinstance(state, dict) for state in self.legacy_dates.values()):
                raise RailCheckpointError("rail timetable legacy date state is malformed")
            payload["dates"] = {
                key: self._summary(key, state) for key, state in self.legacy_dates.items()
                if isinstance(state, dict)
            }
        for key, summary in payload["dates"].items():
            self._validate_date_key(key)
            if not isinstance(summary, dict):
                raise RailCheckpointError("rail timetable manifest date summary is malformed")
        super().__init__(payload)

    @staticmethod
    def _validate_date_key(key: str) -> None:
        try:
            if date.fromisoformat(key).isoformat() != key:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise RailCheckpointError("checkpoint has an invalid service date") from exc

    @classmethod
    def _summary(cls, key: str, state: dict[str, Any]) -> dict[str, Any]:
        cls._validate_date_key(key)
        result = {"state_file": f"{key}.json"}
        for field in (
            "generation", "batch_id", "status", "service_count", "stop_count",
            "deferred_runs", "last_attempt_at", "error_code",
        ):
            if field in state:
                result[field] = state[field]
        discovery = state.get("discovery")
        if isinstance(discovery, dict):
            result["discovery_status"] = discovery.get("status")
            result["query_count"] = discovery.get("query_count", 0)
        return result

    def date_state(self, key: str) -> dict[str, Any]:
        self._validate_date_key(key)
        dates = self.setdefault("dates", {})
        if key in self.loaded_dates:
            return dates[key]
        date_path = self.directory / f"{key}.json"
        if self.resume and date_path.exists():
            if key in dates and dates[key].get("state_file", f"{key}.json") != f"{key}.json":
                raise RailCheckpointError("checkpoint date file is outside its manifest")
            payload = _read_json(date_path)
            if payload.get("version") != 2 or payload.get("service_date") != key:
                raise RailCheckpointError("checkpoint date file identity does not match its manifest")
            state = payload.get("state")
        elif key in self.legacy_dates:
            state = self.legacy_dates[key]
        elif key in dates and dates[key].get("state_file"):
            raise RailCheckpointError("checkpoint manifest references a missing date file")
        else:
            state = {"batch_id": None, "status": "PENDING"}
        if not isinstance(state, dict):
            raise RailCheckpointError("checkpoint date state has an unsupported shape")
        # Scheduling fields in the small manifest may be newer than the large
        # date file. They never affect service/discovery recovery semantics.
        summary = dates.get(key, {})
        for field in ("deferred_runs", "last_attempt_at"):
            if field in summary:
                state[field] = summary[field]
        dates[key] = state
        self.loaded_dates.add(key)
        return state

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        started = time.monotonic()
        try:
            self.bytes_written += atomic_write_json(path, payload)
            self.write_count += 1
        finally:
            self.write_seconds += time.monotonic() - started

    def _migrate_legacy(self) -> None:
        if not self.legacy_dates:
            return
        for key, state in self.legacy_dates.items():
            if not isinstance(state, dict):
                raise RailCheckpointError("legacy checkpoint date state is malformed")
            self._validate_date_key(key)
            date_path = self.directory / f"{key}.json"
            # A previous migration may have stopped after writing the date file
            # but before publishing the manifest. Never roll that state back.
            if date_path.exists():
                existing = _read_json(date_path)
                if existing.get("version") != 2 or existing.get("service_date") != key or not isinstance(existing.get("state"), dict):
                    raise RailCheckpointError("existing migrated checkpoint date file is malformed")
                if key not in self.loaded_dates:
                    self["dates"][key] = self._summary(key, existing["state"])
                continue
            self._write(date_path, {
                "version": 2, "service_date": key, "state": state,
            })
        self.legacy_dates = {}

    def save_date(self, key: str) -> None:
        self._migrate_legacy()
        state = self.date_state(key)
        self._write(self.directory / f"{key}.json", {
            "version": 2, "service_date": key, "state": state,
        })
        self.save_manifest()

    def save_manifest(self) -> None:
        self._migrate_legacy()
        dates = {
            key: self._summary(key, value) if key in self.loaded_dates else value
            for key, value in self["dates"].items()
        }
        payload = {key: value for key, value in self.items() if key != "dates"}
        payload.update({"version": 2, "dates": dates, "updated_at": datetime.now(timezone.utc).isoformat()})
        self._write(self.path, payload)


@contextmanager
def checkpoint_lock(path: Path) -> Iterator[None]:
    """One writer across scheduled and manually started importer processes."""
    lock_path = manifest_path(path).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RailCheckpointBusyError("another timetable importer owns this checkpoint") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
