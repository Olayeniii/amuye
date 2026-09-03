from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from .checkpoint import execute_baseline
from .controlled_session import run_session
from .demo_checkpoint7 import CONTROL_PROFILE, CONTROL_REQUEST
from .sibyl_store import SibylStore


LESSON_ID = "lesson_progressive_specialist_purchasing_v1"
MANDATORY_CONSTRAINT = "security analysis is mandatory for this assessment"


def _node(run: dict, role: str, *, final: bool = False) -> dict:
    graph = run["execution"]["finalGraph"] if final else run["strategy"]["initialGraph"]
    return next(item for item in graph if item["type"] == role)


def run(memory_db: Path, output: Path) -> dict:
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    store = SibylStore(memory_db)
    lesson = store.get_lesson(LESSON_ID)
    if lesson is None:
        _, reflection = execute_baseline(CONTROL_REQUEST, store)
        lesson = reflection.proposedLessons[0]
    lesson_before = lesson.to_dict()

    adapted_request = replace(
        CONTROL_REQUEST,
        hardConstraints=[*CONTROL_REQUEST.hardConstraints, MANDATORY_CONSTRAINT],
        clientId="changed-constraint-proof",
    )
    adapted = run_session("on", str(memory_db), asdict(adapted_request), CONTROL_PROFILE)
    ordinary = run_session("on", str(memory_db), asdict(CONTROL_REQUEST), CONTROL_PROFILE)
    lesson_after = SibylStore(memory_db).get_lesson(LESSON_ID)
    if lesson_after is None:
        raise ValueError("recalled lesson disappeared after job-local override")

    security_initial = _node(adapted, "security_analysis")
    security_final = _node(adapted, "security_analysis", final=True)
    risk_output = next(
        item for item in adapted["execution"]["result"]["evidence"]
        if item["role"] == "risk_synthesis"
    )
    security_output = next(
        item for item in adapted["execution"]["result"]["evidence"]
        if item["role"] == "security_analysis"
    )
    ordinary_security = _node(ordinary, "security_analysis", final=True)

    if adapted["memory"]["recalledLessonIds"] != [LESSON_ID]:
        raise ValueError("progressive-purchasing lesson was not retrieved")
    if risk_output["continueToSecurity"] is not False:
        raise ValueError("controlled risk evidence did not exercise the override")
    if security_final["status"] != "completed":
        raise ValueError("mandatory security analysis did not execute")
    if lesson_before != lesson_after.to_dict():
        raise ValueError("job-local constraint override mutated the Sibyl lesson")
    if ordinary_security["status"] != "skipped":
        raise ValueError("later ordinary task did not retain the progressive security gate")

    override_reason = security_initial["mutationReason"]
    report = {
        "request": asdict(adapted_request),
        "changedConstraint": MANDATORY_CONSTRAINT,
        "recalledLessonId": LESSON_ID,
        "applicabilityAssessment": adapted["memory"]["applicabilityDecision"],
        "conflictingMemoryRule": (
            "Purchase security analysis only if risk evidence justifies it."
        ),
        "preservedMemoryDerivedRules": [
            "Run viability/onchain analysis before risk synthesis.",
            "Purchase risk synthesis only when viability evidence justifies continuation.",
            "Pass accepted viability evidence into risk synthesis.",
            "Run security analysis after risk synthesis with preceding context.",
        ],
        "overriddenRule": "risk continueToSecurity must be true before security purchase",
        "reasonForOverride": override_reason,
        "overrideSource": "hard client constraint enforced by planner and ExecutionController",
        "initialAdaptedGraph": adapted["strategy"]["initialGraph"],
        "finalGraph": adapted["execution"]["finalGraph"],
        "executionSequence": adapted["execution"]["executionSequence"],
        "purchases": adapted["execution"]["providerJobsPurchased"],
        "spend": adapted["execution"]["spent"],
        "remainingBudget": adapted["execution"]["remainingBudget"],
        "finalResult": adapted["execution"]["result"],
        "mandatorySecurityEvidence": {
            "riskContinueToSecurity": risk_output["continueToSecurity"],
            "securityNodeStatus": security_final["status"],
            "securityOutput": security_output,
            "policyMutation": next(
                mutation for mutation in adapted["execution"]["mutations"]
                if mutation["nodeId"] == security_final["id"]
                and "hard client constraint" in mutation["reason"]
            ),
        },
        "lessonIntegrity": {
            "before": lesson_before,
            "after": lesson_after.to_dict(),
            "unchanged": True,
        },
        "laterOrdinaryTask": {
            "recalledLessonIds": ordinary["memory"]["recalledLessonIds"],
            "securityConditionalTrigger": _node(ordinary, "security_analysis")["conditionalTrigger"],
            "securityStatus": ordinary_security["status"],
            "securitySkipReason": ordinary_security["mutationReason"],
        },
        "environment": adapted["environment"],
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Amúyẹ changed-constraint adaptation proof")
    parser.add_argument("--memory-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.memory_db, args.output)
    print(json.dumps({
        "recalledLessonId": report["recalledLessonId"],
        "executionSequence": report["executionSequence"],
        "spend": report["spend"],
        "mandatorySecurityEvidence": report["mandatorySecurityEvidence"],
    }, indent=2))


if __name__ == "__main__":
    main()
