from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_CLASSIFY_ATTACHMENT,
    TOOL_RECORD_SHARE_GRANT,
    TOOL_REQUEST_ATTACHMENT,
    TOOL_SHARE_ATTACHMENT,
)
from app.agents.tools._common import make_tool, owned_match
from app.db.models import AgentAttachment
from app.services.attachments import (
    PURPOSE_VALUES,
    SHARE_PERSONAL,
    classify_attachment,
    create_upload_request,
    pending_permission_exists,
    record_grant,
    request_share_permission,
    share_attachment_to_match,
)
from app.services.privacy import json_result
from app.services.workflow import MATCH_ACCEPTED, MATCH_CONNECTED, MATCH_OPEN


class RequestAttachmentArgs(BaseModel):
    purpose: Literal[
        "resume",
        "listing_photos",
        "portfolio",
        "id_document",
        "personal_photos",
        "other",
    ]
    suggested_share_class: Literal["public", "personal"] = "public"
    hint: str = Field(default="", max_length=400)


class ClassifyAttachmentArgs(BaseModel):
    attachment_id: str
    share_class: Literal["public", "personal"]
    label: str = Field(default="", max_length=160)
    purpose: Literal[
        "resume",
        "listing_photos",
        "portfolio",
        "id_document",
        "personal_photos",
        "other",
    ] = "other"


class ShareAttachmentArgs(BaseModel):
    match_id: str
    attachment_id: str


class RecordShareGrantArgs(BaseModel):
    match_id: str
    attachment_id: str
    granted: bool = True


async def _owned_session_attachment(ctx: ToolContext, attachment_id: str) -> AgentAttachment | None:
    attachment = await ctx.db.get(AgentAttachment, attachment_id)
    if (
        attachment is None
        or attachment.status != "ready"
        or attachment.session_id != ctx.session.id
        or attachment.user_id != ctx.profile.id
    ):
        return None
    return attachment


def build_attachment_tools(ctx: ToolContext) -> list[BaseTool]:
    async def request_attachment(args: RequestAttachmentArgs) -> str:
        if args.purpose not in PURPOSE_VALUES:
            return json_result(ok=False, error="Unknown attachment purpose.")
        _prompt, message = await create_upload_request(
            ctx.db,
            session_id=ctx.session.id,
            user_id=ctx.profile.id,
            purpose=args.purpose,
            suggested_share_class=args.suggested_share_class,
            hint=args.hint,
        )
        ctx.track(message)
        return json_result(
            ok=True,
            request_id=_prompt.id,
            purpose=args.purpose,
            hint="An upload prompt was shown to this user. Do not also ask in the final reply unless needed.",
        )

    async def classify(args: ClassifyAttachmentArgs) -> str:
        attachment = await _owned_session_attachment(ctx, args.attachment_id)
        if attachment is None:
            return json_result(ok=False, error="Attachment not found in this session.")
        updated = await classify_attachment(
            ctx.db,
            attachment,
            share_class=args.share_class,
            label=args.label or None,
            purpose=args.purpose,
        )
        return json_result(
            ok=True,
            attachment_id=updated.id,
            share_class=updated.share_class,
            label=updated.label,
            purpose=updated.purpose,
        )

    async def share_attachment(args: ShareAttachmentArgs) -> str:
        match, current, _other, _source = await owned_match(ctx, args.match_id)
        if match.status not in {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}:
            return json_result(ok=False, error="This match is not open for sharing.")
        attachment = await _owned_session_attachment(ctx, args.attachment_id)
        if attachment is None:
            return json_result(ok=False, error="Attachment not found in this session.")
        share, message, status = await share_attachment_to_match(
            ctx.db,
            match=match,
            attachment=attachment,
            from_request=current,
        )
        if status == "needs_permission":
            if not await pending_permission_exists(
                ctx.db, attachment_id=attachment.id, match_id=match.id
            ):
                prompt = await request_share_permission(
                    ctx.db,
                    session_id=ctx.session.id,
                    match=match,
                    attachment=attachment,
                    user_id=ctx.profile.id,
                )
                ctx.track(prompt)
            return json_result(
                ok=False,
                error="This file is personal. I asked this user for permission.",
                needs_permission=True,
                attachment_id=attachment.id,
                match_id=match.id,
            )
        if status == "match_closed":
            return json_result(ok=False, error="This match is not open for sharing.")
        if status == "missing":
            return json_result(ok=False, error="Could not share that file.")
        if message is not None and message.session_id == ctx.session.id:
            ctx.track(message)
        return json_result(
            ok=True,
            match_id=match.id,
            attachment_id=attachment.id,
            share_id=share.id if share else None,
            status=status,
        )

    async def record_share_grant(args: RecordShareGrantArgs) -> str:
        match, _current, _other, _source = await owned_match(ctx, args.match_id)
        attachment = await _owned_session_attachment(ctx, args.attachment_id)
        if attachment is None:
            return json_result(ok=False, error="Attachment not found in this session.")
        if attachment.share_class not in {SHARE_PERSONAL, "pending"}:
            return json_result(ok=False, error="A grant is only needed for personal files.")
        if not await pending_permission_exists(
            ctx.db, attachment_id=attachment.id, match_id=match.id
        ):
            return json_result(
                ok=False,
                error="Ask with share_attachment first so this user can grant permission.",
            )
        grant = await record_grant(
            ctx.db,
            attachment=attachment,
            match=match,
            user_id=ctx.profile.id,
            granted=args.granted,
            source="chat",
        )
        if not args.granted:
            return json_result(ok=True, granted=False, attachment_id=attachment.id)
        share, _delivered, status = await share_attachment_to_match(
            ctx.db,
            match=match,
            attachment=attachment,
            from_request=_current,
        )
        return json_result(
            ok=status in {"shared", "already_shared"},
            granted=True,
            grant_id=grant.id,
            status=status,
            share_id=share.id if share else None,
        )

    return [
        make_tool(
            name="request_attachment",
            description=TOOL_REQUEST_ATTACHMENT,
            args_model=RequestAttachmentArgs,
            handler=request_attachment,
        ),
        make_tool(
            name="classify_attachment",
            description=TOOL_CLASSIFY_ATTACHMENT,
            args_model=ClassifyAttachmentArgs,
            handler=classify,
        ),
        make_tool(
            name="share_attachment",
            description=TOOL_SHARE_ATTACHMENT,
            args_model=ShareAttachmentArgs,
            handler=share_attachment,
        ),
        make_tool(
            name="record_share_grant",
            description=TOOL_RECORD_SHARE_GRANT,
            args_model=RecordShareGrantArgs,
            handler=record_share_grant,
        ),
    ]
