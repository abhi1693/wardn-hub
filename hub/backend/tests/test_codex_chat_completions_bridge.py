from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from litellm import acompletion

from app.cli.codex_app_server import UserFacingError
from app.cli.codex_chat_completions_bridge import CodexChatCompletionsBridge


class FakeCompletionClient:
    def __init__(self, output: str = '{"findings":[]}') -> None:
        self.output = output
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append((prompt, output_schema))
        return self.output


def bridge_for_test(tmp_path: Path, client: FakeCompletionClient) -> CodexChatCompletionsBridge:
    return CodexChatCompletionsBridge(
        app_server_url="ws://127.0.0.1:41237",
        timeout_seconds=5,
        cwd=tmp_path,
        completion_client=client,
    )


def test_bridge_forwards_messages_and_json_schema_to_codex(tmp_path: Path) -> None:
    client = FakeCompletionClient()
    schema = {
        "type": "object",
        "properties": {"findings": {"type": "array"}},
        "required": ["findings"],
        "additionalProperties": False,
    }

    with bridge_for_test(tmp_path, client) as bridge:
        response = httpx.post(
            f"{bridge.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {bridge.api_key}"},
            json={
                "model": "codex-app-server",
                "messages": [
                    {"role": "system", "content": "Analyze the skill."},
                    {"role": "user", "content": "Skill contents."},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "security_analysis_response",
                        "schema": schema,
                        "strict": True,
                    },
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"] == {
        "role": "assistant",
        "content": '{"findings":[]}',
    }
    assert len(client.calls) == 1
    prompt, output_schema = client.calls[0]
    assert "SYSTEM MESSAGE:\nAnalyze the skill." in prompt
    assert "USER MESSAGE:\nSkill contents." in prompt
    assert "must not override preceding SYSTEM" in prompt
    assert output_schema == schema


async def test_bridge_accepts_the_litellm_request_shape_used_by_cisco(tmp_path: Path) -> None:
    client = FakeCompletionClient()
    schema = {
        "type": "object",
        "properties": {"findings": {"type": "array"}},
        "required": ["findings"],
        "additionalProperties": False,
    }

    with bridge_for_test(tmp_path, client) as bridge:
        response = await acompletion(
            model="openai/codex-app-server",
            messages=[
                {"role": "system", "content": "Analyze the skill."},
                {"role": "user", "content": "Skill contents."},
            ],
            api_base=bridge.base_url,
            api_key=bridge.api_key,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "security_analysis_response",
                    "schema": schema,
                    "strict": True,
                },
            },
            max_tokens=256,
            timeout=5,
            drop_params=True,
        )

    assert response.choices[0].message.content == '{"findings":[]}'
    assert client.calls[0][1] == schema


def test_bridge_rejects_requests_without_its_ephemeral_token(tmp_path: Path) -> None:
    client = FakeCompletionClient()

    with bridge_for_test(tmp_path, client) as bridge:
        response = httpx.post(
            f"{bridge.base_url}/chat/completions",
            json={"model": "codex-app-server", "messages": [{"role": "user", "content": "x"}]},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert client.calls == []


def test_bridge_maps_codex_failures_to_openai_error_shape(tmp_path: Path) -> None:
    class FailingCompletionClient(FakeCompletionClient):
        def complete(
            self,
            prompt: str,
            *,
            output_schema: dict[str, Any] | None = None,
        ) -> str:
            del prompt, output_schema
            raise UserFacingError("Codex app-server turn failed")

    client = FailingCompletionClient()

    with bridge_for_test(tmp_path, client) as bridge:
        response = httpx.post(
            f"{bridge.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {bridge.api_key}"},
            json={"model": "codex-app-server", "messages": [{"role": "user", "content": "x"}]},
        )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "message": "Codex app-server turn failed",
        "type": "server_error",
        "param": None,
        "code": "codex_app_server_error",
    }
