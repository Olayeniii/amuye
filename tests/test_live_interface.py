from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from amuye.api import AssessmentService, make_handler
from amuye.live import run_live_assessment
from amuye.sibyl_store import SibylStore
from amuye.specialists import StaticProtocolDataSource


REQUEST = {
    "objective": "Assess protocol Aave for integration",
    "maxBudget": 100,
    "deadline": "2026-09-10T18:00:00Z",
    "priority": "balanced",
    "hardConstraints": ["protocolSlug=aave"],
    "clientId": "api-test-client",
    "taskClass": "protocol_assessment",
}
PROFILE = {
    "name": "Aave",
    "category": "Dexes",
    "url": "https://aave.com",
    "tvl": 2_000_000,
    "chains": ["Ethereum"],
    "audits": "1",
    "audit_links": ["https://example.test/audit"],
    "change_7d": 1,
}


def wait_for(service: AssessmentService, job_id: str) -> dict:
    for _ in range(100):
        job = service.get(job_id)
        assert job is not None
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("assessment did not finish")


def test_live_service_calls_real_planner_controller_sibyl_and_specialists(tmp_path) -> None:
    source = StaticProtocolDataSource({"aave": PROFILE})
    service = AssessmentService(tmp_path / "sibyl.db", data_source=source)

    cold = wait_for(service, service.submit(REQUEST, memory_enabled=False))
    assert cold["status"] == "completed"
    assert cold["result"]["strategy"]["source"] == "baseline"
    assert cold["result"]["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert cold["result"]["lessonUpdate"]["action"] == "created"

    informed = wait_for(service, service.submit(REQUEST, memory_enabled=True))
    result = informed["result"]
    assert result["memory"]["recalledLessonIds"] == [
        "lesson_progressive_specialist_purchasing_v1",
    ]
    assert result["strategy"]["source"] == "adapted"
    assert result["execution"]["purchasedRoles"] == [
        "viability_onchain", "risk_synthesis",
    ]
    security = next(node for node in result["execution"]["nodes"]
                    if node["type"] == "security_analysis")
    assert security["status"] == "skipped"
    assert result["execution"]["spent"] == 35
    assert [event["type"] for event in informed["events"]][-4:] == [
        "evaluation_completed", "reflection_completed", "lesson_updated",
        "execution_completed",
    ]


def test_http_endpoint_accepts_external_contract_and_can_be_polled(tmp_path) -> None:
    source = StaticProtocolDataSource({"aave": PROFILE})
    service = AssessmentService(tmp_path / "sibyl.db", data_source=source)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("Amúyẹ", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, dist))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request(
            "POST", "/api/assessments?memory=off",
            body=json.dumps(REQUEST), headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        accepted = json.loads(response.read())
        assert response.status == 202
        assert accepted["providerMode"] == "local specialists, no ACP payment"
        job = wait_for(service, accepted["jobId"])

        connection.request("GET", accepted["statusUrl"])
        response = connection.getresponse()
        fetched = json.loads(response.read())
        assert response.status == 200
        assert fetched["result"]["jobId"] == job["result"]["jobId"]
        assert fetched["result"]["request"] == REQUEST
    finally:
        server.shutdown()


def test_http_rejects_invalid_task_class_before_execution(tmp_path) -> None:
    service = AssessmentService(tmp_path / "sibyl.db")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("Amúyẹ", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, dist))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        invalid = {**REQUEST, "taskClass": "another_task"}
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("POST", "/api/assessments", body=json.dumps(invalid))
        response = connection.getresponse()
        assert response.status == 400
        assert "protocol_assessment only" in json.loads(response.read())["error"]
        assert service.jobs == {}
    finally:
        server.shutdown()


def test_frontend_contains_live_form_and_calls_assessment_api() -> None:
    source = Path("frontend/src/app.js").read_text(encoding="utf-8")
    assert "New Assessment" in source
    assert 'fetch(`/api/assessments?memory=${memory}`' in source
    assert "objective" in source and "maxBudget" in source
    assert "hardConstraints" in source and "clientId" in source
    assert "local specialist path" in source


def test_memory_on_source_is_the_sibyl_record_used_by_planning(tmp_path) -> None:
    source = StaticProtocolDataSource({"aave": PROFILE})
    database = tmp_path / "sibyl.db"
    cold = run_live_assessment(
        REQUEST, memory_enabled=False, memory_db=database, data_source=source,
    )
    assert cold["lessonUpdate"]["action"] == "created"

    informed = run_live_assessment(
        REQUEST, memory_enabled=True, memory_db=database, data_source=source,
    )
    proof = informed["memory"]["source"]
    referenced_id = informed["strategy"]["memoryRefs"][0]
    persisted = SibylStore(database).get_lesson(referenced_id)

    assert proof["readPerformed"] is True
    assert proof["returnedLessonIds"] == [referenced_id]
    assert proof["plannerMemoryRefs"] == [referenced_id]
    assert proof["records"][0]["id"] == referenced_id
    assert persisted is not None
    assert proof["records"][0]["strategy"] == persisted.strategy
    assert all(
        SibylStore(database).execution_event_exists(event_id)
        for event_id in proof["records"][0]["supportingExecutionRefs"]
    )
    assert proof["plannerApplicability"] == informed["strategy"]["applicabilityAssessment"]
    assert proof["influencedRules"]


def test_memory_off_performs_no_sibyl_lesson_read(tmp_path, monkeypatch) -> None:
    calls = 0
    original = SibylStore.retrieve_lessons

    def tracked(self, request_terms):
        nonlocal calls
        calls += 1
        return original(self, request_terms)

    monkeypatch.setattr(SibylStore, "retrieve_lessons", tracked)
    result = run_live_assessment(
        REQUEST,
        memory_enabled=False,
        memory_db=tmp_path / "sibyl.db",
        data_source=StaticProtocolDataSource({"aave": PROFILE}),
    )

    assert calls == 0
    assert result["memory"]["source"]["readPerformed"] is False
    assert result["memory"]["source"]["records"] == []
    assert result["memory"]["source"]["message"] == "No Sibyl memory read for this run."


def test_frontend_source_panel_requires_live_api_memory_result() -> None:
    source = Path("frontend/src/app.js").read_text(encoding="utf-8")
    assert "View Sibyl source" in source
    assert "result.memory.source" in source
    assert "lesson_progressive_specialist_purchasing_v1" not in source
    assert "comparison.control.persistedLesson" not in source
    assert "localStorage" not in source
