import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.skills import repository, service
from app.modules.skills.models import Skill, SkillInstallEvent


async def test_indexed_skill_search_uses_bounded_ranked_candidates() -> None:
    class FakeSession:
        statement = ""
        params: dict[str, object] = {}

        async def execute(self, statement: object) -> SimpleNamespace:
            compiled = statement.compile(dialect=postgresql.dialect())
            self.statement = str(compiled)
            self.params = compiled.params
            return SimpleNamespace(all=list)

    session = FakeSession()
    page = await repository.search_skill_documents(  # type: ignore[arg-type]
        session,
        query="document skill",
        limit=8,
        owner="acme",
        official=True,
        audit_status="warn",
    )

    assert page == repository.SkillSearchPage(skills=[], has_more=False, next_cursor=None)
    assert "skill_search_documents.search_vector @@" in session.statement
    assert "skill_search_documents.identity_text %" in session.statement
    assert "similarity(skill_search_documents.identity_text" in session.statement
    assert "skill_search_documents.is_canonical IS true" in session.statement
    assert "skill_search_documents.source_owner" in session.statement
    assert "skill_source_owners.is_official IS true" in session.statement
    assert "skill_audits" in session.statement
    assert "LIMIT" in session.statement
    assert 9 in session.params.values()
    assert "count(" not in session.statement.lower()


async def test_search_skills_returns_and_accepts_stable_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            skill_audit_enabled=True,
            registry_public_base_url="https://hub.example",
        ),
    )
    skill_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    skill = SimpleNamespace(
        id=skill_id,
        source="acme/skills",
        slug="document-search",
        name="Document Search",
        source_type="github",
        source_owner="acme",
        source_name="skills",
        source_owner_url="https://github.com/acme",
        source_owner_icon_url="",
        source_url="https://github.com/acme/skills",
        install_url="https://github.com/acme/skills/tree/main/document-search",
        description="Search skill instructions.",
        installs=5,
    )
    next_position = repository.SkillSearchCursor(
        match_tier=3,
        text_rank=0.25,
        trigram_rank=0.125,
        installs=5,
        name="document search",
        source="acme/skills",
        skill_id=skill_id,
    )
    captured_cursors: list[repository.SkillSearchCursor | None] = []

    async def search_documents(*args: object, **kwargs: object):
        captured_cursors.append(kwargs["cursor"])  # type: ignore[arg-type]
        return repository.SkillSearchPage(
            skills=[skill],  # type: ignore[list-item]
            has_more=True,
            next_cursor=next_position,
        )

    async def official_owner_keys(*args: object):
        return {("github", "acme")}

    async def current_skill_audits(*args: object):
        return {}

    monkeypatch.setattr(service.repository, "search_skill_documents", search_documents)
    monkeypatch.setattr(service.repository, "official_owner_keys", official_owner_keys)
    monkeypatch.setattr(service.repository, "current_skill_audits", current_skill_audits)

    first_page = await service.search_skills(
        object(),  # type: ignore[arg-type]
        query="Document skill",
        limit=1,
        owner="ACME",
        official=True,
    )
    second_page = await service.search_skills(
        object(),  # type: ignore[arg-type]
        query=" document SKILL ",
        limit=1,
        owner="acme",
        official=True,
        cursor=first_page.next_cursor,
    )

    assert first_page.search_type == "lexical"
    assert first_page.count == 1
    assert first_page.has_more is True
    assert first_page.next_cursor
    assert first_page.data[0].is_official is True
    assert captured_cursors == [None, next_position]
    assert second_page.next_cursor == first_page.next_cursor


