import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.modules.skills.exceptions import SkillAuditNotFoundError, SkillNotFoundError
from app.modules.skills.service import get_skill_audit, get_skill_detail, search_skills
from app.modules.users.dependencies import require_bearer_api_token_scopes
from app.modules.users.models import User

router = APIRouter(prefix="/mcp-server", tags=["mcp-server"])
logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_MCP_PROTOCOL_VERSIONS = frozenset({"2025-11-25", "2025-06-18", "2025-03-26"})
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

MCP_ENDPOINT_DESCRIPTION = """
Streamable HTTP MCP endpoint for read-only Wardn Hub skill discovery.

Send one JSON-RPC 2.0 message per HTTP POST. The endpoint requires a bearer
Wardn Hub API token with the `skills:read` scope. It accepts initialization,
tool discovery, tool calls, pings, notifications, and client JSON-RPC responses.

This endpoint only reads Wardn Hub skill catalog data. It never installs skills,
executes skill scripts, invokes registered MCP servers, mutates registry records,
or proxies third-party tools.
"""

MCP_REQUEST_BODY_OPENAPI: dict[str, Any] = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": True,
                "description": "A single JSON-RPC 2.0 request, notification, or response.",
            },
            "examples": {
                "initialize": {
                    "summary": "Initialize the MCP session",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {},
                            "clientInfo": {"name": "example-client", "version": "1.0.0"},
                        },
                    },
                },
                "toolsList": {
                    "summary": "List available read-only tools",
                    "value": {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                },
                "searchSkills": {
                    "summary": "Search Wardn Hub skills",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "search_skills",
                            "arguments": {
                                "query": "code review",
                                "limit": 5,
                                "auditStatus": "pass",
                            },
                        },
                    },
                },
                "getSkillAudit": {
                    "summary": "Read a hash-pinned skill audit",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "get_skill_audit",
                            "arguments": {
                                "skillId": "owner/repository/skill-slug",
                                "contentHash": "a" * 64,
                            },
                        },
                    },
                },
                "initializedNotification": {
                    "summary": "Initialized notification",
                    "value": {"jsonrpc": "2.0", "method": "notifications/initialized"},
                },
            },
        }
    },
}

MCP_SUCCESS_RESPONSE_OPENAPI: dict[str, Any] = {
    "description": "JSON-RPC response.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": True,
                "required": ["jsonrpc", "id"],
                "properties": {
                    "jsonrpc": {"type": "string", "const": "2.0"},
                    "id": {"oneOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
                    "result": {"type": "object", "additionalProperties": True},
                    "error": {"type": "object", "additionalProperties": True},
                },
            },
            "examples": {
                "initialize": {
                    "summary": "Initialize response",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {
                                "name": "wardn-hub-skills",
                                "title": "Wardn Hub Skills",
                                "version": "0.2.169",
                            },
                            "instructions": (
                                "Use this server only for read-only Wardn Hub skill discovery "
                                "and inspection. It does not install skills, invoke registered "
                                "MCP servers, or mutate Wardn Hub records."
                            ),
                        },
                    },
                },
                "toolsList": {
                    "summary": "Tools list response",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "tools": [
                                {
                                    "name": "search_skills",
                                    "title": "Search Wardn Hub Skills",
                                    "description": "Search the public Wardn Hub skill catalog.",
                                    "inputSchema": {
                                        "type": "object",
                                        "required": ["query"],
                                        "properties": {"query": {"type": "string"}},
                                    },
                                    "annotations": {"readOnlyHint": True},
                                }
                            ]
                        },
                    },
                },
                "toolCall": {
                    "summary": "Tool call response",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": '{\n  "count": 1,\n  "data": []\n}',
                                }
                            ],
                            "structuredContent": {"count": 1, "data": []},
                            "isError": False,
                        },
                    },
                },
            },
        }
    },
}

