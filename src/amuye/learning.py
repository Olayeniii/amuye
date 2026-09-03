from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .domain import (
    ExecutionEvaluation,
    LearnedLesson,
    LessonMutationProposal,
    ReflectionResult,
    utc_now,
)
from .sibyl_store import SibylStore


@dataclass(frozen=True)
class LearningResult:
    evaluation: ExecutionEvaluation
    reflection: ReflectionResult
    mutation: LessonMutationProposal
    updatedLesson: LearnedLesson
    stageTrace: list[str]


def evaluate_execution(
    execution: dict[str, Any],
    *,
    relation_to_lesson: str,
    outcome: str,
    successful_decisions: list[str],
    failed_decisions: list[str],
    unnecessary_purchases: list[str],
    missed_dependencies: list[str],
    useful_sequencing: list[str],
    proposed_strategy_changes: list[str],
    evidence_strength: str = "ordinary",
    independently_verified: bool = False,
    material_harm: bool = False,
) -> ExecutionEvaluation:
    if relation_to_lesson not in {"supporting", "contradictory"}:
        raise ValueError("relation_to_lesson must be supporting or contradictory")
    if evidence_strength not in {"ordinary", "strong"}:
        raise ValueError("evidence_strength must be ordinary or strong")
    return ExecutionEvaluation(
        executionId=execution["executionId"],
        relationToLesson=relation_to_lesson,
        outcome=outcome,
        successfulDecisions=successful_decisions,
        failedDecisions=failed_decisions,
        unnecessaryPurchases=unnecessary_purchases,
        missedDependencies=missed_dependencies,
        usefulSequencing=useful_sequencing,
        proposedStrategyChanges=proposed_strategy_changes,
        evidenceStrength=evidence_strength,
        independentlyVerified=independently_verified,
        materialHarm=material_harm,
    )


def reflect_on_evaluation(
    job_id: str,
    evaluation: ExecutionEvaluation,
    evidence_ref: str,
    proposal: LessonMutationProposal,
) -> ReflectionResult:
    return ReflectionResult(
        jobId=job_id,
        successfulDecisions=list(evaluation.successfulDecisions),
        failedDecisions=list(evaluation.failedDecisions),
        unnecessaryPurchases=list(evaluation.unnecessaryPurchases),
        missedDependencies=list(evaluation.missedDependencies),
        strategyChanges=list(evaluation.proposedStrategyChanges),
        proposedLessons=[],
        evidenceRefs=[evidence_ref],
        confidence=0.9 if evaluation.evidenceStrength == "strong" else 0.75,
        usefulSequencing=list(evaluation.usefulSequencing),
        proposedStrategyChanges=list(evaluation.proposedStrategyChanges),
        lessonMutationProposals=[proposal],
    )


def propose_lesson_mutation(
    lesson: LearnedLesson,
    evaluation: ExecutionEvaluation,
    evidence_ref: str,
    *,
    narrow_priority: str | None = None,
    broaden_condition: str | None = None,
    mark_uncertain: bool = False,
) -> LessonMutationProposal:
    if evaluation.relationToLesson == "supporting":
        if broaden_condition:
            return LessonMutationProposal(
                lessonId=lesson.id,
                action="broaden",
                reason=f"Supporting evidence justified removing exclusion {broaden_condition}.",
                evidenceRef=evidence_ref,
                removeNonApplicabilityConditions=[broaden_condition],
            )
        return LessonMutationProposal(
            lessonId=lesson.id,
            action="strengthen",
            reason="Execution evidence supported progressive specialist purchasing.",
            evidenceRef=evidence_ref,
        )
    if (evaluation.evidenceStrength == "strong"
            and evaluation.independentlyVerified
            and evaluation.materialHarm):
        return LessonMutationProposal(
            lessonId=lesson.id,
            action="supersede",
            reason="Independently verified strong contradiction showed material harm.",
            evidenceRef=evidence_ref,
        )
    if narrow_priority:
        return LessonMutationProposal(
            lessonId=lesson.id,
            action="narrow",
            reason=f"Contradictory evidence limits the lesson for {narrow_priority} priority jobs.",
            evidenceRef=evidence_ref,
            addNonApplicabilityConditions=[f"priority={narrow_priority.lower()}"],
        )
    if mark_uncertain:
        return LessonMutationProposal(
            lessonId=lesson.id,
            action="uncertain",
            reason="Conflicting evidence made the lesson uncertain without justifying supersession.",
            evidenceRef=evidence_ref,
        )
    return LessonMutationProposal(
        lessonId=lesson.id,
        action="weaken",
        reason="Contradictory execution evidence reduced confidence in the lesson.",
        evidenceRef=evidence_ref,
    )


def apply_lesson_mutation(
    lesson: LearnedLesson,
    proposal: LessonMutationProposal,
) -> LearnedLesson:
    supporting = list(lesson.supportingExecutionRefs)
    contradictory = list(lesson.contradictoryEvidenceRefs)
    confidence = lesson.confidence
    status = lesson.status
    applicability = list(lesson.applicabilityConditions)
    non_applicability = list(lesson.nonApplicabilityConditions)

    if proposal.action in {"strengthen", "broaden"}:
        if proposal.evidenceRef not in supporting:
            supporting.append(proposal.evidenceRef)
        confidence = min(1.0, confidence + 0.04)
        status = "active"
    else:
        if proposal.evidenceRef not in contradictory:
            contradictory.append(proposal.evidenceRef)
        confidence = max(0.0, confidence - (0.35 if proposal.action == "supersede" else 0.15))
        status = {
            "supersede": "superseded",
            "uncertain": "uncertain",
            "weaken": "weakened",
            "narrow": "active",
        }.get(proposal.action, status)

    for condition in proposal.addApplicabilityConditions:
        if condition not in applicability:
            applicability.append(condition)
    for condition in proposal.addNonApplicabilityConditions:
        if condition not in non_applicability:
            non_applicability.append(condition)
    applicability = [item for item in applicability
                     if item not in proposal.removeApplicabilityConditions]
    non_applicability = [item for item in non_applicability
                         if item not in proposal.removeNonApplicabilityConditions]
    return replace(
        lesson,
        reasoning=f"{lesson.reasoning} Latest update: {proposal.reason}",
        applicabilityConditions=applicability,
        nonApplicabilityConditions=non_applicability,
        supportingExecutionRefs=supporting,
        contradictoryEvidenceRefs=contradictory,
        confidence=round(confidence, 4),
        status=status,
        lastUpdatedAt=utc_now(),
    )


def learn_from_execution(
    store: SibylStore,
    execution: dict[str, Any],
    lesson: LearnedLesson,
    evaluation: ExecutionEvaluation,
    *,
    narrow_priority: str | None = None,
    broaden_condition: str | None = None,
    mark_uncertain: bool = False,
) -> LearningResult:
    stages = ["evaluated"]
    event_ref = store.write_execution_history(execution, evaluation=evaluation.to_dict())
    stages.append("evidence_persisted")
    proposal = propose_lesson_mutation(
        lesson,
        evaluation,
        event_ref,
        narrow_priority=narrow_priority,
        broaden_condition=broaden_condition,
        mark_uncertain=mark_uncertain,
    )
    reflection = reflect_on_evaluation(execution["jobId"], evaluation, event_ref, proposal)
    stages.append("reflected")
    updated = apply_lesson_mutation(lesson, proposal)
    store.write_lesson(updated)
    stages.append("lesson_mutated")
    return LearningResult(evaluation, reflection, proposal, updated, stages)