def test_search_cursor_rejects_filter_changes_and_non_finite_ranks() -> None:
    position = repository.SkillSearchCursor(
        match_tier=3,
        text_rank=0.25,
        trigram_rank=0.125,
        installs=5,
        name="document search",
        source="acme/skills",
        skill_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    fingerprint = service.skill_search_cursor_fingerprint(
        query="document skill",
        owner=None,
        audit_status=None,
        official=None,
    )
    cursor = service.encode_skill_search_cursor(position, fingerprint)

    with pytest.raises(ValueError, match="cursor"):
        service.decode_skill_search_cursor(cursor, "different-filter")

    invalid = repository.SkillSearchCursor(**{**position.__dict__, "text_rank": float("nan")})
    invalid_cursor = service.encode_skill_search_cursor(invalid, fingerprint)
    with pytest.raises(ValueError, match="cursor"):
        service.decode_skill_search_cursor(invalid_cursor, fingerprint)


async def test_skill_leaderboard_views_sort_by_install_activity() -> None:
    class FakeSession:
        statements: list[str]

        def __init__(self) -> None:
            self.statements = []

        async def scalar(self, statement: object) -> int:
            self.statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )
            return 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )
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
    assert "skills_1.install_url !=" in all_time_session.statements[-1]
    assert "skills_1.installs DESC" in all_time_session.statements[-1]
    assert "length(skills_1.slug)" in all_time_session.statements[-1]
    assert "SELECT DISTINCT ON" in all_time_session.statements[-1]
    assert "canonical_rank" not in all_time_session.statements[-1]
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


async def test_list_skills_applies_identifier_match_and_exact_id_ordering() -> None:
    class FakeSession:
        statements: list[str]

        def __init__(self) -> None:
            self.statements = []

        async def scalar(self, statement: object) -> int:
            self.statements.append(
                str(
                    statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                )
            )
            return 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(
                str(
                    statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                )
            )
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    unique=lambda: SimpleNamespace(all=list),
                )
            )

    session = FakeSession()
    await repository.list_skills(
        session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        search="abhi1693/wardn-hub/find-skills",
    )

    sql = session.statements[-1]
    assert "skills.source ILIKE 'abhi1693/wardn-hub'" in sql
    assert "skills.slug ILIKE 'find-skills'" in sql
    assert "ORDER BY CASE WHEN (lower(skills.source)" in sql


async def test_list_skills_filters_by_current_audit_status() -> None:
    class FakeSession:
        statements: list[str]

        def __init__(self) -> None:
            self.statements = []

        async def scalar(self, statement: object) -> int:
            self.statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )
            return 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )
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
    assert "configuration_hash" in warned_sql
    assert "row_number() OVER" not in warned_sql
    assert "audit_status" in warned_sql
    assert " IN (SELECT" in warned_sql

    unaudited_session = FakeSession()
    await repository.list_skills(
        unaudited_session,  # type: ignore[arg-type]
        offset=0,
        limit=10,
        audit_status="unaudited",
    )
    unaudited_sql = unaudited_session.statements[-1]
    assert "NOT IN (SELECT" in unaudited_sql
    assert "LEFT OUTER JOIN" not in unaudited_sql


