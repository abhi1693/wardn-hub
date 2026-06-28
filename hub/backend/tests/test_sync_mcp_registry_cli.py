from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.cli import sync_mcp_registry as cli


class FakeHub:
    def __init__(
        self,
        *,
        duplicate: bool = False,
        existing_server: dict[str, Any] | None = None,
        pending_submissions: list[dict[str, Any]] | None = None,
        submit_error: cli.HubApiError | None = None,
    ) -> None:
        self.duplicate = duplicate
        self.existing_server = existing_server
        self.pending_submissions = pending_submissions or []
        self.submit_error = submit_error
        self.created_submissions: list[dict[str, Any]] = []
        self.updated_submissions: list[tuple[str, dict[str, Any]]] = []
        self.submitted: list[str] = []

    def list_submissions(self) -> list[dict[str, Any]]:
        return self.pending_submissions

    def get_server(self, server_name: str) -> dict[str, Any] | None:
        return self.existing_server

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.duplicate:
            raise cli.HubApiError(409, "server version already published", "/submissions")
        server_json = (
            payload.get("serverJson")
            if isinstance(payload.get("serverJson"), dict)
            else {}
        )
        if payload.get("submissionType") == "new_server" and server_json.get("version") != "1.0.0":
            raise cli.HubApiError(
                422,
                "new server submissions must start at version 1.0.0",
                "/submissions",
            )
        self.created_submissions.append(payload)
        return {"id": f"submission-{len(self.created_submissions)}"}

    def update_submission(self, submission_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updated_submissions.append((submission_id, payload))
        return {"id": submission_id}

    def submit_submission(self, submission_id: str) -> dict[str, Any]:
        if self.submit_error is not None:
            raise self.submit_error
        self.submitted.append(submission_id)
        return {"id": submission_id, "status": "submitted"}


class FakeRegistry:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.requests: list[dict[str, Any]] = []

    def list_servers(
        self,
        *,
        cursor: str | None,
        limit: int,
        version: str,
        updated_since: str | None,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "cursor": cursor,
                "limit": limit,
                "version": version,
                "updated_since": updated_since,
            }
        )
        return self.pages.pop(0)


def registry_entry(
    *,
    name: str = "io.github.example/weather",
    version: str = "1.0.0",
    status: str = "active",
    categories: list[str] | None = None,
) -> dict[str, Any]:
    server: dict[str, Any] = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": name,
        "description": "Weather tools.",
        "version": version,
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "version": version,
                "transport": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@example/weather"],
                },
            }
        ],
    }
    if categories is not None:
        server["_meta"] = {"categories": categories}
    return {
        "server": server,
        "_meta": {
            cli.OFFICIAL_META_KEY: {
                "status": status,
                "publishedAt": "2026-04-13T17:33:26.613537Z",
                "updatedAt": "2026-04-14T17:33:26.613537Z",
                "isLatest": True,
            }
        },
    }


def test_build_import_payload_adds_default_category_and_import_evidence() -> None:
    payload = cli.build_import_payload(
        registry_entry(),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )

    assert payload["_meta"]["categories"] == [cli.DEFAULT_CATEGORY]
    assert payload["_meta"][cli.OFFICIAL_META_KEY]["status"] == "active"
    assert payload["_meta"][cli.IMPORT_META_KEY] == {
        "source": "modelcontextprotocol-registry",
        "registryUrl": cli.DEFAULT_REGISTRY_URL,
        "syncedAt": "2026-06-28T12:00:00Z",
        "upstreamStatus": "active",
        "upstreamPublishedAt": "2026-04-13T17:33:26.613537Z",
        "upstreamUpdatedAt": "2026-04-14T17:33:26.613537Z",
        "upstreamIsLatest": True,
    }
    assert payload["_meta"]["sourceReview"]["llm"]["filesRead"] == [
        f"Official MCP registry record: {cli.DEFAULT_REGISTRY_URL}"
    ]
    assert "## Installation" in payload["documentation"]


def test_build_import_payload_preserves_existing_categories() -> None:
    payload = cli.build_import_payload(
        registry_entry(categories=["developer-tools"]),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )

    assert payload["_meta"]["categories"] == ["developer-tools"]


