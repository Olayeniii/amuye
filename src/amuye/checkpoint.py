from __future__ import annotations

from dataclasses import asdict

from .domain import JobRequest, LearnedLesson, ReflectionResult, new_id, utc_now
from .planner import baseline_plan, plan_with_memory
from .objective import resolve_objective_intent
from .sibyl_store import SibylStore


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
        id="lesson_progressive_specialist_purchasing_v1",
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
    # Classification deliberately precedes the read. Keep the established structural
    # query stable so existing persisted lessons remain retrievable across planner versions.
    lessons = store.retrieve_lessons("protocol assessment progressive specialist purchasing")
    return plan_with_memory(
        request, new_id("job"), lessons, objective_intent=objective_intent,
    ), lessons