def test_audit_filter_uses_single_current_snapshot_result() -> None:
    statement = repository.apply_audit_status_filter(
        repository.published_skill_query(Skill),
        "unaudited",
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "skill_audits.configuration_hash" in compiled
    assert "MATERIALIZED" not in compiled
    assert "NOT IN (SELECT" in compiled


def test_canonical_skill_filter_uses_postgresql_distinct_on() -> None:
    statement = repository.published_skill_query(Skill).where(
        repository.canonical_skill_condition()
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON (skills_1.source_type, skills_1.source" in compiled
    assert "skills_1.installs DESC" in compiled
    assert "row_number()" not in compiled


async def test_list_skills_rejects_unknown_audit_status() -> None:
    with pytest.raises(ValueError, match="audit_status"):
        await service.list_skills(
            object(),  # type: ignore[arg-type]
            audit_status="unknown",
        )


async def test_disabled_audit_gate_hides_statuses_and_ignores_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(skill_audit_enabled=False),
    )
    captured: list[object] = []

    async def list_skills(*args: object, **kwargs: object):
        captured.append(kwargs["audit_status"])
        return [], 0

    async def official_owner_keys(*args: object):
        return set()

    async def unexpected_status_lookup(*args: object):
        raise AssertionError("audit statuses must not be queried while the gate is disabled")

    monkeypatch.setattr(service.repository, "list_skills", list_skills)
    monkeypatch.setattr(service.repository, "official_owner_keys", official_owner_keys)
    monkeypatch.setattr(
        service.repository,
        "current_skill_audits",
        unexpected_status_lookup,
    )

    response = await service.list_skills(object(), audit_status="fail")  # type: ignore[arg-type]

    assert captured == [None]
    assert response.audit_enabled is False


async def test_disabled_audit_gate_hides_stored_audit_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(skill_audit_enabled=False),
    )

    with pytest.raises(service.SkillAuditNotFoundError, match="disabled"):
        await service.get_skill_audit(object(), "acme/skills/weather")  # type: ignore[arg-type]


def test_wardn_find_skills_pin_targets_repository_and_skill_name() -> None:
    expression = repository.wardn_find_skills_order().compile(
        compile_kwargs={"literal_binds": True}
    )

    assert "wardn-hub" in str(expression)
    assert "find-skills" in str(expression)


@pytest.mark.parametrize(
    ("query", "expected_source"),
    [
        ("wardn-hub/find-skills", "wardn-hub"),
        ("abhi1693/wardn-hub/find-skills", "abhi1693/wardn-hub"),
    ],
)
def test_skill_identifier_search_matches_repository_slug_and_full_id(
    query: str,
    expected_source: str,
) -> None:
    condition = repository.skill_identifier_condition(query)
    assert condition is not None

    compiled = str(
        condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"skills.source ILIKE '{expected_source}'" in compiled
    assert "skills.slug ILIKE 'find-skills'" in compiled
    assert "skills.source_name ILIKE" in compiled


def test_skill_identifier_search_prioritizes_exact_full_id() -> None:
    expression = repository.skill_identifier_order(
        "abhi1693/wardn-hub/find-skills"
    )
    assert expression is not None

    compiled = str(
        expression.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "lower(skills.source) = 'abhi1693/wardn-hub'" in compiled
    assert "lower(skills.slug) = 'find-skills'" in compiled
    assert "THEN 0" in compiled


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


async def test_get_current_skill_audit_requires_current_snapshot_hash_and_is_bounded() -> None:
    class FakeSession:
        statement = ""

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statement = str(statement)
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    session = FakeSession()
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="snapshot-id")

    await repository.get_current_skill_audit(session, skill)  # type: ignore[arg-type]

    assert "skill_audits.snapshot_id" in session.statement
    assert "skill_audits.content_hash" in session.statement
    assert "skill_snapshots.content_hash" in session.statement
    assert "LIMIT" in session.statement


async def test_current_skill_audits_uses_unique_snapshot_results() -> None:
    class FakeSession:
        statement = ""

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statement = str(statement)
            return SimpleNamespace(
                all=lambda: [
                    ("skill-one", "warn", 79, "A"),
                    ("skill-two", "fail", 24, "C+"),
                ]
            )

    session = FakeSession()
    skills = [
        SimpleNamespace(id="skill-one", current_snapshot_id="snapshot-one"),
        SimpleNamespace(id="skill-two", current_snapshot_id="snapshot-two"),
    ]

    audits = await repository.current_skill_audits(  # type: ignore[arg-type]
        session,
        skills,
    )

    assert audits == {
        "skill-one": repository.CurrentSkillAudit(status="warn", score=79, rank="A"),
        "skill-two": repository.CurrentSkillAudit(status="fail", score=24, rank="C+"),
    }
    assert "JOIN skill_snapshots" in session.statement
    assert "skill_snapshots.content_hash = skill_audits.content_hash" in session.statement
    assert "skill_snapshots.is_latest" in session.statement
    assert "skill_audits.configuration_hash" in session.statement
    assert "row_number() OVER" not in session.statement


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
        bundle_format_version=2,
        source_commit_sha="a" * 40,
        source_entrypoint="SKILL.md",
        resolution_status="complete",
        resolution_issues=[],
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
    assert bundle_detail.bundle_format_version == 2
    assert bundle_detail.source_entrypoint == "SKILL.md"
    assert bundle_detail.resolution_status == "complete"


async def test_record_skill_install_requires_current_snapshot_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="snapshot-id")
    snapshot = SimpleNamespace(
        id="snapshot-id",
        content_hash="a" * 64,
        bundle_format_version=2,
        resolution_status="complete",
    )

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

    snapshot.resolution_status = "incomplete"
    with pytest.raises(service.SkillNotFoundError, match="snapshot"):
        await service.record_skill_install(
            object(),
            "acme/skills/weather",
            content_hash="a" * 64,
            resolver_version="1",
        )
