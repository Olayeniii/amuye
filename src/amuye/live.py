from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .checkpoint import plan_in_fresh_session
from .domain import JobRequest, LearnedLesson, ReflectionResult, new_id, utc_now
from .execution import ExecutionController
from .learning import evaluate_execution, learn_from_execution
from .planner import baseline_plan
from .sibyl_store import SibylStore
from .specialists import ProtocolAssessmentProvider, ProtocolDataSource


Progress = Callable[[dict[str, Any]], None]
LESSON_ID = "lesson_progressive_specialist_purchasing_v1"
PROCESS_SESSION_ID = f"amuye-process-{os.getpid()}-{uuid4().hex[:8]}"


def _emit(callback: Progress | None, event_type: str, **values: Any) -> None:
    if callback is not None:
        callback({"type": event_type, "at": utc_now(), **values})


def _memory_source_proof(
    *,
    enabled: bool,
    store: SibylStore,
    recalled: list[LearnedLesson],
    strategy: Any,
) -> dict[str, Any]:
    if not enabled:
        return {
            "readPerformed": False,
            "message": "No Sibyl memory read for this run.",
            "processSessionId": PROCESS_SESSION_ID,
            "databaseSource": None,
            "returnedLessonIds": [],
            "plannerMemoryRefs": [],
            "records": [],
            "plannerApplicability": strategy.applicabilityAssessment,
            "influencedRules": [],
        }

    returned_ids = [lesson.id for lesson in recalled]
    influenced_rules = [
        {
            "taskNode": node.type,
            "rule": node.conditionalTrigger or "Unconditional for this job",
            "reason": node.mutationReason,
        }
        for node in strategy.orderedSteps
        if node.mutationReason
        and any(lesson_id in node.mutationReason for lesson_id in returned_ids)
    ]
    return {
        "readPerformed": True,
        "message": (
            "Sibyl returned persisted operational memory to planning."
            if recalled else "Sibyl was queried but returned no applicable lesson."
        ),
        "processSessionId": PROCESS_SESSION_ID,
        "databaseSource": store.database_path,
        "returnedLessonIds": returned_ids,
        "plannerMemoryRefs": list(strategy.memoryRefs),
        "records": [lesson.to_dict() for lesson in recalled],
        "plannerApplicability": strategy.applicabilityAssessment,
        "influencedRules": influenced_rules,
    }


