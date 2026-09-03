from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from amuye.api import AssessmentService, make_handler
from amuye.live import run_live_assessment
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
