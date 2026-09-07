from __future__ import annotations

from dataclasses import asdict

from .domain import JobRequest, LearnedLesson, ReflectionResult, new_id, utc_now
from .planner import baseline_plan, plan_with_memory
from .objective import resolve_objective_intent
from .sibyl_store import SibylStore


PROGRESSIVE_PURCHASING_LESSON_ID = "lesson_progressive_specialist_purchasing_v1"


def execute_baseline(request: JobRequest, store: SibylStore) -> tuple[dict, ReflectionResult]:
    job_id = new_id("job")
    strategy = baseline_plan(request, job_id)
    execution_id = new_id("execution")
    outputs = []
    for index, node in enumerate(strategy.orderedSteps):
        node.status = "completed"
        node.actualCost = node.estimatedCost
        node.startedAt = utc_now()
        node.completedAt = utc_now()
        node.outputRefs = [f"evidence:{execution_id}:{node.type}"]
        outputs.append({
            "role": node.type,
            "purchaseOrder": index + 1,
            "cost": node.actualCost,
            "finding": "viability evidence was sufficient to stop" if index == 0 else "commissioned before prerequisite evidence was assessed",
        })
    execution = {
        "executionId": execution_id,
        "jobId": job_id,
        "request": asdict(request),
        "strategy": strategy.to_dict(),
        "providerOutputs": outputs,
        "totalSpent": sum(item["cost"] for item in outputs),
        "outcome": "objective satisfied by viability evidence; deeper purchases added no decision value",
    }
    history_ref = store.write_execution_history(execution)
    lesson = LearnedLesson(
        id=PROGRESSIVE_PURCHASING_LESSON_ID,
        taskPattern="protocol_assessment",
        strategy="Purchase viability/onchain evidence first. Purchase risk synthesis only if viability evidence justifies continuation. Purchase security analysis only if risk evidence justifies it.",
        reasoning="The baseline bought risk and security work before viability evidence was evaluated. Viability evidence already satisfied the objective, so 85 budget units were avoidable and deeper providers lacked prior context.",
        applicabilityConditions=["protocol assessment", "security analysis is not mandatory at intake", "viability evidence can inform continuation"],
        nonApplicabilityConditions=["hard constraint mandates immediate security analysis", "task is not a protocol assessment"],
        supportingExecutionRefs=[history_ref],
        contradictoryEvidenceRefs=[],
        confidence=0.86,
        status="active",
        lastUpdatedAt=utc_now(),
    )
    reflection = ReflectionResult(
        jobId=job_id,
        successfulDecisions=["viability/onchain analysis produced sufficient decision evidence"],
        failedDecisions=["all specialist work was commissioned before earlier evidence was evaluated"],
        unnecessaryPurchases=["risk_synthesis", "security_analysis"],
        missedDependencies=["risk synthesis should consume viability evidence", "security analysis should consume risk evidence"],
        strategyChanges=[lesson.strategy],
        proposedLessons=[lesson],
        evidenceRefs=[history_ref, *[ref for node in strategy.orderedSteps for ref in node.outputRefs]],
        confidence=0.86,
    )
    store.write_lesson(lesson)
    return execution, reflection


def plan_in_fresh_session(request: JobRequest, store: SibylStore):
    objective_intent = resolve_objective_intent(request)

    # The operational lesson has a stable identity. Read that exact Sibyl entity first so
    # correctness does not depend on full-text ranking/tokenization. Semantic search remains
    # available for additional lessons, but a known persisted policy must be deterministically
    # retrievable in a fresh process.
    lessons: list[LearnedLesson] = []
    primary = store.get_lesson(PROGRESSIVE_PURCHASING_LESSON_ID)
    if primary is not None:
        lessons.append(primary)

    for lesson in store.retrieve_lessons("protocol assessment progressive specialist purchasing"):
        if lesson.id not in {item.id for item in lessons}:
            lessons.append(lesson)

    return plan_with_memory(
        request, new_id("job"), lessons, objective_intent=objective_intent,
    ), lessons
