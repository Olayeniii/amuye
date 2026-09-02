from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from amuye.acp import AcpPurchaseResult, AcpRiskAssessmentProvider, FakeAcpRiskClient
from amuye.checkpoint import execute_baseline, plan_in_fresh_session
from amuye.demo import DEMO_REQUEST
from amuye.execution import ExecutionController, SpecialistEvidence
from amuye.planner import baseline_plan
from amuye.sibyl_store import SibylStore


def learned_strategy(tmp_path, request=DEMO_REQUEST):
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(DEMO_REQUEST, store)
    strategy, lessons = plan_in_fresh_session(request, SibylStore(tmp_path / "sibyl.db"))
    assert lessons
    return strategy


def viability(*, continue_to_risk: bool, objective_satisfied: bool = False):
    return {
        "role": "viability_onchain",
        "objectiveSatisfied": objective_satisfied,
        "continueToRisk": continue_to_risk,
        "gateReason": "scripted ACP gate",
        "protocol": {"slug": "example", "name": "Example"},
        "metrics": {"currentTvlUsd": 10_000_000, "chains": ["Base"]},
        "evidence": [{"source": "fixture", "field": "tvl", "value": 10_000_000}],
    }


def risk(*, continue_to_security: bool = False):
    return {
        "role": "risk_synthesis",
        "objectiveSatisfied": False,
        "continueToSecurity": continue_to_security,
        "gateReason": "ACP risk gate",
        "identifiedRisks": ([{"id": "risk", "severity": "high", "reason": "signal"}]
                            if continue_to_security else []),
        "evidence": [{"source": "viability_onchain", "field": "metrics", "value": {}}],
        "consumedEvidenceRefs": ["viability_onchain"],
    }


def acp_result(job_id: str, deliverable, *, cost=25, status="completed"):
    return AcpPurchaseResult(
        acp_job_id=job_id,
        provider_id="0xprovider",
        quoted_cost=cost,
        settled_cost=cost if status == "completed" else 0,
        status=status,
        deliverable=deliverable,
        deliverable_ref=f"acp:{job_id}:deliverable",
        evaluation_ref=f"acp:{job_id}:self-evaluation",
        submitted_at="2026-09-02T00:00:00+00:00",
        completed_at="2026-09-02T00:01:00+00:00",
    )


class LocalFixtureProvider:
    def __init__(self, viability_outputs, security_output=None):
        self.viability_outputs = list(viability_outputs)
        self.security_output = security_output or {
            "role": "security_analysis", "objectiveSatisfied": True,
            "assessment": "review_required", "findings": [], "evidence": [],
            "consumedEvidenceRefs": ["viability_onchain", "risk_synthesis"],
        }

    def purchase(self, node, request, context, remaining_budget):
        output = (self.viability_outputs.pop(0) if node.type == "viability_onchain"
                  else self.security_output)
        return SpecialistEvidence("completed", output, providerId=f"local-{node.type}")


def provider(client, viability_outputs):
    return AcpRiskAssessmentProvider(client, LocalFixtureProvider(viability_outputs))


def test_acp_offering_schema_uses_sdk_supported_draft():
    schema_path = Path(__file__).parents[1] / "src/acp/risk-offering-requirements.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"


def test_failed_viability_gate_creates_zero_acp_jobs(tmp_path):
    client = FakeAcpRiskClient([])
    runtime = provider(client, [viability(continue_to_risk=False)])
    result = ExecutionController(DEMO_REQUEST, learned_strategy(tmp_path), runtime).run()
    assert client.requests == []
    assert result.providerJobs == []


def test_successful_gate_creates_one_job_and_passes_exact_viability(tmp_path):
    accepted = viability(continue_to_risk=True)
    client = FakeAcpRiskClient([acp_result("101", risk())])
    runtime = provider(client, [accepted])
    result = ExecutionController(DEMO_REQUEST, learned_strategy(tmp_path), runtime).run()
    assert len(client.requests) == 1
    assert client.requests[0]["acceptedViabilityEvidence"] == accepted
    assert len(result.providerJobs) == 1
    assert result.providerJobs[0]["acpJobId"] == "101"


def test_valid_deliverable_becomes_existing_risk_contract(tmp_path):
    delivered = risk(continue_to_security=True)
    client = FakeAcpRiskClient([acp_result("102", delivered)])
    runtime = provider(client, [viability(continue_to_risk=True)])
    result = ExecutionController(DEMO_REQUEST, learned_strategy(tmp_path), runtime).run()
    risk_output = next(item for item in result.outputs.values()
                       if item.get("role") == "risk_synthesis")
    assert risk_output == delivered
    assert runtime.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]


def test_malformed_acp_output_uses_existing_replacement_path(tmp_path):
    client = FakeAcpRiskClient([
        acp_result("bad", {"role": "risk_synthesis"}),
        acp_result("good", risk()),
    ])
    runtime = provider(client, [viability(continue_to_risk=True)])
    result = ExecutionController(DEMO_REQUEST, learned_strategy(tmp_path), runtime).run()
    risk_nodes = [item for item in result.nodes if item["type"] == "risk_synthesis"]
    assert [item["status"] for item in risk_nodes] == ["replaced", "completed"]
    assert len(client.requests) == 2
    assert any(item["mutation"] == "node_added" for item in result.mutations)


def test_acp_settlement_cost_counts_against_budget(tmp_path):
    request = replace(DEMO_REQUEST, maxBudget=40)
    client = FakeAcpRiskClient([acp_result("103", risk(), cost=30)])
    runtime = provider(client, [viability(continue_to_risk=True)])
    result = ExecutionController(request, learned_strategy(tmp_path, request), runtime).run()
    assert client.max_costs == [30]
    assert result.spent == 40
    assert result.remainingBudget == 0
    assert result.providerJobs[0]["settledCost"] == 30


def test_memory_progressive_gate_controls_actual_acp_purchase(tmp_path):
    adapted_client = FakeAcpRiskClient([])
    adapted_runtime = provider(adapted_client, [viability(continue_to_risk=False)])
    adapted = ExecutionController(
        DEMO_REQUEST, learned_strategy(tmp_path), adapted_runtime,
    ).run()
    cold_client = FakeAcpRiskClient([acp_result("104", risk())])
    cold_runtime = provider(cold_client, [viability(continue_to_risk=False)])
    cold = ExecutionController(
        DEMO_REQUEST, baseline_plan(DEMO_REQUEST, "cold-acp"), cold_runtime,
    ).run()
    assert len(adapted_client.requests) == 0
    assert adapted.spent == 10
    assert len(cold_client.requests) == 1
    assert cold.spent == 95
