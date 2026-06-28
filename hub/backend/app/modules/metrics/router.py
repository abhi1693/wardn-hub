from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.metrics import service

router = APIRouter(include_in_schema=False)


@router.get("/metrics")
async def metrics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    database_metrics = await service.collect_database_metrics(session)
    process_metrics = service.process_metrics_text()
    return Response(
        content=f"{process_metrics}{database_metrics}",
        media_type=CONTENT_TYPE_LATEST,
    )
