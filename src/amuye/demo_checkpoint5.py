from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .checkpoint import execute_baseline, plan_in_fresh_session
from .demo import DEMO_REQUEST
from .domain import new_id
from .learning import evaluate_execution, learn_from_execution
from .sibyl_store import SibylStore


def run(memory_db: Path, output: Path) -> dict:
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    store = SibylStore(memory_db)
    _, initial_reflection = execute_baseline(DEMO_REQUEST, store)
    lesson_id = initial_reflection.proposedLessons[0].id
    existing = store.get_lesson(lesson_id)
    assert existing is not None

    urgent = replace(DEMO_REQUEST, priority="urgent")
    before, _ = plan_in_fresh_session(urgent, store)
    execution = {
        "executionId": new_id("execution"),
        "jobId": new_id("job"),
        "request": asdict(urgent),
        "strategy": before.to_dict(),
        "providerOutputs": [],
        "totalSpent": 10.0,
        "outcome": "viability-first ordering delayed a time-critical decision",
    }
    evaluation = evaluate_execution(
        execution,
        relation_to_lesson="contradictory",
        outcome=execution["outcome"],
        successful_decisions=["required evidence was eventually obtained"],
        failed_decisions=["progressive ordering missed the useful decision window"],
        unnecessary_purchases=[],
        missed_dependencies=["deadline urgency was not considered before applying memory"],
        useful_sequencing=[],
        proposed_strategy_changes=["exclude urgent jobs from this lesson"],
    )
    learned = learn_from_execution(
        store, execution, existing, evaluation, narrow_priority="urgent",
    )
    child = subprocess.run(
        [sys.executable, "-m", "amuye.fresh_session", "--memory-db", str(memory_db),
         "--request-json", json.dumps(asdict(urgent))],
        check=True, capture_output=True, text=True,
    )
    fresh = json.loads(child.stdout)
    report = {
        "existingLesson": existing.to_dict(),
        "contradictoryExecution": execution,
        "evaluation": evaluation.to_dict(),
        "reflection": learned.reflection.to_dict(),
        "sibylUpdate": learned.updatedLesson.to_dict(),
        "stageTrace": learned.stageTrace,
        "freshProcess": fresh,
        "behaviorChange": {
            "before": before.source,
            "after": fresh["strategy"]["source"],
            "reason": "priority=urgent became a non-applicability condition",
        },
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Amúyẹ evaluation and lesson evolution proof")
    parser.add_argument("--memory-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.memory_db, args.output)["behaviorChange"], indent=2))


if __name__ == "__main__":
    main()
