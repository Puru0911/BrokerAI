from app.services.titles import create_summary, create_title


def test_create_title_truncates_long_requests() -> None:
    title = create_title("I need a designer " * 20)
    assert title.endswith("...")
    assert len(title) <= 76


def test_create_title_falls_back_when_empty() -> None:
    assert create_title(None) == "New broker request"
    assert create_title("   ") == "New broker request"


def test_create_summary_compacts_whitespace() -> None:
    assert create_summary("Need   a\nflat") == "Need a flat"
