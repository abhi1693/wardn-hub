from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.users.exceptions import BootstrapUserExistsError
from app.modules.users.schemas import BootstrapUserCreate, UserRead
from app.modules.users.service import bootstrap_superuser

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/bootstrap",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="users_bootstrap",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def bootstrap_user(
    payload: BootstrapUserCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    try:
        user = await bootstrap_superuser(session, payload)
    except BootstrapUserExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="bootstrap user already exists",
        ) from exc
    return UserRead.model_validate(user)

