from __future__ import annotations

from dataclasses import replace

from amuye.checkpoint import execute_baseline, plan_in_fresh_session
from amuye.demo import DEMO_REQUEST
from amuye.execution import ExecutionController, ScriptedSpecialistProvider, SpecialistEvidence
from amuye.planner import baseline_plan
from amuye.sibyl_store import SibylStore


def evidence(status="completed", cost=None, provider=None, **findings):
    return SpecialistEvidence(status=status, findings=findings, actualCost=cost, providerId=provider)


def recalled_strategy(tmp_path, request=DEMO_REQUEST):
    store = SibylStore(tmp_path / "sibyl.db")
    execute_baseline(DEMO_REQUEST, store)
    strategy, lessons = plan_in_fresh_session(request, SibylStore(tmp_path / "sibyl.db"))
    assert lessons
    assert strategy.source == "adapted"
    return strategy


def test_viability_gate_can_skip_risk_and_security(tmp_path):
    strategy = recalled_strategy(tmp_path)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=False, continueToRisk=False)],
    })
    result = ExecutionController(DEMO_REQUEST, strategy, provider).run()

    by_role = {node["type"]: node for node in result.nodes}
    assert provider.calls == ["viability_onchain"]
    assert by_role["viability_onchain"]["status"] == "completed"
    assert by_role["risk_synthesis"]["status"] == "skipped"
    assert by_role["security_analysis"]["status"] == "skipped"
    assert result.stoppedEarly is False
    assert result.spent == 10.0
    assert result.remainingBudget == 90.0
    assert "did not justify risk synthesis" in by_role["risk_synthesis"]["mutationReason"]


def test_early_stopping_leaves_unused_budget_unspent(tmp_path):
    strategy = recalled_strategy(tmp_path)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=True, continueToRisk=True)],
    })
    result = ExecutionController(DEMO_REQUEST, strategy, provider).run()

    assert result.stoppedEarly is True
    assert result.stopReason == "objective satisfied by viability_onchain evidence"
    assert provider.calls == ["viability_onchain"]
    assert result.spent == 10.0
    assert result.remainingBudget == 90.0


def test_risk_evidence_conditionally_purchases_security(tmp_path):
    strategy = recalled_strategy(tmp_path)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=False, continueToRisk=True)],
        "risk_synthesis": [evidence(objectiveSatisfied=False, continueToSecurity=True)],
        "security_analysis": [evidence(objectiveSatisfied=True)],
    })
    result = ExecutionController(DEMO_REQUEST, strategy, provider).run()

    assert provider.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]
    assert result.spent == 95.0
    security = next(node for node in result.nodes if node["type"] == "security_analysis")
    assert security["status"] == "completed"
    assert any("risk evidence justified security analysis" in item["reason"]
               for item in result.mutations if item["nodeId"] == security["id"])


def test_failed_node_is_replaced_and_dependents_are_rewired(tmp_path):
    strategy = recalled_strategy(tmp_path)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [
            evidence(status="failed", provider="backup-viability"),
            evidence(objectiveSatisfied=True, continueToRisk=False),
        ],
    })
    result = ExecutionController(DEMO_REQUEST, strategy, provider).run()

    viability_nodes = [node for node in result.nodes if node["type"] == "viability_onchain"]
    assert [node["status"] for node in viability_nodes] == ["replaced", "completed"]
    assert provider.calls == ["viability_onchain", "viability_onchain"]
    assert any(item["mutation"] == "node_added" for item in result.mutations)
    assert any(item["mutation"] == "dependency_rewired" for item in result.mutations)
    assert all(item["reason"].strip() for item in result.mutations)


def test_execution_cannot_exceed_budget(tmp_path):
    request = replace(DEMO_REQUEST, maxBudget=50)
    strategy = recalled_strategy(tmp_path, request)
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=False, continueToRisk=True)],
        "risk_synthesis": [evidence(objectiveSatisfied=False, continueToSecurity=True)],
    })
    result = ExecutionController(request, strategy, provider).run()

    assert result.spent == 35.0
    assert result.spent <= request.maxBudget
    assert provider.calls == ["viability_onchain", "risk_synthesis"]
    security = next(node for node in result.nodes if node["type"] == "security_analysis")
    assert security["status"] == "cancelled"
    assert "budget ceiling" in security["mutationReason"]


def test_recalled_strategy_drives_execution_not_only_plan_shape(tmp_path):
    adapted = recalled_strategy(tmp_path)
    progressive_provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=False, continueToRisk=False)],
        "risk_synthesis": [evidence(objectiveSatisfied=False, continueToSecurity=False)],
        "security_analysis": [evidence(objectiveSatisfied=False)],
    })
    progressive = ExecutionController(DEMO_REQUEST, adapted, progressive_provider).run()

    cold = baseline_plan(DEMO_REQUEST, "cold-comparison")
    cold_provider = ScriptedSpecialistProvider({
        "viability_onchain": [evidence(objectiveSatisfied=False, continueToRisk=False)],
        "risk_synthesis": [evidence(objectiveSatisfied=False, continueToSecurity=False)],
        "security_analysis": [evidence(objectiveSatisfied=False)],
    })
    cold_result = ExecutionController(DEMO_REQUEST, cold, cold_provider).run()

    assert adapted.memoryRefs == ["lesson_progressive_specialist_purchasing_v1"]
    assert progressive_provider.calls == ["viability_onchain"]
    assert progressive.spent == 10.0
    assert cold_provider.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]
    assert cold_result.spent == 95.0
