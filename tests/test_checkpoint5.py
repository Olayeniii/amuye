from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace

from amuye.checkpoint import execute_baseline, plan_in_fresh_session
from amuye.demo import DEMO_REQUEST
from amuye.domain import new_id
from amuye.learning import evaluate_execution, learn_from_execution
from amuye.sibyl_store import SibylStore


def execution_record(*, priority: str = "balanced"):
    return {
        "executionId": new_id("execution"),
        "jobId": new_id("job"),
        "request": asdict(replace(DEMO_REQUEST, priority=priority)),
        "strategy": {"source": "adapted"},
        "providerOutputs": [],
        "totalSpent": 10.0,
        "outcome": "evaluated protocol-assessment outcome",
    }


def evaluation(execution, relation="supporting", *, strong=False):
    contradictory = relation == "contradictory"
    return evaluate_execution(
        execution,
        relation_to_lesson=relation,
        outcome=("progressive ordering delayed a time-critical decision"
                 if contradictory else "progressive ordering avoided unnecessary work"),
        successful_decisions=(["viability evidence avoided deeper purchases"]
                              if not contradictory else ["required evidence was eventually obtained"]),
        failed_decisions=(["viability-first ordering missed the useful decision window"]
                          if contradictory else []),
        unnecessary_purchases=[],
        missed_dependencies=(["deadline urgency was not considered before applying memory"]
                             if contradictory else []),
        useful_sequencing=(["viability before risk reduced spend"] if not contradictory else []),
        proposed_strategy_changes=(["exclude urgent jobs from this lesson"]
                                   if contradictory else ["retain progressive purchasing"]),
        evidence_strength="strong" if strong else "ordinary",
        independently_verified=strong,
        material_harm=strong,
    )


def initialized_store(tmp_path):
    store = SibylStore(tmp_path / "sibyl.db")
    _, reflection = execute_baseline(DEMO_REQUEST, store)
    lesson = store.get_lesson(reflection.proposedLessons[0].id)
    assert lesson is not None
    return store, lesson


def fresh_plan(memory_db, request):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, ["src", env.get("PYTHONPATH")]))
    child = subprocess.run(
        [sys.executable, "-m", "amuye.fresh_session", "--memory-db", str(memory_db),
         "--request-json", json.dumps(asdict(request))],
        check=True, capture_output=True, text=True, env=env,
    )
    return json.loads(child.stdout)


def test_execution_evidence_references_are_real_sibyl_event_ids(tmp_path):
    store, lesson = initialized_store(tmp_path)
    assert lesson.supportingExecutionRefs
    assert all(store.execution_event_exists(ref) for ref in lesson.supportingExecutionRefs)
    assert all(not ref.startswith("execution_") for ref in lesson.supportingExecutionRefs)
    event = store.get_execution_event(lesson.supportingExecutionRefs[0])
    assert event is not None
    assert event["extra"]["applicationExecutionId"].startswith("execution_")


