from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from amuye.api import AssessmentService, make_handler


REQUEST = {
    "objective": "Assess protocol Aave for integration and identify material risks",
    "maxBudget": 100,
    "deadline": "2026-09-10T18:00:00Z",
    "priority": "balanced",
    "hardConstraints": ["protocolSlug=aave"],
    "clientId": "history-test-client",
    "taskClass": "protocol_assessment",
}


def successful_runner(request, **kwargs):
    progress = kwargs.get("progress")
    if progress:
        progress({"type": "plan_created"})
        progress({"type": "execution_completed"})
    return {
        "status": "completed",
        "jobId": "runtime-job-1",
        "request": request,
        "providerMode": "local specialists, no ACP payment",
        "execution": {"providerJobs": []},
        "settlementProofs": [],
    }


def failing_runner(request, **kwargs):
    progress = kwargs.get("progress")
    if progress:
        progress({"type": "plan_created"})
    raise RuntimeError("synthetic execution failure")


def wait_for(service: AssessmentService, job_id: str) -> dict:
    for _ in range(200):
        value = service.get(job_id)
        assert value is not None
        if value["status"] in {"completed", "failed"}:
            return value
        time.sleep(0.01)
    raise AssertionError("assessment did not finish")


def test_completed_job_survives_service_restart(tmp_path) -> None:
    memory_db = tmp_path / "sibyl.db"
    history_db = tmp_path / "assessment-history.db"
    service = AssessmentService(
        memory_db,
        history_db=history_db,
        runner=successful_runner,
    )
    job_id = service.submit(REQUEST, memory_enabled=True)
    completed = wait_for(service, job_id)

    assert completed["status"] == "completed"
    assert completed["createdAt"]
    assert completed["updatedAt"]
    assert completed["events"][0]["type"] == "request_accepted"

    restarted = AssessmentService(
        memory_db,
        history_db=history_db,
        runner=successful_runner,
    )
    restored = restarted.get(job_id)

    assert restarted.jobs == {}
    assert restored is not None
    assert restored["id"] == job_id
    assert restored["status"] == "completed"
    assert restored["request"] == REQUEST
    assert restored["result"]["jobId"] == "runtime-job-1"
    assert [event["type"] for event in restored["events"]] == [
        "request_accepted", "plan_created", "execution_completed",
    ]


def test_failed_job_and_error_survive_restart(tmp_path) -> None:
    history_db = tmp_path / "assessment-history.db"
    service = AssessmentService(
        tmp_path / "sibyl.db",
        history_db=history_db,
        runner=failing_runner,
    )
    job_id = service.submit(REQUEST, memory_enabled=False)
    failed = wait_for(service, job_id)
    assert failed["status"] == "failed"

    restarted = AssessmentService(
        tmp_path / "sibyl.db",
        history_db=history_db,
        runner=successful_runner,
    )
    restored = restarted.get(job_id)

    assert restored is not None
    assert restored["status"] == "failed"
    assert restored["error"] == "synthetic execution failure"
    assert restored["events"][-1]["type"] == "execution_failed"


def test_history_endpoint_lists_persisted_jobs(tmp_path) -> None:
    memory_db = tmp_path / "sibyl.db"
    history_db = tmp_path / "assessment-history.db"
    service = AssessmentService(
        memory_db,
        history_db=history_db,
        runner=successful_runner,
    )
    first = service.submit(REQUEST, memory_enabled=False)
    second = service.submit({**REQUEST, "clientId": "history-test-client-2"}, memory_enabled=True)
    wait_for(service, first)
    wait_for(service, second)

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("Amúyẹ", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/api/assessments?limit=10")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        ids = [item["id"] for item in payload["assessments"]]
        assert first in ids
        assert second in ids
        assert all("result" not in item for item in payload["assessments"])
    finally:
        server.shutdown()
