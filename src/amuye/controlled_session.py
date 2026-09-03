from __future__ import annotations

import argparse
import json
import os
import platform
from dataclasses import asdict

from .checkpoint import plan_in_fresh_session
from .domain import JobRequest, new_id
from .execution import ExecutionController
from .planner import ROLE_COSTS, baseline_plan
from .sibyl_store import SibylStore
from .specialists import ProtocolAssessmentProvider, StaticProtocolDataSource


def _graph_by_role(nodes: list[dict]) -> list[dict]:
    role_by_id = {node["id"]: node["type"] for node in nodes}
    return [{
        "role": node["type"],
        "dependencies": [role_by_id[item] for item in node["dependencies"]],
        "estimatedCost": node["estimatedCost"],
        "conditionalTrigger": node["conditionalTrigger"],
        "status": node["status"],
        "actualCost": node["actualCost"],
        "mutationReason": node["mutationReason"],
    } for node in nodes]


def run_session(
    memory_state: str,
    memory_db: str,
    request_value: dict,
    provider_profile: dict,
) -> dict:
    request = JobRequest.from_dict(request_value)
    if memory_state == "on":
        strategy, recalled = plan_in_fresh_session(request, SibylStore(memory_db))
    elif memory_state == "off":
        strategy = baseline_plan(request, new_id("job"))
        recalled = []
    else:
        raise ValueError("memory_state must be on or off")

    initial_graph = strategy.to_dict()["orderedSteps"]
    slug = next(
        item.split("=", 1)[1].strip().lower()
        for item in request.hardConstraints
        if item.lower().startswith("protocolslug=")
    )
    provider = ProtocolAssessmentProvider(
        StaticProtocolDataSource({slug: provider_profile})
    )
    execution = ExecutionController(request, strategy, provider).run()
    final_graph = execution.nodes
    purchased = []
    for role in execution.purchasedRoles:
        node = next(item for item in final_graph
                    if item["type"] == role and item["actualCost"] > 0)
        purchased.append({
            "providerJobType": "local_specialist",
            "providerId": f"local-{role}",
            "role": role,
            "cost": node["actualCost"],
            "nodeId": node["id"],
        })
    skipped = [{
        "nodeId": node["id"],
        "role": node["type"],
        "status": node["status"],
        "reason": node["mutationReason"],
    } for node in final_graph if node["status"] in {"skipped", "cancelled"}]
    lesson_ids = [lesson.id for lesson in recalled]
    return {
        "freshProcessId": os.getpid(),
        "request": asdict(request),
        "environment": {
            "model": "none, deterministic protocol-assessment specialists",
            "pythonImplementation": platform.python_implementation(),
            "pythonVersion": platform.python_version(),
            "planner": "amuye.planner",
            "providerPool": [
                "ViabilityOnchainSpecialist",
                "RiskSynthesisSpecialist",
                "SecurityAnalysisSpecialist",
            ],
            "providerDataSource": "StaticProtocolDataSource",
            "pricing": dict(ROLE_COSTS),
            "executionController": "ExecutionController",
            "evaluationLogic": "validate_specialist_evidence and role-specific continuation gates",
            "providerProfile": provider_profile,
        },
        "memory": {
            "state": memory_state,
            "operationalMemoryAvailableToPlanner": memory_state == "on",
            "recalledLessonIds": lesson_ids,
            "applicabilityDecision": strategy.applicabilityAssessment,
            "strategyMemoryRefs": list(strategy.memoryRefs),
        },
        "strategy": {
            "source": strategy.source,
            "rationale": strategy.rationale,
            "branchingRules": list(strategy.branchingRules),
            "initialGraph": initial_graph,
            "initialGraphByRole": _graph_by_role(initial_graph),
        },
        "execution": {
            "status": execution.status,
            "finalGraph": final_graph,
            "finalGraphByRole": _graph_by_role(final_graph),
            "providerJobsPurchased": purchased,
            "executionSequence": list(provider.calls),
            "branchesSkippedOrCancelled": skipped,
            "spent": execution.spent,
            "remainingBudget": execution.remainingBudget,
            "stoppedEarly": execution.stoppedEarly,
            "stopReason": execution.stopReason,
            "result": {
                "status": execution.status,
                "evidence": list(execution.outputs.values()),
            },
            "mutations": execution.mutations,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one isolated Amúyẹ memory-control session")
    parser.add_argument("--memory-state", choices=["off", "on"], required=True)
    parser.add_argument("--memory-db", required=True)
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--provider-profile-json", required=True)
    args = parser.parse_args()
    report = run_session(
        args.memory_state,
        args.memory_db,
        json.loads(args.request_json),
        json.loads(args.provider_profile_json),
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
