from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

ANALYSIS_ONLY_DEVELOPER_INSTRUCTIONS = (
    "Complete only the requested analysis from the text supplied by the client. "
    "Do not call shell commands, web search, MCP servers, apps, subagents, or any "
    "other tools. Do not inspect the app-server filesystem: client-local paths are "
    "not available on this host. Return only the requested response."
)

WEB_RESEARCH_DEVELOPER_INSTRUCTIONS = (
    "Complete the requested review from the submission text supplied by the client. "
    "Use only the built-in web search tool when public-source research is required. "
    "Do not call shell commands or shell-based HTTP clients, and do not inspect the "
    "app-server filesystem. Do not use MCP servers, apps, subagents, or any tools "
    "other than built-in web search. Return only the requested response."
)


class UserFacingError(Exception):
    """Error that should be shown without a traceback."""


@dataclass
class CodexAppServerReviewer:
    url: str
    timeout_seconds: int
    cwd: Path | None = None
    progress_stream: TextIO | None = None
    stream_output: bool = False
    auth_token: str = ""
    websocket_connect: Any | None = None
    analysis_only: bool = False
    web_research_only: bool = False

    def __post_init__(self) -> None:
        if self.analysis_only and self.web_research_only:
            raise ValueError(
                "analysis_only and web_research_only cannot both be enabled"
            )

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        del environment
        return self.complete(prompt)

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        if self.progress_stream is not None:
            print(
                "Codex app-server review started. Waiting for reviewer output.",
                file=self.progress_stream,
                flush=True,
            )
        try:
            return asyncio.run(
                asyncio.wait_for(
                    self._review_async(prompt, output_schema=output_schema),
                    timeout=self.timeout_seconds,
                )
            )
        except TimeoutError as exc:
            raise UserFacingError(
                f"Codex app-server review timed out after {self.timeout_seconds} seconds"
            ) from exc
        except UserFacingError:
            raise
        except Exception as exc:
            raise UserFacingError(f"Codex app-server review failed: {exc}") from exc

    async def _review_async(
        self,
        prompt: str,
        *,
        output_schema: dict[str, Any] | None,
    ) -> str:
        connection = self._connect()
        async with connection as websocket:
            await self._request(
                websocket,
                "initialize",
                {
                    "clientInfo": {
                        "name": "wardn-hub-review",
                        "title": None,
                        "version": "0.1",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "requestAttestation": False,
                    },
                },
                request_id=1,
            )
            await websocket.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "initialized",
                        "params": {},
                    }
                )
            )
            thread = await self._request(
                websocket,
                "thread/start",
                self._thread_start_params(),
                request_id=2,
            )
            thread_id = str(thread["thread"]["id"])
            turn = await self._request(
                websocket,
                "turn/start",
                self._turn_start_params(
                    thread_id,
                    prompt,
                    output_schema=output_schema,
                ),
                request_id=3,
            )
            turn_id = str(turn["turn"]["id"])
            return await self._collect_turn_output(websocket, thread_id, turn_id)

    def _connect(self) -> Any:
        headers = self._websocket_headers()
        if self.websocket_connect is not None:
            if headers:
                return self.websocket_connect(self.url, additional_headers=headers)
            return self.websocket_connect(self.url)

        import websockets

        if headers:
            return websockets.connect(
                self.url,
                max_size=None,
                additional_headers=headers,
            )
        return websockets.connect(self.url, max_size=None)

    def _websocket_headers(self) -> dict[str, str]:
        auth_token = self.auth_token.strip()
        if not auth_token:
            return {}
        return {"Authorization": f"Bearer {auth_token}"}

    async def _request(
        self,
        websocket: Any,
        method: str,
        params: dict[str, Any],
        *,
        request_id: int,
    ) -> dict[str, Any]:
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        while True:
            message = json.loads(await websocket.recv())
            if message.get("id") == request_id:
                if "error" in message:
                    raise UserFacingError(
                        f"Codex app-server {method} failed: "
                        f"{format_codex_rpc_error(message['error'])}"
                    )
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            await self._handle_server_message(websocket, message)

    async def _collect_turn_output(
        self,
        websocket: Any,
        thread_id: str,
        turn_id: str,
    ) -> str:
        chunks: list[str] = []
        completed_text = ""
        last_error = ""
        while True:
            message = json.loads(await websocket.recv())
            method = message.get("method")
            params = message.get("params") if isinstance(message.get("params"), dict) else {}

            if method == "item/agentMessage/delta":
                if params.get("threadId") == thread_id and params.get("turnId") == turn_id:
                    delta = str(params.get("delta") or "")
                    chunks.append(delta)
                    if self.stream_output and self.progress_stream is not None:
                        print(delta, end="", file=self.progress_stream, flush=True)
                continue

            if method == "item/completed":
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                if (
                    params.get("threadId") == thread_id
                    and params.get("turnId") == turn_id
                    and item.get("type") == "agentMessage"
                ):
                    completed_text = str(item.get("text") or "")
                continue

            if method == "error":
                if params.get("threadId") == thread_id and params.get("turnId") == turn_id:
                    last_error = format_codex_notification_error(params)
                continue

            if method == "turn/completed":
                turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                if params.get("threadId") != thread_id or turn.get("id") != turn_id:
                    continue
                status = str(turn.get("status") or "")
                if status != "completed":
                    error = turn.get("error")
                    detail = (
                        format_codex_notification_error({"error": error})
                        if isinstance(error, dict)
                        else last_error
                    )
                    raise UserFacingError(
                        "Codex app-server turn failed"
                        + (f": {detail}" if detail else f" with status {status}")
                    )
                output = "".join(chunks).strip() or completed_text.strip()
                if not output:
                    raise UserFacingError("Codex app-server completed without findings")
                return output

            await self._handle_server_message(websocket, message)

    async def _handle_server_message(self, websocket: Any, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        if request_id is None or not method:
            return

        if method == "currentTime/read":
            result: dict[str, Any] = {"currentTimeAt": int(time.time())}
        elif method == "item/tool/requestUserInput":
            result = {"answers": {}}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "decline", "content": None, "_meta": None}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": {}, "scope": "turn", "strictAutoReview": False}
        elif method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            result = {"decision": "decline"}
        elif method in {"applyPatchApproval", "execCommandApproval"}:
            result = {"decision": "denied"}
        else:
            await websocket.send(
                json.dumps(
                    {
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"unsupported server request: {method}",
                        },
                    }
                )
            )
            return

        await websocket.send(json.dumps({"id": request_id, "result": result}))

    def _thread_start_params(self) -> dict[str, Any]:
        if self.analysis_only:
            config: dict[str, Any] = {
                "web_search": "disabled",
                "features": {
                    "multi_agent": False,
                    "multi_agent_v2": False,
                },
                "developer_instructions": ANALYSIS_ONLY_DEVELOPER_INSTRUCTIONS,
            }
        elif self.web_research_only:
            config = {
                "web_search": "live",
                "tools": {"web_search": {"context_size": "medium"}},
                "features": {
                    "multi_agent": False,
                    "multi_agent_v2": False,
                },
                "developer_instructions": WEB_RESEARCH_DEVELOPER_INSTRUCTIONS,
            }
        else:
            config = {
                "web_search": "live",
                "tools": {"web_search": {"context_size": "medium"}},
            }
        params: dict[str, Any] = {
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "config": config,
        }
        if self.cwd is not None:
            cwd = str(self.cwd)
            params["cwd"] = cwd
            params["runtimeWorkspaceRoots"] = [cwd]
        return params

    def _turn_start_params(
        self,
        thread_id: str,
        prompt: str,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": True},
        }
        if output_schema is not None:
            params["outputSchema"] = output_schema
        return params


def format_codex_rpc_error(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(error)
    return str(error)


def format_codex_notification_error(params: dict[str, Any]) -> str:
    error = params.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(error)
    if isinstance(error, str):
        return error
    return ""
