from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, BeforeValidator, Field

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_CLASSIFY_ATTACHMENT,
    TOOL_RECORD_SHARE_GRANT,
    TOOL_REQUEST_ATTACHMENT,
    TOOL_SHARE_ATTACHMENT,
)
from app.agents.tool_call_repair import coerce_str_list
from app.agents.tools._common import make_tool, owned_match
from app.db.models import AgentAttachment
from app.services.attachments import (
    PURPOSE_VALUES,
    SHARE_PERSONAL,
    SHARE_PUBLIC,
    classify_attachment,
    create_upload_request,
    pending_permission_exists,
    record_grant,
    request_share_permission,
    share_attachment_to_match,
    share_attachments_to_match,
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
    ] = Field(description="What kind of file or link would help this request.")
    suggested_share_class: Literal["public", "personal"] = Field(
        default="public",
        description="public can be shared into a match; personal moves after this person agrees.",
    )
    hint: str = Field(
        default="",
        max_length=400,
        description="Short plain-language ask shown on the upload control.",
    )


class ClassifyAttachmentArgs(BaseModel):
    attachment_id: str
    share_class: Literal["public", "personal"] = Field(
        description="public can be shared into a match; personal moves after this person agrees.",
    )
    label: str = Field(
        default="",
        max_length=160,
        description="Short human label for the file or link.",
    )
    purpose: Literal[
        "resume",
        "listing_photos",
        "portfolio",
        "id_document",
        "personal_photos",
        "other",
    ] = Field(
        default="other",
        description="What this file or link is for.",
    )


class ShareAttachmentArgs(BaseModel):
    match_id: str = Field(description="The match that should receive these files or links.")
    attachment_id: str | None = Field(
        default=None,
        description="One file to deliver. Prefer attachment_ids when sharing a set.",
    )
    attachment_ids: Annotated[list[str], BeforeValidator(coerce_str_list)] = Field(
        default_factory=list,
        description=(
            "All related files to deliver together (listing photos, a set of docs). "
            "They arrive as one gallery. Do not call once per photo."
        ),
    )


class RecordShareGrantArgs(BaseModel):
    match_id: str = Field(description="The match the personal file would be shared on.")
    attachment_id: str = Field(description="The personal file or link this person was asked about.")
    granted: bool = Field(
        default=True,
        description="True if this person agreed to share; false if they declined.",
    )


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


async def _match_attachment(
    ctx: ToolContext,
    attachment_id: str,
    current,
    other,
) -> AgentAttachment | None:
    attachment = await ctx.db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready":
        return None
    allowed_sessions = {current.session_id, other.session_id}
    if attachment.session_id not in allowed_sessions:
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
            outcome="Upload prompt shown in this chat.",
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
            outcome=f"Classified as {updated.share_class}.",
        )

    async def share_attachment(args: ShareAttachmentArgs) -> str:
        match, current, other, _source = await owned_match(ctx, args.match_id)
        if match.status not in {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}:
            return json_result(ok=False, error="This match is not open for sharing.")
        wanted_ids = list(dict.fromkeys([*(args.attachment_ids or []), args.attachment_id or ""]))
        wanted_ids = [item_id for item_id in wanted_ids if item_id]
        if not wanted_ids:
            return json_result(ok=False, error="Pass attachment_ids (a list) or attachment_id.")

        found: list[AgentAttachment] = []
        missing_ids: list[str] = []
        for item_id in wanted_ids:
            attachment = await _match_attachment(ctx, item_id, current, other)
            if attachment is None:
                missing_ids.append(item_id)
            else:
                found.append(attachment)
        if not found:
            return json_result(ok=False, error="Attachment not found on this match.")

        permission_ids: list[str] = []
        for attachment in found:
            owned_here = attachment.session_id == ctx.session.id
            if attachment.share_class != SHARE_PUBLIC and not owned_here:
                permission_ids.append(attachment.id)

        shares, message, statuses = await share_attachments_to_match(
            ctx.db,
            match=match,
            attachments=found,
            from_request=current,
        )
        for attachment in found:
            if statuses.get(attachment.id) != "needs_permission":
                continue
            owned_here = attachment.session_id == ctx.session.id
            if owned_here and not await pending_permission_exists(
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
            permission_ids.append(attachment.id)

        if message is not None and message.session_id == ctx.session.id:
            ctx.track(message)

        shared_ids = [item_id for item_id, status in statuses.items() if status == "shared"]
        already = [item_id for item_id, status in statuses.items() if status == "already_shared"]
        ok = bool(shared_ids or already) and not missing_ids
        if shared_ids:
            outcome = f"Delivered {len(shared_ids)} file(s) as one gallery."
        elif already and not permission_ids:
            outcome = "Those files were already shared."
            ok = True
        elif permission_ids and not shared_ids:
            outcome = "Permission requested for personal file(s). Nothing was delivered."
            ok = False
        else:
            outcome = "Could not share those files."
            ok = False
        return json_result(
            ok=ok,
            match_id=match.id,
            attachment_ids=wanted_ids,
            shared=shared_ids,
            already_shared=already,
            needs_permission=list(dict.fromkeys(permission_ids)),
            missing=missing_ids,
            share_ids=[share.id for share in shares],
            outcome=outcome,
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
                error="No pending permission request for this file on this match.",
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
            return json_result(
                ok=True,
                granted=False,
                attachment_id=attachment.id,
                outcome="Share refused. File not delivered.",
            )
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
            outcome=f"Grant recorded. Attachment {status}.",
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