def run_live_assessment(
    request_value: dict[str, Any],
    *,
    memory_enabled: bool,
    memory_db: str | Path,
    data_source: ProtocolDataSource | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    request = JobRequest.from_dict(request_value)
    store = SibylStore(memory_db)
    _emit(progress, "intake_accepted", taskClass=request.taskClass)
    _emit(progress, "memory_retrieval_started", enabled=memory_enabled)
    if memory_enabled:
        strategy, recalled = plan_in_fresh_session(request, store)
    else:
        strategy = baseline_plan(request, new_id("job"))
        recalled = []
    memory_source = _memory_source_proof(
        enabled=memory_enabled,
        store=store,
        recalled=recalled,
        strategy=strategy,
    )
    _emit(
        progress,
        "plan_created",
        source=strategy.source,
        memoryRefs=strategy.memoryRefs,
        applicability=strategy.applicabilityAssessment,
        graph=strategy.to_dict()["orderedSteps"],
    )

    provider = ProtocolAssessmentProvider(data_source)
    controller = ExecutionController(
        request,
        strategy,
        provider,
        event_callback=progress,
    )
    result = controller.run()
    execution_id = new_id("execution")
    outputs = list(result.outputs.values())
    risk = next((item for item in outputs if item.get("role") == "risk_synthesis"), None)
    security_purchased = "security_analysis" in result.purchasedRoles
    security_unnecessary = bool(
        risk and risk.get("continueToSecurity") is False and security_purchased
        and "mandatory security" not in " ".join(request.hardConstraints).lower()
    )
    execution_record = {
        "executionId": execution_id,
        "jobId": result.jobId,
        "request": asdict(request),
        "strategy": strategy.to_dict(),
        "providerOutputs": outputs,
        "totalSpent": result.spent,
        "outcome": "protocol assessment completed" if result.status == "completed" else "protocol assessment failed",
    }
    evaluation = evaluate_execution(
        execution_record,
        relation_to_lesson="supporting",
        outcome=execution_record["outcome"],
        successful_decisions=["specialist outputs passed their role-specific contracts"],
        failed_decisions=(["security was purchased after risk evidence did not justify it"] if security_unnecessary else []),
        unnecessary_purchases=(["security_analysis"] if security_unnecessary else []),
        missed_dependencies=[],
        useful_sequencing=(["viability evidence preceded risk synthesis"] if strategy.source == "adapted" else []),
        proposed_strategy_changes=(["apply progressive specialist purchasing"] if security_unnecessary else ["retain current strategy"]),
    )
    _emit(progress, "evaluation_completed", evaluation=evaluation.to_dict())

    current_lesson = store.get_lesson(strategy.memoryRefs[0]) if strategy.memoryRefs else None
    lesson_update: dict[str, Any] | None = None
    if current_lesson is not None:
        learned = learn_from_execution(store, execution_record, current_lesson, evaluation)
        reflection = learned.reflection
        lesson_update = {
            "action": learned.mutation.action,
            "lesson": learned.updatedLesson.to_dict(),
            "evidenceRef": learned.mutation.evidenceRef,
        }
    else:
        evidence_ref = store.write_execution_history(execution_record, evaluation=evaluation.to_dict())
        reflection = ReflectionResult(
            jobId=result.jobId,
            successfulDecisions=evaluation.successfulDecisions,
            failedDecisions=evaluation.failedDecisions,
            unnecessaryPurchases=evaluation.unnecessaryPurchases,
            missedDependencies=evaluation.missedDependencies,
            strategyChanges=evaluation.proposedStrategyChanges,
            proposedLessons=[],
            evidenceRefs=[evidence_ref],
            confidence=0.75,
            usefulSequencing=evaluation.usefulSequencing,
            proposedStrategyChanges=evaluation.proposedStrategyChanges,
        )
        if security_unnecessary:
            lesson = LearnedLesson(
                id=LESSON_ID,
                taskPattern="protocol_assessment",
                strategy="Purchase viability evidence first, then risk and security only when accepted evidence justifies continuation.",
                reasoning="Evaluated execution purchased security after risk evidence rejected that continuation.",
                applicabilityConditions=["protocol assessment", "viability evidence can inform continuation"],
                nonApplicabilityConditions=["task is not a protocol assessment"],
                supportingExecutionRefs=[evidence_ref],
                contradictoryEvidenceRefs=[],
                confidence=0.75,
                status="active",
                lastUpdatedAt=utc_now(),
            )
            reflection.proposedLessons.append(lesson)
            store.write_lesson(lesson)
            lesson_update = {"action": "created", "lesson": lesson.to_dict(), "evidenceRef": evidence_ref}
    _emit(progress, "reflection_completed", reflection=reflection.to_dict())
    if lesson_update:
        _emit(progress, "lesson_updated", **lesson_update)

    response = {
        "jobId": result.jobId,
        "status": result.status,
        "request": asdict(request),
        "memory": {
            "enabled": memory_enabled,
            "recalledLessonIds": [lesson.id for lesson in recalled],
            "applicability": strategy.applicabilityAssessment,
            "source": memory_source,
        },
        "strategy": strategy.to_dict(),
        "execution": asdict(result),
        "evaluation": evaluation.to_dict(),
        "reflection": reflection.to_dict(),
        "lessonUpdate": lesson_update,
        "providerMode": "local specialists, no ACP payment",
        "finalResult": {
            "status": result.status,
            "decision": "Assessment complete. Review accepted evidence and procurement decisions.",
            "verification": "All accepted specialist outputs passed role-specific validation.",
            "evidence": outputs,
        },
    }
    _emit(progress, "execution_completed", result=response)
    return response