MCP_BAD_REQUEST_RESPONSE_OPENAPI: dict[str, Any] = {
    "description": "Invalid MCP transport request.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": True,
                "description": "JSON-RPC error response or FastAPI detail response.",
            },
            "examples": {
                "parseError": {
                    "summary": "Malformed JSON",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": JSONRPC_PARSE_ERROR, "message": "Parse error"},
                    },
                },
                "invalidRequest": {
                    "summary": "Invalid JSON-RPC request",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": JSONRPC_INVALID_REQUEST,
                            "message": "request must be a JSON-RPC 2.0 object",
                        },
                    },
                },
                "unsupportedProtocol": {
                    "summary": "Unsupported MCP protocol header",
                    "value": {"detail": "unsupported MCP protocol version"},
                },
            }
        }
    },
}

MCP_UNAUTHORIZED_RESPONSE_OPENAPI: dict[str, Any] = {
    "description": "API token authentication required.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["detail"],
                "properties": {"detail": {"type": "string"}},
            },
            "examples": {
                "missingBearer": {
                    "summary": "Missing or invalid bearer token",
                    "value": {"detail": "API token authentication required"},
                }
            },
        }
    },
}

MCP_FORBIDDEN_RESPONSE_OPENAPI: dict[str, Any] = {
    "description": "API token missing skills:read scope.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["detail"],
                "properties": {"detail": {"type": "string"}},
            },
            "examples": {
                "missingScope": {
                    "summary": "Token missing skills:read",
                    "value": {"detail": "API token missing required scope: skills:read"},
                }
            },
        }
    },
}


class SearchSkillsArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query: str = Field(min_length=3, max_length=200)
    limit: int = Field(default=8, ge=1, le=25)
    owner: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    audit_status: Literal["pass", "warn", "fail"] | None = Field(
        default=None,
        alias="auditStatus",
    )
    official: bool | None = None
    cursor: str | None = Field(default=None, max_length=2048)


class SkillLookupArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    skill_id: str = Field(alias="skillId", min_length=3, max_length=300)
    content_hash: str | None = Field(
        default=None,
        alias="contentHash",
        pattern=r"^[a-f0-9]{64}$",
    )


class GetSkillArguments(SkillLookupArguments):
    include_bundle: bool = Field(default=False, alias="includeBundle")


def tool_annotations() -> dict[str, Any]:
    return {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }


def tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_skills",
            "title": "Search Wardn Hub Skills",
            "description": (
                "Search the public Wardn Hub skill catalog when an agent needs to find "
                "reusable agent skills. Returns compact metadata, stable skill IDs, audit "
                "status, source links, and pagination cursor. Use get_skill before relying "
                "on a result's instructions, and get_skill_audit before installing or applying it."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 200,
                        "description": (
                            "Catalog search terms such as 'code review' or 'playwright'."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 25,
                        "default": 8,
                    },
                    "owner": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                        "description": "Optional publisher or source owner filter.",
                    },
                    "category": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                        "description": "Optional existing Wardn category slug or name filter.",
                    },
                    "auditStatus": {
                        "type": "string",
                        "enum": ["pass", "warn", "fail"],
                        "description": "Optional current audit status filter.",
                    },
                    "official": {
                        "type": "boolean",
                        "description": "Filter to official publishers when true.",
                    },
                    "cursor": {
                        "type": "string",
                        "maxLength": 2048,
                        "description": "Cursor returned by a previous search_skills call.",
                    },
                },
                "required": ["query"],
            },
            "annotations": tool_annotations(),
        },
        {
            "name": "get_skill",
            "title": "Get Wardn Hub Skill",
            "description": (
                "Read one Wardn Hub skill snapshot by stable skill ID. By default this returns "
                "snapshot metadata and SKILL.md only; set includeBundle only when the user needs "
                "all retained package files. This never installs, updates, removes, or executes "
                "a skill."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "skillId": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 300,
                        "description": (
                            "Skill ID in source/slug form, for example owner/repo/skill."
                        ),
                    },
                    "contentHash": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                        "description": "Optional retained snapshot hash.",
                    },
                    "includeBundle": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return every retained file instead of just SKILL.md.",
                    },
                },
                "required": ["skillId"],
            },
            "annotations": tool_annotations(),
        },
        {
            "name": "get_skill_audit",
            "title": "Get Wardn Hub Skill Audit",
            "description": (
                "Read the Cisco audit for a Wardn Hub skill. Use this before applying, fetching, "
                "or recommending a skill; pass contentHash to verify a specific snapshot."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "skillId": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 300,
                        "description": (
                            "Skill ID in source/slug form, for example owner/repo/skill."
                        ),
                    },
                    "contentHash": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                        "description": "Optional retained snapshot hash.",
                    },
                },
                "required": ["skillId"],
            },
            "annotations": tool_annotations(),
        },
    ]


