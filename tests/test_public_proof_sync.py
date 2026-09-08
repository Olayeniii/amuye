from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from amuye.api import AssessmentService, make_handler


REQUEST = {
    "objective": "Assess protocol Aave for integration and identify material risks",
    "maxBudget": 100,
    "deadline": "2026-09-10T18:00:00Z",
    "priority": "balanced",
    "hardConstraints": ["protocolSlug=aave"],
    "clientId": "public-safety-test",
    "taskClass": "protocol_assessment",
}

ACP_CONFIG = {
    "enabled": True,
    "provider": "0x00000000000000000000000000000000000000aa",
    "offering": "riskSynthesis",
    "network": "Base mainnet",
    "chainId": 8453,
    "maxExpectedSpend": 0.1,
    "asset": "USDC",
    "notice": "This creates and funds a real paid Virtuals ACP job.",
    "missingConfiguration": [],
}

PROOF = {
    "job": {
        "acpJobId": "99001",
        "providerId": "0x00000000000000000000000000000000000000aa",
        "status": "completed",
    },
    "proof": {
        "chainId": 8453,
        "network": "Base mainnet",
        "jobId": "99001",
        "escrowedAmount": 0.1,
        "providerReleasedAmount": 0.09,
        "funding": {
            "transactionHash": "0xfunding",
            "explorerUrl": "https://basescan.org/tx/0xfunding",
        },
        "completion": {
            "transactionHash": "0xcompletion",
            "explorerUrl": "https://basescan.org/tx/0xcompletion",
        },
    },
    "capturedAt": "2026-09-08T20:00:00Z",
}


def start_server(service: AssessmentService, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("Amúyẹ", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_public_deployment_rejects_live_acp_even_when_configured(tmp_path) -> None:
    service = AssessmentService(
        tmp_path / "sibyl.db",
        acp_config=ACP_CONFIG,
        allow_live_acp=False,
    )

    with pytest.raises(ValueError, match="disabled on this deployment"):
        service.submit(
            REQUEST,
            memory_enabled=True,
            provider_mode="live_acp",
            acp_confirmed=True,
        )
    assert service.jobs == {}

    server = start_server(service, tmp_path)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/api/acp/config")
        response = connection.getresponse()
        config = json.loads(response.read())
        assert response.status == 200
        assert config["enabled"] is False
        assert config["status"] == "Live ACP is disabled on this deployment"

        connection.request(
            "POST",
            "/api/assessments?memory=on&provider=live_acp&confirmAcp=true",
            body=json.dumps(REQUEST),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 400
        assert "disabled on this deployment" in body["error"]
        assert service.jobs == {}
    finally:
        server.shutdown()


def test_partner_proof_publish_requires_secret_and_updates_public_read(tmp_path) -> None:
    service = AssessmentService(
        tmp_path / "sibyl.db",
        allow_live_acp=False,
        proof_publish_token="test-secret",
    )
    server = start_server(service, tmp_path)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request(
            "POST",
            "/api/partner-proof/publish",
            body=json.dumps(PROOF),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 401
        response.read()

        connection.request(
            "POST",
            "/api/partner-proof/publish",
            body=json.dumps(PROOF),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret",
            },
        )
        response = connection.getresponse()
        published = json.loads(response.read())
        assert response.status == 200
        assert published == {"status": "published", "jobId": "99001"}

        connection.request("GET", "/api/partner-proof/latest")
        response = connection.getresponse()
        latest = json.loads(response.read())
        assert response.status == 200
        assert latest["job"]["acpJobId"] == "99001"
        assert latest["proof"]["funding"]["transactionHash"] == "0xfunding"
        assert latest["proof"]["completion"]["transactionHash"] == "0xcompletion"
    finally:
        server.shutdown()


def test_partner_proof_publish_rejects_non_base_or_mismatched_job(tmp_path) -> None:
    service = AssessmentService(tmp_path / "sibyl.db")
    wrong_chain = json.loads(json.dumps(PROOF))
    wrong_chain["proof"]["chainId"] = 1
    with pytest.raises(ValueError, match="Base mainnet chain 8453"):
        service.publish_partner_proof(wrong_chain)

    wrong_job = json.loads(json.dumps(PROOF))
    wrong_job["proof"]["jobId"] = "other"
    with pytest.raises(ValueError, match="job IDs do not match"):
        service.publish_partner_proof(wrong_job)