def test_import_entry_skips_duplicate_by_default() -> None:
    hub = FakeHub(duplicate=True)

    outcome = cli.import_entry(
        hub,
        registry_entry(),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("skipped", "server version already published")
    assert hub.created_submissions == []


def test_import_entry_creates_and_submits_new_server_submission() -> None:
    hub = FakeHub()

    outcome = cli.import_entry(
        hub,
        registry_entry(version="1.0.0"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("submitted", "submission_id=submission-1")
    assert hub.created_submissions[0]["submissionType"] == "new_server"
    assert hub.created_submissions[0]["serverJson"]["version"] == "1.0.0"
    assert hub.submitted == ["submission-1"]


def test_import_entry_skips_new_server_import_that_breaks_initial_version_rule() -> None:
    hub = FakeHub()

    outcome = cli.import_entry(
        hub,
        registry_entry(version="1.0.1"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome(
        "skipped",
        "new_server_requires_initial_version=1.0.0; upstream_version=1.0.1",
    )
    assert hub.created_submissions == []
    assert hub.submitted == []


def test_import_entry_creates_new_version_submission_for_existing_server() -> None:
    hub = FakeHub(
        existing_server={
            "server": {
                "owner": {"id": "49a69100-26be-49b1-be9b-69619aaaf311"},
                "organization": None,
            }
        }
    )

    outcome = cli.import_entry(
        hub,
        registry_entry(version="1.0.0"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("submitted", "submission_id=submission-1")
    assert hub.created_submissions[0]["submissionType"] == "new_version"
    assert hub.created_submissions[0]["ownerUserId"] == "49a69100-26be-49b1-be9b-69619aaaf311"


def test_import_entry_allows_non_initial_version_for_existing_server() -> None:
    hub = FakeHub(existing_server={"server": {"owner": {"id": "owner-1"}}})

    outcome = cli.import_entry(
        hub,
        registry_entry(version="1.2.3"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("submitted", "submission_id=submission-1")
    assert hub.created_submissions[0]["submissionType"] == "new_version"
    assert hub.created_submissions[0]["serverJson"]["version"] == "1.2.3"


def test_import_entry_keeps_draft_when_submit_validation_blocks_review() -> None:
    hub = FakeHub(submit_error=cli.HubApiError(400, "submission is not ready", "/submit"))

    outcome = cli.import_entry(
        hub,
        registry_entry(version="1.0.0"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("draft", "submission is not ready")
    assert len(hub.created_submissions) == 1
    assert hub.submitted == []


def test_import_entry_skips_upstream_deleted_versions() -> None:
    hub = FakeHub()

    outcome = cli.import_entry(
        hub,
        registry_entry(status="deleted"),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={},
    )

    assert outcome == cli.ImportOutcome("skipped", "upstream_deleted")
    assert hub.created_submissions == []


def test_import_entry_skips_existing_submitted_submission() -> None:
    hub = FakeHub()

    outcome = cli.import_entry(
        hub,
        registry_entry(),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={
            ("io.github.example/weather", "1.0.0"): {
                "id": "submission-1",
                "name": "io.github.example/weather",
                "version": "1.0.0",
                "status": "submitted",
            }
        },
    )

    assert outcome == cli.ImportOutcome("skipped", "pending_submission_status=submitted")
    assert hub.created_submissions == []


def test_import_entry_updates_and_submits_existing_draft_submission() -> None:
    hub = FakeHub()

    outcome = cli.import_entry(
        hub,
        registry_entry(),
        registry_url=cli.DEFAULT_REGISTRY_URL,
        synced_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        dry_run=False,
        existing_submissions={
            ("io.github.example/weather", "1.0.0"): {
                "id": "submission-1",
                "name": "io.github.example/weather",
                "version": "1.0.0",
                "status": "draft",
            }
        },
    )

    assert outcome == cli.ImportOutcome("submitted", "submission_id=submission-1")
    assert hub.created_submissions == []
    assert hub.updated_submissions[0][0] == "submission-1"
    assert hub.submitted == ["submission-1"]


def test_sync_registry_paginates_and_counts_duplicate_skips() -> None:
    registry = FakeRegistry(
        [
            {
                "servers": [registry_entry(name="io.github.example/one")],
                "metadata": {"nextCursor": "next"},
            },
            {
                "servers": [registry_entry(name="io.github.example/two")],
                "metadata": {},
            },
        ]
    )
    hub = FakeHub(duplicate=True)

    stats = cli.sync_registry(
        registry=registry,  # type: ignore[arg-type]
        hub=hub,
        registry_url=cli.DEFAULT_REGISTRY_URL,
        limit=100,
        version="latest",
        updated_since="2026-06-27T12:00:00Z",
        dry_run=False,
        max_pages=None,
        max_records=None,
        verbose=False,
    )

    assert stats.pages == 2
    assert stats.seen == 2
    assert stats.skipped == 2
    assert registry.requests[0]["cursor"] is None
    assert registry.requests[1]["cursor"] == "next"
    assert all(request["updated_since"] == "2026-06-27T12:00:00Z" for request in registry.requests)
    assert all("include_deleted" not in request for request in registry.requests)


def test_sync_registry_verbose_prints_page_and_record_progress(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = FakeRegistry(
        [
            {
                "servers": [registry_entry(name="io.github.example/one")],
                "metadata": {},
            },
        ]
    )
    hub = FakeHub()

    cli.sync_registry(
        registry=registry,  # type: ignore[arg-type]
        hub=hub,
        registry_url=cli.DEFAULT_REGISTRY_URL,
        limit=10,
        version="latest",
        updated_since=None,
        dry_run=True,
        max_pages=None,
        max_records=None,
        verbose=True,
    )

    output = capsys.readouterr().out
    assert "fetching registry page 1 cursor=<initial>" in output
    assert "fetched page 1: records=1" in output
    assert "dry-run candidate: name=io.github.example/one version=1.0.0 reason=dry_run" in output
    assert "registry pagination complete" in output


def test_build_parser_rejects_bad_datetime() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--updated-since", "not-a-date"])
