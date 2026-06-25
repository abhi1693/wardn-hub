import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.schemas import ErrorResponse
from app.modules.imports.exceptions import SourceNotFoundError, UnsupportedSourceError
from app.modules.imports.schemas import ServerSourceImportRequest, ServerSourceImportResponse
from app.modules.imports.service import import_server_source
from app.modules.users.dependencies import require_api_token_scopes
from app.modules.users.models import User

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post(
    "/server-source",
    response_model=ServerSourceImportResponse,
    operation_id="imports_server_source",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def import_server_source_endpoint(
    payload: ServerSourceImportRequest,
    _current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> ServerSourceImportResponse:
    try:
        return await asyncio.to_thread(import_server_source, payload)
    except UnsupportedSourceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
