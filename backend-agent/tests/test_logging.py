from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from app.core.logging import DailyFileHandler, dated_log_path


def test_dated_log_path_inserts_the_calendar_day() -> None:
    base = Path("/tmp/logs/brokerai.log")
    assert dated_log_path(base, date(2026, 9, 24)) == Path("/tmp/logs/brokerai-2026-09-24.log")


def test_daily_file_handler_writes_today_file(tmp_path: Path) -> None:
    base = tmp_path / "brokerai.log"
    handler = DailyFileHandler(base)
    handler.setFormatter(logging.Formatter("%(message)s"))
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello daily log",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    handler.close()
    expected = dated_log_path(base, date.today())
    assert expected.exists()
    assert "hello daily log" in expected.read_text()
    assert not base.exists()
