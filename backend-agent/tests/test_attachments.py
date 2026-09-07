from __future__ import annotations

import json

import pytest

from app.db.models import AgentAttachment
from app.services.attachments import (
    ATTACHMENT_PERMISSION_KIND,
    ATTACHMENT_REQUEST_KIND,
    ATTACHMENT_SHARE_KIND,
    AttachmentError,
    can_share_directly,
    extract_urls,
    normalize_content_type,
    parse_structured_card,
    sanitize_filename,
    upload_notice,
)
from app.services.storage import MemoryAttachmentStore


def test_sanitize_filename_strips_paths_and_unsafe_chars() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("My Resume (final).pdf") == "My_Resume_final_.pdf"
    assert sanitize_filename("") == "upload"


def test_normalize_content_type_accepts_allowlist() -> None:
    assert normalize_content_type("image/jpeg", "apt.jpg") == "image/jpeg"
    assert normalize_content_type("application/pdf", "cv.pdf") == "application/pdf"
    assert normalize_content_type(None, "photo.webp") == "image/webp"


def test_normalize_content_type_rejects_mismatch_and_unknown() -> None:
    with pytest.raises(AttachmentError):
        normalize_content_type("image/jpeg", "notes.pdf")
    with pytest.raises(AttachmentError):
        normalize_content_type("application/zip", "archive.zip")


def test_can_share_directly_only_public() -> None:
    assert can_share_directly("public") is True
    assert can_share_directly("personal") is False
    assert can_share_directly("pending") is False


def test_extract_urls_dedupes_and_strips_punctuation() -> None:
    text = "See https://example.com/listing and https://example.com/listing, plus http://foo.test/a."
    assert extract_urls(text) == ["https://example.com/listing", "http://foo.test/a"]


def test_upload_notice_prefers_caption() -> None:
    item = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        original_filename="resume.pdf",
        label="resume.pdf",
        status="ready",
    )
    assert upload_notice([item], "Here is my CV") == "Here is my CV"
    assert upload_notice([item], "") == "Uploaded a file: resume.pdf"


def test_parse_structured_cards() -> None:
    request = {
        "kind": ATTACHMENT_REQUEST_KIND,
        "version": 1,
        "request_id": "r1",
        "purpose": "resume",
    }
    permission = {
        "kind": ATTACHMENT_PERMISSION_KIND,
        "version": 1,
        "match_id": "m1",
        "attachment_id": "a1",
    }
    share = {
        "kind": ATTACHMENT_SHARE_KIND,
        "version": 1,
        "match_id": "m1",
        "attachments": [],
    }
    assert parse_structured_card(json.dumps(request))["purpose"] == "resume"
    assert parse_structured_card(json.dumps(permission))["attachment_id"] == "a1"
    assert parse_structured_card(json.dumps(share))["match_id"] == "m1"
    assert parse_structured_card("hello") is None
    assert parse_structured_card(json.dumps({"kind": "broker_contact_card", "version": 1})) is None


async def test_memory_store_roundtrip() -> None:
    store = MemoryAttachmentStore()
    await store.put("u/s/a/file.pdf", b"%PDF", "application/pdf")
    url = await store.sign("u/s/a/file.pdf")
    assert url.startswith("memory://")
    await store.delete("u/s/a/file.pdf")
    with pytest.raises(FileNotFoundError):
        await store.sign("u/s/a/file.pdf")
