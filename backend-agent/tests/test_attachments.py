from __future__ import annotations

import json

import pytest

from unittest.mock import AsyncMock

from app.db.models import AgentAttachment, AgentAttachmentRequest
from app.services.attachments import (
    ATTACHMENT_PERMISSION_KIND,
    ATTACHMENT_REQUEST_KIND,
    ATTACHMENT_SHARE_KIND,
    AttachmentError,
    _share_card_item,
    apply_permission_grant_status,
    blur_image_bytes,
    blur_storage_key,
    can_share_directly,
    classify_attachment,
    counterpart_file_inventory,
    extract_urls,
    fulfill_upload_request,
    gallery_title,
    generic_file_label,
    is_device_filename,
    model_facing_label,
    normalize_content_type,
    owner_and_recipient_requests,
    parse_structured_card,
    placeholder_blur_jpeg,
    sanitize_filename,
    stored_basename,
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
                "caption": "these are the room photos",
                "description": "Listing photos of the Baner PG",
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
    assert inventory["public"][0]["owner"] == "counterpart"
    assert inventory["public"][1]["shared"] is True
    assert inventory["public"][0]["purpose"] == "listing_photos"
    assert inventory["public"][0]["label"] == "Desk photo"
    assert inventory["public"][0]["description"] == "Listing photos of the Baner PG"
    assert "caption" not in inventory["public"][0]
    assert "filename" not in inventory["public"][0]
    assert "url" not in inventory["public"][0]
    assert "these are the room photos" not in str(inventory)
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


def test_generic_file_label_never_uses_the_device_name() -> None:
    assert generic_file_label("application/pdf", "resume") == "Resume"
    assert generic_file_label("image/jpeg", "listing_photos") == "Photo"
    assert generic_file_label("application/pdf", None) == "PDF"
    assert stored_basename("image/jpeg", "IMG_6181.jpeg") == "file.jpeg"
    assert stored_basename("application/pdf", "My Resume (final).pdf") == "file.pdf"
    assert is_device_filename("IMG_6181.jpeg") is True
    assert is_device_filename("Royal Enfield GT650") is False
    assert is_device_filename("Photo", "IMG_6181.jpeg") is False
    assert is_device_filename("My_Resume_final_.pdf", "My_Resume_final_.pdf") is True


def test_model_facing_label_strips_device_filenames() -> None:
    leaked = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        content_type="image/jpeg",
        original_filename="IMG_6181.jpeg",
        label="IMG_6181.jpeg",
        purpose="listing_photos",
        status="ready",
    )
    named = AgentAttachment(
        id="a2",
        user_id="u1",
        session_id="s1",
        kind="file",
        content_type="image/jpeg",
        original_filename="IMG_6181.jpeg",
        label="Royal Enfield GT650",
        purpose="listing_photos",
        status="ready",
    )
    assert model_facing_label(leaked) == "Photo"
    assert model_facing_label(named) == "Royal Enfield GT650"


def test_upload_notice_prefers_caption() -> None:
    item = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        content_type="application/pdf",
        original_filename="resume.pdf",
        label="Resume",
        status="ready",
    )
    photo = AgentAttachment(
        id="a2",
        user_id="u1",
        session_id="s1",
        kind="file",
        content_type="image/jpeg",
        original_filename="IMG_6181.jpeg",
        label="Photo",
        status="ready",
    )
    assert upload_notice([item], "Here is my CV") == "Here is my CV"
    assert upload_notice([item], "") == "Uploaded a file."
    assert upload_notice([photo], "") == "Uploaded a photo."
    assert upload_notice([photo, photo], "") == "Uploaded 2 photos."
    assert "resume.pdf" not in upload_notice([item], "")
    assert "IMG_6181.jpeg" not in upload_notice([photo], "")


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


