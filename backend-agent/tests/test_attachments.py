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
    counterpart_file_inventory,
    extract_urls,
    gallery_title,
    normalize_content_type,
    owner_and_recipient_requests,
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


def test_counterpart_file_inventory_lists_public_and_counts_the_rest() -> None:
    inventory = counterpart_file_inventory(
        [
            {
                "id": "pub-1",
                "kind": "file",
                "share_class": "public",
                "purpose": "listing_photos",
                "label": "Desk photo",
                "filename": "IMG_0042.JPG",
                "content_type": "image/jpeg",
                "url": "https://secret.example/file",
            },
            {
                "id": "pub-2",
                "kind": "file",
                "share_class": "public",
                "purpose": "listing_photos",
                "label": "Drawer",
                "content_type": "image/jpeg",
            },
            {
                "id": "per-1",
                "kind": "file",
                "share_class": "personal",
                "purpose": "id_document",
                "label": "Passport",
                "filename": "passport.jpg",
            },
            {
                "id": "pend-1",
                "kind": "file",
                "share_class": "pending",
                "label": "unknown",
            },
        ],
        shared_ids={"pub-2"},
    )
    assert inventory["personal_count"] == 1
    assert inventory["personal"] == [{"purpose": "id_document"}]
    assert inventory["pending_count"] == 1
    assert [item["id"] for item in inventory["public"]] == ["pub-1", "pub-2"]
    assert inventory["public"][0]["shared"] is False
    assert inventory["public"][1]["shared"] is True
    assert inventory["public"][0]["purpose"] == "listing_photos"
    assert inventory["public"][0]["label"] == "Desk photo"
    assert "filename" not in inventory["public"][0]
    assert "url" not in inventory["public"][0]
    assert "Passport" not in str(inventory)
    assert "passport.jpg" not in str(inventory)


def test_owner_and_recipient_is_the_file_holder_not_the_caller() -> None:
    source = type("R", (), {"id": "s", "session_id": "sess-s", "user_id": "u-s"})()
    candidate = type("R", (), {"id": "c", "session_id": "sess-c", "user_id": "u-c"})()
    seller_file = type("A", (), {"session_id": "sess-c", "user_id": "u-c"})()
    owner, recipient = owner_and_recipient_requests(source, candidate, seller_file)
    assert owner.id == "c"
    assert recipient.id == "s"
    buyer_file = type("A", (), {"session_id": "sess-s", "user_id": "u-s"})()
    owner, recipient = owner_and_recipient_requests(source, candidate, buyer_file)
    assert owner.id == "s"
    assert recipient.id == "c"


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


def test_gallery_title_collapses_numbered_photos() -> None:
    photos = [
        AgentAttachment(
            id=f"a{index}",
            user_id="u1",
            session_id="s1",
            kind="file",
            label=f"Royal Enfield GT650 photo {index}",
            content_type="image/jpeg",
            purpose="listing_photos",
            status="ready",
        )
        for index in (1, 2, 3)
    ]
    assert gallery_title(photos) == "Royal Enfield GT650"


async def test_memory_store_roundtrip() -> None:
    store = MemoryAttachmentStore()
    await store.put("u/s/a/file.pdf", b"%PDF", "application/pdf")
    data, content_type = await store.fetch("u/s/a/file.pdf")
    assert data == b"%PDF"
    assert content_type == "application/pdf"
    url = await store.sign("u/s/a/file.pdf")
    assert url.startswith("memory://")
    await store.delete("u/s/a/file.pdf")
    with pytest.raises(FileNotFoundError):
        await store.fetch("u/s/a/file.pdf")
