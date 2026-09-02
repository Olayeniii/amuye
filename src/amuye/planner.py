from __future__ import annotations

from .domain import ExecutionStrategy, JobRequest, LearnedLesson, TaskNode, new_id


ROLE_COSTS = {
    "viability_onchain": 10.0,
    "risk_synthesis": 25.0,
    "security_analysis": 60.0,
}


def _node(job_id: str, role: str, *, dependencies: list[str] | None = None,
          trigger: str | None = None, reason: str | None = None) -> TaskNode:
    return TaskNode(
        id=new_id("node"),
        jobId=job_id,
        type=role,
        description={
            "viability_onchain": "Collect protocol viability and onchain evidence",
            "risk_synthesis": "Synthesize material protocol risks",
            "security_analysis": "Perform deeper security analysis",
        }[role],
        assignedProvider=f"checkpoint1-{role}",
        dependencies=dependencies or [],
        estimatedCost=ROLE_COSTS[role],
        conditionalTrigger=trigger,
        mutationReason=reason,
    )


def baseline_plan(request: JobRequest, job_id: str) -> ExecutionStrategy:
    nodes = [_node(job_id, role) for role in ROLE_COSTS]
    total = sum(node.estimatedCost for node in nodes)
    if total > request.maxBudget:
        raise ValueError("baseline specialist purchases exceed maxBudget")
    return ExecutionStrategy(
        jobId=job_id,
        source="baseline",
        taskPattern="protocol_assessment",
        orderedSteps=nodes,
        branchingRules=[],
        budgetPlan={"ceiling": request.maxBudget, "planned": total},
        expectedLatency="three specialist units commissioned immediately",
        memoryRefs=[],
        rationale="No applicable operational lesson was recalled, so all reasonable specialist roles are commissioned up front.",
        applicabilityAssessment="No relevant memory available.",
    )


def plan_with_memory(request: JobRequest, job_id: str,
                     lessons: list[LearnedLesson]) -> ExecutionStrategy:
    applicable = [
        lesson for lesson in lessons
        if lesson.status == "active"
        and lesson.taskPattern == request.taskClass
        and "mandatory security check" not in " ".join(request.hardConstraints).lower()
    ]
    if not applicable:
        return baseline_plan(request, job_id)
    lesson = max(applicable, key=lambda item: item.confidence)
    viability = _node(job_id, "viability_onchain", reason=f"Applied Sibyl lesson {lesson.id}")
    risk = _node(
        job_id,
        "risk_synthesis",
        dependencies=[viability.id],
        trigger="viability evidence shows continued assessment is justified",
        reason=f"Made conditional by Sibyl lesson {lesson.id}",
    )
    security = _node(
        job_id,
        "security_analysis",
        dependencies=[risk.id],
        trigger="risk evidence identifies material issues requiring deeper security analysis",
        reason=f"Made conditional by Sibyl lesson {lesson.id}",
    )
    return ExecutionStrategy(
        jobId=job_id,
        source="adapted",
        taskPattern="protocol_assessment",
        orderedSteps=[viability, risk, security],
        branchingRules=[risk.conditionalTrigger or "", security.conditionalTrigger or ""],
        budgetPlan={"ceiling": request.maxBudget, "initialCommitment": viability.estimatedCost,
                    "conditionalMaximum": sum(ROLE_COSTS.values())},
        expectedLatency="one specialist unit first, deeper work only after evidence gates",
        memoryRefs=[lesson.id],
        rationale="Recalled execution evidence showed that early deep purchases were unnecessary and lacked prerequisite context.",
        applicabilityAssessment="Applicable: same protocol-assessment pattern and no hard constraint requiring immediate security work.",
    )

