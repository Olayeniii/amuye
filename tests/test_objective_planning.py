from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from amuye.acp import FakeAcpRiskClient
from amuye.api import AssessmentService
from amuye.checkpoint import execute_baseline, plan_in_fresh_session
from amuye.demo import DEMO_REQUEST
from amuye.execution import ExecutionController, ScriptedSpecialistProvider, SpecialistEvidence
from amuye.live import run_live_assessment
from amuye.objective import UnsupportedObjectiveError, classify_objective, resolve_objective_intent
from amuye.planner import baseline_plan
from amuye.sibyl_store import SibylStore
from amuye.specialists import StaticProtocolDataSource


EVIDENCE_OBJECTIVE = "Assess Aave for basic integration viability. I only need public protocol evidence."
RISK_OBJECTIVE = "Assess Aave for integration and identify material risks."
SECURITY_OBJECTIVE = "Assess Aave for integration. A security review is mandatory."
RESEARCH_OBJECTIVE = (
    "Research Aave's recent governance and protocol developments and identify anything relevant to an integrator."
)
PROFILE = {
    "name": "Aave", "category": "Lending", "url": "https://aave.com",
    "tvl": 2_000_000, "chains": ["Ethereum"], "audits": "2",
    "audit_links": ["https://example.test/audit"], "change_7d": 1,
}


def request(objective: str, *, budget: float = 100,
            constraints: list[str] | None = None):
    return replace(
        DEMO_REQUEST,
        objective=objective,
        maxBudget=budget,
        hardConstraints=constraints or ["protocolSlug=aave"],
    )


def test_classifier_returns_constrained_structured_intents() -> None:
    evidence = classify_objective(EVIDENCE_OBJECTIVE)
    risk = classify_objective(RISK_OBJECTIVE)
    security = classify_objective(SECURITY_OBJECTIVE)
    unsupported = classify_objective(RESEARCH_OBJECTIVE)

    assert evidence.to_dict() == {
        "intent": "evidence_only",
        "requiredCapabilities": ["viability_onchain"],
        "unsupportedNeeds": [],
        "reason": "The objective explicitly limits the assessment to public viability evidence.",
    }
    assert risk.intent == "risk_assessment"
    assert risk.requiredCapabilities == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert security.intent == "security_assessment"
    assert unsupported.intent == "unsupported"
    assert unsupported.unsupportedNeeds == ["recent_protocol_governance_research"]


@pytest.mark.parametrize((
    "objective", "constraints", "intent", "capabilities", "unsupported", "maximum",
), [
    (
        "Assess Aave for integration viability.", ["protocolSlug=aave"],
        "evidence_only", ["viability_onchain"], [], 10.0,
    ),
    (
        "Assess Aave.", ["protocolSlug=aave"],
        "unsupported", [], ["ambiguous_protocol_assessment_need"], None,
    ),
    (
        "Is Aave viable for integration?", ["protocolSlug=aave"],
        "evidence_only", ["viability_onchain"], [], 10.0,
    ),
    (
        "Assess Aave for integration viability and material risks.", ["protocolSlug=aave"],
        "risk_assessment", ["viability_onchain", "risk_synthesis", "security_analysis"], [], 95.0,
    ),
    (
        "Assess Aave's security.", ["protocolSlug=aave"],
        "security_assessment", ["viability_onchain", "risk_synthesis", "security_analysis"], [], 95.0,
    ),
    (
        "Research recent Aave governance changes.", ["protocolSlug=aave"],
        "unsupported", [], ["recent_protocol_governance_research"], None,
    ),
    (
        "Assess Aave for integration viability. Security review is mandatory.",
        ["protocolSlug=aave", "security review is mandatory"],
        "security_assessment", ["viability_onchain", "risk_synthesis", "security_analysis"], [], 95.0,
    ),
])
def test_exact_objective_phrase_regressions(
    objective, constraints, intent, capabilities, unsupported, maximum,
) -> None:
    assessment = request(objective, constraints=constraints)
    classified = classify_objective(objective)

    if intent == "unsupported":
        assert classified.intent == intent
        assert classified.requiredCapabilities == capabilities
        assert classified.unsupportedNeeds == unsupported
        with pytest.raises(UnsupportedObjectiveError):
            baseline_plan(assessment, "exact-phrase")
        return

    resolved = resolve_objective_intent(assessment)
    strategy = baseline_plan(assessment, "exact-phrase", resolved)
    assert resolved.intent == intent
    assert resolved.requiredCapabilities == capabilities
    assert resolved.unsupportedNeeds == unsupported
    assert strategy.budgetPlan["planned"] == maximum
    assert ("risk_synthesis" in capabilities) is (maximum == 95.0)
    assert ("security_analysis" in capabilities) is (maximum == 95.0)


