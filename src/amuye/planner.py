from __future__ import annotations

from .domain import ExecutionStrategy, JobRequest, LearnedLesson, ObjectiveIntent, TaskNode, new_id
from .objective import mandatory_security_constraint, resolve_objective_intent


ROLE_COSTS = {
    "viability_onchain": 10.0,
    "risk_synthesis": 25.0,
    "security_analysis": 60.0,
}


def requires_mandatory_security(request: JobRequest) -> bool:
    return mandatory_security_constraint(request)


def _node(job_id: str, role: str, *, dependencies: list[str] | None = None,
          trigger: str | None = None, reason: str | None = None) -> TaskNode:
    return TaskNode(
        id=new_id("node"), jobId=job_id, type=role,
        description={
            "viability_onchain": "Collect protocol viability and onchain evidence",
            "risk_synthesis": "Synthesize material protocol risks",
            "security_analysis": "Perform deeper security analysis",
        }[role],
        assignedProvider=f"specialist-pool-{role}", dependencies=dependencies or [],
        estimatedCost=ROLE_COSTS[role], conditionalTrigger=trigger, mutationReason=reason,
    )


def _intent(request: JobRequest, supplied: ObjectiveIntent | None) -> ObjectiveIntent:
    return supplied or resolve_objective_intent(request)


def baseline_plan(request: JobRequest, job_id: str,
                  objective_intent: ObjectiveIntent | None = None) -> ExecutionStrategy:
    selected = _intent(request, objective_intent)
    nodes = [_node(job_id, role) for role in selected.requiredCapabilities]
    total = sum(node.estimatedCost for node in nodes)
    if total > request.maxBudget:
        raise ValueError("selected specialist purchases exceed maxBudget")
    count = len(nodes)
    return ExecutionStrategy(
        jobId=job_id, source="baseline", taskPattern="protocol_assessment",
        orderedSteps=nodes, branchingRules=[],
        budgetPlan={"ceiling": request.maxBudget, "planned": total},
        expectedLatency=f"{count} selected specialist unit{'s' if count != 1 else ''} commissioned immediately",
        memoryRefs=[],
        rationale=(
            "No applicable operational lesson was recalled, so the capabilities selected "
            "from the client objective are commissioned up front."
        ),
        applicabilityAssessment="No relevant memory available.",
        objectiveIntent=selected.to_dict(),
    )


def plan_with_memory(request: JobRequest, job_id: str,
                     lessons: list[LearnedLesson],
                     objective_intent: ObjectiveIntent | None = None) -> ExecutionStrategy:
    selected = _intent(request, objective_intent)
    priority_exclusion = f"priority={request.priority.lower()}"
    constraint_exclusions = {
        f"hardconstraint={constraint.lower()}" for constraint in request.hardConstraints
    }
    applicable = [
        lesson for lesson in lessons
        if lesson.status == "active"
        and lesson.taskPattern == request.taskClass
        and "mandatory security check" not in " ".join(request.hardConstraints).lower()
        and priority_exclusion not in {condition.lower() for condition in lesson.nonApplicabilityConditions}
        and not constraint_exclusions.intersection({
            condition.lower() for condition in lesson.nonApplicabilityConditions
        })
    ]
    if not applicable:
        return baseline_plan(request, job_id, selected)
    lesson = max(applicable, key=lambda item: item.confidence)
    mandatory_security = requires_mandatory_security(request)
    security_required = selected.intent == "security_assessment"
    nodes: list[TaskNode] = []
    by_role: dict[str, TaskNode] = {}

    if "viability_onchain" in selected.requiredCapabilities:
        by_role["viability_onchain"] = _node(
            job_id, "viability_onchain", reason=f"Applied Sibyl lesson {lesson.id}"
        )
        nodes.append(by_role["viability_onchain"])
    if "risk_synthesis" in selected.requiredCapabilities:
        viability = by_role.get("viability_onchain")
        by_role["risk_synthesis"] = _node(
            job_id, "risk_synthesis",
            dependencies=[viability.id] if viability else [],
            trigger="viability evidence shows continued assessment is justified",
            reason=f"Made conditional by Sibyl lesson {lesson.id}",
        )
        nodes.append(by_role["risk_synthesis"])
    if "security_analysis" in selected.requiredCapabilities:
        risk = by_role.get("risk_synthesis")
        trigger = None if security_required else (
            "risk evidence identifies material issues requiring deeper security analysis"
        )
        if mandatory_security:
            reason = (
                "Security continuation gate from Sibyl lesson "
                f"{lesson.id} overridden by hard client constraint: mandatory security analysis"
            )
        elif security_required:
            reason = "Security continuation gate omitted because the client objective explicitly requires security analysis"
        else:
            reason = f"Made conditional by Sibyl lesson {lesson.id}"
        by_role["security_analysis"] = _node(
            job_id, "security_analysis", dependencies=[risk.id] if risk else [],
            trigger=trigger, reason=reason,
        )
        nodes.append(by_role["security_analysis"])

    if mandatory_security:
        applicability = (
            "Partially applicable: progressive sequencing remains relevant; the security "
            "continuation gate conflicts with mandatory security analysis and is overridden for this job."
        )
    elif len(nodes) == 1:
        applicability = (
            "Applicable only to the selected viability capability; memory cannot add risk "
            "or security work that the objective did not request."
        )
    elif security_required:
        applicability = (
            "Partially applicable: progressive viability-first sequencing remains relevant, "
            "but the explicit security objective cannot be made optional."
        )
    else:
        applicability = (
            "Applicable: same protocol-assessment pattern and no hard constraint requiring "
            "immediate security work."
        )

    selected_cost = sum(ROLE_COSTS[role] for role in selected.requiredCapabilities)
    return ExecutionStrategy(
        jobId=job_id, source="adapted", taskPattern="protocol_assessment",
        orderedSteps=nodes,
        branchingRules=[node.conditionalTrigger for node in nodes if node.conditionalTrigger],
        budgetPlan={
            "ceiling": request.maxBudget,
            "initialCommitment": nodes[0].estimatedCost if nodes else 0.0,
            "conditionalMaximum": selected_cost,
        },
        expectedLatency="one selected specialist unit first, deeper selected work only after evidence gates",
        memoryRefs=[lesson.id],
        rationale=(
            "Recalled execution evidence was applied only to the capabilities selected from "
            "the objective. Current objective and hard constraints remain authoritative."
        ),
        applicabilityAssessment=applicability,
        objectiveIntent=selected.to_dict(),
    )
