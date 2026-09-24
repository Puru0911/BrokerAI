from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agents.context import ToolContext
from app.agents.prompts import TOOL_THINK
from app.agents.tools._common import make_tool
from app.core.logging import clip
from app.services.privacy import json_result

logger = logging.getLogger(__name__)


class ThinkArgs(BaseModel):
    note: str = Field(
        min_length=1,
        max_length=1200,
        description="A private working note for this turn. Discarded afterward.",
    )


def build_think_tools(ctx: ToolContext) -> list[BaseTool]:
    async def think(args: ThinkArgs) -> str:
        logger.info("think session=%s note=%s", ctx.session.id, clip(args.note, 300))
        return json_result(ok=True, outcome="Private note recorded for this turn. Not persisted.")

    return [
        make_tool(name="think", description=TOOL_THINK, args_model=ThinkArgs, handler=think),
    ]
