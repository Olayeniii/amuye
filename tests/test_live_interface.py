from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from amuye.acp import AcpPurchaseResult, FakeAcpRiskClient
from amuye.api import AssessmentService, make_handler
from amuye.live import run_live_assessment
from amuye.sibyl_store import SibylStore
from amuye.specialists import StaticProtocolDataSource


REQUEST = {
    "objective": "Assess protocol Aave for integration and identify material risks",
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
ACP_CONFIG = {
    "enabled": True,
    "provider": "0x00000000000000000000000000000000000000aa",
    "offering": "riskSynthesis",
    "network": "Base mainnet",
    "chainId": 8453,
    "maxExpectedSpend": 25.0,
    "asset": "USDC",
    "notice": "This creates and funds a real paid Virtuals ACP job.",
    "missingConfiguration": [],
}


def acp_risk_result() -> AcpPurchaseResult:
    return AcpPurchaseResult(
        acp_job_id="88001",
        provider_id=ACP_CONFIG["provider"],
        quoted_cost=0.1,
        settled_cost=0.1,
        status="completed",
        deliverable={
            "role": "risk_synthesis",
            "objectiveSatisfied": False,
            "continueToSecurity": False,
            "gateReason": "Accepted viability evidence did not justify deeper security work.",
            "identifiedRisks": [],
            "evidence": [{"source": "viability_onchain", "field": "metrics", "value": {}}],
            "consumedEvidenceRefs": ["viability_onchain"],
        },
        deliverable_ref="acp:88001:deliverable",
        evaluation_ref="acp:88001:self-evaluation",
        submitted_at="2026-09-04T00:00:00Z",
        completed_at="2026-09-04T00:01:00Z",
    )


def settlement_proof(job) -> dict:
    assert job.acpJobId == "88001"
    return {
        "chainId": 8453,
        "network": "Base mainnet",
        "jobId": job.acpJobId,
        "provider": job.providerId,
        "jobBudget": 0.1,
        "escrowedAmount": 0.1,
        "providerReleasedAmount": 0.09,
        "evaluatorFeeAmount": 0.005,
        "platformFeeAmount": 0.005,
        "funding": {"transactionHash": "0xfunding", "explorerUrl": "https://basescan.org/tx/0xfunding"},
        "completion": {"transactionHash": "0xcompletion", "explorerUrl": "https://basescan.org/tx/0xcompletion"},
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
    assert 'fetch(`/api/assessments?memory=${memory}&${providerQuery}`' in source
    assert "objective" in source and "maxBudget" in source
    assert "hardConstraints" in source and "clientId" in source
    assert "Local mode by default" in source


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


def test_live_acp_mode_requires_explicit_confirmation(tmp_path) -> None:
    service = AssessmentService(tmp_path / "sibyl.db", acp_config=ACP_CONFIG)
    with pytest.raises(ValueError, match="explicit paid-job confirmation"):
        service.submit(REQUEST, memory_enabled=True, provider_mode="live_acp")
    assert service.jobs == {}


def test_http_live_acp_confirmation_and_config_boundary(tmp_path) -> None:
    service = AssessmentService(tmp_path / "sibyl.db", acp_config=ACP_CONFIG)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("Amúyẹ", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/api/acp/config")
        response = connection.getresponse()
        config = json.loads(response.read())
        assert response.status == 200
        assert config["enabled"] is True
        assert config["offering"] == "riskSynthesis"
        assert config["network"] == "Base mainnet"
        assert config["chainId"] == 8453
        assert config["maxExpectedSpend"] == 25.0
        assert config["asset"] == "USDC"
        assert config["status"] == "Live ACP is configured"
        assert "provider" not in config
        assert "missingConfiguration" not in config
        assert not any("key" in name.lower() or "wallet" in name.lower()
                       for name in config)

        connection.request(
            "POST", "/api/assessments?provider=live_acp",
            body=json.dumps(REQUEST), headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 400
        assert "explicit paid-job confirmation" in json.loads(response.read())["error"]
        assert service.jobs == {}
    finally:
        server.shutdown()


def test_confirmed_live_acp_uses_existing_adapter_and_attaches_settlement(tmp_path) -> None:
    source = StaticProtocolDataSource({"aave": PROFILE})
    database = tmp_path / "sibyl.db"
    seed = AssessmentService(database, data_source=source)
    assert wait_for(seed, seed.submit(REQUEST, memory_enabled=False))["status"] == "completed"

    client = FakeAcpRiskClient([acp_risk_result()])
    service = AssessmentService(
        database,
        data_source=source,
        acp_client=client,
        settlement_capture=settlement_proof,
        acp_config=ACP_CONFIG,
    )
    job = wait_for(service, service.submit(
        REQUEST,
        memory_enabled=True,
        provider_mode="live_acp",
        acp_confirmed=True,
    ))
    result = job["result"]

    assert job["status"] == "completed"
    assert len(client.requests) == 1
    assert client.max_costs == [25.0]
    accepted_viability = next(
        output for output in result["execution"]["outputs"].values()
        if output["role"] == "viability_onchain"
    )
    assert client.requests[0]["acceptedViabilityEvidence"] == accepted_viability
    assert result["execution"]["providerJobs"][0]["acpJobId"] == "88001"
    assert result["execution"]["providerJobs"][0]["deliverableRef"] == "acp:88001:deliverable"
    assert result["execution"]["purchasedRoles"] == ["viability_onchain", "risk_synthesis"]
    assert result["settlementProofs"][0]["jobId"] == "88001"
    assert result["settlementProofs"][0]["funding"]["transactionHash"] == "0xfunding"
    event_types = [event["type"] for event in job["events"]]
    assert "acp_purchase_started" in event_types
    assert "acp_job_completed" in event_types
    assert "settlement_verified" in event_types


def test_failed_viability_gate_creates_no_live_acp_job(tmp_path) -> None:
    inactive = {**PROFILE, "tvl": 0, "chains": []}
    client = FakeAcpRiskClient([])
    settlement_calls = []
    service = AssessmentService(
        tmp_path / "sibyl.db",
        data_source=StaticProtocolDataSource({"aave": inactive}),
        acp_client=client,
        settlement_capture=lambda job: settlement_calls.append(job),
        acp_config=ACP_CONFIG,
    )
    job = wait_for(service, service.submit(
        REQUEST,
        memory_enabled=True,
        provider_mode="live_acp",
        acp_confirmed=True,
    ))
    assert job["status"] == "completed"
    assert client.requests == []
    assert job["result"]["execution"]["providerJobs"] == []
    assert job["result"]["settlementProofs"] == []
    assert settlement_calls == []


def test_local_mode_is_deterministic_and_never_calls_acp_or_settlement(tmp_path) -> None:
    client = FakeAcpRiskClient([acp_risk_result()])
    settlement_calls = []
    service = AssessmentService(
        tmp_path / "sibyl.db",
        data_source=StaticProtocolDataSource({"aave": PROFILE}),
        acp_client=client,
        settlement_capture=lambda job: settlement_calls.append(job),
        acp_config=ACP_CONFIG,
    )
    job = wait_for(service, service.submit(REQUEST, memory_enabled=False))
    assert job["status"] == "completed"
    assert client.requests == []
    assert settlement_calls == []
    assert job["result"]["providerMode"] == "local specialists, no ACP payment"


def test_frontend_only_selects_backend_acp_mode_and_does_not_procure() -> None:
    source = Path("frontend/src/app.js").read_text(encoding="utf-8")
    assert "Live ACP risk purchase" in source
    assert 'fetch("/api/acp/config")' in source
    assert "provider=live_acp&confirmAcp=true" in source
    assert "createJobFromOffering" not in source
    assert ".fund(" not in source
