from __future__ import annotations

from dataclasses import replace

from amuye.checkpoint import execute_baseline, plan_in_fresh_session
from amuye.demo import DEMO_REQUEST
from amuye.execution import ExecutionController, ScriptedSpecialistProvider, SpecialistEvidence
from amuye.planner import baseline_plan
from amuye.sibyl_store import SibylStore
from amuye.specialists import ProtocolAssessmentProvider, StaticProtocolDataSource


def protocol_request(slug: str, budget: float = 100):
    return replace(
        DEMO_REQUEST,
        objective=f"Assess whether protocol {slug} warrants deeper diligence before integration",
        maxBudget=budget,
        hardConstraints=["do not exceed budget", f"protocolSlug={slug}"],
    )


def learned_strategy(tmp_path, request):
    memory_db = tmp_path / "sibyl.db"
    execute_baseline(request, SibylStore(memory_db))
    strategy, lessons = plan_in_fresh_session(request, SibylStore(memory_db))
    assert lessons
    return strategy


def active_profile(*, audits="0", chains=None, category="Lending"):
    return {
        "name": "Example Protocol",
        "category": category,
        "url": "https://example.invalid",
        "tvl": [{"date": 1, "totalLiquidityUSD": 250_000_000}],
        "chains": chains or ["Ethereum", "Base", "Arbitrum", "Optimism"],
        "audits": audits,
        "audit_links": ["https://audit.example/report"] if audits != "0" else [],
        "change_1d": 1.5,
        "change_7d": -2.0,
        "mcap": 500_000_000,
    }


def test_risk_receives_viability_evidence_as_input(tmp_path):
    request = protocol_request("example")
    provider = ProtocolAssessmentProvider(StaticProtocolDataSource({"example": active_profile()}))
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()

    assert provider.calls[:2] == ["viability_onchain", "risk_synthesis"]
    assert "viability_onchain" in provider.contexts[1]
    risk_output = next(output for output in result.outputs.values()
                       if output.get("role") == "risk_synthesis")
    assert risk_output["consumedEvidenceRefs"] == ["viability_onchain"]


def test_security_receives_viability_and_risk_context(tmp_path):
    request = protocol_request("example")
    provider = ProtocolAssessmentProvider(StaticProtocolDataSource({"example": active_profile()}))
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()

    assert provider.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]
    assert set(provider.contexts[2]) == {"viability_onchain", "risk_synthesis"}
    security = next(output for output in result.outputs.values()
                    if output.get("role") == "security_analysis")
    assert security["consumedEvidenceRefs"] == ["viability_onchain", "risk_synthesis"]


def test_malformed_output_triggers_failure_and_replacement(tmp_path):
    request = protocol_request("example")
    provider = ScriptedSpecialistProvider({
        "viability_onchain": [
            {"objectiveSatisfied": True},
            SpecialistEvidence("completed", {
                "objectiveSatisfied": True,
                "continueToRisk": False,
            }),
        ],
    })
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()

    viability_nodes = [node for node in result.nodes if node["type"] == "viability_onchain"]
    assert [node["status"] for node in viability_nodes] == ["replaced", "completed"]
    first_output = result.outputs[viability_nodes[0]["id"]]
    assert "validationError" in first_output
    assert any(item["mutation"] == "node_added" for item in result.mutations)


def test_real_specialist_output_can_stop_early(tmp_path):
    request = protocol_request("inactive")
    profile = {
        "name": "Inactive Protocol",
        "category": "DEX",
        "tvl": [{"date": 1, "totalLiquidityUSD": 25_000}],
        "chains": ["Ethereum"],
        "audits": "0",
    }
    provider = ProtocolAssessmentProvider(StaticProtocolDataSource({"inactive": profile}))
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()

    assert provider.calls == ["viability_onchain"]
    assert result.stoppedEarly is True
    assert result.spent == 10.0
    assert result.remainingBudget == 90.0


def test_viability_derives_chains_from_current_chain_tvl(tmp_path):
    request = protocol_request("derived")
    profile = {
        "name": "Derived Chains",
        "tvl": [{"date": 1, "totalLiquidityUSD": 20_000_000}],
        "chains": [],
        "currentChainTvls": {
            "Ethereum": 12_000_000,
            "Base": 8_000_000,
            "Ethereum-borrowed": 4_000_000,
        },
    }
    provider = ProtocolAssessmentProvider(StaticProtocolDataSource({"derived": profile}))
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()
    viability = next(output for output in result.outputs.values()
                     if output.get("role") == "viability_onchain")

    assert viability["metrics"]["chains"] == ["Base", "Ethereum"]
    assert viability["continueToRisk"] is True


def test_real_specialists_can_execute_full_progressive_path(tmp_path):
    request = protocol_request("example")
    provider = ProtocolAssessmentProvider(StaticProtocolDataSource({"example": active_profile()}))
    result = ExecutionController(request, learned_strategy(tmp_path, request), provider).run()

    assert provider.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]
    assert result.purchasedRoles == provider.calls
    assert result.spent == 95.0
    assert all(node["status"] == "completed" for node in result.nodes)


def test_memory_changes_real_specialist_purchases(tmp_path):
    request = protocol_request("lower-risk")
    profile = active_profile(audits="2", chains=["Ethereum"], category="DEX")
    source = StaticProtocolDataSource({"lower-risk": profile})

    informed_provider = ProtocolAssessmentProvider(source)
    informed = ExecutionController(
        request,
        learned_strategy(tmp_path, request),
        informed_provider,
    ).run()

    cold_provider = ProtocolAssessmentProvider(source)
    cold = ExecutionController(
        request,
        baseline_plan(request, "cold-real-specialists"),
        cold_provider,
    ).run()

    assert informed_provider.calls == ["viability_onchain", "risk_synthesis"]
    assert informed.spent == 35.0
    assert cold_provider.calls == ["viability_onchain", "risk_synthesis", "security_analysis"]
    assert cold.spent == 95.0
