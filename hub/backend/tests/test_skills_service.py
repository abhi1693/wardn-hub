from types import SimpleNamespace

import pytest

from app.modules.skills import repository, service


async def test_get_skill_snapshot_can_defer_bundle_files() -> None:
    class FakeSession:
        statement = ""

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statement = str(statement)
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    session = FakeSession()
    skill = SimpleNamespace(current_snapshot_id="snapshot-id", id="skill-id")

    await repository.get_skill_snapshot(  # type: ignore[arg-type]
        session,
        skill,
        include_files=False,
    )

    selected_columns = session.statement.partition("FROM")[0]
    assert "skill_snapshots.skill_md" in selected_columns
    assert "skill_snapshots.content_hash" in selected_columns
    assert "skill_snapshots.files" not in selected_columns


async def test_list_skill_audits_requires_current_snapshot_hash_and_is_bounded() -> None:
    class FakeSession:
        statement = ""

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statement = str(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))

    session = FakeSession()
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="snapshot-id")

    await repository.list_skill_audits(session, skill)  # type: ignore[arg-type]

    assert "skill_audits.snapshot_id" in session.statement
    assert "skill_audits.content_hash" in session.statement
    assert "skill_snapshots.content_hash" in session.statement
    assert "LIMIT" in session.statement


async def test_current_skill_audit_statuses_uses_latest_check_results() -> None:
    class FakeSession:
        statement = ""

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statement = str(statement)
            return SimpleNamespace(
                all=lambda: [
                    ("skill-one", "warn"),
                    ("skill-one", "pass"),
                    ("skill-two", "fail"),
                ]
            )

    session = FakeSession()
    skills = [
        SimpleNamespace(id="skill-one", current_snapshot_id="snapshot-one"),
        SimpleNamespace(id="skill-two", current_snapshot_id="snapshot-two"),
    ]

    statuses = await repository.current_skill_audit_statuses(  # type: ignore[arg-type]
        session,
        skills,
    )

    assert statuses == {"skill-one": "warn", "skill-two": "fail"}
    assert "JOIN skill_snapshots" in session.statement
    assert "skill_snapshots.content_hash = skill_audits.content_hash" in session.statement
    assert "skill_snapshots.is_latest" in session.statement
    assert "row_number() OVER" in session.statement


async def test_get_skill_detail_only_expands_bundle_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = SimpleNamespace(
        source="acme/agent-skills",
        slug="weather",
        source_owner="acme",
        source_name="agent-skills",
        source_owner_url="https://github.com/acme",
        source_owner_icon_url="",
        source_url="https://github.com/acme/agent-skills",
    )
    snapshot = SimpleNamespace(
        content_hash="abc123",
        skill_md="# Weather",
        files=[
            {"path": "SKILL.md", "contents": "# Weather"},
            {"path": "references/api.md", "contents": "# API"},
            {
                "path": "assets/icon.png",
                "contents": "iVBORw0KGgo=",
                "encoding": "base64",
            },
            {
                "path": "scripts/weather.sh",
                "contents": "#!/bin/sh\n",
                "executable": True,
            },
        ],
    )

    async def get_skill(*args: object) -> SimpleNamespace:
        return skill

    include_files_values: list[object] = []

    async def get_skill_snapshot(*args: object, **kwargs: object) -> SimpleNamespace:
        include_files_values.append(kwargs["include_files"])
        return snapshot

    monkeypatch.setattr(service.repository, "get_skill", get_skill)
    monkeypatch.setattr(service.repository, "get_skill_snapshot", get_skill_snapshot)

    default_detail = await service.get_skill_detail(object(), "acme/agent-skills/weather")
    bundle_detail = await service.get_skill_detail(
        object(),
        "acme/agent-skills/weather",
        include_bundle=True,
    )

    assert [file.path for file in default_detail.files or []] == ["SKILL.md"]
    assert include_files_values == [False, True]
    assert [file.path for file in bundle_detail.files or []] == [
        "SKILL.md",
        "references/api.md",
        "assets/icon.png",
        "scripts/weather.sh",
    ]
    assert (bundle_detail.files or [])[0].encoding == "utf-8"
    assert (bundle_detail.files or [])[2].encoding == "base64"
    assert (bundle_detail.files or [])[3].executable is True
