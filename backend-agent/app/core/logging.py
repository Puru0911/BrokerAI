from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.core.config import settings

_CONFIGURED = False
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_NOISY_LOGGERS = (
    "uvicorn.access",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "httpx",
    "httpcore",
    "chromadb",
    "openai",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_groq",
)

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def clip(value: Any, limit: int = 800) -> str:
    """Compact a value for a single log line."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.split())
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
        text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def log_file_path() -> Path:
    path = Path(settings.LOG_FILE)
    if not path.is_absolute():
        path = _BACKEND_ROOT / path
    return path


def dated_log_path(base: Path, day: date | None = None) -> Path:
    """logs/brokerai.log -> logs/brokerai-2026-09-24.log"""
    stamp = (day or date.today()).isoformat()
    return base.with_name(f"{base.stem}-{stamp}{base.suffix}")


class DailyFileHandler(logging.FileHandler):
    """One log file per calendar day, named from LOG_FILE plus YYYY-MM-DD."""

    def __init__(self, base_path: str | Path, encoding: str = "utf-8") -> None:
        self.base_path = Path(base_path)
        self._current_date = date.today()
        self.base_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(
            str(dated_log_path(self.base_path, self._current_date)),
            encoding=encoding,
        )

    def emit(self, record: logging.LogRecord) -> None:
        today = date.today()
        if today != self._current_date:
            self._open_for_day(today)
        super().emit(record)

    def _open_for_day(self, day: date) -> None:
        if self.stream:
            self.flush()
            self.stream.close()
            self.stream = None
        self._current_date = day
        self.baseFilename = str(dated_log_path(self.base_path, day))
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        self.stream = self._open()


def configure_logging() -> Path:
    """Send app logs to a daily file and the console. Safe to call more than once."""
    global _CONFIGURED
    base = log_file_path()
    path = dated_log_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    level_name = (settings.LOG_LEVEL or "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    if _CONFIGURED:
        logging.getLogger().setLevel(level)
        return path

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler = DailyFileHandler(base)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(level)

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger(__name__).info("File logging at %s level=%s", path, level_name)
    return path