def jsonrpc_response(
    request_id: str | int | None,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result or {}
    return JSONResponse(body)


def jsonrpc_error(
    request_id: str | int | None,
    code: int,
    message: str,
    *,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    response = jsonrpc_response(request_id, error={"code": code, "message": message})
    response.status_code = status_code
    return response


def validation_error_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = first.get("msg", "invalid value")
    return f"{location}: {message}" if location else message


def structured_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    encoded = jsonable_encoder(value)
    return encoded if isinstance(encoded, dict) else {"data": encoded}


def tool_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    structured = structured_payload(value)
    text = json.dumps(structured, ensure_ascii=False, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": is_error,
    }


def tool_error(message: str, *, code: str = "not_found") -> dict[str, Any]:
    return tool_result({"error": {"code": code, "message": message}}, is_error=True)


def validate_protocol_version(protocol_version: str | None) -> None:
    if protocol_version and protocol_version not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported MCP protocol version",
        )


def request_id(message: dict[str, Any]) -> str | int | None:
    if "id" not in message:
        return None
    value = message["id"]
    if value is None or isinstance(value, str | int):
        return value
    raise ValueError("id must be a string, integer, or null")


async def call_tool(
    session: AsyncSession,
    *,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if name == "search_skills":
        args = SearchSkillsArguments.model_validate(arguments)
        result = await search_skills(
            session,
            query=args.query,
            limit=args.limit,
            owner=args.owner,
            category=args.category,
            audit_status=args.audit_status,
            official=args.official,
            cursor=args.cursor,
        )
        return tool_result(result)

    if name == "get_skill":
        args = GetSkillArguments.model_validate(arguments)
        try:
            result = await get_skill_detail(
                session,
                args.skill_id,
                content_hash=args.content_hash,
                include_bundle=args.include_bundle,
            )
        except SkillNotFoundError as exc:
            return tool_error(str(exc))
        return tool_result(result)

    if name == "get_skill_audit":
        args = SkillLookupArguments.model_validate(arguments)
        try:
            result = await get_skill_audit(
                session,
                args.skill_id,
                content_hash=args.content_hash,
            )
        except (SkillNotFoundError, SkillAuditNotFoundError) as exc:
            return tool_error(str(exc))
        return tool_result(result)

    raise LookupError(f"Unknown tool: {name}")


async def handle_jsonrpc_request(
    session: AsyncSession,
    message: dict[str, Any],
) -> JSONResponse:
    try:
        current_id = request_id(message)
    except ValueError as exc:
        return jsonrpc_error(
            None,
            JSONRPC_INVALID_REQUEST,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    method = message.get("method")
    if not isinstance(method, str) or not method:
        return jsonrpc_error(
            current_id,
            JSONRPC_INVALID_REQUEST,
            "method must be a non-empty string",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    params_value = message.get("params", {})
    params = {} if params_value is None else params_value
    if not isinstance(params, dict):
        return jsonrpc_error(current_id, JSONRPC_INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        protocol_version = (
            requested_version
            if requested_version in SUPPORTED_MCP_PROTOCOL_VERSIONS
            else MCP_PROTOCOL_VERSION
        )
        return jsonrpc_response(
            current_id,
            result={
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "wardn-hub-skills",
                    "title": "Wardn Hub Skills",
                    "version": get_settings().app_version,
                },
                "instructions": (
                    "Use this server only for read-only Wardn Hub skill discovery and "
                    "inspection. It does not install skills, invoke registered MCP servers, "
                    "or mutate Wardn Hub records."
                ),
            },
        )

    if method == "ping":
        return jsonrpc_response(current_id, result={})

    if method == "tools/list":
        return jsonrpc_response(current_id, result={"tools": tools()})

    if method == "tools/call":
        name = params.get("name")
        arguments_value = params.get("arguments", {})
        arguments = {} if arguments_value is None else arguments_value
        if not isinstance(name, str) or not name:
            return jsonrpc_error(current_id, JSONRPC_INVALID_PARAMS, "name must be a string")
        if not isinstance(arguments, dict):
            return jsonrpc_error(current_id, JSONRPC_INVALID_PARAMS, "arguments must be an object")
        try:
            result = await call_tool(session, name=name, arguments=arguments)
        except LookupError as exc:
            return jsonrpc_error(current_id, JSONRPC_INVALID_PARAMS, str(exc))
        except ValidationError as exc:
            return jsonrpc_error(
                current_id,
                JSONRPC_INVALID_PARAMS,
                validation_error_message(exc),
            )
        except ValueError as exc:
            return jsonrpc_error(current_id, JSONRPC_INVALID_PARAMS, str(exc))
        except Exception:
            logger.exception("mcp skills tool call failed", extra={"tool_name": name})
            return jsonrpc_error(
                current_id,
                JSONRPC_INTERNAL_ERROR,
                "internal error while calling tool",
            )
        return jsonrpc_response(current_id, result=result)

    return jsonrpc_error(current_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")


@router.post(
    "",
    summary="Wardn Hub read-only skills MCP server",
    description=MCP_ENDPOINT_DESCRIPTION,
    operation_id="mcp_skills_endpoint",
    openapi_extra={"requestBody": MCP_REQUEST_BODY_OPENAPI},
    responses={
        status.HTTP_200_OK: MCP_SUCCESS_RESPONSE_OPENAPI,
        status.HTTP_202_ACCEPTED: {
            "description": "Accepted JSON-RPC notification or client response."
        },
        status.HTTP_400_BAD_REQUEST: MCP_BAD_REQUEST_RESPONSE_OPENAPI,
        status.HTTP_401_UNAUTHORIZED: MCP_UNAUTHORIZED_RESPONSE_OPENAPI,
        status.HTTP_403_FORBIDDEN: MCP_FORBIDDEN_RESPONSE_OPENAPI,
    },
)
async def mcp_skills_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_bearer_api_token_scopes("skills:read"))],
    mcp_protocol_version: Annotated[str | None, Header(alias="MCP-Protocol-Version")] = None,
) -> Response:
    """Handle one read-only MCP JSON-RPC message over Streamable HTTP."""
    validate_protocol_version(mcp_protocol_version)
    try:
        message = await request.json()
    except json.JSONDecodeError:
        return jsonrpc_error(
            None,
            JSONRPC_PARSE_ERROR,
            "Parse error",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return jsonrpc_error(
            None,
            JSONRPC_INVALID_REQUEST,
            "request must be a JSON-RPC 2.0 object",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if "method" not in message:
        if "id" in message and ("result" in message or "error" in message):
            return Response(status_code=status.HTTP_202_ACCEPTED)
        return jsonrpc_error(
            None,
            JSONRPC_INVALID_REQUEST,
            "method is required",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if "id" not in message:
        return Response(status_code=status.HTTP_202_ACCEPTED)

    return await handle_jsonrpc_request(session, message)
