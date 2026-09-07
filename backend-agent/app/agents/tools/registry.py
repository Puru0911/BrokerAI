from __future__ import annotations

from langchain_core.tools import BaseTool

from app.agents.context import ToolContext
from app.agents.tools.attachment_tools import build_attachment_tools
from app.agents.tools.contact_tools import build_contact_tools
from app.agents.tools.match_tools import build_match_tools
from app.agents.tools.request_tools import build_request_tools
from app.agents.tools.search_tools import build_search_tools
from app.agents.tools.think_tools import build_think_tools


def build_broker_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        *build_think_tools(ctx),
        *build_request_tools(ctx),
        *build_search_tools(ctx),
        *build_match_tools(ctx),
        *build_contact_tools(ctx),
        *build_attachment_tools(ctx),
    ]
