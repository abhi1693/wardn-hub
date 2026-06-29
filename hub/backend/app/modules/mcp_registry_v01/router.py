from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.registry.exceptions import (
    InvalidRegistryCursorError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.schemas import (
    RegistryServerRead,
    RegistryServerVersionRead,
)
from app.modules.registry.service import (
    get_version_detail,
    list_servers,
    list_versions,
    public_registry_json,
    registry_remotes_json,
)
from app.modules.users.dependencies import require_api_token_scopes
from app.modules.users.models import User

router = APIRouter(prefix="/v0.1", tags=["mcp-registry-v0.1"])

CatalogReadUser = Annotated[User, Depends(require_api_token_scopes("catalog:read"))]
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"
WARDN_META_KEY = "ai.wardn.hub"


class MCPRegistryV01ServerResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server: dict[str, Any]
    meta: dict[str, Any] = Field(alias="_meta")


class MCPRegistryV01ListMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    count: int
    next_cursor: str = Field(default="", alias="nextCursor")


class MCPRegistryV01ServerList(BaseModel):
    servers: list[MCPRegistryV01ServerResponse]
    metadata: MCPRegistryV01ListMetadata


def registry_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def icon_payload(icon: dict[str, Any]) -> dict[str, Any]:
    payload = dict(icon)
    mime_type = payload.pop("type", None)
    if mime_type and "mimeType" not in payload:
        payload["mimeType"] = mime_type

    sizes = payload.get("sizes")
    if isinstance(sizes, str):
        payload["sizes"] = [sizes] if sizes else []

    return payload


def server_document(
    server: RegistryServerRead,
    version: RegistryServerVersionRead,
) -> dict[str, Any]:
    document = public_registry_json(version.server_json)
    if not isinstance(document, dict):
        document = {}

    document.update(
        {
            "name": version.name,
            "description": version.description,
            "version": version.version,
            "packages": public_registry_json(version.packages),
            "remotes": public_registry_json(registry_remotes_json(version.remotes)),
        }
    )

    if version.title:
        document["title"] = version.title
    if version.repository:
        document["repository"] = public_registry_json(version.repository)
    if version.website_url:
        document["websiteUrl"] = version.website_url
    if version.icons:
        document["icons"] = [icon_payload(icon) for icon in public_registry_json(version.icons)]
    elif server.icons:
        document["icons"] = [icon_payload(icon) for icon in public_registry_json(server.icons)]

    return document


def server_response(
    server: RegistryServerRead,
    version: RegistryServerVersionRead,
) -> dict[str, Any]:
    official_meta: dict[str, Any] = {
        "status": version.status,
        "statusChangedAt": timestamp(version.status_changed_at),
        "publishedAt": timestamp(version.published_at),
        "updatedAt": timestamp(version.updated_at),
        "isLatest": version.is_latest,
    }
    if version.status_message:
        official_meta["statusMessage"] = version.status_message

    wardn_meta: dict[str, Any] = {
        "serverId": str(server.id),
        "versionId": str(version.id),
    }
    if version.quality_score is not None:
        wardn_meta["qualityScore"] = version.quality_score
    if version.trust_report is not None:
        wardn_meta["trustReport"] = version.trust_report.model_dump(by_alias=True, mode="json")

    return {
        "server": server_document(server, version),
        "_meta": {
            OFFICIAL_META_KEY: official_meta,
            WARDN_META_KEY: wardn_meta,
        },
    }


@router.get(
    "/servers",
    operation_id="mcp_registry_v01_servers_list",
    response_model=MCPRegistryV01ServerList,
)
async def list_registry_servers_v01(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: CatalogReadUser,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    include_deleted: bool = False,
) -> Any:
    _ = include_deleted
    try:
        response = await list_servers(
            session,
            cursor=cursor,
            limit=limit,
            search=search,
            updated_since=updated_since,
            version=version,
        )
    except InvalidRegistryCursorError:
        return registry_error(status.HTTP_400_BAD_REQUEST, "Invalid cursor")

    servers = []
    for server in response.servers:
        try:
            detail = await get_version_detail(session, server.name, version or "latest")
        except (RegistryServerNotFoundError, RegistryVersionNotFoundError):
            continue
        servers.append(server_response(detail.server, detail.version))

    return {
        "servers": servers,
        "metadata": {
            "count": len(servers),
            "nextCursor": response.metadata.next_cursor,
        },
    }


@router.get(
    "/servers/{server_name:path}/versions/{version}",
    operation_id="mcp_registry_v01_servers_get_version",
    response_model=MCPRegistryV01ServerResponse,
)
async def get_registry_server_version_v01(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: CatalogReadUser,
    include_deleted: bool = False,
) -> Any:
    _ = include_deleted
    try:
        detail = await get_version_detail(session, server_name, version)
    except RegistryServerNotFoundError:
        return registry_error(status.HTTP_404_NOT_FOUND, "Server not found")
    except RegistryVersionNotFoundError:
        return registry_error(status.HTTP_404_NOT_FOUND, "Server version not found")

    return server_response(detail.server, detail.version)


@router.get(
    "/servers/{server_name:path}/versions",
    operation_id="mcp_registry_v01_servers_list_versions",
    response_model=MCPRegistryV01ServerList,
)
async def list_registry_server_versions_v01(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: CatalogReadUser,
    include_deleted: bool = False,
) -> Any:
    _ = include_deleted
    try:
        response = await list_versions(session, server_name)
    except RegistryServerNotFoundError:
        return registry_error(status.HTTP_404_NOT_FOUND, "Server not found")

    servers = []
    server = None
    for version in response.versions:
        if server is None:
            try:
                detail = await get_version_detail(session, server_name, version.version)
            except (RegistryServerNotFoundError, RegistryVersionNotFoundError):
                continue
            server = detail.server
            servers.append(server_response(detail.server, detail.version))
        else:
            servers.append(server_response(server, version))

    return {
        "servers": servers,
        "metadata": {
            "count": len(servers),
            "nextCursor": "",
        },
    }