def test_apply_permission_grant_status_stamps_card() -> None:
    content = json.dumps(
        {
            "kind": ATTACHMENT_PERMISSION_KIND,
            "version": 1,
            "match_id": "m1",
            "attachment_id": "a1",
            "label": "face photo",
        }
    )
    granted = apply_permission_grant_status(content, "granted")
    payload = json.loads(granted)
    assert payload["status"] == "granted"
    assert payload["attachment_id"] == "a1"
    assert apply_permission_grant_status(content, None) == content
    assert apply_permission_grant_status("hello", "granted") == "hello"


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


def test_gallery_title_ignores_device_filenames() -> None:
    photos = [
        AgentAttachment(
            id=f"a{index}",
            user_id="u1",
            session_id="s1",
            kind="file",
            label=f"IMG_618{index}.jpeg",
            original_filename=f"IMG_618{index}.jpeg",
            content_type="image/jpeg",
            purpose="listing_photos",
            status="ready",
        )
        for index in (1, 2, 3)
    ]
    assert gallery_title(photos) == "Listing photos"
    assert "IMG_618" not in gallery_title(photos)


def test_gallery_title_uses_shared_description_when_labels_are_generic() -> None:
    photos = [
        AgentAttachment(
            id=f"a{index}",
            user_id="u1",
            session_id="s1",
            kind="file",
            label="Photo",
            content_type="image/jpeg",
            description="Room photos of the Baner PG",
            status="ready",
        )
        for index in (1, 2)
    ]
    assert gallery_title(photos) == "Room photos of the Baner PG"


def test_share_card_item_omits_original_filename() -> None:
    item = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        label="IMG_6181.jpeg",
        original_filename="IMG_6181.jpeg",
        content_type="image/jpeg",
        purpose="listing_photos",
        share_class="public",
        caption="these are the room photos",
        description="Listing photos of the Baner PG",
        status="ready",
    )
    payload = _share_card_item(item)
    assert "original_filename" not in payload
    assert "filename" not in payload
    assert "caption" not in payload
    assert payload["label"] == "Photo"
    assert payload["description"] == "Listing photos of the Baner PG"
    assert payload["id"] == "a1"


@pytest.mark.asyncio
async def test_classify_attachment_writes_description_and_keeps_caption() -> None:
    db = AsyncMock()
    item = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        content_type="image/jpeg",
        caption="these are the room photos",
        description=None,
        share_class="pending",
        status="ready",
    )
    updated = await classify_attachment(
        db,
        item,
        share_class="public",
        label="Baner PG",
        purpose="listing_photos",
        description="Listing photos of the Baner PG sent after we asked for rooms.",
    )
    assert updated.caption == "these are the room photos"
    assert updated.description == (
        "Listing photos of the Baner PG sent after we asked for rooms."
    )
    assert updated.share_class == "public"
    assert updated.purpose == "listing_photos"
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_fulfill_upload_request_does_not_copy_hint_into_description() -> None:
    prompt = AgentAttachmentRequest(
        id="r1",
        session_id="s1",
        user_id="u1",
        purpose="resume",
        hint="A recent resume helps.",
        status="pending",
    )
    item = AgentAttachment(
        id="a1",
        user_id="u1",
        session_id="s1",
        kind="file",
        caption=None,
        description=None,
        status="ready",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=prompt)
    await fulfill_upload_request(db, "r1", item)
    assert item.purpose == "resume"
    assert item.description is None
    assert item.caption is None


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


def test_blur_storage_key_sits_next_to_the_original() -> None:
    assert blur_storage_key("user/session/att/file.jpg") == "user/session/att/blur.jpg"
    assert blur_storage_key("file.jpg") == "blur.jpg"


def test_blur_image_bytes_returns_jpeg_smaller_than_source() -> None:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (240, 240), (180, 40, 40)).save(buffer, format="JPEG", quality=90)
    original = buffer.getvalue()
    blurred = blur_image_bytes(original)
    assert blurred != original
    assert blurred[:2] == b"\xff\xd8"
    placeholder = placeholder_blur_jpeg()
    assert placeholder[:2] == b"\xff\xd8"
