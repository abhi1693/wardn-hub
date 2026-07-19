import json
from datetime import UTC, datetime
from pathlib import Path

from app.modules.skills.schemas import (
    SkillAuditFindingRead,
    SkillAuditRead,
    SkillAuditResponse,
    SkillAuditScoreDeductionRead,
    SkillRead,
    SkillSearchResponse,
)

CONTRACT_FIXTURE = (
    Path(__file__).parents[2] / "cli" / "test" / "fixtures" / "skill-api-contract.json"
)


def contract_payload() -> dict[str, object]:
    skill = SkillRead(
        id="acme/skills/code-audit",
        slug="code-audit",
        name="Code Audit",
        source="acme/skills",
        sourceType="github",
        sourceOwner="acme",
        sourceName="skills",
        sourceOwnerUrl="https://github.com/acme",
        sourceOwnerIconUrl="https://avatars.githubusercontent.com/u/1?v=4",
        sourceUrl="https://github.com/acme/skills/tree/main/code-audit",
        installUrl="https://github.com/acme/skills/tree/main/code-audit",
        url="https://hub.wardnai.dev/skills/acme/skills/code-audit",
        description="Review source safely.",
        installs=42,
        isOfficial=False,
        auditStatus="warn",
        auditScore=79,
        auditRank="A",
    )
    search = SkillSearchResponse(
        data=[skill],
        query="code audit",
        searchType="lexical",
        count=1,
        hasMore=False,
        nextCursor=None,
        durationMs=3,
        auditEnabled=True,
    )
    audit = SkillAuditResponse(
        id=skill.id,
        source=skill.source,
        slug=skill.slug,
        contentHash="a" * 64,
        audit=SkillAuditRead(
            scannerName="Cisco AI Skill Scanner",
            scannerVersion="2.0.12",
            policyName="balanced",
            policyVersion="1.0",
            policyFingerprint="b" * 64,
            status="warn",
            summary="One medium-risk finding requires review.",
            auditedAt=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
            riskLevel="medium",
            score=79,
            rank="A",
            scoreDeductions=[
                SkillAuditScoreDeductionRead(
                    category="prompt-injection",
                    points=21,
                    findingCount=1,
                    maxSeverity="medium",
                )
            ],
            categories=["prompt-injection"],
            findings=[
                SkillAuditFindingRead(
                    id="RULE-1",
                    ruleId="RULE-1",
                    category="prompt-injection",
                    severity="medium",
                    title="Prompt injection pattern",
                    description="The skill contains an instruction that requires review.",
                    filePath="SKILL.md",
                    lineNumber=12,
                    snippet=None,
                    remediation="Remove or constrain the instruction.",
                    analyzer="static_analyzer",
                    metadata={},
                )
            ],
            analyzers=[
                "static_analyzer",
                "bytecode",
                "pipeline",
                "behavioral_analyzer",
            ],
            scanDurationMs=123,
        ),
    )
    return {
        "audit": audit.model_dump(mode="json", by_alias=True),
        "search": search.model_dump(mode="json", by_alias=True),
    }


def test_skill_cli_contract_fixture_matches_backend_schemas() -> None:
    assert json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8")) == contract_payload()
