from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from app.data_sources.config_loader import PROJECT_ROOT, load_project_env

DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_PREFIX = "backend"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_LOG_LEVEL = "INFO"

_HANDLER_MARKER = "_travel_planner_managed_handler"
_CONFIGURED = False


@dataclass(frozen=True)
class LoggingSettings:
    file_enabled: bool
    log_dir: Path
    log_level: str
    max_bytes: int
    current_log_path: Path | None


class TimestampRotatingFileHandler(logging.Handler):
    """Write logs to timestamp-named files and rotate before max_bytes is exceeded."""

    terminator = "\n"

    def __init__(
        self,
        log_dir: Path,
        *,
        prefix: str = DEFAULT_LOG_PREFIX,
        max_bytes: int = DEFAULT_MAX_BYTES,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.prefix = prefix
        self.max_bytes = max(1, max_bytes)
        self.encoding = encoding
        self.current_log_path: Path | None = None
        self._stream = None
        self._current_bytes = 0
        self._lock = RLock()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._open_new_stream()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + self.terminator
            encoded = message.encode(self.encoding)
            with self._lock:
                if self._stream is None:
                    self._open_new_stream()
                if self._current_bytes > 0 and self._current_bytes + len(encoded) > self.max_bytes:
                    self._close_stream()
                    self._open_new_stream()
                self._stream.write(message)
                self._stream.flush()
                self._current_bytes += len(encoded)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            self._close_stream()
        super().close()

    def _open_new_stream(self) -> None:
        self.current_log_path = self._next_log_path()
        self._stream = self.current_log_path.open("a", encoding=self.encoding)
        self._current_bytes = self.current_log_path.stat().st_size

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _next_log_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        first = self.log_dir / f"{self.prefix}-{timestamp}.log"
        if not first.exists():
            return first
        index = 2
        while True:
            candidate = self.log_dir / f"{self.prefix}-{timestamp}-{index:03d}.log"
            if not candidate.exists():
                return candidate
            index += 1


def configure_logging(*, force: bool = False) -> LoggingSettings:
    global _CONFIGURED
    load_project_env()
    if _CONFIGURED and not force:
        existing = _managed_file_handler()
        return LoggingSettings(
            file_enabled=existing is not None,
            log_dir=_log_dir(),
            log_level=_log_level_name(),
            max_bytes=_max_bytes(),
            current_log_path=existing.current_log_path if existing else None,
        )

    if force:
        _remove_managed_handlers()

    level_name = _log_level_name()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    file_handler: TimestampRotatingFileHandler | None = None
    if _file_enabled():
        file_handler = TimestampRotatingFileHandler(
            _log_dir(),
            prefix=os.getenv("TRAVEL_LOG_FILE_PREFIX", DEFAULT_LOG_PREFIX),
            max_bytes=_max_bytes(),
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_MARKER, True)
        root_logger.addHandler(file_handler)
        _attach_file_handler_to_configured_uvicorn_loggers(file_handler, level)

    _CONFIGURED = True
    logging.getLogger("app").setLevel(level)
    logging.getLogger("app.core.logging").info(
        "logging_configured file_enabled=%s log_file=%s max_bytes=%s level=%s",
        file_handler is not None,
        file_handler.current_log_path if file_handler else None,
        _max_bytes(),
        level_name,
    )
    return LoggingSettings(
        file_enabled=file_handler is not None,
        log_dir=_log_dir(),
        log_level=level_name,
        max_bytes=_max_bytes(),
        current_log_path=file_handler.current_log_path if file_handler else None,
    )


def _file_enabled() -> bool:
    return _env_bool("TRAVEL_LOG_FILE_ENABLED", True)


def _log_dir() -> Path:
    raw = os.getenv("TRAVEL_LOG_DIR", "logs")
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _max_bytes() -> int:
    return _env_int("TRAVEL_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)


def _log_level_name() -> str:
    return os.getenv("TRAVEL_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _managed_file_handler() -> TimestampRotatingFileHandler | None:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, TimestampRotatingFileHandler) and getattr(handler, _HANDLER_MARKER, False):
            return handler
    return None


def _remove_managed_handlers() -> None:
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            if getattr(handler, _HANDLER_MARKER, False):
                logger.removeHandler(handler)
                handler.close()


def _attach_file_handler_to_configured_uvicorn_loggers(handler: logging.Handler, level: int) -> None:
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        if logger.handlers or not logger.propagate:
            logger.addHandler(handler)