def test_evidence_only_plan_has_one_node_and_selected_budget() -> None:
    strategy = baseline_plan(request(EVIDENCE_OBJECTIVE, budget=10), "evidence-job")

    assert [node.type for node in strategy.orderedSteps] == ["viability_onchain"]
    assert strategy.budgetPlan == {"ceiling": 10, "planned": 10.0}
    assert strategy.objectiveIntent["intent"] == "evidence_only"


def test_sibyl_cannot_add_unselected_capabilities(tmp_path) -> None:
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(DEMO_REQUEST, store)

    strategy, recalled = plan_in_fresh_session(
        request(EVIDENCE_OBJECTIVE, budget=10), store,
    )

    assert recalled
    assert strategy.memoryRefs == ["lesson_progressive_specialist_purchasing_v1"]
    assert [node.type for node in strategy.orderedSteps] == ["viability_onchain"]
    assert strategy.budgetPlan["conditionalMaximum"] == 10.0


def test_risk_objective_preserves_controlled_memory_difference(tmp_path) -> None:
    assessment = request(RISK_OBJECTIVE)
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(assessment, store)
    cold = baseline_plan(assessment, "cold")
    informed, recalled = plan_in_fresh_session(assessment, store)

    assert [node.type for node in cold.orderedSteps] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert all(node.conditionalTrigger is None for node in cold.orderedSteps)
    assert recalled and informed.memoryRefs == [recalled[0].id]
    assert informed.orderedSteps[1].conditionalTrigger is not None
    assert informed.orderedSteps[2].conditionalTrigger is not None


def test_hard_constraint_adds_security_and_controller_enforces_it(tmp_path) -> None:
    assessment = request(
        EVIDENCE_OBJECTIVE,
        constraints=["protocolSlug=aave", "security review is mandatory"],
    )
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(DEMO_REQUEST, store)
    strategy, _ = plan_in_fresh_session(assessment, store)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [SpecialistEvidence("completed", {"objectiveSatisfied": False, "continueToRisk": True})],
        "risk_synthesis": [SpecialistEvidence("completed", {"objectiveSatisfied": False, "continueToSecurity": False})],
        "security_analysis": [SpecialistEvidence("completed", {"objectiveSatisfied": True})],
    })

    result = ExecutionController(assessment, strategy, provider).run()

    assert strategy.objectiveIntent["intent"] == "security_assessment"
    assert [node.type for node in strategy.orderedSteps] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert strategy.orderedSteps[2].conditionalTrigger is None
    assert result.purchasedRoles == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]


def test_unsupported_research_is_rejected_before_job_creation(tmp_path) -> None:
    service = AssessmentService(tmp_path / "sibyl.db")

    with pytest.raises(UnsupportedObjectiveError, match="not supported"):
        service.submit(asdict(request(RESEARCH_OBJECTIVE)), memory_enabled=True)

    assert service.jobs == {}


def test_evidence_only_live_acp_mode_never_calls_risk_purchase(tmp_path) -> None:
    client = FakeAcpRiskClient([])
    result = run_live_assessment(
        asdict(request(EVIDENCE_OBJECTIVE, budget=10)),
        memory_enabled=False,
        memory_db=tmp_path / "sibyl.db",
        data_source=StaticProtocolDataSource({"aave": PROFILE}),
        provider_mode="live_acp",
        acp_confirmed=True,
        acp_client=client,
        settlement_capture=lambda job: pytest.fail("settlement must not be captured"),
        acp_max_cost=0.1,
    )

    assert client.requests == []
    assert result["execution"]["purchasedRoles"] == ["viability_onchain"]
    assert result["execution"]["providerJobs"] == []
    assert result["settlementProofs"] == []


def test_security_objective_selects_security_without_a_hard_constraint() -> None:
    strategy = baseline_plan(request(SECURITY_OBJECTIVE), "security-job")

    assert strategy.objectiveIntent["intent"] == "security_assessment"
    assert [node.type for node in strategy.orderedSteps] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]


def test_frontend_only_displays_backend_intent_and_does_not_classify() -> None:
    source = Path("frontend/src/app.js").read_text(encoding="utf-8")

    assert "result.strategy.objectiveIntent" in source
    assert "unsupportedNeeds" not in source
    assert "evidence_only" not in source
    assert "risk_assessment" not in source
    assert "security_assessment" not in source
