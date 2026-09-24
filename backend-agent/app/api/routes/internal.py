from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_job_secret
from app.db.models import AgentMatch
from app.db.session import get_db
from app.schemas.broker import BrokerMatchRead
from app.services.orchestrator import process_stale_matches
from app.services.outreach import schedule_outreach

router = APIRouter()


@router.post(
    "/process-stale",
    response_model=list[BrokerMatchRead],
    dependencies=[Depends(require_job_secret)],
)
async def process_stale_route(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[AgentMatch]:
    stale, outreach = await process_stale_matches(db, min(max(limit, 1), 100))
    await db.commit()
    schedule_outreach(outreach)
    for match in stale:
        await db.refresh(match)
    return stale
