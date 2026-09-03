from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from amuye.checkpoint import execute_baseline
from amuye.controlled_session import run_session
from amuye.demo_checkpoint7 import CONTROL_PROFILE, CONTROL_REQUEST
from amuye.demo_checkpoint8 import LESSON_ID, MANDATORY_CONSTRAINT, run
from amuye.sibyl_store import SibylStore


@pytest.fixture(scope="module")
def adaptation_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("constraint-adaptation")
    output = root / "adaptation.json"
    return run(root / "sibyl.db", output), output


def test_relevant_sibyl_lesson_is_retrieved_and_partially_applicable(adaptation_report):
    report, _ = adaptation_report
    assert report["recalledLessonId"] == LESSON_ID
    assert report["applicabilityAssessment"].startswith("Partially applicable:")
    assert report["conflictingMemoryRule"] == (
        "Purchase security analysis only if risk evidence justifies it."
    )


def test_compatible_memory_rules_are_preserved(adaptation_report):
    report, _ = adaptation_report
    graph = report["initialAdaptedGraph"]
    viability, risk, security = graph
    assert risk["dependencies"] == [viability["id"]]
    assert risk["conditionalTrigger"] is not None
    assert LESSON_ID in risk["mutationReason"]
    assert security["dependencies"] == [risk["id"]]
    assert len(report["preservedMemoryDerivedRules"]) == 4


def test_conflicting_security_gate_is_overridden_by_client_constraint(adaptation_report):
    report, _ = adaptation_report
    security = next(node for node in report["initialAdaptedGraph"]
                    if node["type"] == "security_analysis")
    assert security["conditionalTrigger"] is None
    assert MANDATORY_CONSTRAINT in report["request"]["hardConstraints"]
    assert "hard client constraint" in report["reasonForOverride"]
    assert report["overrideSource"] == (
        "hard client constraint enforced by planner and ExecutionController"
    )


def test_security_executes_despite_negative_risk_gate(adaptation_report):
    report, _ = adaptation_report
    proof = report["mandatorySecurityEvidence"]
    assert proof["riskContinueToSecurity"] is False
    assert proof["securityNodeStatus"] == "completed"
    assert proof["securityOutput"]["role"] == "security_analysis"
    assert report["executionSequence"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert [item["role"] for item in report["purchases"]] == report["executionSequence"]
    assert "hard client constraint" in proof["policyMutation"]["reason"]


def test_job_override_does_not_mutate_sibyl_lesson(adaptation_report):
    report, _ = adaptation_report
    assert report["lessonIntegrity"]["unchanged"] is True
    assert report["lessonIntegrity"]["before"] == report["lessonIntegrity"]["after"]
    assert report["laterOrdinaryTask"]["recalledLessonIds"] == [LESSON_ID]
    assert report["laterOrdinaryTask"]["securityConditionalTrigger"] is not None
    assert report["laterOrdinaryTask"]["securityStatus"] == "skipped"


def test_budget_policy_still_blocks_mandatory_purchase_without_expanding_authority(tmp_path):
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(CONTROL_REQUEST, store)
    request = replace(
        CONTROL_REQUEST,
        maxBudget=50,
        hardConstraints=[*CONTROL_REQUEST.hardConstraints, MANDATORY_CONSTRAINT],
    )
    result = run_session("on", str(tmp_path / "sibyl.db"), asdict(request), CONTROL_PROFILE)
    security = next(node for node in result["execution"]["finalGraph"]
                    if node["type"] == "security_analysis")
    assert result["execution"]["spent"] == 35.0
    assert result["execution"]["spent"] <= request.maxBudget
    assert security["status"] == "cancelled"
    assert "budget ceiling" in security["mutationReason"]


def test_adaptation_artifact_is_machine_readable_and_consistent(adaptation_report):
    report, output = adaptation_report
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == report
    assert report["spend"] == 95.0
    assert report["remainingBudget"] == 5.0
    assert sum(item["cost"] for item in report["purchases"]) == report["spend"]
    assert next(node for node in report["finalGraph"]
                if node["type"] == "security_analysis")["status"] == "completed"
