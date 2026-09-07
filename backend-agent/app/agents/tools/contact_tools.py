from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.agents.context import ToolContext
from app.agents.prompts import TOOL_SHARE_CONTACTS
from app.agents.tools._common import make_tool, owned_match
from app.services.contact import share_match_contacts
from app.services.privacy import json_result
from app.services.workflow import MATCH_ACCEPTED, MATCH_CONNECTED


class ShareContactsArgs(BaseModel):
    match_id: str


def build_contact_tools(ctx: ToolContext) -> list[BaseTool]:
    async def share_contacts(args: ShareContactsArgs) -> str:
        match, _current, _other, _source = await owned_match(ctx, args.match_id)
        if match.status not in {MATCH_ACCEPTED, MATCH_CONNECTED}:
            return json_result(ok=False, error="Both parties must accept before contacts can be shared.")
        messages = await share_match_contacts(ctx.db, match)
        for message in messages:
            ctx.track(message)
        return json_result(ok=True, match_id=match.id, contact_cards=len(messages))

    return [
        make_tool(
            name="share_contacts",
            description=TOOL_SHARE_CONTACTS,
            args_model=ShareContactsArgs,
            handler=share_contacts,
        )
    ]
