from types import SimpleNamespace

import pytest

from app.modules.skills import repository, service
from app.modules.skills.models import SkillInstallEvent


async def test_skill_leaderboard_views_sort_by_install_activity() -> None:
    class FakeSession:
        statements: list[str]

        def __init__(self) -> None:
            self.statements = []

        async def scalar(self, statement: object) -> int:
            self.statements.append(str(statement))
            return 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(str(statement))
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    unique=lambda: SimpleNamespace(all=list),
                )
            )

    all_time_session = FakeSession()
    await repository.list_skills(
        all_time_session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        view="all-time",
    )
    assert "skills.installs DESC" in all_time_session.statements[-1]
    assert "CASE WHEN" in all_time_session.statements[-1]
    assert "lower(skills.source_name)" in all_time_session.statements[-1]
    assert "lower(skills.name)" in all_time_session.statements[-1]
    assert "row_number() OVER" in all_time_session.statements[-1]
    assert "skills_1.install_url !=" in all_time_session.statements[-1]
    assert "skills_1.installs DESC" in all_time_session.statements[-1]
    assert "length(skills_1.slug)" in all_time_session.statements[-1]
    assert "canonical_rank" in all_time_session.statements[-1]
    assert "NOT (EXISTS" not in all_time_session.statements[-1]
    assert "ORDER BY CASE WHEN" in all_time_session.statements[-1]

    trending_session = FakeSession()
    await repository.list_skills(
        trending_session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        view="trending",
    )
    assert "skill_install_events" in trending_session.statements[-1]
    assert "count(skill_install_events.id)" in trending_session.statements[-1]
    assert "recent_installs" in trending_session.statements[-1]
    assert "ORDER BY CASE WHEN" in trending_session.statements[-1]


async def test_list_skills_filters_by_current_audit_status() -> None:
    class FakeSession:
        statements: list[str]

        def __init__(self) -> None:
            self.statements = []

        async def scalar(self, statement: object) -> int:
            self.statements.append(str(statement))
            return 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(str(statement))
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    unique=lambda: SimpleNamespace(all=list),
                )
            )

    warned_session = FakeSession()
    await repository.list_skills(
        warned_session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        audit_status="warn",
    )
    warned_sql = warned_session.statements[-1]
    assert "skill_audits" in warned_sql
    assert "row_number() OVER" in warned_sql
    assert "max(CASE" in warned_sql
    assert "audit_status" in warned_sql
    assert "JOIN" in warned_sql

    unaudited_session = FakeSession()
    await repository.list_skills(
        unaudited_session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        audit_status="unaudited",
    )
    unaudited_sql = unaudited_session.statements[-1]
    assert "LEFT OUTER JOIN" in unaudited_sql
    assert "IS NULL" in unaudited_sql


async def test_list_skills_rejects_unknown_audit_status() -> None:
    with pytest.raises(ValueError, match="audit_status"):
        await service.list_skills(
            object(),  # type: ignore[arg-type]
            audit_status="unknown",
        )


def test_wardn_find_skills_pin_targets_repository_and_skill_name() -> None:
    expression = repository.wardn_find_skills_order().compile(
        compile_kwargs={"literal_binds": True}
    )

    assert "wardn-hub" in str(expression)
    assert "find-skills" in str(expression)


@pytest.mark.parametrize(
    ("path", "subfolder"),
    [
        ("", ""),
        ("SKILL.md", ""),
        ("skills/weather", "skills/weather"),
        ("skills/weather/SKILL.md", "skills/weather"),
    ],
)
def test_github_import_subfolder_from_url_path(path: str, subfolder: str) -> None:
    assert service.github_import_subfolder_from_url_path(path) == subfolder


async def test_record_install_event_increments_counter_atomically() -> None:
    class FakeSession:
        added: list[object]
        statement: str
        committed: bool

        def __init__(self) -> None:
            self.added = []
            self.statement = ""
            self.committed = False

        def add(self, value: object) -> None:
            self.added.append(value)

        async def execute(self, statement: object) -> None:
            self.statement = str(statement)

        async def commit(self) -> None:
            self.committed = True

    session = FakeSession()
    skill = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
    snapshot = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        content_hash="a" * 64,
    )

    await repository.record_install_event(
        session,  # type: ignore[arg-type]
        skill=skill,  # type: ignore[arg-type]
        snapshot=snapshot,  # type: ignore[arg-type]
        source="wardn-cli",
        resolver_version="1",
    )

    assert len(session.added) == 1
    event = session.added[0]
    assert isinstance(event, SkillInstallEvent)
    assert event.content_hash == "a" * 64
    assert event.source == "wardn-cli"
    assert event.resolver_version == "1"
    assert "installs=(skills.installs +" in session.statement
    assert session.committed is True


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


async def test_record_skill_install_requires_current_snapshot_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="snapshot-id")
    snapshot = SimpleNamespace(id="snapshot-id", content_hash="a" * 64)

    async def get_skill(*args: object) -> SimpleNamespace:
        return skill

    async def get_skill_snapshot(*args: object, **kwargs: object) -> SimpleNamespace:
        return snapshot

    recorded: list[dict[str, object]] = []

    async def record_install_event(*args: object, **kwargs: object) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(service.repository, "get_skill", get_skill)
    monkeypatch.setattr(service.repository, "get_skill_snapshot", get_skill_snapshot)
    monkeypatch.setattr(service.repository, "record_install_event", record_install_event)

    await service.record_skill_install(
        object(),
        "acme/skills/weather",
        content_hash="a" * 64,
        resolver_version="1",
        client="wardn-cli",
    )

    assert recorded == [
        {
            "skill": skill,
            "snapshot": snapshot,
            "source": "wardn-cli",
            "resolver_version": "1",
        }
    ]

    with pytest.raises(service.SkillNotFoundError, match="snapshot"):
        await service.record_skill_install(
            object(),
            "acme/skills/weather",
            content_hash="b" * 64,
            resolver_version="1",
        )
