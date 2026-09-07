from __future__ import annotations

from amuye.api import AssessmentService
from amuye.live import LESSON_ID, run_live_assessment
from amuye.sibyl_store import SibylStore
from amuye.specialists import StaticProtocolDataSource


REQUEST = {
    "objective": "Assess protocol Aave for integration and identify material risks",
    "maxBudget": 100,
    "deadline": "2026-09-10T18:00:00Z",
    "priority": "balanced",
    "hardConstraints": ["protocolSlug=aave"],
    "clientId": "live-memory-test",
    "taskClass": "protocol_assessment",
}

LOW_RISK = {
    "name": "Aave",
    "category": "Dexes",
    "url": "https://aave.com",
    "tvl": 2_000_000,
    "chains": ["Ethereum"],
    "audits": "1",
    "audit_links": ["https://example.test/audit"],
    "change_7d": 1,
}

SECURITY_WARRANTED = {
    **LOW_RISK,
    "category": "Lending",
    "chains": ["Ethereum", "Base", "Arbitrum", "Optimism"],
}


def test_cold_completed_assessment_persists_reusable_procurement_lesson_even_when_security_is_warranted(tmp_path) -> None:
    database = tmp_path / "sibyl.db"
    source = StaticProtocolDataSource({"aave": SECURITY_WARRANTED})

    cold = run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=source,
    )

    assert cold["status"] == "completed"
    assert cold["memory"]["recalledLessonIds"] == []
    assert cold["strategy"]["source"] == "baseline"
    assert cold["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert cold["lessonUpdate"]["action"] == "created"
    persisted = SibylStore(database).get_lesson(LESSON_ID)
    assert persisted is not None
    assert "commit" in persisted.strategy.lower()
    assert "current objective and hard constraints" in persisted.strategy.lower()
    assert "specific protocol" in persisted.reasoning.lower()


def test_fresh_service_recalls_lesson_and_changes_procurement_policy_without_forcing_security_skip(tmp_path) -> None:
    database = tmp_path / "sibyl.db"
    source = StaticProtocolDataSource({"aave": SECURITY_WARRANTED})

    run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=source,
    )
    fresh_service = AssessmentService(database, data_source=source)
    job_id = fresh_service.submit(REQUEST, memory_enabled=True)

    import time
    for _ in range(100):
        job = fresh_service.get(job_id)
        if job and job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("assessment did not finish")

    assert job is not None
    assert job["status"] == "completed"
    result = job["result"]
    assert result["memory"]["recalledLessonIds"] == [LESSON_ID]
    assert result["strategy"]["source"] == "adapted"
    assert result["memory"]["source"]["returnedLessonIds"] == [LESSON_ID]
    assert result["memory"]["source"]["influencedRules"]
    # Current evidence still warrants security. Memory changes commitment timing,
    # not the truth of the current risk result.
    assert result["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert result["execution"]["spent"] == 95


def test_same_recalled_policy_can_avoid_security_when_current_risk_does_not_warrant_it(tmp_path) -> None:
    database = tmp_path / "sibyl.db"
    high = StaticProtocolDataSource({"aave": SECURITY_WARRANTED})
    low = StaticProtocolDataSource({"aave": LOW_RISK})

    seed = run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=high,
    )
    assert seed["lessonUpdate"]["action"] == "created"

    informed = run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=low,
    )
    assert informed["memory"]["recalledLessonIds"] == [LESSON_ID]
    assert informed["strategy"]["source"] == "adapted"
    assert informed["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis",
    ]
    assert informed["execution"]["spent"] == 35
    security = next(
        node for node in informed["execution"]["nodes"]
        if node["type"] == "security_analysis"
    )
    assert security["status"] == "skipped"


def test_memory_off_does_not_recall_existing_lesson(tmp_path) -> None:
    database = tmp_path / "sibyl.db"
    source = StaticProtocolDataSource({"aave": LOW_RISK})
    run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=source,
    )

    off = run_live_assessment(
        REQUEST, memory_enabled=False, memory_db=database, data_source=source,
    )
    assert off["memory"]["recalledLessonIds"] == []
    assert off["memory"]["source"]["readPerformed"] is False
    assert off["strategy"]["source"] == "baseline"
    assert off["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert off["execution"]["spent"] == 95
