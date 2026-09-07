from __future__ import annotations

import re

WELCOME_MESSAGE = "Looking for someone or something specific? Tell me, and I'll get started."


def create_title(message: str | None) -> str:
    if not message:
        return "New broker request"
    normalized = " ".join(message.strip().split())
    if not normalized:
        return "New broker request"
    title = normalized[:72].rstrip(" .,")
    return title if len(normalized) <= 72 else f"{title}..."


def create_summary(text: str | None) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return compact[:1000]
