from __future__ import annotations

import logging
import re

from app.core.logging import TimestampRotatingFileHandler, configure_logging


def test_timestamp_rotating_file_handler_creates_timestamp_named_files(tmp_path):
    handler = TimestampRotatingFileHandler(tmp_path, prefix="debug", max_bytes=80)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("app.tests.timestamp_rotating_file_handler")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        logger.info("first-%s", "x" * 60)
        first_path = handler.current_log_path
        logger.info("second-%s", "y" * 60)
        second_path = handler.current_log_path
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.propagate = True

    assert first_path is not None
    assert second_path is not None
    assert first_path != second_path
    assert re.match(r"debug-\d{8}-\d{6}(?:-\d{3})?\.log", first_path.name)
    assert re.match(r"debug-\d{8}-\d{6}(?:-\d{3})?\.log", second_path.name)
    assert first_path.stat().st_size <= 80
    assert second_path.stat().st_size <= 80


def test_configure_logging_uses_env_file_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAVEL_LOG_FILE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TRAVEL_LOG_FILE_PREFIX", "backend-test")
    monkeypatch.setenv("TRAVEL_LOG_LEVEL", "INFO")
    monkeypatch.setenv("TRAVEL_LOG_MAX_BYTES", "1000")

    settings = configure_logging(force=True)
    logger = logging.getLogger("app.tests.configure_logging")
    logger.info("configured logging test message")

    try:
        assert settings.file_enabled is True
        assert settings.log_dir == tmp_path
        assert settings.max_bytes == 1000
        assert settings.current_log_path is not None
        assert settings.current_log_path.exists()
        assert settings.current_log_path.name.startswith("backend-test-")
        assert "configured logging test message" in settings.current_log_path.read_text(encoding="utf-8")
    finally:
        monkeypatch.setenv("TRAVEL_LOG_FILE_ENABLED", "false")
        configure_logging(force=True)
