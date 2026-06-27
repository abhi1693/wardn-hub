from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


def http_error(
    exc: Exception | None,
    status_code: int,
    *,
    detail: str | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail if detail is not None else str(exc or ""),
    )


def bad_request(exc: Exception | None = None, *, detail: str | None = None) -> HTTPException:
    return http_error(exc, status.HTTP_400_BAD_REQUEST, detail=detail)


def unauthorized(exc: Exception | None = None, *, detail: str | None = None) -> HTTPException:
    return http_error(exc, status.HTTP_401_UNAUTHORIZED, detail=detail)


def forbidden(exc: Exception | None = None, *, detail: str | None = None) -> HTTPException:
    return http_error(exc, status.HTTP_403_FORBIDDEN, detail=detail)


def not_found(exc: Exception | None = None, *, detail: str | None = None) -> HTTPException:
    return http_error(exc, status.HTTP_404_NOT_FOUND, detail=detail)


def conflict(exc: Exception | None = None, *, detail: str | None = None) -> HTTPException:
    return http_error(exc, status.HTTP_409_CONFLICT, detail=detail)


async def commit_session(session: AsyncSession) -> None:
    await session.commit()


async def commit_response[T](session: AsyncSession, response: T) -> T:
    await commit_session(session)
    return response


async def commit_and_refresh[T](session: AsyncSession, record: T) -> T:
    await commit_session(session)
    await session.refresh(record)
    return record
