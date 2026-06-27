from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router import bad_request, commit_response, commit_session, forbidden, not_found
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.events.exceptions import (
    EventAccessDeniedError,
    EventDeliveryError,
    EventDeliveryNotFoundError,
    EventRuleNotFoundError,
    EventValidationError,
)
from app.modules.events.schemas import (
    EventDeliveryListResponse,
    EventDeliveryRead,
    EventRuleCreate,
    EventRuleListResponse,
    EventRuleRead,
    EventRuleUpdate,
    EventSecretRotateResponse,
    EventTypeListResponse,
)
from app.modules.events.service import (
    create_rule,
    delete_rule,
    get_delivery,
    get_rule,
    list_deliveries,
    list_event_types,
    list_rules,
    replay_delivery,
    rotate_rule_secret,
    test_rule_delivery,
    update_rule,
)
from app.modules.users.dependencies import get_request_api_token, require_api_token_scopes
from app.modules.users.models import User

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/types", response_model=EventTypeListResponse, operation_id="events_types_list")
async def list_event_type_records(
    _current_user: Annotated[User, Depends(require_api_token_scopes("events:read"))],
) -> EventTypeListResponse:
    return await list_event_types()


@router.get("/rules", response_model=EventRuleListResponse, operation_id="events_rules_list")
async def list_event_rule_records(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:read"))],
) -> EventRuleListResponse:
    return await list_rules(session, current_user, api_token=get_request_api_token(request))


@router.post(
    "/rules",
    response_model=EventRuleRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="events_rules_create",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
async def create_event_rule_record(
    request: Request,
    payload: EventRuleCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> EventRuleRead:
    try:
        response = await create_rule(
            session,
            current_user,
            payload,
            api_token=get_request_api_token(request),
        )
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except EventValidationError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.get(
    "/rules/{rule_id}",
    response_model=EventRuleRead,
    operation_id="events_rules_get",
)
async def get_event_rule_record(
    rule_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:read"))],
) -> EventRuleRead:
    try:
        return await get_rule(
            session,
            current_user,
            rule_id,
            api_token=get_request_api_token(request),
        )
    except EventRuleNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.put(
    "/rules/{rule_id}",
    response_model=EventRuleRead,
    operation_id="events_rules_update",
)
async def update_event_rule_record(
    rule_id: UUID,
    request: Request,
    payload: EventRuleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> EventRuleRead:
    try:
        response = await update_rule(
            session,
            current_user,
            rule_id,
            payload,
            api_token=get_request_api_token(request),
        )
    except EventRuleNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except EventValidationError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="events_rules_delete",
)
async def delete_event_rule_record(
    rule_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> None:
    try:
        await delete_rule(
            session,
            current_user,
            rule_id,
            api_token=get_request_api_token(request),
        )
    except EventRuleNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    await commit_session(session)


@router.post(
    "/rules/{rule_id}/test",
    response_model=EventDeliveryRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="events_rules_test",
)
async def test_event_rule_record(
    rule_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> EventDeliveryRead:
    try:
        response = await test_rule_delivery(
            session,
            current_user,
            rule_id,
            api_token=get_request_api_token(request),
        )
    except EventRuleNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    return await commit_response(session, response)


@router.post(
    "/rules/{rule_id}/rotate-secret",
    response_model=EventSecretRotateResponse,
    operation_id="events_rules_rotate_secret",
)
async def rotate_event_rule_secret(
    rule_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> EventSecretRotateResponse:
    try:
        response = await rotate_rule_secret(
            session,
            current_user,
            rule_id,
            api_token=get_request_api_token(request),
        )
    except EventRuleNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    return await commit_response(session, response)


@router.get(
    "/deliveries",
    response_model=EventDeliveryListResponse,
    operation_id="events_deliveries_list",
)
async def list_event_delivery_records(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    rule_id: Annotated[UUID | None, Query()] = None,
) -> EventDeliveryListResponse:
    return await list_deliveries(
        session,
        current_user,
        api_token=get_request_api_token(request),
        limit=limit,
        rule_id=rule_id,
    )


@router.get(
    "/deliveries/{delivery_id}",
    response_model=EventDeliveryRead,
    operation_id="events_deliveries_get",
)
async def get_event_delivery_record(
    delivery_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:read"))],
) -> EventDeliveryRead:
    try:
        return await get_delivery(
            session,
            current_user,
            delivery_id,
            api_token=get_request_api_token(request),
        )
    except EventDeliveryNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.post(
    "/deliveries/{delivery_id}/replay",
    response_model=EventDeliveryRead,
    operation_id="events_deliveries_replay",
)
async def replay_event_delivery_record(
    delivery_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("events:write"))],
) -> EventDeliveryRead:
    try:
        response = await replay_delivery(
            session,
            current_user,
            delivery_id,
            api_token=get_request_api_token(request),
        )
    except EventDeliveryNotFoundError as exc:
        raise not_found(exc) from exc
    except EventAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except EventDeliveryError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)
