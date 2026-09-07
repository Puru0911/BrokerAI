from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
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


def configure_logging() -> Path:
    """Send app logs to a rotating file and the console. Safe to call more than once."""
    global _CONFIGURED
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    level_name = (settings.LOG_LEVEL or "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    if _CONFIGURED:
        logging.getLogger().setLevel(level)
        return path

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler = RotatingFileHandler(
        path,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
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