def test_evaluation_and_reflection_precede_lesson_mutation(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record()
    result = learn_from_execution(store, execution, lesson, evaluation(execution))
    assert result.stageTrace == [
        "evaluated", "evidence_persisted", "reflected", "lesson_mutated",
    ]
    assert result.reflection.evidenceRefs == [result.mutation.evidenceRef]
    assert result.reflection.lessonMutationProposals == [result.mutation]


def test_successful_execution_strengthens_lesson_with_traceable_support(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record()
    result = learn_from_execution(store, execution, lesson, evaluation(execution))
    assert result.mutation.action == "strengthen"
    assert result.updatedLesson.confidence > lesson.confidence
    assert result.mutation.evidenceRef in result.updatedLesson.supportingExecutionRefs
    assert store.execution_event_exists(result.mutation.evidenceRef)


def test_ordinary_contradiction_narrows_and_weakens_existing_lesson(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record(priority="urgent")
    result = learn_from_execution(
        store, execution, lesson, evaluation(execution, "contradictory"),
        narrow_priority="urgent",
    )
    assert result.mutation.action == "narrow"
    assert result.updatedLesson.confidence < lesson.confidence
    assert "priority=urgent" in result.updatedLesson.nonApplicabilityConditions
    assert result.mutation.evidenceRef in result.updatedLesson.contradictoryEvidenceRefs
    assert result.updatedLesson.status == "active"


def test_strong_verified_material_contradiction_can_supersede(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record()
    result = learn_from_execution(
        store, execution, lesson,
        evaluation(execution, "contradictory", strong=True),
    )
    assert result.mutation.action == "supersede"
    assert result.updatedLesson.status == "superseded"
    assert store.execution_event_exists(result.mutation.evidenceRef)
    strategy, _ = plan_in_fresh_session(DEMO_REQUEST, SibylStore(tmp_path / "sibyl.db"))
    assert strategy.source == "baseline"


def test_unverified_strong_claim_cannot_supersede(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record()
    claimed_strong = evaluate_execution(
        execution,
        relation_to_lesson="contradictory",
        outcome="reported delay without independent verification",
        successful_decisions=[], failed_decisions=["reported delay"],
        unnecessary_purchases=[], missed_dependencies=[], useful_sequencing=[],
        proposed_strategy_changes=["reconsider lesson"], evidence_strength="strong",
        independently_verified=False, material_harm=True,
    )
    result = learn_from_execution(store, execution, lesson, claimed_strong)
    assert result.mutation.action == "weaken"
    assert result.updatedLesson.status == "weakened"


def test_conflict_can_mark_lesson_uncertain_without_superseding(tmp_path):
    store, lesson = initialized_store(tmp_path)
    execution = execution_record()
    result = learn_from_execution(
        store, execution, lesson, evaluation(execution, "contradictory"),
        mark_uncertain=True,
    )
    assert result.mutation.action == "uncertain"
    assert result.updatedLesson.status == "uncertain"


def test_support_can_broaden_a_previously_narrowed_lesson(tmp_path):
    store, lesson = initialized_store(tmp_path)
    narrowed = replace(
        lesson,
        nonApplicabilityConditions=[*lesson.nonApplicabilityConditions, "priority=urgent"],
    )
    store.write_lesson(narrowed)
    execution = execution_record(priority="urgent")
    result = learn_from_execution(
        store, execution, narrowed, evaluation(execution),
        broaden_condition="priority=urgent",
    )
    assert result.mutation.action == "broaden"
    assert "priority=urgent" not in result.updatedLesson.nonApplicabilityConditions


def test_fresh_process_gets_updated_lesson_and_changes_urgent_plan(tmp_path):
    store, lesson = initialized_store(tmp_path)
    urgent = replace(DEMO_REQUEST, priority="urgent")
    before, _ = plan_in_fresh_session(urgent, store)
    assert before.source == "adapted"

    execution = execution_record(priority="urgent")
    result = learn_from_execution(
        store, execution, lesson, evaluation(execution, "contradictory"),
        narrow_priority="urgent",
    )
    recalled = fresh_plan(tmp_path / "sibyl.db", urgent)
    recalled_lesson = recalled["recalledLessons"][0]
    assert recalled_lesson["lastUpdatedAt"] == result.updatedLesson.lastUpdatedAt
    assert recalled_lesson["contradictoryEvidenceRefs"] == [result.mutation.evidenceRef]
    assert recalled["strategy"]["source"] == "baseline"
    assert recalled["strategy"]["memoryRefs"] == []


def test_current_constraints_still_override_updated_memory(tmp_path):
    store, _ = initialized_store(tmp_path)
    mandatory = replace(DEMO_REQUEST, hardConstraints=["mandatory security check"])
    strategy, _ = plan_in_fresh_session(mandatory, store)
    assert strategy.source == "baseline"
    assert strategy.memoryRefs == []
